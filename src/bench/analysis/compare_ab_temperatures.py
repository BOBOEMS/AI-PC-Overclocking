"""Compare the two engine A/B arms from their sensor_samples.jsonl.

Reads the HWiNFO-sourced protected temperatures that the watchdog logged for each
arm and reports the same statistics for both, so the SSE3-vs-AVX-512 temperature
difference is a number rather than an impression.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

# --- shared path resolution -------------------------------------------------
# This script lives under <repo>/src/, so the repository root is reached from
# this file rather than from the working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.common import paths as _paths  # noqa: E402

ROOT = _paths.SESSION_ROOT
ARMS = [
    ("AVX-512 (24-ZN5 ~ Komari)", ROOT / "co-ab-zn5-20261001" / "sensor_samples.jsonl"),
    ("SSE3 (04-P4P)", ROOT / "co-ab-p4p-20261001" / "sensor_samples.jsonl"),
]


def series(path: Path, needle: str) -> list[float]:
    values: list[float] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        for key, value in (row.get("protected_temperatures") or {}).items():
            if needle in key:
                values.append(float(value))
    return values


def median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def main() -> int:
    print(f"{'arm':28} {'n':>4} {'min':>7} {'median':>7} {'p90':>7} {'max':>7} {'>=85':>6} {'>=90':>6}")
    peaks: dict[str, float] = {}
    for label, path in ARMS:
        if not path.exists():
            print(f"{label:28} MISSING {path}")
            return 1
        tctl = series(path, "Tctl")
        if not tctl:
            print(f"{label:28} no Tctl samples")
            return 1
        p90 = sorted(tctl)[int(len(tctl) * 0.9) - 1]
        over85 = sum(1 for v in tctl if v >= 85)
        over90 = sum(1 for v in tctl if v >= 90)
        peaks[label] = max(tctl)
        print(f"{label:28} {len(tctl):4d} {min(tctl):7.2f} {median(tctl):7.2f} {p90:7.2f} {max(tctl):7.2f} {over85:6d} {over90:6d}")

    zn5, p4p = (peaks[label] for label, _ in ARMS)
    print()
    print(f"peak difference (AVX-512 - SSE3): {zn5 - p4p:+.2f} C")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
