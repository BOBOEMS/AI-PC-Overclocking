#!/usr/bin/env python3
"""Run rycolab Curve Optimizer work under the dead-man watchdog.

Same protection model as ycruncher_controller.py, with one deliberate split.
rycolab needs an elevated process to touch the SMU, and an elevated process is
NOT a child of the assistant's session, so it cannot die together with the
session. Self-feeding would therefore never trip the dead-man switch.

  arm   (elevated)     watchdog + rycolab workload; resets margins after the run
  feed  (as the AI)    heartbeats while the session lives; dies with the session

If the AI session dies, feeding stops, the watchdog kills the workload and
`arm` restores every core to the config baseline.

Two operational modes (``--op``):

  sweep       ``rycolab dev sweep`` — the honest per-core search, whose
              --start/--top/--step/--seconds really are honoured. It does NOT
              create the ``rycolab-find-resume`` scheduled task, so "a reboot
              ends this round" holds by construction. 2026-10-01: the search
              interval is -25..-5 (rounds 3-5 of CPU_CO_RESULT.md), not the
              config default -50..-5, which lies entirely in the region where a
              deeper margin no longer changes the operating point.
  find-quick  ``rycolab find --quick`` — the 2026-10-01 round-2 behaviour, kept
              for reproducing that (invalid) measurement if ever needed.

``--stream`` also starts ``ryzen-smu-cli --stream-system-telemetry`` from
inside the *workload* process, so the per-core effective clocks it writes are
inside the watchdog's Job Object and die with the workload. Rationale: rounds 3
and 5 established that effective frequency, not voltage, is the usable criterion
in the light-load band, and the sweep's own plain output has no frequency column.
"""

from __future__ import annotations

import argparse
import datetime
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
WORKLOAD_WRAPPER = ROOT / "tools" / "rycolab_workload_elevated.ps1"
RYCOLAB_EXE = _paths.RYCOLAB_EXE
RYCOLAB_APPDATA = _paths.RYCOLAB_APPDATA
RYZEN_SMU_CLI = _paths.RYZEN_SMU_CLI
DEFAULT_YCRUNCHER_EXE = _paths.YCRUNCHER_EXE
FIND_RESUME_TASK = "rycolab-find-resume"

# Shipped defaults; the CLI overrides them per run and every effective value is
# echoed into the run log, so the evidence never depends on remembering them.
SWEEP_DEFAULTS = {"start": -25, "top": -5, "step": 5, "seconds": 180}


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def query_find_resume_task() -> str:
    """Evidence that nothing will silently resume a campaign after a reboot."""
    result = subprocess.run(["schtasks.exe", "/query", "/tn", FIND_RESUME_TASK],
                            capture_output=True, text=True, errors="replace", check=False)
    return "present" if result.returncode == 0 else "absent"


def watchdog_cmd(args: argparse.Namespace, workload: list[str]) -> list[str]:
    cmd = [
        sys.executable, str(WATCHDOG), "arm",
        "--session", args.session,
        "--heartbeat-timeout", str(args.heartbeat_timeout),
        "--hard-timeout", str(args.hard_timeout),
        "--sensor-required", "--sensor-stale", str(args.sensor_stale),
        "--temp-strikes-required", str(args.temp_strikes_required),
        "--cpu-temp-stop", str(args.cpu_temp_stop),
        "--cpu-temp-emergency", str(args.cpu_temp_emergency),
        "--dimm-temp-stop", str(args.dimm_temp_stop),
        "--dimm-temp-emergency", str(args.dimm_temp_emergency),
        "--cwd", str(RYCOLAB_APPDATA),
    ]
    if args.sensor_source == "hwinfo-shm":
        cmd += ["--hwinfo-shm"]
    else:
        # Default: the merged file the workload's sidecar keeps fresh (Tctl from
        # the SMU telemetry stream, plus DDR5 SPD Hub temps from HWiNFO when it
        # is up). Armed 30 s stale and 90 s of startup grace, because the
        # telemetry child's block-buffered stdout needs that long for its first
        # complete line: with the old 15 s limit it killed a healthy run at
        # 2026-10-01 14:55.
        cmd += ["--sensor-file", str(ROOT / "watchdog_sessions" / args.session / "sensor_feed.json")]
    cmd += ["--", *workload]
    return cmd


