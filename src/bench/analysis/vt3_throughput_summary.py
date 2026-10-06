"""Summarise every VT3 first-iteration throughput reading in the repository.

y-cruncher prints 'Running VT3: Passed  Test Speed: N * 10^09 bits / sec' after
`Iteration: 0` - the FIRST complete VT3 pass, which takes ~3-5 s. So the figure is
independent of how long the overall stress run lasts, which is why a 180 s check
is comparable to a 30 min acceptance run.

Run:  python -X utf8 vt3_throughput_summary.py
"""
from __future__ import annotations

import re
from pathlib import Path
import sys

# --- shared path resolution -------------------------------------------------
# This script lives under <repo>/src/, so the repository root is reached from
# this file rather than from the working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.common import paths as _paths  # noqa: E402

ROOT = _paths.REPO_ROOT
PATTERN = re.compile(r"Running VT3: (Passed|Failed)\s+Test Speed:\s+([0-9.]+) \* 10\^09")

# (label, path, condition note)
SOURCES = [
    ("09-29 preflight", ROOT / "runs/20260929-205719-ddr5-6400-30383870-trfc960/attempts/ddr6400-30383870-rfc960-vt3-preflight-20260929/workload.stdout.log", "CO 0, tRFC960"),
    ("09-29 30 min", ROOT / "runs/20260929-205719-ddr5-6400-30383870-trfc960/attempts/ddr6400-30383870-rfc960-vt3-30m-20260929/workload.stdout.log", "CO 0, tRFC960"),
    ("09-30 preflight", ROOT / "runs/20260930-002633-ddr5-6400-30383870-trfc700/attempts/ddr6400-30383870-rfc700-vt3-preflight-20260930/workload.stdout.log", "CO 0, tRFC700"),
    ("09-30 30 min", ROOT / "runs/20260930-002633-ddr5-6400-30383870-trfc700/attempts/ddr6400-30383870-rfc700-vt3-30m-20260930/workload.stdout.log", "CO 0, tRFC700"),
    ("10-01 19:43 30 min", ROOT / "runs/20261001-144528-cpu-co-sweep-core0-1/attempts/co-accept-m15-vt3-30m-20261001/workload.stdout.log", "SMU -15, tRFC960, LatencyKiller OFF"),
    ("10-01 22:25 30 min", ROOT / "sessions/co-accept-m15-vt3-30m-20261001/workload.stdout.log", "BIOS -15, tRFC960, LatencyKiller ON"),
    ("10-01 23:18 180 s", ROOT / "sessions/co-quickcheck-vt3-180s-20261001/workload.stdout.log", "BIOS -15, LatencyKiller off"),
    ("10-01 23:38 180 s", ROOT / "sessions/co-quickcheck-vt3-180s-r2-20261001/workload.stdout.log", "BIOS -15, LatencyKiller off"),
    ("10-01 23:57 180 s", ROOT / "sessions/co-quickcheck-vt3-180s-r3-20261001/workload.stdout.log", "BIOS -15, LatencyKiller off"),
]


def main() -> int:
    print(f"{'run':22}{'verdict':>9}{'bits/sec':>12}  condition")
    values = []
    for label, path, note in SOURCES:
        if not path.exists():
            print(f"{label:22}{'(missing)':>9}{'':>12}  {path}")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        match = PATTERN.search(text)
        if not match:
            print(f"{label:22}{'(no VT3 line)':>9}{'':>12}  {note}")
            continue
        verdict, value = match.group(1), float(match.group(2))
        values.append(value)
        print(f"{label:22}{verdict:>9}{value:12.2f}  {note}")

    if values:
        print()
        print(f"n={len(values)}  min={min(values):.2f}  max={max(values):.2f}  "
              f"mean={sum(values) / len(values):.2f}")
        current = [v for v in values[-3:]]
        print(f"current-state repeats (last 3): {current}  spread={max(current) - min(current):.2f} "
              f"({(max(current) - min(current)) / (sum(current) / 3) * 100:.2f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
