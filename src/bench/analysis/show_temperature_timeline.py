"""Print the temperature/clock timeline of one CO session using HWiNFO's own data.

HWiNFO reads the same CPU sensors but through its own polling loop, so it keeps
working when ryzen-smu-cli's PM-table telemetry goes stale (which is exactly what
happened at 2026-10-01 15:26 when two concurrent SMU streams starved the feed).
Keys are matched on substrings that are ASCII-safe, because the raw HWiNFO labels
carry CJK unit names that do not survive a GBK console.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def find(values: dict, *needles: str) -> float | None:
    for key, value in values.items():
        if all(needle in key for needle in needles):
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    return None


def main() -> int:
    folder = Path(sys.argv[1])
    path = folder / "sensor_samples.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    print(f"{folder.name}: {len(rows)} samples")
    print("  time      pmTctl  hwTctl  hwCCD1  coreClk  SPDhub")
    for row in rows:
        t = row.get("protected_temperatures") or {}
        pm = t.get("CPU (Tctl/Tdie) [C]")
        hw = next((v for k, v in t.items() if "Tctl" in k and "AMD Ryzen" in k), None)
        ccd = next((v for k, v in t.items() if "CCD1 (Tdie)" in k and "AMD Ryzen" in k), None)
        spd = next((v for k, v in t.items() if "SPD Hub" in k), None)
        clk = find(row.get("readings") or {}, "Core 0 ", "perf")
        if clk is None:
            clk = find(row.get("readings") or {}, "Core 0 ")
        fmt = lambda v: "  -   " if v is None else f"{v:7.2f}"  # noqa: E731
        print(f"  {row['time'][11:19]} {fmt(pm)} {fmt(hw)} {fmt(ccd)} {fmt(clk)} {fmt(spd)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
