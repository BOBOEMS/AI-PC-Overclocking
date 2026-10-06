#!/usr/bin/env python3
"""Run y-cruncher under the HWiNFO-backed dead-man watchdog.

Canonical controller. The copies under runs/*/attempts/ are frozen evidence of
what actually ran in those sessions - do not edit them, use this one instead.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

# --- shared path resolution -------------------------------------------------
# This script lives under <repo>/src/, so the repository root is reached from
# this file rather than from the working directory. All machine-specific paths
# (third-party tools, artifact output) come from src/common/paths.py so that a
# clone works without editing source.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.common import paths as _paths  # noqa: E402


ROOT = _paths.REPO_ROOT
DEFAULT_YCRUNCHER_DIR = _paths.YCRUNCHER_DIR
WATCHDOG = _paths.SRC_ROOT / "watchdog" / "deadman_watchdog.py"
SESSION_ROOT = _paths.SESSION_ROOT


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def summarize_status(status: dict | None) -> dict:
    if not status:
        return {"state": "status-unavailable"}
    temperatures = status.get("last_temperatures", {})
    summary = {"state": status.get("state"), "elapsedSeconds": status.get("elapsed_seconds")}
    for key, value in temperatures.items():
        if "CPU (Tctl/Tdie)" in key:
            summary["cpuTctlTdieC"] = value
        elif "CPU CCD1" in key:
            summary["cpuCcd1C"] = value
        elif "SPD Hub" in key:
            summary.setdefault("dimmSpdHubC", []).append(value)
    if "heartbeat_age_seconds" in status:
        summary["heartbeatAgeSeconds"] = status["heartbeat_age_seconds"]
    if status.get("reason"):
        summary["reason"] = status["reason"]
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("session", help="watchdog session name, written under artifacts/sessions/")
    parser.add_argument("--tests", nargs="+", choices=("FFT", "VT3"), default=("FFT", "VT3"))
    parser.add_argument("--test-duration", type=int, default=1800, help="Seconds per test.")
    parser.add_argument("--memory", default="24G", help="y-cruncher -M size, e.g. 24G. Check free physical RAM first.")
    parser.add_argument("--tool-dir", type=Path, default=DEFAULT_YCRUNCHER_DIR)
    parser.add_argument("--heartbeat-timeout", type=float, default=30.0)
    parser.add_argument("--timeout-slack", type=float, default=300.0, help="Extra seconds on the hard deadline.")
    parser.add_argument("--cpu-temp-stop", type=float, default=95.0)
    parser.add_argument("--cpu-temp-emergency", type=float, default=100.0)
    parser.add_argument("--dimm-temp-stop", type=float, default=80.0)
    parser.add_argument("--dimm-temp-emergency", type=float, default=85.0)
    parser.add_argument("--feed-interval", type=float, default=8.0)
    parser.add_argument("--report-interval", type=float, default=55.0)
    args = parser.parse_args()
    total_limit = args.test_duration * len(args.tests)

    ycruncher_dir = args.tool_dir
    ycruncher = ycruncher_dir / "y-cruncher.exe"
    session_dir = SESSION_ROOT / args.session
    if session_dir.exists():
        parser.error(f"watchdog session already exists: {args.session}")
    if not ycruncher.is_file():
        parser.error(f"y-cruncher executable not found: {ycruncher}")
    if args.dimm_temp_stop >= args.dimm_temp_emergency:
        parser.error("DIMM emergency limit must be above the stop limit")
    if args.cpu_temp_stop >= args.cpu_temp_emergency:
        parser.error("CPU emergency limit must be above the stop limit")

    watchdog_stdout = session_dir.parent / f"{args.session}.controller-watchdog.stdout.log"
    watchdog_stderr = session_dir.parent / f"{args.session}.controller-watchdog.stderr.log"
    session_dir.parent.mkdir(parents=True, exist_ok=True)
    out_handle = watchdog_stdout.open("wb")
    err_handle = watchdog_stderr.open("wb")

    command = [
        sys.executable,
        str(WATCHDOG),
        "arm",
        "--session",
        args.session,
        "--heartbeat-timeout",
        str(args.heartbeat_timeout),
        "--hard-timeout",
        str(total_limit + args.timeout_slack),
        "--hwinfo-shm",
        "--sensor-required",
        "--sensor-stale",
        "8",
        "--cpu-temp-stop",
        str(args.cpu_temp_stop),
        "--cpu-temp-emergency",
        str(args.cpu_temp_emergency),
        "--dimm-temp-stop",
        str(args.dimm_temp_stop),
        "--dimm-temp-emergency",
        str(args.dimm_temp_emergency),
        "--cwd",
        str(ycruncher_dir),
        "--",
        str(ycruncher),
        "skip-warnings",
        "pause:-2",
        "stress",
        f"-M:{args.memory}",
        f"-D:{args.test_duration}",
        f"-TL:{total_limit}",
        *args.tests,
    ]
    watchdog = subprocess.Popen(command, cwd=ROOT, stdout=out_handle, stderr=err_handle)
    metadata_path = session_dir / "session.json"
    deadline = time.monotonic() + 20.0
    metadata = None
    while time.monotonic() < deadline and watchdog.poll() is None:
        metadata = read_json(metadata_path)
        if metadata:
            break
        time.sleep(0.25)
    if not metadata:
        if watchdog.poll() is None:
            watchdog.terminate()
            watchdog.wait(timeout=10)
        out_handle.close()
        err_handle.close()
        print(json.dumps({"state": "failed-to-arm", "watchdogReturnCode": watchdog.returncode}))
        return 2

    token = str(metadata["token"])
    started = time.monotonic()
    next_feed = started
    next_report = started + args.report_interval
    tests_label = " + ".join(args.tests)
    print(
        json.dumps(
            {
                "state": "armed",
                "session": args.session,
                "workload": f"y-cruncher {args.memory} {tests_label} ({args.test_duration // 60}m each)",
                "limits": {
                    "cpuStopC": args.cpu_temp_stop,
                    "dimmStopC": args.dimm_temp_stop,
                    "heartbeatTimeoutS": args.heartbeat_timeout,
                    "hardTimeoutS": total_limit + args.timeout_slack,
                },
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    try:
        while watchdog.poll() is None:
            now = time.monotonic()
            if now >= next_feed:
                feed_result = subprocess.run(
                    [
                        sys.executable,
                        str(WATCHDOG),
                        "feed",
                        "--session",
                        args.session,
                        "--token",
                        token,
                        "--note",
                        "controller active",
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=8,
                    check=False,
                )
                if feed_result.returncode != 0:
                    print(json.dumps({"state": "heartbeat-feed-error", "returnCode": feed_result.returncode}), flush=True)
                next_feed = now + args.feed_interval
            if now >= next_report:
                print(json.dumps(summarize_status(read_json(session_dir / "status.json")), ensure_ascii=False), flush=True)
                next_report = now + args.report_interval
            time.sleep(0.25)
    except KeyboardInterrupt:
        stop = subprocess.run(
            [
                sys.executable,
                str(WATCHDOG),
                "stop",
                "--session",
                args.session,
                "--token",
                token,
                "--reason",
                "controller interrupted",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        if stop.returncode != 0 and watchdog.poll() is None:
            watchdog.terminate()
        watchdog.wait(timeout=45)

    status = read_json(session_dir / "status.json")
    out_handle.close()
    err_handle.close()
    print(json.dumps({"FINAL": summarize_status(status), "watchdogReturnCode": watchdog.returncode}, ensure_ascii=False), flush=True)
    return int(watchdog.returncode or 0)


if __name__ == "__main__":
    raise SystemExit(main())
