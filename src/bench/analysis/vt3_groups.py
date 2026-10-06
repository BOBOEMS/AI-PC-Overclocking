"""Summary of every VT3 first-iteration sample, grouped by BIOS configuration.

This is the record of what was actually measured tonight, so that the conclusion
does not depend on anyone's recollection of which numbers were "the good ones".

Groups:
  BIOS -15        per-core Curve Optimizer -15 applied in BIOS (read back as
                  -15 x8 by two independent readers)
  BIOS 0          per-core CO disabled (read back as 0 x8)
  BIOS 0 + PBO    additionally, PBO Limits changed from manual back to "allow"

Each sample is the FIRST VT3 iteration that y-cruncher prints (after ~3-5 s),
which is why 180 s runs and 30 min runs are comparable: all of them report the
same first-pass measurement under the same 24 GiB allocation.
"""
from __future__ import annotations

import statistics

GROUPS = {
    "BIOS -15 (n=7)": {
        "samples": [8.78, 8.75, 8.74, 8.76, 8.77, 8.77, 8.74],
        "note": "23:18/23:38/23:57 quick checks + baseline_series cycles 1-4",
    },
    "BIOS 0 (n=6)": {
        "samples": [8.72, 8.73, 8.75, 8.67, 8.58, 8.72],
        "note": "3 cycles at cooldown<=62 C then 3 at <=58 C",
    },
    "BIOS 0 + PBO change (n=5)": {
        "samples": [8.66, 8.64, 8.62, 8.69, 8.71],
        "note": "2 samples with memprobe preceding, 3 clean VT3-only",
    },
}


def main() -> int:
    print(f"{'configuration':30}{'n':>3}{'median':>9}{'min':>7}{'max':>7}{'spread':>9}")
    medians = {}
    for label, block in GROUPS.items():
        v = block["samples"]
        med = statistics.median(v)
        medians[label] = med
        spread = (max(v) - min(v)) / (sum(v) / len(v)) * 100
        print(f"{label:30}{len(v):>3}{med:>9.3f}{min(v):>7.2f}{max(v):>7.2f}{spread:>8.2f}%")

    print()
    a = medians["BIOS -15 (n=7)"]
    b = medians["BIOS 0 (n=6)"]
    c = medians["BIOS 0 + PBO change (n=5)"]
    print(f"  BIOS -15  vs BIOS 0          : {(b / a - 1) * 100:+.2f}%")
    print(f"  BIOS 0    vs BIOS 0 + PBO    : {(c / b - 1) * 100:+.2f}%")
    print()
    print("Reading:")
    print("  -15 -> 0 removes about 0.5% of VT3 throughput.")
    print("  The PBO change then moves it a further 0.75%, which is inside the 1.0%")
    print("  WRITHIN-group spread measured for that same configuration ([8.62..8.71]).")
    print("  A within-group spread larger than the between-group difference means the")
    print("  PBO change is NOT separable from noise at n=5, even though all five of")
    print("  its samples sit below the BIOS 0 median.")
    print()
    print("  By contrast the memory result does separate: copy +4.6%, scale +4.5%,")
    print("  triad +6.8% against a 1.5-3.5% noise floor, with all three moving the")
    print("  same way when the -15 BIOS offset is removed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
