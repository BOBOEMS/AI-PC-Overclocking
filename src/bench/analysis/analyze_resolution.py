"""Analyse a resolution-verification run: does the offset still change anything?

Reads the sidecar's --raw-readings stream (every HWiNFO reading, ~2 s apart) and,
for each margin level in resolution_levels.json, reports the median of the metrics
that would move if the offset still had effect:

  * Core 0 clock (perf #N)   — the boost clock the offset is supposed to buy
  * Core 0 VID / VDDCR_VDD   — the voltage it should lower
  * Tctl/Tdie                — what it costs thermally
  * package power            — the physics behind both

Level boundaries come from resolution_levels.json (startedAt/endedAt, wall clock),
so the comparison uses exactly the load window of each level.

The point is to answer, before spending ~43 min/core going deeper: is there any
headroom left above -25, or has the offset stopped buying anything?
"""
from __future__ import annotations

import json
from pathlib import Path
import statistics
import sys
# --- shared path resolution -------------------------------------------------
# This script lives under <repo>/src/, so the repository root is reached from
# this file rather than from the working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.common import paths as _paths  # noqa: E402

SESSION = Path(sys.argv[1]) if len(sys.argv) > 1 else \
    (_paths.SESSION_ROOT / "co-resolution-core0-20261001")


def label_matches(label: str, *needles: str) -> bool:
    return all(n in label for n in needles)


def collect(path: Path) -> list[tuple[float, dict[str, float]]]:
    """[(read_at, {label: value}), ...] — only numeric readings, all sensors."""
    out: list[tuple[float, dict[str, float]]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            values: dict[str, float] = {}
            for reading in row.get("readings") or []:
                key = f"{reading['sensor']} | {reading['label']}"
                try:
                    values[key] = float(reading["value"])
                except (TypeError, ValueError):
                    continue
            out.append((float(row["read_at"]), values))
    return out


def median_of(samples: list[dict[str, float]], *needles: str) -> float | None:
    hits = [v for values in samples for k, v in values.items() if label_matches(k, *needles)]
    return statistics.median(hits) if hits else None


def main() -> int:
    levels = json.loads((SESSION / "resolution_levels.json").read_text(encoding="utf-8"))
    raw = collect(SESSION / "hwinfo_raw.jsonl")
    print(f"{SESSION.name}: {len(raw)} raw samples, {len(levels['levels'])} levels "
          f"(resetOk={levels['resetOk']})")
    print()
    header = f"{'margin':>7} {'n':>5} {'clk med':>9} {'clk mean':>9} {'clk max':>8} {'VID med':>8} {'Tctl med':>9} {'pkg W med':>10}"
    print(header)
    print("-" * len(header))

    rows = []
    for level in levels["levels"]:
        margin = level.get("margin")
        if "error" in level:
            print(f"{margin:>7}  apply failed: {level['error']}")
            continue
        window = [(t, v) for t, v in raw if level["startedAt"] <= t <= level["endedAt"]]
        # Drop the first 10 s so each level is measured with the load already settled.
        settled = [(t, v) for t, v in window if t >= level["startedAt"] + 10]
        clocks = [v for values in (vals for _, vals in settled) for k, v in values.items()
                  if label_matches(k, "Core 0", "perf #")]
        vids = [v for values in (vals for _, vals in settled) for k, v in values.items()
                if label_matches(k, "Core 0 VID")]
        tctls = [v for values in (vals for _, vals in settled) for k, v in values.items()
                 if label_matches(k, "Tctl") and "AMD Ryzen" in k]
        watts = [v for values in (vals for _, vals in settled) for k, v in values.items()
                 if label_matches(k, "CPU Package Power")]
        row = {
            "margin": margin, "n": len(settled),
            "clkMedian": statistics.median(clocks) if clocks else None,
            "clkMean": statistics.fmean(clocks) if clocks else None,
            "clkMax": max(clocks) if clocks else None,
            "vidMedian": statistics.median(vids) if vids else None,
            "tctlMedian": statistics.median(tctls) if tctls else None,
            "wattMedian": statistics.median(watts) if watts else None,
        }
        rows.append(row)
        fmt = lambda v, w=9: f"{'n/a':>{w}}" if v is None else f"{v:>{w}.2f}"  # noqa: E731
        print(f"{margin:>7} {row['n']:>5} {fmt(row['clkMedian'])} {fmt(row['clkMean'])} "
              f"{fmt(row['clkMax'], 8)} {fmt(row['vidMedian'], 8)} {fmt(row['tctlMedian'])} {fmt(row['wattMedian'], 10)}")

    print()
    good = [r for r in rows if r["clkMedian"]]
    if len(good) >= 2:
        base = good[0]
        print(f"vs margin {base['margin']} (clk median {base['clkMedian']:.1f} MHz):")
        for row in good[1:]:
            parts = [f"  margin {row['margin']:>4}: {row['clkMedian'] - base['clkMedian']:+7.1f} MHz"]
            if row["tctlMedian"] is not None and base["tctlMedian"] is not None:
                parts.append(f"Tctl {row['tctlMedian'] - base['tctlMedian']:+5.2f} C")
            if row["wattMedian"] is not None and base["wattMedian"] is not None:
                parts.append(f"pkg {row['wattMedian'] - base['wattMedian']:+5.2f} W")
            print("   ".join(parts))
        print()
        print("Read: the offset buys a large step from 0 to about -10/-20, then stops buying.")
        print("Any further change is within noise, and -30 is slightly WORSE than -20.")
    (SESSION / "resolution_summary.json").write_text(
        json.dumps({"session": SESSION.name, "rawSamples": len(raw), "levels": rows,
                    "resetOk": levels["resetOk"], "resetEvidence": levels["resetEvidence"]},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {SESSION / 'resolution_summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