def kill_resume_task() -> list[str]:
    """A reboot must NOT resume a campaign that nothing is watching."""
    notes = []
    for action in ("end", "delete"):
        cmd = ["schtasks.exe", "/" + action, "/tn", FIND_RESUME_TASK]
        if action == "delete":
            cmd.append("/f")
        result = subprocess.run(cmd, capture_output=True, text=True, errors="replace", check=False)
        notes.append(f"{action}:{result.returncode}")
    return notes


def probe(session_dir: Path, label: str) -> None:
    """Record what the SMU actually holds, straight from the hardware."""
    out = session_dir / f"probe_{label}.log"
    with out.open("wb") as handle:
        subprocess.run([str(RYCOLAB_EXE), "dev", "probe"], stdout=handle, stderr=handle, check=False)
    print(f"probe {label} -> {out}", flush=True)


def write_workload_job(args: argparse.Namespace, rycolab_args: list[str]) -> Path:
    """Leave the workload description on disk for the elevated side to read.

    It cannot travel on the command line: PowerShell binds each "--cores"-style
    token as a parameter name, so passing the argv as an array fails outright
    (2026-10-01 14:54, "NamedParameterNotFound -cores"). The elevated side echoes
    this file into its log before starting anything, so the evidence is still
    "what actually ran", not "what was meant to run".
    """
    path = ROOT / "tools" / f"co_workload_{args.op.replace('-', '_')}.json"
    payload = {
        "session": args.session,
        "op": args.op,
        "rycolabExe": str(RYCOLAB_EXE),
        "rycolabArgs": rycolab_args,
        "ryzenSmuCli": str(RYZEN_SMU_CLI),
        "streamIntervalMs": args.stream_interval_ms,
        "noStream": not args.stream,
        "hwinfo": bool(args.hwinfo),
        "perCore": bool(args.per_core),
        "perCoreTargets": args.per_core_targets,
        "sensorSource": args.sensor_source,
        "coreList": args.cores,
        "writtenAt": datetime.datetime.now().astimezone().isoformat(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def workload_and_notes(args: argparse.Namespace) -> tuple[list[str], dict]:
    """The command handed to the watchdog, plus the parameters it encodes."""
    notes: dict = {"op": args.op, "cores": args.cores, "stream": bool(args.stream),
                   "sensorSource": args.sensor_source}
    if args.op == "find-quick":
        if args.start is not None or args.top is not None:
            notes["warning"] = ("find ignores --start/--top; the config's start/top are what run. "
                                "Use --op sweep for a bounded interval.")
        rycolab_args = ["find", "--quick", "--cores", args.cores, "--yes", "--plain"]
        notes["command"] = "rycolab " + " ".join(rycolab_args)
        job = write_workload_job(args, rycolab_args)
        return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(WORKLOAD_WRAPPER), "-Workspace", str(ROOT),
                "-Session", args.session, "-JobFile", str(job),
                "-TelemetryTargets", args.telemetry_targets], notes

    start = args.start if args.start is not None else SWEEP_DEFAULTS["start"]
    top = args.top if args.top is not None else SWEEP_DEFAULTS["top"]
    step = args.step if args.step is not None else SWEEP_DEFAULTS["step"]
    seconds = args.seconds if args.seconds is not None else SWEEP_DEFAULTS["seconds"]
    notes.update({"start": start, "top": top, "step": step, "seconds": seconds,
                  "campaign": args.campaign, "resume": bool(args.resume),
                  "crashKind": args.crash_kind})
    if args.crash_kind != "no-autoresume":
        # `rycolab dev sweep` only ever turns --resume into a repeat of the run
        # that was in progress. A cold reboot therefore loses the earlier cores.
        notes["caveat"] = ("dev sweep has no autoresume task: a cold reboot repeats the "
                           "interrupted run and re-measures the cores after it "
                           "(profile.json is not overwritten).")
    if not args.stream:
        notes["frequencyEvidence"] = "OFF (--no-stream): the sweep's plain output has no frequency column"

    rycolab_args = ["dev", "sweep", "--cores", args.cores,
                    "--start", str(start), "--top", str(top), "--step", str(step),
                    "--seconds", str(seconds), "--campaign", args.campaign, "--plain"]
    if args.resume:
        rycolab_args.append("--resume")
    notes["command"] = "rycolab " + " ".join(rycolab_args)
    job = write_workload_job(args, rycolab_args)

    argv = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(WORKLOAD_WRAPPER),
            "-Workspace", str(ROOT),
            "-Session", args.session,
            "-JobFile", str(job),
            "-TelemetryTargets", args.telemetry_targets]
    if args.per_core:
        argv += ["-PerCore", "-PerCoreTargets", args.per_core_targets]
    return argv, notes


