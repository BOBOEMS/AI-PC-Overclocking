#!/usr/bin/env python3
"""Run one y-cruncher engine exactly the way rycolab runs it, and log everything.

Why this exists rather than calling the engine directly: for the SSE3-vs-AVX-512
temperature A/B agreed on 2026-10-01, the *only* permitted difference between the
two arms is the engine binary. That means replicating rycolab's invocation
precisely (rycolab/src/Rycolab.Core/Engines/YCruncherEngine.cs):

  * config file next to the engine's working directory, with LogicalCores,
    1 GiB, SecondsPerTest 60, StopOnError and the same 8 tests;
  * command line `pause:-2 colors:0 priority:-1 config "<cfg>"`;
  * **stdin kept open** — y-cruncher loads the config and then parks on its
    interactive menu ("Press any key to continue"). With stdin at DEVNULL it gets
    EOF, never starts the test, and burns CPU at the menu (observed 2026-10-01
    16:18). The runner writes a newline and keeps the stream alive;
  * a **wall-clock duration**, after which the whole process tree is killed.
    y-cruncher with `SecondsTotal: 0` reports "Run Forever" in its own header and
    does not stop by itself: a 15 s per-test limit still had it on iteration 15
    after 230 s. rycolab behaves the same way — it kills the engine at its
    deadline (`Stop()` -> `_p.Kill(true)`), which is why its output shows a fixed
    180 s window. The runner therefore reproduces the wall-clock window and
    reports a clean stop rather than an error;
  * affinity pinned, after a short settle, to both SMT siblings of the target
    physical core (rycolab: `3L << LogicalProcessor(core)`);
  * **suspend/resume cycling**: rycolab suspends the process for 1 s roughly
    every 10 s. This is not a detail — it is the mechanism that produces the
    90-93 C cycle this A/B is trying to attribute, so both arms must have it.
    The `suspensions` count is reported the same way rycolab reports it, so the
    comparison against `co-valid-20261001-core0-1b` stays valid.

Output is captured to <workdir>/engine_output.log (tee of stdout+stderr) and the
engine's own exit code is propagated, so a self-exit crash shows up as a
non-zero exit exactly as rycolab would see it.
"""

from __future__ import annotations

import argparse
import ctypes
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

# --- shared path resolution -------------------------------------------------
# This script lives under <repo>/src/, so the repository root is reached from
# this file rather than from the working directory. All machine-specific paths
# (third-party tools, artifact output) come from src/common/paths.py so that a
# clone works without editing source.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.common import paths as _paths  # noqa: E402

RYCOLAB_BINARIES = _paths.RYCOLAB_BINARIES
DEFAULT_TESTS = ("BKT", "BBP", "SFTv4", "SNT", "SVT", "FFTv4", "N63", "VT3")

ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
ntdll.NtSuspendProcess.argtypes = [ctypes.c_void_p]
ntdll.NtSuspendProcess.restype = ctypes.c_long
ntdll.NtResumeProcess.argtypes = [ctypes.c_void_p]
ntdll.NtResumeProcess.restype = ctypes.c_long


