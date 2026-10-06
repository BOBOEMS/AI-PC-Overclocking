#!/usr/bin/env python3
"""Own the workload's sensor sources and keep one continuously fresh file.

Why this exists
---------------
The watchdog's `arm` needs a sensor file that is fresh within `--sensor-stale`
(default 15 s) at all times. Reading ryzen-smu-cli's stdout directly cannot
provide that: the child's stdout is block-buffered (4-8 KiB), so the file sits
untouched for 15-30 s at a time even though the stream is perfectly healthy.
On 2026-10-01 14:55 that killed a healthy sweep with "lost sensor monitoring:
sensor source stale for 15.5s".

So the sources are merged here and rewritten every `--interval` seconds, with
the write time as the newest sample's timestamp. Consequences that matter:

  * a source that stops updating is reported as stale independently
    (``source_age_seconds`` for ryzen-smu-cli, which trips the run; HWiNFO going
    away only removes the DDR5 coverage and is recorded, because this run's
    workload cannot heat the DIMMs);
  * the HWiNFO shared memory is read from this non-elevated process on purpose,
    so UIPI and the splash screen cannot break it (see CPU_CO_RESULT.md round 6);
  * one file carries Tctl/Tdie (CPU protection), the per-core effective clocks
    (the criterion rounds 3-5 established) and, when HWiNFO is up, the DDR5 SPD
    Hub temperatures.

Never writes a synthetic temperature. If a source has never answered, its
values are simply absent, and the watchdog's "no protected temperature" path
decides what that means.
"""

from __future__ import annotations


import argparse
import json
import os
from pathlib import Path
import sys
import time

# --- shared path resolution -------------------------------------------------
# This script lives under <repo>/src/, so the repository root is reached from
# this file rather than from the working directory. All machine-specific paths
# (third-party tools, artifact output) come from src/common/paths.py so that a
# clone works without editing source.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.common import paths as _paths  # noqa: E402
from src.common import hwinfo_shared  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))

TCTL_KEYS = ("CPU (Tctl/Tdie) [C]", "CPU CCD1 (Tdie) [C]")
HOT_LABELS = ("Tctl", "Tdie", "SPD Hub", "DIMM", "Vcore", "VDDCR")


def read_telemetry(path: Path) -> tuple[str, dict[str, float]]:
    """Newest line of the ryzen-smu-cli stream, verbatim, plus its parsed fields."""
    if not path.exists():
        raise ValueError(f"telemetry file does not exist yet: {path}")
    line = None
    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - 65536))
        for candidate in reversed(handle.read().decode("utf-8", "replace").splitlines()):
            if candidate.strip().startswith("{"):
                line = candidate.strip()
                break
    if line is None:
        raise ValueError(f"no telemetry line in {path}")
    record = json.loads(line)
    temperatures: dict[str, float] = {}
    values: dict[str, float] = {}
    tctl = record.get("cpuTemperatureCelsius")
    if tctl is not None:
        for key in TCTL_KEYS:
            temperatures[key] = float(tctl)
            values[key] = float(tctl)
    if (vcore := record.get("vcoreVolts")) is not None:
        values["Vcore [V]"] = float(vcore)
    if (watts := record.get("packagePowerWatts")) is not None:
        values["CPU Package Power [W]"] = float(watts)
    for target in record.get("targets") or []:
        if (clock := target.get("effectiveMhz")) is None:
            continue
        values[f"Core {target.get('processor')} Effective Clock [MHz]"] = float(clock)
    if not temperatures:
        raise ValueError(f"telemetry line has no cpuTemperatureCelsius: {path}")
    return line, {**temperatures, **values}


def read_hwinfo() -> tuple[dict[str, float], dict[str, float]]:
    """Protected temperatures and interesting values from HWiNFO's shared memory."""


    snapshot = hwinfo_shared.read_snapshot()
    temperatures: dict[str, float] = {}
    values: dict[str, float] = {}
    for reading in snapshot["readings"]:
        blob = f"{reading['sensor']} | {reading['label']}"
        key = f"{reading['sensor']} | {reading['label']} [{reading['unit']}]"
        if reading["type"] == "temp" and reading["value"] > 0:
            temperatures[key] = float(reading["value"])
        if any(label in blob for label in HOT_LABELS):
            values[key] = float(reading["value"])
    if not temperatures:
        raise ValueError("HWiNFO shared memory carried no temperature reading")
    return temperatures, values


