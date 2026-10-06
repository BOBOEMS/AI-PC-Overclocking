#!/usr/bin/env python3
"""Archive watchdog evidence into a run directory without copying its heartbeat credential.

Canonical archiver. Copies under runs/*/attempts/ are frozen per-run copies.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import gzip
import json
from pathlib import Path
import shutil
import sys

# --- shared path resolution -------------------------------------------------
# This script lives under <repo>/src/, so the repository root is reached from
# this file rather than from the working directory. All machine-specific paths
# (third-party tools, artifact output) come from src/common/paths.py so that a
# clone works without editing source.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.common import paths as _paths  # noqa: E402


ROOT = _paths.REPO_ROOT
RUNS = _paths.RUN_ROOT


def resolve_run(run: str | None) -> Path:
    if run:
        candidate = Path(run)
        if not candidate.is_absolute():
            candidate = RUNS / run if (RUNS / run).is_dir() else ROOT / run
        if candidate.is_dir():
            return candidate
        raise SystemExit(f"run directory not found: {run}")
    pointer = RUNS / "CURRENT_RUN.txt"
    name = pointer.read_text(encoding="utf-8").strip().rstrip("/").split("/")[-1]
    run_dir = RUNS / name
    if not run_dir.is_dir():
        raise SystemExit(f"CURRENT_RUN.txt points at a missing directory: {run_dir}")
    return run_dir


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("session")
    parser.add_argument("--run", help="Run directory name under runs/. Defaults to runs/CURRENT_RUN.txt.")
    parser.add_argument("--keep-live-credentials", action="store_true",
                        help="Do not strip the token from artifacts/sessions/ copies (default strips it after archiving).")
    args = parser.parse_args()

    source = _paths.SESSION_ROOT / args.session
    if not source.is_dir():
        raise SystemExit(f"watchdog session not found: {source}")
    destination = resolve_run(args.run) / "attempts" / args.session
    destination.mkdir(parents=True, exist_ok=True)

    for name in ("events.jsonl", "status.json", "workload.stdout.log", "workload.stderr.log"):
        shutil.copy2(source / name, destination / name)

    for name in ("session.json", "heartbeat.json"):
        path = source / name
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        data.pop("token", None)
        redacted_name = name.removesuffix(".json") + ".redacted.json"
        (destination / redacted_name).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if not args.keep_live_credentials:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    samples = source / "sensor_samples.jsonl"
    if samples.is_file():
        with samples.open("rb") as input_file:
            with gzip.open(destination / "sensor_samples.jsonl.gz", "wb", compresslevel=6) as output_file:
                shutil.copyfileobj(input_file, output_file)

    events = [
        json.loads(line)
        for line in (source / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    event_by_name = {event["event"]: event for event in events}
    started_at = event_by_name.get("workload_started", {}).get("time")
    finished_at = event_by_name.get("finished", {}).get("time")
    duration = None
    if started_at and finished_at:
        duration = round((parse_time(finished_at) - parse_time(started_at)).total_seconds(), 1)

    stats: dict[str, dict[str, float]] = {}
    first = last = None
    count = 0
    if samples.is_file():
        with samples.open(encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                count += 1
                first = first or row["time"]
                last = row["time"]
                for key, raw_value in row.get("protected_temperatures", {}).items():
                    value = float(raw_value)
                    item = stats.setdefault(key, {"min": value, "max": value})
                    item["min"] = min(item["min"], value)
                    item["max"] = max(item["max"], value)

    summary = {
        "session": args.session,
        "state": event_by_name.get("finished", {}).get("state"),
        "reason": event_by_name.get("finished", {}).get("reason"),
        "workload_duration_seconds": duration,
        "sample_count": count,
        "first_sample_utc": first,
        "last_sample_utc": last,
        "protected_temperature_min_max_c": stats,
    }
    (destination / "sensor_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
