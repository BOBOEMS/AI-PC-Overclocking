"""Self-test of the sidecar sensor path the sweep now depends on.

Hermetic: a fake telemetry writer stands in for ryzen-smu-cli (the same JSON
schema, a new sequence number every interval), so nothing here touches the SMU
and the test cannot perturb a running sweep. Verifies:

  1. the sidecar's merged file is a schema the watchdog's `--sensor-file` parser
     accepts, with CPU protection present;
  2. the watchdog does not refuse an arm where the sidecar file exists but has no
     reading yet (the arm handshake);
  3. a stalled telemetry stream ends up reported stale, so the run trips rather
     than silently losing thermal protection;
  4. HWiNFO's shared memory merges in as DDR5 coverage when it is running.

HWiNFO being down is not a failure: coverage is optional, staleness is not.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import threading
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
SIDECAR = TOOLS / "sidecar_sensors.py"
PYTHON = str(_paths.PYTHON_EXE)
SESSION = "selftest-sidecar-20261001"
SESSION_DIR = ROOT / _paths.SESSION_ROOT / SESSION
TELEMETRY = SESSION_DIR / "smu_telemetry.jsonl"
FEED = SESSION_DIR / "sensor_feed.json"
HWINFO_PROBE = TOOLS / "hwinfo_shared.py"


def load_watchdog():
    spec = importlib.util.spec_from_file_location("wd", WATCHDOG)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeTelemetry:
    """Writes ryzen-smu-cli-shaped lines, with a switch to stop mid-test."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.sequence = 0
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self.stop.is_set():
            self.sequence += 1
            record = {
                "kind": "system-telemetry", "schemaVersion": 2, "sequence": self.sequence,
                "timestampUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "vcoreVolts": 1.34, "cpuTemperatureCelsius": 60.0 + self.sequence % 5,
                "temperatureSource": "tctl-tdie", "packagePowerWatts": 70.0,
                "packagePowerSource": "amd-rapl-package-energy",
                "targets": [{"group": 0, "processor": 0, "effectiveMhz": 5400.0}],
            }
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
            time.sleep(0.5)

    def start(self) -> None:
        self.thread.start()


def read_feed() -> dict:
    return json.loads(FEED.read_text(encoding="utf-8"))


def main() -> int:
    failures: list[str] = []
    wd = load_watchdog()

    if SESSION_DIR.exists():
        # A previous aborted run can leave its stderr handle open (WinError 32).
        for _ in range(5):
            try:
                shutil.rmtree(SESSION_DIR)
                break
            except PermissionError:
                time.sleep(1)
        else:
            print(f"cannot reset {SESSION_DIR}: another process still holds a file there")
            return 3
    SESSION_DIR.mkdir(parents=True)

    hwinfo_up = subprocess.run([PYTHON, str(HWINFO_PROBE)], capture_output=True, check=False).returncode == 0
    print(f"HWiNFO shared memory available: {hwinfo_up}")

    sidecar_args = [PYTHON, str(SIDECAR), "--telemetry", str(TELEMETRY), "--out", str(FEED),
                    "--interval", "2", "--telemetry-stale-trip", "20"]
    if hwinfo_up:
        sidecar_args.append("--hwinfo")
    sidecar_err = (SESSION_DIR / "sidecar.stderr.log").open("wb")

    # ---- 1. sidecar alone, no telemetry yet ---------------------------------
    sidecar = subprocess.Popen(sidecar_args, stderr=sidecar_err, stdout=subprocess.DEVNULL)
    time.sleep(3)
    if not FEED.exists():
        failures.append("the sidecar did not create its output file")
    else:
        payload = read_feed()
        print("before telemetry -> telemetry markers:",
              [k for k in payload["temperatures"] if k in ("CPU (Tctl/Tdie) [C]", "CPU CCD1 (Tdie) [C]")],
              "age:", payload["source_age_seconds"], "hwinfo:", payload["hwinfo_available"])
        temperatures, values, age = wd.read_sensor_feed(FEED)
        print(f"   watchdog strict read: {len(temperatures)} temperatures, age={age:.1f}")
        # HWiNFO supplies its own temperatures, so "no telemetry yet" means no
        # HWiNFO-free markers, not an empty map. What must never happen is a
        # synthesized value for a source that has not answered.
        if any(k in temperatures for k in ("CPU (Tctl/Tdie) [C]", "CPU CCD1 (Tdie) [C]")):
            failures.append("the feed invented a telemetry-format temperature before any line arrived")
        # The arm handshake must tolerate exactly this state.
        temperatures, age = wd.sensor_file_readings(FEED, time.time())
        print(f"   arm-handshake read: {len(temperatures)} temperatures, age={age:.1f}")

    # ---- 2. telemetry arrives and the feed becomes real ---------------------
    fake = FakeTelemetry(TELEMETRY)
    fake.start()
    deadline = time.time() + 40
    ok = False
    while time.time() < deadline:
        time.sleep(2)
        try:
            payload = read_feed()
        except (OSError, ValueError):
            continue
        if payload["temperatures"]:
            ok = True
            break
    if not ok:
        failures.append("the feed never carried a temperature after the telemetry appeared")
    else:
        print("with telemetry   -> temperatures:", json.dumps(payload["temperatures"], ensure_ascii=False))
        print("   hwinfo_available:", payload["hwinfo_available"], "values:", len(payload["values"]))
        temperatures, _, age = wd.read_sensor_feed(FEED)
        stops, emergencies, matched = wd.evaluate_temperatures(temperatures)
        print("   SENSOR_LIMITS matched:", json.dumps(matched, ensure_ascii=False))
        if not matched:
            failures.append("the watchdog's SENSOR_LIMITS do not match the merged feed")
        if hwinfo_up and not any("SPD Hub" in key for key in matched):
            failures.append("HWiNFO is up but the feed carries no SPD Hub temperature")
        if not hwinfo_up:
            print("   (HWiNFO down: DDR5 coverage absent by design, recorded not failed)")

    # ---- 3. the stream dies; the feed must go stale --------------------------
    fake.stop.set()
    fake.thread.join(timeout=5)
    print("telemetry stopped; watching the reported age grow…")
    stale_seen = False
    deadline = time.time() + 60
    while time.time() < deadline:
        time.sleep(3)
        payload = read_feed()
        if payload["source_age_seconds"] > 30:
            stale_seen = True
            print(f"   age now {payload['source_age_seconds']}s (watchdog limit 30 s)")
            break
    if not stale_seen:
        failures.append("a stopped telemetry stream never pushed the reported age past the watchdog limit")

    sidecar.terminate()
    try:
        sidecar.wait(timeout=10)
    except subprocess.TimeoutExpired:
        sidecar.kill()
    sidecar_err.close()

    print("sidecar stderr:", (SESSION_DIR / "sidecar.stderr.log").read_text(encoding="utf-8", errors="replace").strip()[:400] or "(empty)")

    if failures:
        print("RESULT: FAIL")
        for failure in failures:
            print("  -", failure)
        return 1
    print("RESULT: PASS - the merged feed protects the run, tolerates the arm handshake, and goes stale when the stream dies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
