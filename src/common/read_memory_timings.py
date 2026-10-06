#!/usr/bin/env python3
"""Read-only HWiNFO shared-memory probe for memory / fabric / DRAM voltage readings.

Chapter 1 requires recorded *actual readings*, not BIOS input values. Run this
before arming a stress test and save the output into the run directory.
"""

from __future__ import annotations


import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

# --- shared path resolution -------------------------------------------------
# This script lives under <repo>/src/, so the repository root is reached from
# this file rather than from the working directory. All machine-specific paths
# (third-party tools, artifact output) come from src/common/paths.py so that a
# clone works without editing source.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.common import paths as _paths  # noqa: E402
from src.common import hwinfo_shared  # noqa: E402


KEYS = (
    "tRFC", "tRC", "tCL", "tRCD", "tRP", "tRAS", "tRRD", "tWTR", "tFAW", "tREFI",
    "command rate", "memory clock", "memclk", "uclk", "fclk", "mclk", "soc", "vdd",
    "vpp", "dram", "spd hub", "latency", "内存", "时序", "频率", "电压", "温度",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, help="Write the filtered snapshot JSON here.")
    parser.add_argument("--all", action="store_true", help="Dump every reading, not just memory-related ones.")
    args = parser.parse_args()

    try:
        snapshot = hwinfo_shared.read_snapshot()
    except RuntimeError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        print("HWiNFO64 must be running with Shared Memory enabled.", file=sys.stderr)
        return 1

    rows = [
        reading
        for reading in snapshot["readings"]
        if args.all
        or any(key.lower() in f"{reading['sensor']}|{reading['label']}".lower() for key in KEYS)
    ]
    payload = {
        "readAtUtc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "readAtLocal": datetime.now().astimezone().isoformat(timespec="seconds"),
        "pollingPeriodMs": snapshot["polling_period"],
        "readingCount": len(rows),
        "readings": rows,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out} ({len(rows)} readings)")
    else:
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
