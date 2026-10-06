#!/usr/bin/env python3
"""Run one y-cruncher engine pinned to a core, under the dead-man watchdog.

Purpose: the SSE3-vs-AVX-512 temperature A/B agreed with the user on
2026-10-01. Same core, same work, same sampling; only the engine binary differs.

  * `24-ZN5 ~ Komari` = y-cruncher's Zen 5 build, the AVX-512 binary rycolab
    picks as its sweep engine ("the widest vector binary the CPU runs, the one
    that finds the errors"). This is what produced the 90-93 C cycle measured in
    runs/20261001-144528-cpu-co-sweep-core0-1/THERMAL_90C_DIAGNOSIS.md.
  * `04-P4P` = the SSE3 build rycolab uses for its soak stage, the one its
    docs describe as reaching fMax at light load.

The engine binaries are the ones under %LOCALAPPDATA%\\rycolab, not the
repository's y-cruncher 0.8.5: mixing the two versions would break the
comparison against the existing rounds (HANDOFF section 5 warns about exactly
this).

The work item is configured the way rycolab configures it -- a stressTest.cfg
with SecondsPerTest, a single LogicalCore and StopOnError -- so the instruction
mix, the 60 s test slots and the per-test pause/resume pattern are all
identical. Temperature comes from HWiNFO shared memory (`--hwinfo-shm`), the
only path that stayed reliable all afternoon, with --temp-strikes-required
matching the current watchdog policy.
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
WATCHDOG = ROOT / "tools" / "deadman_watchdog.py"
ENGINE_RUNNER = ROOT / "tools" / "engine_runner.py"
RYCOLAB_BINARIES = _paths.RYCOLAB_BINARIES
ENGINES = {
    "zn5": "24-ZN5 ~ Komari.exe",
    "p4p": "04-P4P.exe",
}
DEFAULT_TESTS = ("BKT", "BBP", "SFTv4", "SNT", "SVT", "FFTv4", "N63", "VT3")


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def summarize_status(status: dict | None) -> dict:
    if not status:
        return {"state": "status-unavailable"}
    summary = {"state": status.get("state"), "elapsedSeconds": status.get("elapsed_seconds")}
    for key, value in (status.get("last_temperatures") or {}).items():
        if "Tctl" in key and "AMD Ryzen" in key:
            summary["cpuTctlTdieC"] = value
        elif "CCD1" in key and "AMD Ryzen" in key:
            summary["cpuCcd1C"] = value
        elif "SPD Hub" in key:
            summary.setdefault("dimmSpdHubC", []).append(value)
    if status.get("reason"):
        summary["reason"] = status["reason"]
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", help="watchdog session name under watchdog_sessions/")
    parser.add_argument("--engine", choices=sorted(ENGINES), required=True,
                        help="zn5 = 24-ZN5 ~ Komari (AVX-512), p4p = 04-P4P (SSE3)")
    parser.add_argument("--core", type=int, default=0, help="logical core to pin (rycolab pins one thread)")
    parser.add_argument("--tests", nargs="+", default=list(DEFAULT_TESTS))
    parser.add_argument("--seconds-per-test", type=int, default=60)
    parser.add_argument("--memory-mib", type=int, default=1024)
    parser.add_argument("--cpu-temp-stop", type=float, default=95.0)
    parser.add_argument("--cpu-temp-emergency", type=float, default=100.0)
    parser.add_argument("--dimm-temp-stop", type=float, default=70.0)
    parser.add_argument("--dimm-temp-emergency", type=float, default=75.0)
    parser.add_argument("--temp-strikes-required", type=int, default=3)
    parser.add_argument("--no-suspend", action="store_true",
                        help="Disable the 1 s suspend every ~10 s. Not for the A/B: the suspend/resume pattern is the mechanism under test.")
    parser.add_argument("--heartbeat-timeout", type=float, default=45.0)
    parser.add_argument("--timeout-slack", type=float, default=120.0)
    parser.add_argument("--feed-interval", type=float, default=8.0)
    parser.add_argument("--report-interval", type=float, default=60.0)
    args = parser.parse_args()

    engine_path = RYCOLAB_BINARIES / ENGINES[args.engine]
    session_dir = ROOT / "watchdog_sessions" / args.session
    if session_dir.exists():
        parser.error(f"watchdog session already exists: {args.session}")
    if not engine_path.is_file():
        parser.error(f"engine not found: {engine_path}")

    engine_path = RYCOLAB_BINARIES / ENGINES[args.engine]
    session_dir = ROOT / "watchdog_sessions" / args.session
    if session_dir.exists():
        parser.error(f"watchdog session already exists: {args.session}")
    if not engine_path.is_file():
        parser.error(f"engine not found: {engine_path}")

    work_dir = session_dir / "work"
    total_seconds = args.seconds_per_test * len(args.tests)
    # The watchdog validates --cwd up front and does not create it, so a missing
    # directory fails the arm with NotADirectoryError (hit 2026-10-01 17:1x).
    work_dir.mkdir(parents=True, exist_ok=True)

    # The engine runs under tools/engine_runner.py, which replicates rycolab's
    # invocation (config shape, stdin redirect, affinity to both SMT siblings,
    # the 1 s suspend every ~10 s). Doing it here instead would drop the
    # suspend/resume pattern, which is the very mechanism being attributed.
    runner_args = [
        sys.executable, str(ENGINE_RUNNER),
        "--engine", ENGINES[args.engine],
        "--workdir", str(work_dir),
        "--physical-core", str(args.core),
        "--seconds-per-test", str(args.seconds_per_test),
        "--memory-mib", str(args.memory_mib),
        "--tests", *args.tests,
        # y-cruncher does not stop on its own with SecondsTotal 0 ("Run Forever"),
        # and rycolab kills it at its deadline, so the wall-clock window is explicit.
        "--duration", str(total_seconds),
    ]
    if args.no_suspend:
        runner_args.append("--no-suspend")

    command = [
        sys.executable, str(WATCHDOG), "arm",
        "--session", args.session,
        "--heartbeat-timeout", str(args.heartbeat_timeout),
        "--hard-timeout", str(total_seconds * 3 + args.timeout_slack),
        "--hwinfo-shm", "--sensor-required", "--sensor-stale", "20",
        "--temp-strikes-required", str(args.temp_strikes_required),
        "--cpu-temp-stop", str(args.cpu_temp_stop),
        "--cpu-temp-emergency", str(args.cpu_temp_emergency),
        "--dimm-temp-stop", str(args.dimm_temp_stop),
        "--dimm-temp-emergency", str(args.dimm_temp_emergency),
        "--cwd", str(work_dir),
        "--", *runner_args,
    ]

    session_dir.parent.mkdir(parents=True, exist_ok=True)
    out_handle = (session_dir.parent / f"{args.session}.controller-watchdog.stdout.log").open("wb")
    err_handle = (session_dir.parent / f"{args.session}.controller-watchdog.stderr.log").open("wb")
    metadata_path = session_dir / "session.json"

    watchdog = subprocess.Popen(command, cwd=ROOT, stdout=out_handle, stderr=err_handle)
    deadline = time.monotonic() + 30.0
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
        status = read_json(session_dir / "status.json") or {}
        print(json.dumps({"state": "failed-to-arm", "status": status,
                          "watchdogReturnCode": watchdog.returncode}, ensure_ascii=False))
        return 2

    token = str(metadata["token"])
    print(json.dumps({
        "state": "armed", "session": args.session, "engine": ENGINES[args.engine],
        "engineKind": "AVX-512 (Zen 5)" if args.engine == "zn5" else "SSE3",
        "core": args.core, "tests": list(args.tests),
        "secondsPerTest": args.seconds_per_test, "totalSeconds": total_seconds,
        "memoryMiB": args.memory_mib, "suspend": not args.no_suspend,
        "runner": str(ENGINE_RUNNER), "workDir": str(work_dir),
        "limits": {"cpuStopC": args.cpu_temp_stop, "cpuEmergencyC": args.cpu_temp_emergency,
                   "dimmStopC": args.dimm_temp_stop, "strikesRequired": args.temp_strikes_required},
    }, ensure_ascii=False), flush=True)

    next_feed = time.monotonic()
    next_report = time.monotonic() + args.report_interval
    try:
        while watchdog.poll() is None:
            now = time.monotonic()
            if now >= next_feed:
                subprocess.run([sys.executable, str(WATCHDOG), "feed", "--session", args.session,
                                "--token", token, "--note", f"ab controller ({args.engine})"],
                               cwd=ROOT, capture_output=True, text=True, timeout=8, check=False)
                next_feed = now + args.feed_interval
            if now >= next_report:
                print(json.dumps(summarize_status(read_json(session_dir / "status.json")), ensure_ascii=False), flush=True)
                next_report = now + args.report_interval
            time.sleep(0.25)
    except KeyboardInterrupt:
        subprocess.run([sys.executable, str(WATCHDOG), "stop", "--session", args.session,
                        "--token", token, "--reason", "ab controller interrupted"],
                       cwd=ROOT, capture_output=True, text=True, timeout=8, check=False)
        watchdog.wait(timeout=45)

    out_handle.close()
    err_handle.close()
    print(json.dumps({"FINAL": summarize_status(read_json(session_dir / "status.json")),
                      "watchdogReturnCode": watchdog.returncode}, ensure_ascii=False), flush=True)
    return int(watchdog.returncode or 0)


if __name__ == "__main__":
    raise SystemExit(main())