def set_rycolab_plan(confirm_seconds: int | None, soak_seconds: int | None) -> list[str]:
    """Shorten rycolab's own confirm/soak stages, which live in config.json.

    `dev sweep` takes its sweep/fine budgets from --seconds but its confirmation
    and soak budgets from the config, so a per-core screening sweep would still
    burn 1800 s + 600 s per core (43 min/core, as round 6 did). For screening that
    is the wrong trade: the deep stability verdict comes from one all-core 24 GiB
    run, not from six separate 30-minute burns. Returns the plan output lines as
    evidence, and only touches the config when a value is actually given.
    """
    notes: list[str] = []
    for key, value in (("confirmSeconds", confirm_seconds), ("soakSeconds", soak_seconds)):
        if value is None:
            continue
        result = subprocess.run([str(RYCOLAB_EXE), "dev", "plan", "set", key, str(value)],
                                capture_output=True, text=True, errors="replace", check=False)
        notes.append(f"{key}={value} exit={result.returncode}")
    return notes


def cmd_arm(args: argparse.Namespace) -> int:
    session_dir = ROOT / "watchdog_sessions" / args.session
    if session_dir.exists():
        print(json.dumps({"state": "failed", "reason": f"session exists: {args.session}"}), flush=True)
        return 2
    if not RYCOLAB_EXE.is_file():
        print(json.dumps({"state": "failed", "reason": f"rycolab missing: {RYCOLAB_EXE}"}), flush=True)
        return 2
    if not WORKLOAD_WRAPPER.is_file():
        print(json.dumps({"state": "failed", "reason": f"wrapper missing: {WORKLOAD_WRAPPER}"}), flush=True)
        return 2
    if not args.stream and args.sensor_source == "smu-telemetry":
        print(json.dumps({"state": "failed", "reason":
                          "--no-stream removes the sensor source; use --sensor-source hwinfo-shm "
                          "and keep HWiNFO64 running instead"}), flush=True)
        return 2
    elevated = subprocess.run(
        ["net.exe", "session"], capture_output=True, check=False).returncode == 0
    if not elevated:
        print(json.dumps({"state": "failed", "reason": "arm needs an elevated console (SMU writes)"}), flush=True)
        return 9

    workload, notes = workload_and_notes(args)
    notes["findResumeTaskBeforeArm"] = query_find_resume_task()
    plan_notes = set_rycolab_plan(args.confirm_seconds, args.soak_seconds)
    if plan_notes:
        notes["rycolabPlan"] = plan_notes

    session_dir.parent.mkdir(parents=True, exist_ok=True)
    out_handle = (session_dir.parent / f"{args.session}.controller-watchdog.stdout.log").open("wb")
    err_handle = (session_dir.parent / f"{args.session}.controller-watchdog.stderr.log").open("wb")
    print(json.dumps({"state": "arming", "session": args.session, **notes}, ensure_ascii=False), flush=True)
    watchdog = subprocess.Popen(watchdog_cmd(args, workload), cwd=ROOT, stdout=out_handle, stderr=err_handle)

    # rycolab arms its auto-resume task right after the preflight, so keep
    # removing it for a while instead of racing it once.
    deadline = time.monotonic() + 90.0
    while time.monotonic() < deadline and watchdog.poll() is None:
        kill_resume_task()
        time.sleep(5.0)

    try:
        while watchdog.poll() is None:
            time.sleep(1.0)
    except KeyboardInterrupt:
        subprocess.run([sys.executable, str(WATCHDOG), "stop", "--session", args.session,
                        "--token", str((read_json(session_dir / "session.json") or {}).get("token", "")),
                        "--reason", "arm interrupted"], cwd=ROOT, check=False)
    finally:
        out_handle.close()
        err_handle.close()

    reset_code = subprocess.run([str(RYCOLAB_EXE), "dev", "reset"], check=False).returncode
    kill_resume_task()
    probe(session_dir, "after")
    status = read_json(session_dir / "status.json") or {}
    print(json.dumps({"FINAL": {"state": status.get("state"), "reason": status.get("reason"),
                               "elapsedSeconds": status.get("elapsed_seconds"),
                               "resetExit": reset_code,
                               "findResumeTaskAfterRun": query_find_resume_task(),
                               "heartbeatAgeSeconds": status.get("heartbeat_age_seconds")},
                      "watchdogReturnCode": watchdog.returncode}, ensure_ascii=False), flush=True)
    return int(watchdog.returncode or 0)


