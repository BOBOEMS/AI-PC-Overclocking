"""Compare what the CPU was actually doing in two VT3 runs.

Same loader, same sensors, so a throughput difference must show up somewhere:
either the core clocks / power / temperature were different (CPU side), or they
match and the difference is on the memory side. This distinguishes the two
without needing another 30-minute run.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path
# --- shared path resolution -------------------------------------------------
# This script lives under <repo>/src/, so the repository root is reached from
# this file rather than from the working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.common import paths as _paths  # noqa: E402

RUNS = {
    "SMU -15 (19:43, 9.21e9)": (_paths.TASK_LOG_ROOT / "smu_m15_archive"),
    "BIOS -15 (22:25, 7.93e9)": (_paths.SESSION_ROOT / "co-accept-m15-vt3-30m-20261001"),
}

# Substrings that identify the readings worth comparing across runs.
WANTED = [
    ("Core 0 频率 (perf", "Core0 clock"),
    ("Core 0 T0 有效频率", "Core0 T0 eff"),
    ("Core 0 T1 有效频率", "Core0 T1 eff"),
    ("CPU Package Power", "Package power"),
    ("CPU PPT", "PPT"),
    ("CPU (Tctl/Tdie)", "Tctl"),
    ("CPU CCD1 (Tdie)", "CCD1"),
    ("Core 0 VID", "Core0 VID"),
    ("Core 0 功率", "Core0 power"),
    ("CPU VDDCR_VDD 电压", "VDDCR_VDD"),
    ("CPU VDDCR_SOC 电压", "VDDCR_SOC"),
    ("Infinity Fabric 频率", "FCLK"),
    ("内存控制器频率", "UCLK"),
]


def series_by_label(folder: Path) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for line in (folder / "sensor_samples.jsonl").read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        for key, value in (row.get("readings") or {}).items():
            out.setdefault(key, []).append(float(value))
    return out


def main() -> int:
    data = {}
    for label, folder in RUNS.items():
        if not (folder / "sensor_samples.jsonl").exists():
            print(f"missing sensor_samples.jsonl: {folder}")
            return 2
        data[label] = series_by_label(folder)

    labels = list(RUNS)
    print(f"{'reading':18}{labels[0][:22]:>24}{labels[1][:22]:>24}{'delta':>10}")
    for needle, title in WANTED:
        values = {}
        for label in labels:
            hits = [v for k, vs in data[label].items() if needle in k for v in vs]
            values[label] = statistics.median(hits) if hits else None
        a, b = values[labels[0]], values[labels[1]]
        fa = "n/a" if a is None else f"{a:.2f}"
        fb = "n/a" if b is None else f"{b:.2f}"
        fd = "" if (a is None or b is None) else f"{b - a:+.2f}"
        print(f"{title:18}{fa:>24}{fb:>24}{fd:>10}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
