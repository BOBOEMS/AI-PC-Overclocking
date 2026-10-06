"""Compare power telemetry across the VT3 sessions of each BIOS configuration.

The question this answers: the PBO "允许" change did not move the PPT CEILING
(~130 W everywhere, checked separately), but it did coincide with VT3 throughput
dropping from a 8.720 median to 8.64-8.66 and with memory bandwidth falling from
61.5 to 58.9 GB/s. So the interesting question is whether the power DELIVERY
changed - a lower sustained package power or a lower current limit would explain
both a slower run and a CPU that boosts less aggressively.

Reads CPU PPT (instantaneous watts), PPT/TDC/EDC percentages and CPU TDC amps
from the watchdog's sensor_samples.jsonl for each session.
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

ROOT = _paths.SESSION_ROOT

SESSIONS = [
    ("BIOS -20 (30 min VT3)", "co-accept-m20-vt3-30m-20261001"),
    ("BIOS -15 (30 min VT3)", "co-accept-m15-vt3-30m-20261001"),
    ("BIOS -15 (180 s r1)", "co-quickcheck-vt3-180s-20261001"),
    ("BIOS -15 (180 s r2)", "co-quickcheck-vt3-180s-r2-20261001"),
    ("BIOS -15 (180 s r3)", "co-quickcheck-vt3-180s-r3-20261001"),
    ("BIOS 0 (180 s series)", "co-baseline-vt3-20261001"),
]

WANTED = [
    ("CPU PPT", "PPT W"),
    ("CPU TDC", "TDC A"),
    ("CPU EDT", "EDC A"),
    ("CPU EDC", "EDC A"),
    ("PPT Limit", "PPT%"),
    ("TDC Limit", "TDC%"),
    ("EDC Limit", "EDC%"),
]


def read(session: str) -> dict[str, list[float]]:
    path = ROOT / session / "sensor_samples.jsonl"
    out: dict[str, list[float]] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        for key, value in (row.get("readings") or {}).items():
            for needle, label in WANTED:
                if needle in key and "Limit" not in key.split(needle)[-1][:6] if needle != "PPT Limit" else needle in key:
                    pass
            # simpler explicit matching
            for needle, label in WANTED:
                if needle == "CPU PPT" and "CPU PPT" in key and "Limit" not in key and "FAST" not in key:
                    out.setdefault(label, []).append(float(value))
                elif needle == "PPT Limit" and "CPU PPT Limit" in key:
                    out.setdefault(label, []).append(float(value))
                elif needle == "CPU TDC" and "CPU TDC" in key and "Limit" not in key:
                    out.setdefault(label, []).append(float(value))
                elif needle == "TDC Limit" and "CPU TDC Limit" in key:
                    out.setdefault(label, []).append(float(value))
                elif needle == "CPU EDC" and "CPU EDC" in key and "Limit" not in key:
                    out.setdefault(label, []).append(float(value))
                elif needle == "EDC Limit" and "CPU EDC Limit" in key:
                    out.setdefault(label, []).append(float(value))
    return out


def main() -> int:
    print(f"{'session':26}{'n':>6}{'PPT med':>9}{'PPT max':>9}{'PPT% med':>10}{'TDC med':>9}{'EDC med':>9}")
    for label, session in SESSIONS:
        data = read(session)
        if not data:
            print(f"{label:26}{'  (missing)':>6}")
            continue
        ppt = data.get("PPT W", [])
        pct = data.get("PPT%", [])
        tdc = data.get("TDC A", [])
        edc = data.get("EDC A", [])
        n = max((len(v) for v in data.values()), default=0)
        def m(v):
            return f"{statistics.median(v):.2f}" if v else "n/a"
        def mx(v):
            return f"{max(v):.2f}" if v else "n/a"
        print(f"{label:26}{n:>6}{m(ppt):>9}{mx(ppt):>9}{m(pct):>10}{m(tdc):>9}{m(edc):>9}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