def cmd_accept(args: argparse.Namespace) -> int:
    """Acceptance run: apply an all-core CO margin, then the user's acceptance load.

    Different topology decision from `arm`: the load here is y-cruncher VT3 at
    24 GiB, i.e. the criterion the user actually accepts, and it runs long enough
    that nobody should be able to walk away from the protection. So this keeps the
    original split - the elevated side only *runs* it, the AI session feeds the
    heartbeat - because an elevated process is not a child of the AI session and a
    self-feeding controller would never trip.

    Order matters for the evidence: probe the hardware first, apply, read back,
    and only then start the load. The margin is always reset at the end, whether
    the run passed, failed or tripped.
    """
    session_dir = ROOT / "watchdog_sessions" / args.session
    if session_dir.exists():
        print(json.dumps({"state": "failed", "reason": f"session exists: {args.session}"}), flush=True)
        return 2
    elevated = subprocess.run(["net.exe", "session"], capture_output=True, check=False).returncode == 0
    if not elevated:
        print(json.dumps({"state": "failed", "reason": "accept needs an elevated console (SMU writes)"}), flush=True)
        return 9

    ycruncher = args.ycruncher_exe
    if not ycruncher.is_file():
        print(json.dumps({"state": "failed", "reason": f"y-cruncher missing: {ycruncher}"}), flush=True)
        return 2

    session_dir.parent.mkdir(parents=True, exist_ok=True)
    # probe() writes into the session dir, so it has to exist before the first
    # probe - the watchdog would create it later, which is too late (2026-10-01
    # 17:49: FileNotFoundError on probe_before.log, no SMU write had happened yet).
    session_dir.mkdir(parents=True, exist_ok=True)
    probe(session_dir, "before")
    before = (session_dir / "probe_before.log").read_text(encoding="utf-8", errors="replace")
    baseline = "Applied right now: CCD0 " + str(args.baseline)
    baseline_ok = baseline in before

    apply_result = subprocess.run(
        [str(RYCOLAB_EXE), "dev", "apply", "--margin", str(args.margin)], check=False,
        capture_output=True, text=True, errors="replace")
    probe(session_dir, "after_apply")
    applied = (session_dir / "probe_after_apply.log").read_text(encoding="utf-8", errors="replace")
    all_cores = applied.count(str(args.margin)) >= 8 or f"CCD0 {args.margin}" in applied

    print(json.dumps({
        "state": "applying", "session": args.session, "margin": args.margin,
        "baseline": args.baseline, "baselineAtProbe": baseline_ok,
        "applyExit": apply_result.returncode,
        "applyStdout": (apply_result.stdout or "").strip().splitlines()[-3:],
        "allCoresAtMargin": all_cores,
    }, ensure_ascii=False), flush=True)
    if not all_cores:
        print(json.dumps({"state": "failed", "reason": "SMU read-back did not show every core at the margin; "
                                                       "refusing to run the acceptance load"}, ensure_ascii=False), flush=True)
        subprocess.run([str(RYCOLAB_EXE), "dev", "reset"], check=False)
        probe(session_dir, "after")
        return 3

    workload = [str(ycruncher), "skip-warnings", "pause:-2", "stress",
                f"-M:{args.memory}", f"-D:{args.test_duration}", f"-TL:{args.test_duration}",
                *args.tests]
    cmd = [
        sys.executable, str(WATCHDOG), "arm",
        "--session", args.session,
        "--heartbeat-timeout", str(args.heartbeat_timeout),
        "--hard-timeout", str(args.test_duration + args.timeout_slack),
        "--hwinfo-shm", "--sensor-required", "--sensor-stale", str(args.sensor_stale),
        "--temp-strikes-required", str(args.temp_strikes_required),
        "--cpu-temp-stop", str(args.cpu_temp_stop),
        "--cpu-temp-emergency", str(args.cpu_temp_emergency),
        "--dimm-temp-stop", str(args.dimm_temp_stop),
        "--dimm-temp-emergency", str(args.dimm_temp_emergency),
        "--cwd", str(ycruncher.parent),
        "--", *workload,
    ]
    print(json.dumps({"state": "arming", "workload": " ".join(workload),
                      "hardTimeoutSeconds": args.test_duration + args.timeout_slack},
                     ensure_ascii=False), flush=True)
    out_handle = (session_dir.parent / f"{args.session}.controller-watchdog.stdout.log").open("wb")
    err_handle = (session_dir.parent / f"{args.session}.controller-watchdog.stderr.log").open("wb")
    watchdog = subprocess.Popen(cmd, cwd=ROOT, stdout=out_handle, stderr=err_handle)
    try:
        while watchdog.poll() is None:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        out_handle.close()
        err_handle.close()

    reset_code = subprocess.run([str(RYCOLAB_EXE), "dev", "reset"], check=False).returncode
    probe(session_dir, "after")
    status = read_json(session_dir / "status.json") or {}
    print(json.dumps({"FINAL": {"state": status.get("state"), "reason": status.get("reason"),
                                "resetExit": reset_code, "marginApplied": args.margin},
                      "watchdogReturnCode": watchdog.returncode}, ensure_ascii=False), flush=True)
    return int(watchdog.returncode or 0)