def atomic_write_json(path: Path, payload: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--telemetry", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--telemetry-stale-trip", type=float, default=20.0,
                        help="seconds without a NEW telemetry line before the emitted age is pushed past the watchdog's limit")
    parser.add_argument("--hwinfo", action="store_true", help="also merge HWiNFO shared memory")
    parser.add_argument("--raw-readings", type=Path, default=None,
                        help="Also append EVERY HWiNFO reading to this jsonl, every sample. The merged "
                             "output keeps only protected temperatures and a couple of value labels, "
                             "which is not enough to analyse per-core clocks after the fact.")
    parser.add_argument("--seconds", type=float, default=0.0, help="stop after this long (0 = until killed)")
    args = parser.parse_args()

    started = time.monotonic()
    last_telemetry: dict[str, float] | None = None
    last_line: str | None = None
    last_new_line = 0.0
    last_hwinfo: tuple[dict[str, float], dict[str, float]] | None = None
    hwinfo_failures = 0
    note_emitted = False
    if args.raw_readings:
        args.raw_readings.parent.mkdir(parents=True, exist_ok=True)

    while True:
        now = time.monotonic()
        try:
            line, parsed = read_telemetry(args.telemetry)
            # Age is measured from the last NEW line, not the file's mtime: the
            # child's stdout is block-buffered, so the file legitimately sits
            # unchanged for 15-30 s while the stream is perfectly healthy.
            if line != last_line:
                last_line = line
                last_new_line = now
            last_telemetry = parsed
        except (OSError, ValueError) as error:
            print(f"telemetry: {error}", file=sys.stderr, flush=True)

        if args.hwinfo:
            try:
                last_hwinfo = read_hwinfo()
                hwinfo_failures = 0
                if args.raw_readings:


                    snapshot = hwinfo_shared.read_snapshot()
                    with args.raw_readings.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps({
                            "read_at": time.time(),
                            "readings": [{
                                "sensor": r["sensor"], "label": r["label"], "unit": r["unit"],
                                "type": r["type"], "value": float(r["value"]),
                            } for r in snapshot["readings"]],
                        }, ensure_ascii=False) + "\n")
            except Exception as error:  # noqa: BLE001 - any failure just drops DIMM coverage
                hwinfo_failures += 1
                if not note_emitted or hwinfo_failures % 30 == 0:
                    print(f"hwinfo unavailable ({hwinfo_failures}): {error}", file=sys.stderr, flush=True)
                    note_emitted = True

        temperatures: dict[str, float] = {}
        values: dict[str, float] = {}
        if last_telemetry is not None:
            for key, value in last_telemetry.items():
                if key in TCTL_KEYS:
                    temperatures[key] = value
                else:
                    values[key] = value
            telemetry_age = max(0.0, now - last_new_line)
            values["SMU telemetry line age [s]"] = round(telemetry_age, 2)
        else:
            telemetry_age = float("inf")
        if last_hwinfo is not None:
            hwinfo_temperatures, hwinfo_values = last_hwinfo
            temperatures.update(hwinfo_temperatures)
            values.update(hwinfo_values)

        # The watchdog compares this against --sensor-stale, so a stream that
        # really stopped stops protecting the run. Brief buffering gaps do not.
        reported_age = telemetry_age if telemetry_age != float("inf") else args.telemetry_stale_trip + 1.0
        atomic_write_json(args.out, {
            "source_age_seconds": round(reported_age, 2),
            "telemetry_age_seconds": None if telemetry_age == float("inf") else round(telemetry_age, 2),
            "hwinfo_available": last_hwinfo is not None,
            "temperatures": temperatures,
            "values": values,
            "note": ("heartbeat written by tools/sidecar_sensors.py; temperatures are real readings, "
                     "never synthesized"),
        })

        if args.seconds and time.monotonic() - started > args.seconds:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
