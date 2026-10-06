#!/usr/bin/env python3
"""Resolution verification: does going deeper than -25 still change anything?

Round 6 (runs/20261001-144528-cpu-co-sweep-core0-1/CPU_CO_RESULT_ROUND6.md) left a
fork in the road: both cores passed at -25, the deepest margin searched, so -25 is
the *edge of the search*, not the cores' limit. Going deeper costs ~43 min per core,
and rounds 3-5 already established that the negative offset stops changing the
operating point somewhere around -20. So before spending that time, measure whether
the interval still has resolution at all.

Design (same load every level, one variable):

  engine   04-P4P (SSE3)  — the light-load engine that reaches fMax, i.e. exactly
                            the band where the offset gets converted into frequency
                            (round 5). Not AVX-512: that clamps the core near 5.0 GHz
                            and would hide the effect while adding 12 C of heat.
  test     SFTv4          — one test, so each level's load is the same shape.
  window   120 s          — matches rycolab's soak length.
  margins  0, -10, -20, -30 (configurable) with a read-back before every level.
  measured HWiNFO's per-core clock (median over the load window) + Tctl, and the
           engine's own "Test Speed" as an independent throughput check.

Everything runs under the dead-man watchdog with HWiNFO protection, and the sidecar
logs every HWiNFO reading continuously (--raw-readings) so the clocks can be
analysed per level afterwards.

This tool performs NO SMU writes other than the margin itself and never leaves a
nonzero margin behind: the final step is always `--offset 0:0,...,7:0` with a
read-back, and that final value is printed as evidence.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

# --- shared path resolution -------------------------------------------------
# This script lives under <repo>/src/, so the repository root is reached from
# this file rather than from the working directory. All machine-specific paths
# (third-party tools, artifact output) come from src/common/paths.py so that a
# clone works without editing source.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.common import paths as _paths  # noqa: E402
ROOT = _paths.REPO_ROOT
WATCHDOG = ROOT / "tools" / "deadman_watchdog.py"
RUNNER = ROOT / "tools" / "engine_runner.py"
SIDECAR = ROOT / "tools" / "sidecar_sensors.py"
SMU_CLI = _paths.RYZEN_SMU_CLI
RYCOLAB_BINARIES = _paths.RYCOLAB_BINARIES
PYTHON = _paths.PYTHON_EXE


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace", check=False, **kwargs)


def apply_margin(core: int, margin: int) -> tuple[bool, str]:
    """Write one core's offset and read it back. The read-back is the evidence."""
    written = run([str(SMU_CLI), "--offset", f"{core}:{margin}"])
    read_back = run([str(SMU_CLI), "--get-offsets-terse"])
    line = (read_back.stdout or "").strip().splitlines()[-1] if read_back.stdout else ""
    values = [v.strip() for v in line.split(",")]
    ok = written.returncode == 0 and len(values) > core and values[core] == str(margin)
    return ok, f"write_exit={written.returncode} readback={line or '(none)'}"