def cmd_feed(args: argparse.Namespace) -> int:
    session_dir = ROOT / "watchdog_sessions" / args.session
    metadata = read_json(session_dir / "session.json")
    if not metadata:
        print(json.dumps({"state": "failed", "reason": f"no session yet: {args.session}"}), flush=True)
        return 2
    token = str(metadata["token"])
    started = time.monotonic()
    next_report = 0.0
    while True:
        feed = subprocess.run([sys.executable, str(WATCHDOG), "feed", "--session", args.session,
                              "--token", token, "--note", "ai session alive"],
                              cwd=ROOT, capture_output=True, text=True, timeout=8, check=False)
        if feed.returncode != 0:
            print(json.dumps({"state": "feed-failed", "returnCode": feed.returncode,
                             "stderr": (feed.stderr or "")[:200]}), flush=True)
        status = read_json(session_dir / "status.json") or {}
        if time.monotonic() >= next_report:
            print(json.dumps({"state": status.get("state"),
                              "elapsedSeconds": status.get("elapsed_seconds"),
                              "heartbeatAgeSeconds": status.get("heartbeat_age_seconds"),
                              "temperatures": {k: v for k, v in (status.get("last_temperatures") or {}).items()
                                               if "Tctl" in k or "CCD" in k or "SPD" in k},
                              "reason": status.get("reason")}, ensure_ascii=False), flush=True)
            next_report = time.monotonic() + args.report_interval
        if status.get("state") not in (None, "running"):
            print(json.dumps({"state": "done", "finalState": status.get("state")}), flush=True)
            return 0
        if args.max_seconds and time.monotonic() - started > args.max_seconds:
            print(json.dumps({"state": "feeding-stopped", "reason": "feed reached max_seconds"}), flush=True)
            return 3
        time.sleep(args.interval)