def write_config(path: Path, logical_core: int, tests: tuple[str, ...],
                 seconds_per_test: int, memory_bytes: int) -> None:
    """The exact shape rycolab writes (CoreCycler's generated config)."""
    body = f"""\
{{
    Action : "StressTest"
    StressTest : {{
        AllocateLocally : "true"
        LogicalCores : [{logical_core}]
        TotalMemory : {memory_bytes}
        SecondsPerTest : {seconds_per_test}
        SecondsTotal : 0
        StopOnError : "true"
        Tests : [
{chr(10).join('            "' + t + '"' for t in tests)}
        ]
    }}
}}
"""
    path.write_text(body, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, help="engine binary name, e.g. '24-ZN5 ~ Komari' or 04-P4P")
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--physical-core", type=int, default=0)
    parser.add_argument("--logical-core", type=int, default=None,
                        help="OS logical processor for the config's LogicalCores (default: 2 * physical core)")
    parser.add_argument("--tests", nargs="+", default=list(DEFAULT_TESTS))
    parser.add_argument("--seconds-per-test", type=int, default=60)
    parser.add_argument("--memory-mib", type=int, default=1024)
    parser.add_argument("--suspend", dest="suspend", action="store_true", default=True)
    parser.add_argument("--no-suspend", dest="suspend", action="store_false")
    parser.add_argument("--suspend-every", type=float, default=10.0)
    parser.add_argument("--suspend-for", type=float, default=1.0)
    parser.add_argument("--duration", type=float, default=0.0,
                        help="Wall-clock seconds to run before killing the engine tree (0 = until it stops by itself). "
                             "Required in practice: y-cruncher with SecondsTotal 0 runs forever.")
    args = parser.parse_args()

    engine = RYCOLAB_BINARIES / (args.engine if args.engine.lower().endswith(".exe") else args.engine + ".exe")
    if not engine.is_file():
        print(f"engine not found: {engine}", file=sys.stderr)
        return 2
    logical = args.logical_core if args.logical_core is not None else args.physical_core * 2

    args.workdir.mkdir(parents=True, exist_ok=True)
    config_path = args.workdir / "stressTest.cfg"
    write_config(config_path, logical, tuple(args.tests), args.seconds_per_test, args.memory_mib * 1024 * 1024)
    output_path = args.workdir / "engine_output.log"

    info = {
        "engine": engine.name,
        "engineKind": "AVX-512 (Zen 5)" if "ZN5" in engine.name else "SSE3",
        "physicalCore": args.physical_core,
        "logicalCoreInConfig": logical,
        "affinityMask": hex(3 << logical),
        "suspend": args.suspend,
        "suspendEverySeconds": args.suspend_every,
        "config": str(config_path),
        "tests": list(args.tests),
        "secondsPerTest": args.seconds_per_test,
        "memoryMiB": args.memory_mib,
        "startedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    print("RUNNER " + json.dumps(info, ensure_ascii=False), flush=True)

    command = [str(engine), "pause:-2", "colors:0", "priority:-1", "config", str(config_path)]
    with output_path.open("w", encoding="utf-8", errors="replace", buffering=1) as log:
        log.write("COMMAND " + " ".join(f'"{c}"' if " " in c else c for c in command) + "\n")
        log.write("INFO " + json.dumps(info, ensure_ascii=False) + "\n")
        process = subprocess.Popen(
            command,
            cwd=str(RYCOLAB_BINARIES),      # rycolab runs the engine from its binaries dir
            # stdin stays an OPEN pipe, not DEVNULL. y-cruncher loads the config and
            # then parks on its interactive menu ("Press any key to continue"):
            # with DEVNULL it gets EOF and never starts the test (observed
            # 2026-10-01 16:18, the smoke run sat at the menu burning CPU until it
            # was killed). rycolab keeps the stream open for the same reason.
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        def pump() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                log.write(line)

        pump_thread = threading.Thread(target=pump, daemon=True)
        pump_thread.start()

        # Keep stdin "alive" so the engine never waits on the console. Writing a
        # newline once is enough to leave the menu; repeating it is harmless
        # (while the stress test runs there is nothing reading stdin) and covers
        # the case where the first write lands before the menu is drawn.
        stop_stdin = threading.Event()

        def keepalive() -> None:
            while not stop_stdin.is_set() and process.poll() is None:
                try:
                    if process.stdin and not process.stdin.closed:
                        process.stdin.write("\n")
                        process.stdin.flush()
                except (OSError, ValueError):
                    return
                stop_stdin.wait(3.0)

        stdin_thread = threading.Thread(target=keepalive, daemon=True)
        stdin_thread.start()

        # rycolab waits 900 ms before touching affinity, then pins both siblings.
        time.sleep(0.9)
        PROCESS_SUSPEND_RESUME = 0x0800
        PROCESS_SET_INFORMATION = 0x0200
        PROCESS_QUERY_INFORMATION = 0x0400
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        process_handle = kernel32.OpenProcess(
            PROCESS_SUSPEND_RESUME | PROCESS_SET_INFORMATION | PROCESS_QUERY_INFORMATION, False, process.pid)
        if not process_handle:
            log.write(f"WARN OpenProcess failed (err {ctypes.get_last_error()}); affinity and suspend disabled\n")
            process_handle = None
        else:
            if not kernel32.SetProcessAffinityMask(ctypes.c_void_p(process_handle), ctypes.c_size_t(3 << logical)):
                log.write(f"WARN SetProcessAffinityMask failed (err {ctypes.get_last_error()})\n")

        suspensions = 0
        stop_suspending = threading.Event()

        def suspend_loop() -> None:
            """rycolab: sleep ~10 s, suspend 1 s, resume. This is the mechanism that
            produces the 90-93 C cycle, so both A/B arms must run it."""
            nonlocal suspensions
            while not stop_suspending.is_set() and process.poll() is None:
                if stop_suspending.wait(args.suspend_every) or process.poll() is not None:
                    return
                try:
                    ntdll.NtSuspendProcess(ctypes.c_void_p(process_handle))
                    time.sleep(args.suspend_for)
                    ntdll.NtResumeProcess(ctypes.c_void_p(process_handle))
                    suspensions += 1
                except Exception:  # noqa: BLE001 - the process may have died in between
                    pass

        suspender = None
        if args.suspend:
            suspender = threading.Thread(target=suspend_loop, daemon=True)
            suspender.start()

        try:
            if args.duration and args.duration > 0:
                try:
                    exit_code = process.wait(timeout=args.duration)
                    stopped_by = "engine exit"
                except subprocess.TimeoutExpired:
                    stopped_by = f"duration {args.duration:g}s reached"
                    # Kill the TREE: the engine spawns worker processes, and killing
                    # only the parent leaves them running (observed 2026-10-01).
                    subprocess.run(["taskkill.exe", "/F", "/T", "/PID", str(process.pid)],
                                   capture_output=True, check=False)
                    process.wait(timeout=30)
                    # A deliberate stop is a clean result, exactly like rycolab's
                    # Stop() which kills the process and reports Clean.
                    exit_code = 0
            else:
                exit_code = process.wait()
                stopped_by = "engine exit"
        except KeyboardInterrupt:
            subprocess.run(["taskkill.exe", "/F", "/T", "/PID", str(process.pid)],
                           capture_output=True, check=False)
            exit_code = process.wait()
            stopped_by = "interrupted"
        finally:
            stop_suspending.set()
            stop_stdin.set()
            if suspender:
                suspender.join(timeout=3)
            pump_thread.join(timeout=3)
            try:
                if process.stdin and not process.stdin.closed:
                    process.stdin.close()
            except (OSError, ValueError):
                pass
            if process_handle:
                kernel32.CloseHandle(ctypes.c_void_p(process_handle))
            log.write(f"RUNNER END exit={exit_code} suspensions={suspensions} stoppedBy={stopped_by}\n")

    print(f"RUNNER END exit={exit_code} suspensions={suspensions} stoppedBy={stopped_by}", flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
