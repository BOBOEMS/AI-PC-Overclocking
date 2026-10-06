"""Final statistics for an acceptance run, and the -15 vs -20 comparison."""
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

SESSIONS = {
    "-15 (this run)": (_paths.SESSION_ROOT / "co-accept-m15-vt3-30m-20261001"),
    "-20 (earlier)": (_paths.SESSION_ROOT / "co-accept-m20-vt3-30m-20261001"),
}


def load(folder: Path) -> dict[str, list[float]]:
    series: dict[str, list[float]] = {}
    for line in (folder / "sensor_samples.jsonl").read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        for key, value in (row.get("protected_temperatures") or {}).items():
            series.setdefault(key, []).append(float(value))
    return series


def gather(series: dict[str, list[float]], *needles: str) -> list[float]:
    """Flatten every series whose key contains all the needles.

    Note the series VALUES are lists; picking keys and comparing them directly is
    what produced "'<' not supported between instances of 'list' and 'int'".
    """
    out: list[float] = []
    for key, values in series.items():
        if all(n in key for n in needles):
            out.extend(values)
    return out


def main() -> int:
    summary: dict[str, dict] = {}
    for label, folder in SESSIONS.items():
        if not (folder / "sensor_samples.jsonl").exists():
            print(f"{label}: missing")
            continue
        series = load(folder)
        tctl = gather(series, "Tctl")
        ccd1 = gather(series, "CCD1")
        spd = gather(series, "SPD Hub")
        mos = gather(series, "MOS")
        samples = max((len(v) for v in series.values()), default=0)
        stats = {
            "tctlMedian": statistics.median(tctl), "tctlMax": max(tctl),
            "tctlOver90": sum(1 for v in tctl if v > 90),
            "ccd1Max": max(ccd1), "spdMax": max(spd),
            "spdMedian": statistics.median(spd), "mosMax": max(mos),
            "samples": samples,
        }
        summary[label] = stats
        print(f"=== {label}  ({samples} samples) ===")
        print(f"  Tctl      median {stats['tctlMedian']:6.2f}  max {stats['tctlMax']:6.2f}   samples >90 C: {stats['tctlOver90']}")
        print(f"  CCD1      max {stats['ccd1Max']:6.2f}")
        print(f"  SPD Hub   median {stats['spdMedian']:6.2f}  max {stats['spdMax']:6.2f}")
        print(f"  MOS       max {stats['mosMax']:6.2f}")
        print()

    if len(summary) == 2:
        a, b = summary["-15 (this run)"], summary["-20 (earlier)"]
        print("--- -15 minus -20 ---")
        print(f"  Tctl peak   {a['tctlMax'] - b['tctlMax']:+.2f} C")
        print(f"  Tctl median {a['tctlMedian'] - b['tctlMedian']:+.2f} C")
        print(f"  SPD peak    {a['spdMax'] - b['spdMax']:+.2f} C")
    Decision = "PASS" if summary.get("-15 (this run)", {}).get("tctlMax", 999) <= 90 else "FAIL"
    print(f"\ndecision rule (pass AND CPU peak <= 90 C): {Decision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