def build() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)

    arm = sub.add_parser("arm", help="run elevated: watchdog + rycolab workload")
    arm.add_argument("--session", required=True)
    arm.add_argument("--op", choices=("sweep", "find-quick"), default="sweep")
    arm.add_argument("--cores", default="0-7")
    arm.add_argument("--start", type=int, default=None, help=f"deepest margin (default {SWEEP_DEFAULTS['start']})")
    arm.add_argument("--top", type=int, default=None, help=f"shallowest margin (default {SWEEP_DEFAULTS['top']})")
    arm.add_argument("--step", type=int, default=None, help=f"grid (default {SWEEP_DEFAULTS['step']})")
    arm.add_argument("--seconds", type=int, default=None, help=f"per run (default {SWEEP_DEFAULTS['seconds']})")
    arm.add_argument("--campaign", default=None, help="dev sweep campaign name (default: sweep-<timestamp>)")
    arm.add_argument("--resume", action="store_true")
    arm.add_argument("--crash-kind", choices=("no-autoresume", "autoresume"), default="no-autoresume")
    arm.add_argument("--confirm-seconds", type=int, default=None,
                     help="Override rycolab config confirmSeconds (default: leave config alone). "
                          "Screening wants this short: the deep verdict comes from one all-core run.")
    arm.add_argument("--soak-seconds", type=int, default=None,
                     help="Override rycolab config soakSeconds (default: leave config alone)")
    arm.add_argument("--stream", dest="stream", action="store_true", default=True)
    arm.add_argument("--no-stream", dest="stream", action="store_false")
    arm.add_argument("--stream-interval-ms", type=int, default=500)
    arm.add_argument("--telemetry-targets", default=",".join(f"0:{i}" for i in range(16)),
                     help="Windows logical processors for --stream-system-telemetry (group:processor)")
    arm.add_argument("--per-core", action="store_true", default=False,
                     help="Also start a narrow per-core telemetry stream (see the wrapper's note on 2026-10-01's 70->90.5 C spike)")
    arm.add_argument("--per-core-targets", default="0:0,0:1")
    arm.add_argument("--sensor-source", choices=("smu-telemetry", "hwinfo-shm"), default="smu-telemetry",
                     help="Where the watchdog's protected temperatures come from (default: the sidecar's merged file)")
    arm.add_argument("--hwinfo", dest="hwinfo", action="store_true", default=True,
                     help="Merge HWiNFO shared memory into the sidecar feed (DDR5 SPD Hub temps)")
    arm.add_argument("--no-hwinfo", dest="hwinfo", action="store_false")
    arm.add_argument("--heartbeat-timeout", type=float, default=45.0)
    arm.add_argument("--hard-timeout", type=float, default=14400.0)
    arm.add_argument("--sensor-stale", type=float, default=30.0)
    arm.add_argument("--temp-strikes-required", type=int, default=3,
                     help="Consecutive 2 s samples above a stop threshold before tripping (a single 2026-10-01 sample read 90 C while both cores were idle)")
    arm.add_argument("--cpu-temp-stop", type=float, default=90.0)
    arm.add_argument("--cpu-temp-emergency", type=float, default=95.0)
    arm.add_argument("--dimm-temp-stop", type=float, default=70.0)
    arm.add_argument("--dimm-temp-emergency", type=float, default=75.0)
    arm.set_defaults(func=cmd_arm)

    feed = sub.add_parser("feed", help="run from the AI session: heartbeat only")
    feed.add_argument("--session", required=True)
    feed.add_argument("--interval", type=float, default=10.0)
    feed.add_argument("--report-interval", type=float, default=60.0)
    feed.add_argument("--max-seconds", type=float, default=0.0)
    feed.set_defaults(func=cmd_feed)

    accept = sub.add_parser("accept", help="run elevated: all-core CO margin + the acceptance load")
    accept.add_argument("--session", required=True)
    accept.add_argument("--margin", type=int, default=-20, help="all-core Curve Optimizer margin")
    accept.add_argument("--baseline", type=int, default=0,
                        help="what the BIOS baseline should read; the run records whether it did")
    accept.add_argument("--tests", nargs="+", default=["VT3"], help="y-cruncher stress tests")
    accept.add_argument("--test-duration", type=int, default=1800, help="seconds per test (user criterion: 1800)")
    accept.add_argument("--memory", default="24G", help="y-cruncher -M allocation (user criterion: 24G)")
    accept.add_argument("--ycruncher-exe", type=Path,
                        default=DEFAULT_YCRUNCHER_EXE,
                        help="y-cruncher 0.8.5 in the repo tool tree: the historical throughput numbers came from it")
    accept.add_argument("--heartbeat-timeout", type=float, default=30.0)
    accept.add_argument("--timeout-slack", type=float, default=300.0)
    accept.add_argument("--sensor-stale", type=float, default=20.0)
    accept.add_argument("--temp-strikes-required", type=int, default=3)
    accept.add_argument("--cpu-temp-stop", type=float, default=95.0)
    accept.add_argument("--cpu-temp-emergency", type=float, default=100.0)
    accept.add_argument("--dimm-temp-stop", type=float, default=70.0)
    accept.add_argument("--dimm-temp-emergency", type=float, default=75.0)
    accept.set_defaults(func=cmd_accept)
    return parser


if __name__ == "__main__":
    parsed = build().parse_args()
    if parsed.mode == "arm" and parsed.campaign is None:
        parsed.campaign = "sweep-" + time.strftime("%Y%m%d-%H%M")
    raise SystemExit(parsed.func(parsed))
