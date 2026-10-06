"""Self-test of the telemetry/sensor path the sweep depends on.

Hermetic: it writes the sidecar's feed schema directly, so nothing here touches
the SMU and it cannot perturb a running sweep. Covers:

  1. the feed schema the watchdog now reads (`--sensor-file`), and the arm
     handshake that tolerates a feed without a reading yet;
  2. a missing/stale feed reads as stale rather than silently removing thermal
     protection;
  3. a one-sample 90 C reading does NOT trip (`--temp-strikes-required`), while
     the same reading held across consecutive samples does.

Point 3 exists because of 2026-10-01: three runs (margins -25, -25, -5) tripped
on a single sample that read 90 C while both cores were simultaneously near idle
(132 / 24.7 MHz) and package power was *falling* to 58 W.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
# --- shared path resolution -------------------------------------------------
# This script lives under <repo>/src/, so the repository root is reached from
# this file rather than from the working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.common import paths as _paths  # noqa: E402

ROOT = _paths.REPO_ROOT
TOOLS = ROOT / "tools"
WATCHDOG = TOOLS / "deadman_watchdog.py"
PYTHON = str(_paths.PYTHON_EXE)
SESSION = "selftest-sensor-file-20261001"
SESSION_DIR = ROOT / _paths.SESSION_ROOT / SESSION
FEED = SESSION_DIR / "sensor_feed.json"
WORKLOAD = ROOT / _paths.TASK_LOG_ROOT / "selftest_sleep_workload.py"
ROUND5_STREAM = _paths.RYZEN_SMU_CLI.parent / "ab4-light-repeat" / "stream_r2_m0.jsonl"


def load_watchdog():
    spec = importlib.util.spec_from_file_location("wd", WATCHDOG)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_feed(tctl: float, age: float = 0.0) -> None:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_age_seconds": age,
        "telemetry_age_seconds": age,
        "hwinfo_available": False,
        "temperatures": {"CPU (Tctl/Tdie) [C]": tctl, "CPU CCD1 (Tdie) [C]": tctl},
        "values": {"CPU (Tctl/Tdie) [C]": tctl, "Core 0 Effective Clock [MHz]": 5400.0},
        "note": "selftest",
    }
    FEED.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def main() -> int:
    failures: list[str] = []
    wd = load_watchdog()

    if SESSION_DIR.exists():
        for _ in range(5):
            try:
                shutil.rmtree(SESSION_DIR)
                break
            except PermissionError:
                time.sleep(1)
        else:
            print(f"cannot reset {SESSION_DIR}")
            return 3
    SESSION_DIR.mkdir(parents=True)
    WORKLOAD.write_text("import time\ntime.sleep(120)\n", encoding="utf-8")

    # ---- 1. feed schema + arm handshake --------------------------------------
    write_feed(58.0, age=0.0)
    temperatures, values, age = wd.read_sensor_feed(FEED)
    stops, emergencies, matched = wd.evaluate_temperatures(temperatures)
    print("feed -> temperatures:", temperatures, "age:", age)
    print("        matched:", matched, "stops:", stops)
    if not matched:
        failures.append("the watchdog's SENSOR_LIMITS do not match the feed schema")
    if age != 0.0:
        failures.append(f"feed age should be 0.0, got {age}")

    no_feed = SESSION_DIR / "does-not-exist.json"
    temperatures, age = wd.sensor_file_readings(no_feed, time.time())
    print("arm handshake with no feed yet ->", temperatures, age)
    if temperatures or age != 0.0:
        failures.append("the arm handshake must tolerate a feed that does not exist yet")
    try:
        wd.sensor_file_readings(no_feed, time.time() - 600)
        failures.append("a feed still missing after the grace window did not raise")
    except (OSError, ValueError) as error:
        print("after grace ->", type(error).__name__, str(error)[:60])

    # ---- 3. one-sample spike vs sustained spike ------------------------------
    def arm_and_probe(strike_temp: float, strikes_required: int, hold_samples: int) -> tuple[str, list[dict]]:
        if SESSION_DIR.exists():
            shutil.rmtree(SESSION_DIR)
        SESSION_DIR.mkdir(parents=True)
        write_feed(70.0)
        arm_cmd = [
            PYTHON, str(WATCHDOG), "arm",
            "--session", SESSION,
            "--heartbeat-timeout", "15", "--hard-timeout", "40",
            "--sensor-required", "--sensor-stale", "30",
            "--temp-strikes-required", str(strikes_required),
            "--cpu-temp-stop", "90", "--cpu-temp-emergency", "95",
            "--dimm-temp-stop", "70", "--dimm-temp-emergency", "75",
            "--sensor-file", str(FEED),
            "--cwd", str(ROOT), "--", PYTHON, str(WORKLOAD),
        ]
        watchdog = subprocess.Popen(arm_cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        token = None
        sent = 0
        deadline = time.time() + 60
        while time.time() < deadline and watchdog.poll() is None:
            if token is None and (SESSION_DIR / "session.json").exists():
                token = json.loads((SESSION_DIR / "session.json").read_text(encoding="utf-8"))["token"]
                write_feed(70.0)
            if token:
                subprocess.run([PYTHON, str(WATCHDOG), "feed", "--session", SESSION, "--token", token],
                               capture_output=True, check=False)
            if sent < hold_samples:
                write_feed(strike_temp)
                sent += 1
            else:
                write_feed(70.0)
            time.sleep(2)
        if watchdog.poll() is None:
            watchdog.terminate()
            watchdog.wait(timeout=10)
        status = json.loads((SESSION_DIR / "status.json").read_text(encoding="utf-8")) if (SESSION_DIR / "status.json").exists() else {}
        events = [json.loads(line) for line in (SESSION_DIR / "events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        return status.get("state", "?"), events

    # One 90.4 C sample, 3 required: must survive (the artifact case).
    state, events = arm_and_probe(90.4, strikes_required=3, hold_samples=1)
    ignored = [e for e in events if e["event"] == "thermal_glitch_ignored"]
    print(f"one-sample 90.4 C with strikes=3 -> state={state}, glitch_ignored={len(ignored)}")
    if state == "tripped" and any("90.4" in str(e.get("reason", "")) for e in events[-1:]):
        failures.append("a single 90 C sample tripped a 3-strike watchdog")
    if not ignored:
        failures.append("the ignored single sample was not recorded as evidence")

    # Sustained 90.4 C: must trip.
    state, events = arm_and_probe(90.4, strikes_required=3, hold_samples=8)
    tripped = [e for e in events if e["event"] == "finished" and e.get("state") == "tripped"]
    print(f"sustained 90.4 C with strikes=3 -> state={state}, tripped_events={len(tripped)}")
    if state != "tripped":
        failures.append("a sustained 90.4 C reading did not trip")

    if failures:
        print("RESULT: FAIL")
        for failure in failures:
            print("  -", failure)
        return 1
    print("RESULT: PASS - feed schema, arm handshake, and one-sample-vs-sustained trip logic")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
