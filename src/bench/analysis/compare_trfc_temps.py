"""Did tightening tRFC1 (2120 -> 960 -> 700 -> 620) improve temperatures?

Reads the WATCHDOG temperature samples from each historical VT3 run, decompressing
.gz where the archive step compressed them. Every run is the same load
(y-cruncher stress -M:24G, VT3) and the same HWiNFO source, so the columns are
comparable; the other BIOS differences that moved alongside tRFC are noted so no
one reads a difference here as caused by tRFC alone.

tRFC1 values, and where they came from:
  2120  EXPO default, seen in the 2026-09-28 backup-1 screenshot
   960  set by the user on 2026-10-01 (and used on 09-29 for the 9.10e9 run)
   700  set on 2026-09-30
   620  tried on 09-29 with the tighter 30-36-36-72 primary timings
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
    ("09-29 tRFC620 30-36-36-72 (FAILED 6.87)", r"watchdog_sessions\ddr6400-303672-rfc620-vt3-30m-20260929"),
    ("09-29 tRFC960 30-38-38-70 (9.10)", r"watchdog_sessions\ddr6400-30383870-rfc960-vt3-30m-20260929"),
    ("09-30 tRFC700 30-38-38-70 (9.08)", r"watchdog_sessions\ddr6400-30383870-rfc700-vt3-30m-20260930"),
    ("10-01 tRFC960 BIOS-15 (8.76)", r"watchdog_sessions\co-accept-m15-vt3-30m-20261001"),
    ("10-02 tRFC960 BIOS0 (8.72)", r"watchdog_sessions\co-baseline-vt3-20261001"),
]

WANTED = [("Tctl", "Tctl"), ("CCD1", "CCD1"), ("SPD Hub", "SPD Hub"), ("MOS", "MOS")]


def load(folder: Path) -> list[dict]:
    """Read the sample log, skipping anything that is not valid JSON.

    The tRFC620 run's file is 61 KB of NUL bytes (truncated when that run failed),
    so a plain json.loads per line raises on the first line. Counting the skipped
    lines matters: it is the honest way to report a damaged sample rather than
    silently showing an empty row.
    """
    plain = folder / "sensor_samples.jsonl"
    packed = folder / "sensor_samples.jsonl.gz"
    text = ""
    if plain.exists():
        text = plain.read_text(encoding="utf-8", errors="replace")
    elif packed.exists():
        text = gzip.open(packed, "rt", encoding="utf-8", errors="replace").read()
    else:
        return []

    rows, skipped = [], 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except (ValueError, TypeError):
            skipped += 1
    if skipped:
        print(f"  note: {folder.name}: skipped {skipped} unparseable line(s)")
    return rows


def temperatures(rows: list[dict]) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for row in rows:
        for key, value in (row.get("protected_temperatures") or {}).items():
            for needle, label in WANTED:
                if needle in key:
                    out.setdefault(label, []).append(float(value))
    return out


def main() -> int:
    print(f"{'run':40}{'n':>6}{'Tctl med':>10}{'Tctl max':>10}{'CCD1 max':>10}"
          f"{'SPD med':>9}{'SPD max':>9}{'MOS max':>9}")
    for label, rel in RUNS:
        rows = load(ROOT / rel)
        if not rows:
            print(f"{label:40}{'missing':>6}")
            continue
        t = temperatures(rows)
        def med(k):
            return statistics.median(t[k]) if t.get(k) else float("nan")
        def mx(k):
            return max(t[k]) if t.get(k) else float("nan")
        print(f"{label:40}{len(rows):>6}{med('Tctl'):>10.2f}{mx('Tctl'):>10.2f}{mx('CCD1'):>10.2f}"
              f"{med('SPD Hub'):>9.2f}{mx('SPD Hub'):>9.2f}{mx('MOS'):>9.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
