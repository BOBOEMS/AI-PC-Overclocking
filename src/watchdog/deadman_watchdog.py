#!/usr/bin/env python3
"""Local dead-man switch for unattended stability tests on Windows.

The watchdog never refreshes its own external heartbeat. A remote controller must
run the ``feed`` command periodically. If feeding stops, all launched stress-test
processes are terminated through a Windows Job Object and an explicit process
allow-list cleanup.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
from ctypes import wintypes
import datetime as dt
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
from typing import Iterable

# --- shared path resolution -------------------------------------------------
# This script lives under <repo>/src/, so the repository root is reached from
# this file rather than from the working directory. All machine-specific paths
# (third-party tools, artifact output) come from src/common/paths.py so that a
# clone works without editing source.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.common import paths as _paths  # noqa: E402


WORKSPACE = _paths.REPO_ROOT
SESSIONS = _paths.SESSION_ROOT
STRESS_IMAGES = (
    "Cinebench.exe",
    "y-cruncher.exe",
    "prime95.exe",
    "TM5.exe",
    "MemTest64.exe",
    "memtest.exe",
    "memtestpro.exe",
    "FurMark.exe",
    "furmark.exe",
    "FurMark_GUI.exe",
    "cpuburner.exe",
    "linpack_xeon64.exe",
    "linpack_xeon32.exe",
    # Curve Optimizer runs (rycolab): the CLI plus the y-cruncher engine binaries
    # it pins to a single core. Official 0.8.7 binary names.
    "rycolab.exe",
    "04-P4P.exe",
    "19-ZN2 ~ Kagari.exe",
    "22-ZN4 ~ Kizuna.exe",
    "24-ZN5 ~ Komari.exe",
)

SENSOR_LIMITS = (
    # (case-insensitive regex, stop threshold, emergency threshold, label)
    (r"CPU \(Tctl/Tdie\)|CPU CCD.*Tdie|CPU Die \(average\)|CPU Package|\|\s*CPU\s*$", 90.0, 95.0, "CPU"),
    (r"GPU Hot ?Spot Temperature|GPU Junction Temperature|GPU 热点温度|热点温度", 100.0, 105.0, "GPU hotspot"),
    (r"GPU Memory Junction Temperature|GPU Memory Temperature|显存结温", 96.0, 100.0, "GPU memory"),
    (r"\|\s*GPU Temperature\s*(?:\[[^]]*\])?$|\|\s*GPU 温度\s*(?:\[[^]]*\])?$|GPU Core Temperature", 90.0, 95.0, "GPU core"),
    (r"DIMM.*Temperature|SPD Hub Temperature|SPD Hub 温度", 60.0, 65.0, "DDR5"),
    (r"VRM.*Temperature|MOS.*Temperature|\|\s*MOS\s*(?:\[[^]]*\])?$", 100.0, 110.0, "VRM"),
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Use a unique sibling file so overlapping writers or stale leftovers can
    # never share the same temporary path. Windows can briefly deny replacing
    # a file while a reader (for example, a status poller) has it open, so
    # retry that transient condition before treating status I/O as a failure.
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2))
            handle.flush()
        for attempt in range(6):
            try:
                os.replace(temporary, path)
                return
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.05 * (2**attempt))
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def session_dir(name: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", name):
        raise SystemExit("Session name may contain only letters, digits, dot, underscore and dash")
    return SESSIONS / name


def append_event(folder: Path, event: str, **details: object) -> None:
    record = {"time": utc_now(), "event": event, **details}
    with (folder / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def feed(args: argparse.Namespace) -> int:
    folder = session_dir(args.session)
    metadata_path = folder / "session.json"
    if not metadata_path.exists():
        raise SystemExit(f"Unknown watchdog session: {args.session}")
    metadata = read_json(metadata_path)
    if not secrets.compare_digest(str(metadata.get("token", "")), args.token):
        raise SystemExit("Heartbeat token mismatch")
    heartbeat = {
        "session": args.session,
        "token": args.token,
        "fed_at": utc_now(),
        "controller_note": args.note,
    }
    atomic_json(folder / "heartbeat.json", heartbeat)
    print(json.dumps({"ok": True, "session": args.session, "fed_at": heartbeat["fed_at"]}))
    return 0


def status(args: argparse.Namespace) -> int:
    folder = session_dir(args.session)
    status_path = folder / "status.json"
    if not status_path.exists():
        raise SystemExit(f"No status for watchdog session: {args.session}")
    print(status_path.read_text(encoding="utf-8"))
    return 0


def request_stop(args: argparse.Namespace) -> int:
    folder = session_dir(args.session)
    metadata = read_json(folder / "session.json")
    if not secrets.compare_digest(str(metadata.get("token", "")), args.token):
        raise SystemExit("Stop token mismatch")
    atomic_json(folder / "stop.json", {"requested_at": utc_now(), "reason": args.reason})
    print(json.dumps({"ok": True, "session": args.session, "stop_requested": True}))
    return 0


class WindowsJob:
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JobObjectExtendedLimitInformation = 9

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        pass

    EXTENDED_LIMIT_INFORMATION._fields_ = [
        ("BasicLimitInformation", BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("Windows Job Objects are required")
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32 = kernel32
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        self.handle = kernel32.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = self.EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = self.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = kernel32.SetInformationJobObject(
            self.handle,
            self.JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

    def assign(self, process_handle: int) -> None:
        if not self._kernel32.AssignProcessToJobObject(self.handle, process_handle):
            raise ctypes.WinError(ctypes.get_last_error())

    def terminate(self, exit_code: int = 1223) -> None:
        if self.handle:
            self._kernel32.TerminateJobObject(self.handle, exit_code)

    def close(self) -> None:
        if getattr(self, "handle", None):
            self._kernel32.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self) -> "WindowsJob":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def latest_whea_record_id() -> int | None:
    command = [
        "wevtutil.exe",
        "qe",
        "System",
        "/q:*[System[Provider[@Name='Microsoft-Windows-WHEA-Logger']]]",
        "/rd:true",
        "/c:1",
        "/f:xml",
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=8, check=False)
        raw = result.stdout
        for encoding in ("utf-8", "utf-16", "mbcs"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeError:
                continue
        else:
            return None
        match = re.search(r"<EventRecordID[^>]*>(\d+)</EventRecordID>", text)
        if match:
            return int(match.group(1))
        # A successful query with no matching event is a valid zero baseline.
        return 0 if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def parse_number(value: str) -> float | None:
    match = re.search(r"-?\d+(?:[.,]\d+)?", value.replace("\u202f", "").replace(" ", ""))
    if not match:
        return None
    candidate = match.group(0)
    if candidate.count(",") == 1 and "." not in candidate:
        candidate = candidate.replace(",", ".")
    else:
        candidate = candidate.replace(",", "")
    try:
        return float(candidate)
    except ValueError:
        return None


def read_hwinfo_latest(path: Path) -> tuple[dict[str, float], float]:
    """Read the last complete HWiNFO CSV row and return numeric fields + file age."""
    stat = path.stat()
    age = max(0.0, time.time() - stat.st_mtime)
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        rows = list(csv.reader(handle))
    if len(rows) < 2:
        raise ValueError("HWiNFO CSV has no data rows")
    header_index = next(
        (i for i, row in enumerate(rows[:5]) if row and any("date" in x.lower() for x in row)),
        0,
    )
    header = rows[header_index]
    data_rows = [row for row in rows[header_index + 1 :] if len(row) == len(header)]
    if not data_rows:
        raise ValueError("HWiNFO CSV has no complete data row")
    latest = data_rows[-1]
    numbers: dict[str, float] = {}
    for key, raw in zip(header, latest):
        value = parse_number(raw)
        if value is not None:
            numbers[key] = value
    return numbers, age


def read_smu_telemetry(path: Path) -> tuple[dict[str, float], float]:
    """Protected readings from a ryzen-smu-cli system telemetry stream.

    Raises when the stream is missing, empty or unparsable — that is what a dead
    stream must look like, so `--sensor-required` trips instead of quietly
    dropping thermal protection. `sensor_file_readings` adds the startup grace.
    """
    if not path.exists():
        raise ValueError(f"telemetry file does not exist yet: {path}")
    age = max(0.0, time.time() - path.stat().st_mtime)
    line: str | None = None
    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - 65536))
        for candidate in reversed(handle.read().decode("utf-8", "replace").splitlines()):
            if candidate.strip().startswith("{"):
                line = candidate
                break
    if line is None:
        raise ValueError(f"no telemetry line in {path}")
    record = json.loads(line)
    temperatures: dict[str, float] = {}
    values: dict[str, float] = {}
    tctl = record.get("cpuTemperatureCelsius")
    if tctl is not None:
        # ASCII labels: the value crosses a GBK console on its way out of the
        # log, and a mangled unit character would be a silent non-match.
        temperatures["CPU (Tctl/Tdie) [C]"] = float(tctl)
        temperatures["CPU CCD1 (Tdie) [C]"] = float(tctl)
        values["CPU (Tctl/Tdie) [C]"] = float(tctl)
    if (vcore := record.get("vcoreVolts")) is not None:
        values["Vcore [V]"] = float(vcore)
    if (watts := record.get("packagePowerWatts")) is not None:
        values["CPU Package Power [W]"] = float(watts)
    values["SMU telemetry line age [s]"] = round(age, 2)
    for target in record.get("targets") or []:
        if (clock := target.get("effectiveMhz")) is None:
            continue
        values[f"Core {target.get('processor')} Effective Clock [MHz]"] = float(clock)
    if not temperatures:
        raise ValueError(f"telemetry line has no cpuTemperatureCelsius: {path}")
    return temperatures, age


def sensor_file_readings(path: Path, started: float, start_grace: float = 90.0) -> tuple[dict[str, float], float]:
    """`read_sensor_feed` with a startup grace window for the arm handshake.

    The watchdog samples the sensors before the workload it just launched has had
    a chance to create the feed, so a missing/empty/unparsable feed inside the
    first ``start_grace`` seconds reads as age 0 with no temperatures: the only
    consequence is a sample without protected values. Outside the window the
    strict reader's exception stands, which is what trips the run when the stream
    really is dead. (Observed 2026-10-01 14:53: the pre-flight check refused an
    otherwise healthy arm with "telemetry file does not exist yet".)
    """
    if time.time() - started < start_grace:
        try:
            temperatures, _, age = read_sensor_feed(path)
            return temperatures, age
        except (OSError, ValueError, KeyError):
            return {}, 0.0
    temperatures, _, age = read_sensor_feed(path)
    return temperatures, age


def read_sensor_feed(path: Path) -> tuple[dict[str, float], dict[str, float], float]:
    """Sidecar schema: the merged, continuously refreshed sensor file.

    ``tools/sidecar_sensors.py`` owns the real sources (ryzen-smu-cli's telemetry
    stream plus, when it is up, HWiNFO's shared memory) and rewrites this file
    every couple of seconds. That is what makes a *fresh* file and *fresh*
    readings the same thing: the raw telemetry file cannot provide it, because
    the child's stdout is block-buffered and sits unchanged for 10-30 s while the
    stream is healthy (that produced "sensor source stale for 15.5s" on a healthy
    run at 2026-10-01 14:55).

    ``source_age_seconds`` measures the newest real reading, not the write time,
    so a source that stops ends up reported stale and trips the run.
    """
    if not path.exists():
        raise ValueError(f"sensor feed does not exist yet: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    temperatures = {str(k): float(v) for k, v in (payload.get("temperatures") or {}).items()}
    values = {str(k): float(v) for k, v in (payload.get("values") or {}).items()}
    age = float(payload.get("source_age_seconds") if payload.get("source_age_seconds") is not None else 0.0)
    return temperatures, values, age


def read_sensor_source(args: argparse.Namespace, sensor_state: dict) -> tuple[dict[str, float], float]:
    """Return flattened protected sensor readings and freshness age."""
    if args.sensor_file:
        try:
            temperatures, values, age = read_sensor_feed(args.sensor_file)
        except (OSError, ValueError):
            temperatures, age = sensor_file_readings(args.sensor_file, sensor_state["started"])
            values = dict(temperatures)
        sensor_state["last_values"] = values
        return temperatures, age
    if args.hwinfo_shm:
        try:
            from src.common.hwinfo_shared import read_snapshot

            snapshot = read_snapshot()
        except Exception as error:
            raise ValueError(str(error)) from error
        values: dict[str, float] = {}
        selected_values: dict[str, float] = {}
        for reading in snapshot["readings"]:
            key = f"{reading['sensor']} | {reading['label']} [{reading['unit']}]"
            if reading["type"] in {"temp", "power", "clock", "usage", "voltage", "fan"} or re.search(
                r"Power|PPT|功率|功耗|Clock|频率|Voltage|电压|Fan|风扇|Utilization|使用率",
                reading["label"],
                flags=re.IGNORECASE,
            ):
                selected_values[key] = float(reading["value"])
            if reading["type"] == "temp":
                values[key] = float(reading["value"])
        sensor_state["last_values"] = selected_values
        poll_time = int(snapshot.get("poll_time", 0))
        now = time.time()
        previous = sensor_state.get("poll_time")
        if previous != poll_time:
            sensor_state["poll_time"] = poll_time
            sensor_state["last_change"] = now
        age = 0.0 if "last_change" not in sensor_state else max(0.0, now - sensor_state["last_change"])
        return values, age
    if args.sensor_csv:
        sensor_state["last_values"] = {}
        return read_hwinfo_latest(args.sensor_csv)
    raise ValueError("no HWiNFO sensor source configured")


def evaluate_temperatures(
    values: dict[str, float], limits: tuple = SENSOR_LIMITS
) -> tuple[list[str], list[str], dict[str, float]]:
    stops: list[str] = []
    emergencies: list[str] = []
    matched: dict[str, float] = {}
    for header, value in values.items():
        for pattern, stop_limit, emergency_limit, label in limits:
            if re.search(pattern, header, flags=re.IGNORECASE):
                matched[header] = value
                if value >= emergency_limit:
                    emergencies.append(f"{label} {value:.1f}C >= {emergency_limit:.1f}C ({header})")
                elif value >= stop_limit:
                    stops.append(f"{label} {value:.1f}C >= {stop_limit:.1f}C ({header})")
    return stops, emergencies, matched


def cleanup_stress_images(folder: Path) -> None:
    for image in STRESS_IMAGES:
        result = subprocess.run(
            ["taskkill.exe", "/F", "/T", "/IM", image],
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
        )
        if result.returncode == 0:
            append_event(folder, "cleanup_image", image=image)


def arm(args: argparse.Namespace) -> int:
    folder = session_dir(args.session)
    if folder.exists() and (folder / "status.json").exists():
        old = read_json(folder / "status.json")
        if old.get("state") == "running":
            raise SystemExit(f"Session {args.session} is already running")
    folder.mkdir(parents=True, exist_ok=True)
    token = args.token or secrets.token_urlsafe(24)
    started = time.time()
    sensor_state: dict = {"started": started}
    limits = tuple(
        (
            pattern,
            args.cpu_temp_stop if label == "CPU" else args.dimm_temp_stop if label == "DDR5" else stop_limit,
            args.cpu_temp_emergency if label == "CPU" else args.dimm_temp_emergency if label == "DDR5" else emergency_limit,
            label,
        )
        for pattern, stop_limit, emergency_limit, label in SENSOR_LIMITS
    )
    metadata = {
        "session": args.session,
        "token": token,
        "created_at": utc_now(),
        "heartbeat_timeout_seconds": args.heartbeat_timeout,
        "hard_timeout_seconds": args.hard_timeout,
        "sensor_csv": str(args.sensor_csv) if args.sensor_csv else None,
        "sensor_file": str(args.sensor_file) if args.sensor_file else None,
        "sensor_required": args.sensor_required,
        "sensor_stale_seconds": args.sensor_stale,
        "shutdown_on_thermal": args.shutdown_on_thermal,
        "temperature_limits_celsius": [
            {"label": label, "stop": stop_limit, "emergency": emergency_limit}
            for _, stop_limit, emergency_limit, label in limits
        ],
        "command": args.command,
    }
    atomic_json(folder / "session.json", metadata)
    atomic_json(folder / "heartbeat.json", {"session": args.session, "token": token, "fed_at": utc_now()})
    for marker in ("stop.json",):
        marker_path = folder / marker
        if marker_path.exists():
            marker_path.unlink()

    baseline_whea = latest_whea_record_id()
    append_event(folder, "armed", baseline_whea=baseline_whea, command=args.command)

    if args.sensor_required:
        if not args.sensor_csv and not args.hwinfo_shm and not args.sensor_file:
            atomic_json(folder / "status.json", {"state": "refused", "reason": "required sensor source missing"})
            return 2
        if args.sensor_csv and not args.sensor_csv.exists():
            atomic_json(folder / "status.json", {"state": "refused", "reason": "required sensor CSV missing"})
            return 2
        try:
            readings_state: dict = {"started": started}
            values, age = read_sensor_source(args, readings_state)
        except (OSError, ValueError) as error:
            atomic_json(folder / "status.json", {"state": "refused", "reason": str(error)})
            return 2
        if age > args.sensor_stale:
            atomic_json(folder / "status.json", {"state": "refused", "reason": f"sensor source stale: {age:.1f}s"})
            return 2
        _, emergencies, matched = evaluate_temperatures(values, limits)
        if not matched:
            # Within the arm handshake the workload's sidecar may not have a real
            # reading yet: the merged file exists immediately, but the first
            # complete telemetry line needs the child's block-buffered stdout to
            # flush. Do not refuse on that — en route the in-loop check trips the
            # run if the stream never shows up (it is what killed the 14:55 run
            # once the grace was too short). HWiNFO/CSV sources have no grace.
            if not (args.sensor_file and time.time() - started < 90.0):
                atomic_json(folder / "status.json", {"state": "refused", "reason": "no protected temperature sensors matched"})
                return 2
        if emergencies:
            atomic_json(folder / "status.json", {"state": "refused", "reason": "; ".join(emergencies)})
            return 2

    stdout_path = folder / "workload.stdout.log"
    stderr_path = folder / "workload.stderr.log"
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process: subprocess.Popen[bytes] | None = None
    final_state = "failed"
    final_reason = "watchdog internal failure"
    thermal_emergency = False
    # Consecutive samples above a stop threshold before it counts as a trip; see
    # the thermal_glitch_ignored branch for why a single sample is not enough.
    thermal_strikes = 0
    thermal_state: dict = {}

    try:
        with WindowsJob() as job, stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(
                args.command,
                cwd=args.cwd,
                stdout=stdout,
                stderr=stderr,
                creationflags=creationflags,
            )
            job.assign(int(process._handle))  # Windows Popen exposes the native process handle.
            append_event(folder, "workload_started", pid=process.pid)

            last_whea_check = 0.0
            last_sensor_check = 0.0
            # sensor_state is already {started: ...}; keep it so the grace window
            # works even when --sensor-required is off.
            last_matched: dict[str, float] = {}
            while True:
                now = time.time()
                heartbeat_path = folder / "heartbeat.json"
                heartbeat_age = now - heartbeat_path.stat().st_mtime if heartbeat_path.exists() else float("inf")
                elapsed = now - started
                returncode = process.poll()
                status_payload = {
                    "state": "running",
                    "session": args.session,
                    "pid": process.pid,
                    "elapsed_seconds": round(elapsed, 1),
                    "heartbeat_age_seconds": round(heartbeat_age, 1),
                    "hard_timeout_seconds": args.hard_timeout,
                    "last_temperatures": last_matched,
                    "updated_at": utc_now(),
                }
                atomic_json(folder / "status.json", status_payload)

                if returncode is not None:
                    final_state = "completed" if returncode == 0 else "failed"
                    final_reason = f"workload exited with code {returncode}"
                    break
                if (folder / "stop.json").exists():
                    stop_data = read_json(folder / "stop.json")
                    final_state = "stopped"
                    final_reason = f"stop requested: {stop_data.get('reason', 'unspecified')}"
                    job.terminate()
                    cleanup_stress_images(folder)
                    break
                if heartbeat_age > args.heartbeat_timeout:
                    final_state = "tripped"
                    final_reason = f"external heartbeat stale for {heartbeat_age:.1f}s"
                    job.terminate()
                    cleanup_stress_images(folder)
                    break
                if elapsed > args.hard_timeout:
                    final_state = "tripped"
                    final_reason = f"hard runtime limit reached ({args.hard_timeout}s)"
                    job.terminate()
                    cleanup_stress_images(folder)
                    break

                if now - last_whea_check >= 5.0:
                    last_whea_check = now
                    current_whea = latest_whea_record_id()
                    if baseline_whea is not None and current_whea is not None and current_whea != baseline_whea:
                        final_state = "tripped"
                        final_reason = f"new WHEA record detected ({baseline_whea} -> {current_whea})"
                        job.terminate()
                        cleanup_stress_images(folder)
                        break

                if (args.sensor_csv or args.hwinfo_shm or args.sensor_file) and now - last_sensor_check >= 2.0:
                    last_sensor_check = now
                    try:
                        values, age = read_sensor_source(args, sensor_state)
                        if age > args.sensor_stale:
                            raise ValueError(f"sensor source stale for {age:.1f}s")
                        stops, emergencies, last_matched = evaluate_temperatures(values, limits)
                        sample = {
                            "time": utc_now(),
                            "sensor_age_seconds": round(age, 3),
                            "protected_temperatures": last_matched,
                            "readings": sensor_state.get("last_values", {}),
                        }
                        with (folder / "sensor_samples.jsonl").open("a", encoding="utf-8") as sensor_log:
                            sensor_log.write(json.dumps(sample, ensure_ascii=False) + "\n")
                        if emergencies or stops:
                            # A trip must be a *state*, not an instant. On 2026-10-01
                            # three runs (margins -25, -25 and -5) showed one sample at
                            # t~=65 s reading 90 C while both cores were simultaneously
                            # near idle (132 / 24.7 MHz, package power *falling* to
                            # 58 W). Tripping on that single sample aborted a healthy
                            # sweep three times. Requiring the condition to persist
                            # costs a few seconds against a real thermal event, which
                            # climbs and stays, and refuses the one-sample artifact.
                            thermal_strikes += 1
                            first_seen = thermal_state.get("first_seen") or {
                                "time": utc_now(), "reason": "; ".join(emergencies or stops)}
                            thermal_state["first_seen"] = first_seen
                            if thermal_strikes < max(1, args.temp_strikes_required):
                                append_event(folder, "thermal_glitch_ignored", strikes=thermal_strikes,
                                             required=args.temp_strikes_required,
                                             reason="; ".join(emergencies or stops),
                                             readings=dict(last_matched))
                                continue
                            thermal_emergency = bool(emergencies)
                            final_state = "tripped"
                            final_reason = "; ".join(emergencies or stops)
                            if thermal_strikes > 1:
                                final_reason = (f"{final_reason} (confirmed by {thermal_strikes} consecutive samples; "
                                                f"first at {first_seen['time']}: {first_seen['reason']})")
                            job.terminate()
                            cleanup_stress_images(folder)
                            break
                        if thermal_strikes:
                            append_event(folder, "thermal_glitch_recovered", strikes=thermal_strikes,
                                         reason="; ".join(thermal_state.get("first_seen", {}).get("reason", "").split("; ")))
                            thermal_strikes = 0
                            thermal_state.pop("first_seen", None)
                    except (OSError, ValueError) as error:
                        if args.sensor_required:
                            final_state = "tripped"
                            final_reason = f"lost sensor monitoring: {error}"
                            job.terminate()
                            cleanup_stress_images(folder)
                            break
                time.sleep(1.0)
    except Exception as error:
        final_state = "failed"
        final_reason = f"watchdog exception: {type(error).__name__}: {error}"
        cleanup_stress_images(folder)
    finally:
        if process is not None and process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
        append_event(folder, "finished", state=final_state, reason=final_reason)
        atomic_json(
            folder / "status.json",
            {
                "state": final_state,
                "session": args.session,
                "reason": final_reason,
                "finished_at": utc_now(),
                "shutdown_scheduled": bool(thermal_emergency and args.shutdown_on_thermal),
            },
        )
        if thermal_emergency and args.shutdown_on_thermal:
            subprocess.run(
                ["shutdown.exe", "/s", "/t", "15", "/c", "Thermal emergency detected by stability watchdog"],
                check=False,
            )
    return 0 if final_state == "completed" else 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)

    arm_parser = sub.add_parser("arm", help="Launch a command under dead-man protection")
    arm_parser.add_argument("--session", required=True)
    arm_parser.add_argument("--token")
    arm_parser.add_argument("--heartbeat-timeout", type=float, default=90.0)
    arm_parser.add_argument("--hard-timeout", type=float, required=True)
    arm_parser.add_argument("--cwd", type=Path, default=WORKSPACE)
    arm_parser.add_argument("--sensor-csv", type=Path)
    arm_parser.add_argument("--hwinfo-shm", action="store_true", help="Read HWiNFO64 Shared Memory v2")
    arm_parser.add_argument("--sensor-file", type=Path, default=None,
                            help="ryzen-smu-cli --stream-system-telemetry JSONL: protected CPU temperatures and per-core effective clocks")
    arm_parser.add_argument("--sensor-required", action="store_true")
    arm_parser.add_argument("--sensor-stale", type=float, default=20.0)
    arm_parser.add_argument("--temp-strikes-required", type=int, default=3,
                            help="Consecutive 2 s samples above a stop threshold before tripping (1 = trip on the first sample)")
    arm_parser.add_argument("--shutdown-on-thermal", action="store_true")
    arm_parser.add_argument("--cpu-temp-stop", type=float, default=90.0)
    arm_parser.add_argument("--cpu-temp-emergency", type=float, default=95.0)
    arm_parser.add_argument("--dimm-temp-stop", type=float, default=60.0)
    arm_parser.add_argument("--dimm-temp-emergency", type=float, default=65.0)
    arm_parser.add_argument("command", nargs=argparse.REMAINDER)
    arm_parser.set_defaults(func=arm)

    feed_parser = sub.add_parser("feed", help="Refresh an external controller heartbeat")
    feed_parser.add_argument("--session", required=True)
    feed_parser.add_argument("--token", required=True)
    feed_parser.add_argument("--note", default="remote controller alive")
    feed_parser.set_defaults(func=feed)

    status_parser = sub.add_parser("status", help="Read session status")
    status_parser.add_argument("--session", required=True)
    status_parser.set_defaults(func=status)

    stop_parser = sub.add_parser("stop", help="Request an orderly watchdog trip")
    stop_parser.add_argument("--session", required=True)
    stop_parser.add_argument("--token", required=True)
    stop_parser.add_argument("--reason", default="controller requested stop")
    stop_parser.set_defaults(func=request_stop)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.action == "arm":
        if args.command and args.command[0] == "--":
            args.command = args.command[1:]
        if not args.command:
            parser.error("arm requires a command after --")
        if args.heartbeat_timeout < 15:
            parser.error("heartbeat timeout must be at least 15 seconds")
        if args.hard_timeout <= args.heartbeat_timeout:
            parser.error("hard timeout must exceed heartbeat timeout")
        if args.cpu_temp_stop <= 0 or args.cpu_temp_emergency < args.cpu_temp_stop:
            parser.error("CPU emergency temperature must be >= a positive stop temperature")
        if args.dimm_temp_stop <= 0 or args.dimm_temp_emergency < args.dimm_temp_stop:
            parser.error("DIMM emergency temperature must be >= a positive stop temperature")
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
