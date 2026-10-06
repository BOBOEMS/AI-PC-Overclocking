import sys
from pathlib import Path

# --- shared path resolution -------------------------------------------------
# This script lives under <repo>/src/, so the repository root is reached from
# this file rather than from the working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.common import paths as _paths  # noqa: E402
"""BIOS-side vs SMU-side -15 comparison for the same acceptance load.

Both runs: all-core -15, 30 min VT3 24 GiB, HWiNFO temperature source.
  A = tonight, CO applied in BIOS (per-core -15), verified by two independent readers
  B = earlier tonight, CO applied at runtime via the SMU (margin -15), BIOS was 0

If the two delivery paths are equivalent, these should agree; the interesting
outcome is if they do NOT, because that would mean the BIOS setting is not the
same -15 we validated.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

RUNS = {
    "BIOS -15": (_paths.SESSION_ROOT / "co-accept-m15-vt3-30m-20261001"),
    "SMU -15": (_paths.RUN_ROOT / "20261001-144528-cpu-co-sweep-core0-1\attempts\co-accept-m15-vt3-30m-20261001"),
}
THROUGHPUT = {"BIOS -15": 7.93e9, "SMU -15": 9.21e9}


def stats(folder: Path) -> dict:
    rows = [json.loads(line) for line in (folder / "sensor_samples.jsonl").read_text(
        encoding="utf-8", errors="replace").splitlines() if line.strip()]
    series: dict[str, list[float]] = {}
    for row in rows:
        for key, value in (row.get("protected_temperatures") or {}).items():
            series.setdefault(key, []).append(float(value))

    def gather(*needles: str) -> list[float]:
        out: list[float] = []
        for key, values in series.items():
            if all(n in key for n in needles):
                out.extend(values)
        return out

    tctl, ccd1, spd, mos = gather("Tctl"), gather("CCD1"), gather("SPD Hub"), gather("MOS")
    return {
        "n": len(rows), "tctl_med": statistics.median(tctl), "tctl_max": max(tctl),
        "tctl_over90": sum(1 for v in tctl if v > 90),
        "ccd1_max": max(ccd1), "spd_med": statistics.median(spd), "spd_max": max(spd),
        "mos_max": max(mos),
    }


def main() -> int:
    data = {}
    for label, folder in RUNS.items():
        if not (folder / "sensor_samples.jsonl").exists():
            print(f"{label}: no sensor_samples.jsonl at {folder}")
            return 2
        data[label] = stats(folder)

    rows = [
        ("samples", "n", "{:d}"),
        ("Tctl median C", "tctl_med", "{:.2f}"),
        ("Tctl peak C", "tctl_max", "{:.2f}"),
        ("Tctl samples >90 C", "tctl_over90", "{:d}"),
        ("CCD1 peak C", "ccd1_max", "{:.2f}"),
        ("SPD Hub median C", "spd_med", "{:.2f}"),
        ("SPD Hub peak C", "spd_max", "{:.2f}"),
        ("MOS peak C", "mos_max", "{:.2f}"),
    ]
    print(f"{'metric':22} {'BIOS -15':>12} {'SMU -15':>12} {'delta':>10}")
    for title, key, fmt in rows:
        a, b = data["BIOS -15"][key], data["SMU -15"][key]
        print(f"{title:22} {fmt.format(a):>12} {fmt.format(b):>12} {a - b:>+10.2f}")
    ta, tb = THROUGHPUT["BIOS -15"], THROUGHPUT["SMU -15"]
    print(f"{'VT3 bits/sec':22} {ta:12.3g} {tb:12.3g} {(ta/tb - 1)*100:>+9.1f}%")
    print()
    print("Reading: temperature is +1.6 C and throughput -13.9%. A same-direction")
    print("temperature move is consistent with a warmer room, but a 14% throughput")
    print("gap is larger than ambient alone explains, so the two delivery paths are")
    print("NOT established as equivalent and need a same-session control.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
