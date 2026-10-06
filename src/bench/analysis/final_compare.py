"""Final comparison: BIOS per-core CO -15 vs CO 0, matched thermal protocol.

Baseline (BIOS -15):
    memory  5-sample memprobe series, task_logs/mem_bios_m15_series/r1..r5.json
            (each sample taken after cooling to Tctl <= 58 C)
    VT3     7 samples: 23:18 / 23:38 / 23:57 (180 s runs) + baseline_series cycles 1-4

Current (BIOS 0, per-core CO disabled, read back as 0,0,0,0,0,0,0,0):
    memory  3 cycles at <=62 C plus 3 cycles at <=58 C, from the run logs
    VT3     6 samples: 8.72, 8.73, 8.75 (<=62 C), 8.67, 8.58 (<=58 C), 8.72

Note on the VT3 numbers: the first two samples of the 58 C group looked like a
downward trend, but the later 8.72 does not continue it, so that was scatter, not
drift. Across six samples the two configurations differ by about half a percent -
no usable difference. The memory figures, by contrast, separate by 4-6% against a
1.5-3.5% noise floor, and all four move the same way.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path
import sys

# --- shared path resolution -------------------------------------------------
# This script lives under <repo>/src/, so the repository root is reached from
# this file rather than from the working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.common import paths as _paths  # noqa: E402

LOGS = _paths.TASK_LOG_ROOT

base_mem = [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted((LOGS / "mem_bios_m15_series").glob("*.json"))]
base_vt3 = [8.78, 8.75, 8.74, 8.76, 8.77, 8.77, 8.74]

cur_mem = [{"copyGBs": 61.687, "scaleGBs": 48.559, "triadGBs": 54.212, "latencyNsMedian": 9.93},
           {"copyGBs": 61.414, "scaleGBs": 47.869, "triadGBs": 53.653, "latencyNsMedian": 10.22},
           {"copyGBs": 61.584, "scaleGBs": 48.216, "triadGBs": 53.461, "latencyNsMedian": 9.86},
           {"copyGBs": 60.901, "scaleGBs": 48.354, "triadGBs": 52.818, "latencyNsMedian": 10.27},
           {"copyGBs": 61.794, "scaleGBs": 48.089, "triadGBs": 53.559, "latencyNsMedian": 9.82},
           {"copyGBs": 59.577, "scaleGBs": 44.036, "triadGBs": 50.547, "latencyNsMedian": 10.20}]
cur_vt3 = [8.72, 8.73, 8.75, 8.67, 8.58, 8.72]


def med(v):
    return statistics.median(v)


print("=== memory bandwidth / latency (memprobe, matched protocol) ===")
print(f"{'metric':10}{'BIOS -15':>22}{'BIOS 0':>22}{'change':>10}{'noise':>9}")
noise = {"copyGBs": 1.46, "scaleGBs": 2.14, "triadGBs": 3.47, "latencyNsMedian": 4.13}
for key, label in (("copyGBs", "copy"), ("scaleGBs", "scale"), ("triadGBs", "triad"),
                   ("latencyNsMedian", "latency")):
    b = [m[key] for m in base_mem if key in m]
    c = [m[key] for m in cur_mem if key in m]
    bm, cm = med(b), med(c)
    print(f"{label:10}{f'{bm:.2f} (n={len(b)})':>22}{f'{cm:.2f} (n={len(c)})':>22}"
          f"{(cm / bm - 1) * 100:>+9.1f}%{noise[key]:>8.1f}%")

print()
print("=== VT3 throughput (first iteration, 180 s) ===")
print(f"  BIOS -15: n={len(base_vt3)} median={med(base_vt3):.3f}  range={min(base_vt3)}-{max(base_vt3)}")
print(f"  BIOS  0: n={len(cur_vt3)} median={med(cur_vt3):.3f}  range={min(cur_vt3)}-{max(cur_vt3)}")
delta = (med(cur_vt3) / med(base_vt3) - 1) * 100
print(f"  change:  {delta:+.2f}%   (within the ~0.5% repeatability of this metric)")
