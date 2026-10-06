"""Compare the VT3 temperature TRAJECTORY, not just the summary.

09-29 (tRFC960, 105W) reached 9.10e9 with Tctl median 79.50 C; today's runs on the
same nominal settings sit at 8.72-8.76 with Tctl median 82.0-82.8. Before blaming a
setting, check the obvious alternative: heat soak. Tonight the machine has run a
dozen-plus stress rounds back to back, so the room, chassis and cooler may all be
warmer than they were on 09-29.

If the difference were pure soak, the two trajectories should look like the same
curve shifted up. If they look like different curve SHAPES (e.g. today climbing
throughout while 09-29 plateaus), that points at a real difference in behaviour
rather than a warmer room.
"""
from __future__ import annotations

import gzip
import json
import statistics
from pathlib import Path
import sys

# --- shared path resolution -------------------------------------------------
# This script lives under <repo>/src/, so the repository root is reached from
# this file rather than from the working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.common import paths as _paths  # noqa: E402

ROOT = _paths.REPO_ROOT

RUNS = [
    ("09-29 tRFC960 105W (9.10e9)", r"watchdog_sessions\ddr6400-30383870-rfc960-vt3-30m-20260929"),
    ("10-01 tRFC960 BIOS-15 (8.76e9)", r"watchdog_sessions\co-accept-m15-vt3-30m-20261001"),
    ("10-02 tRFC960 BIOS0 (8.72e9)", r"watchdog_sessions\co-baseline-vt3-20261001"),
]

TCTL = "Tctl"


def load(folder: Path) -> list[tuple[float, float]]:
    """Return (elapsed_seconds, Tctl) pairs."""
    plain = folder / "sensor_samples.jsonl"
    packed = folder / "sensor_samples.jsonl.gz"
    if plain.exists():
        text = plain.read_text(encoding="utf-8", errors="replace")
    elif packed.exists():
        text = gzip.open(packed, "rt", encoding="utf-8", errors="replace").read()
    else:
        return []

    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        tctl = None
        for key, value in (row.get("protected_temperatures") or {}).items():
            if "Tctl" in key:
                tctl = float(value)
                break
        if tctl is not None:
            rows.append((row.get("elapsed_seconds", len(rows)), tctl))
    return rows


def main() -> int:
    print(f"{'run':32}{'start':>8}{'2 min':>8}{'5 min':>8}{'10 min':>8}{'end':>8}{'median':>8}{'max':>7}")
    for label, rel in RUNS:
        rows = load(ROOT / rel)
        if not rows:
            print(f"{label:32}{'(missing)':>8}")
            continue
        series = [v for _, v in rows]
        n = len(series)

        def at(fraction: float) -> float:
            idx = min(n - 1, max(0, int(n * fraction)))
            return series[idx]

        print(f"{label:32}{series[0]:>8.2f}{at(0.07):>8.2f}{at(0.17):>8.2f}"
              f"{at(0.33):>8.2f}{series[-1]:>8.2f}{statistics.median(series):>8.2f}{max(series):>7.2f}")

    print()
    print("Note: the 10-02 row has only ~180 samples (3 min), because each collection")
    print("cycle overwrote the session directory, so its '10 min' columns saturate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
