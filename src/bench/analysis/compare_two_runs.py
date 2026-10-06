"""BIOS-era vs SMU-era -15 comparison. Usage: compare_two_runs.py <dirA> <dirB>

Both runs are all-core -15 with the same acceptance load (30 min VT3 24 GiB) and
the same HWiNFO temperature source, so if the two delivery paths are equivalent
the numbers should agree. A disagreement is the interesting case: it would mean
the BIOS setting is not the same -15 that was validated at runtime.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path


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
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    a_dir, b_dir = Path(sys.argv[1]), Path(sys.argv[2])
    a, b = stats(a_dir), stats(b_dir)
    print(f"A = {a_dir}")
    print(f"B = {b_dir}")
    print()
    print(f"{'metric':24}{'A':>12}{'B':>12}{'A-B':>10}")
    for key, label in (("n", "samples"), ("tctl_med", "Tctl median C"), ("tctl_max", "Tctl peak C"),
                       ("tctl_over90", "Tctl samples >90 C"), ("ccd1_max", "CCD1 peak C"),
                       ("spd_med", "SPD Hub median C"), ("spd_max", "SPD Hub peak C"),
                       ("mos_max", "MOS peak C")):
        fmt = "{:d}" if key in ("n", "tctl_over90") else "{:.2f}"
        print(f"{label:24}{fmt.format(a[key]):>12}{fmt.format(b[key]):>12}{a[key] - b[key]:>+10.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