def reset_all() -> tuple[bool, str]:
    offsets = ",".join(f"{c}:0" for c in range(8))
    written = run([str(SMU_CLI), "--offset", offsets])
    read_back = run([str(SMU_CLI), "--get-offsets-terse"])
    line = (read_back.stdout or "").strip().splitlines()[-1] if read_back.stdout else ""
    return written.returncode == 0 and line == "0,0,0,0,0,0,0,0", f"write_exit={written.returncode} readback={line or '(none)'}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", help="watchdog session name under watchdog_sessions/")
    parser.add_argument("--core", type=int, default=0)
    parser.add_argument("--margins", type=int, nargs="+", default=[0, -10, -20, -30])
    parser.add_argument("--seconds", type=int, default=120, help="load window per level")
    parser.add_argument("--engine", default="04-P4P")
    parser.add_argument("--test", default="SFTv4")
    parser.add_argument("--memory-mib", type=int, default=1024)
    parser.add_argument("--settle", type=float, default=4.0, help="pause after the read-back before loading")
    parser.add_argument("--cooldown", type=float, default=30.0,
                        help="pause after each level's load so the next level starts from a comparable "
                             "temperature: boost behaviour is temperature dependent, so a heat-soaked "
                             "level would bias the frequency comparison")
    parser.add_argument("--cpu-temp-stop", type=float, default=95.0)
    parser.add_argument("--cpu-temp-emergency", type=float, default=100.0)
    parser.add_argument("--dimm-temp-stop", type=float, default=70.0)
    parser.add_argument("--dimm-temp-emergency", type=float, default=75.0)
    args = parser.parse_args()

    session_dir = ROOT / "watchdog_sessions" / args.session
    if session_dir.exists():
        parser.error(f"watchdog session already exists: {args.session}")
    if not SMU_CLI.is_file():
        parser.error(f"ryzen-smu-cli not found: {SMU_CLI}")
    work_dir = session_dir / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    raw_readings = session_dir / "hwinfo_raw.jsonl"
    sensor_feed = session_dir / "sensor_feed.json"
    telemetry = session_dir / "smu_telemetry.jsonl"   # never created: no SMU stream (that is the point)
    sidecar_err = (session_dir / "sidecar.stderr.log").open("wb")

    sidecar = subprocess.Popen([
        str(PYTHON), str(SIDECAR), "--telemetry", str(telemetry), "--out", str(sensor_feed),
        "--interval", "2", "--hwinfo", "--raw-readings", str(raw_readings),
    ], stdout=subprocess.DEVNULL, stderr=sidecar_err)

    # The watchdog needs the feed to exist before it arms.
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and not sensor_feed.exists():
        time.sleep(0.5)
    if not sensor_feed.exists():
        sidecar.terminate()
        print(json.dumps({"state": "failed", "reason": "sidecar never produced the sensor feed"}))
        return 2

    total = args.seconds * len(args.margins) + len(args.margins) * 30
    arm_cmd = [
        str(PYTHON), str(WATCHDOG), "arm",
        "--session", args.session,
        "--heartbeat-timeout", "45",
        "--hard-timeout", str(total * 2 + 300),
        "--sensor-file", str(sensor_feed), "--sensor-required", "--sensor-stale", "30",
        "--temp-strikes-required", "3",
        "--cpu-temp-stop", str(args.cpu_temp_stop),
        "--cpu-temp-emergency", str(args.cpu_temp_emergency),
        "--dimm-temp-stop", str(args.dimm_temp_stop),
        "--dimm-temp-emergency", str(args.dimm_temp_emergency),
        "--cwd", str(work_dir),
        "--", str(PYTHON), str(RUNNER),
        "--engine", args.engine, "--workdir", str(work_dir / "engine"),
        "--physical-core", str(args.core), "--tests", args.test,
        "--seconds-per-test", "60", "--memory-mib", str(args.memory_mib),
        "--duration", "999999",          # park the engine; one shared tree for all levels
    ]
    out_handle = (session_dir.parent / f"{args.session}.controller-watchdog.stdout.log").open("wb")
    err_handle = (session_dir.parent / f"{args.session}.controller-watchdog.stderr.log").open("wb")
    watchdog = subprocess.Popen(arm_cmd, cwd=ROOT, stdout=out_handle, stderr=err_handle)

    metadata = None
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and watchdog.poll() is None:
        try:
            metadata = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
            break
        except (OSError, ValueError):
            time.sleep(0.25)
    if not metadata:
        watchdog.terminate()
        sidecar.terminate()
        print(json.dumps({"state": "failed-to-arm"}))
        return 2
    token = str(metadata["token"])

    def feed() -> None:
        run([str(PYTHON), str(WATCHDOG), "feed", "--session", args.session, "--token", token,
             "--note", "resolution controller"])

    results = []
    print(json.dumps({"state": "armed", "session": args.session, "core": args.core,
                      "margins": args.margins, "secondsPerLevel": args.seconds,
                      "engine": args.engine, "test": args.test}, ensure_ascii=False), flush=True)
    try:
        for margin in args.margins:
            ok, evidence = apply_margin(args.core, margin)
            print(json.dumps({"level": margin, "apply": "ok" if ok else "MISMATCH",
                              "evidence": evidence}, ensure_ascii=False), flush=True)
            if not ok:
                results.append({"margin": margin, "error": evidence})
                continue
            time.sleep(args.settle)

            start = time.time()
            end = start + args.seconds
            feed()
            while time.time() < end:
                if watchdog.poll() is not None:
                    break
                feed()
                time.sleep(8)
            results.append({"margin": margin, "startedAt": start, "endedAt": time.time(),
                            "applyEvidence": evidence})
            status = json.loads((session_dir / "status.json").read_text(encoding="utf-8"))
            print(json.dumps({"level": margin, "watchdog": status.get("state"),
                              "reason": status.get("reason")}, ensure_ascii=False), flush=True)
            if status.get("state") not in ("running",):
                break
            # Let it cool before the next level, so every level's boost behaviour
            # starts from a comparable die temperature.
            if margin != args.margins[-1]:
                cooldown_end = time.time() + args.cooldown
                while time.time() < cooldown_end and watchdog.poll() is None:
                    feed()
                    time.sleep(8)
    finally:
        try:
            run([str(PYTHON), str(WATCHDOG), "stop", "--session", args.session, "--token", token,
                 "--reason", "resolution verification complete"])
        except Exception:  # noqa: BLE001
            pass
        watchdog.wait(timeout=60)
        out_handle.close()
        err_handle.close()
        sidecar.terminate()
        try:
            sidecar.wait(timeout=10)
        except subprocess.TimeoutExpired:
            sidecar.kill()
        sidecar_err.close()

    reset_ok, reset_evidence = reset_all()
    print(json.dumps({"state": "done", "levels": results, "reset": "ok" if reset_ok else "FAILED",
                      "resetEvidence": reset_evidence}, ensure_ascii=False), flush=True)
    (session_dir / "resolution_levels.json").write_text(
        json.dumps({"session": args.session, "core": args.core, "levels": results,
                    "resetOk": reset_ok, "resetEvidence": reset_evidence,
                    "rawReadings": str(raw_readings)}, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if reset_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
