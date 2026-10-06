"""Collect a repeatable baseline of memory bandwidth/latency AND VT3 throughput.

Both halves of the earlier finding need multiple samples, because the first
attempt at this drifted with heat: three back-to-back memprobe runs moved
monotonically (copy 60.71 -> 58.27 -> 58.30 GB/s) purely because the machine was
warming up. With a cooldown to a fixed Tctl before each sample the same tool
tightened to 1.5% on copy, so the cooldown is not optional and is enforced here.

For each cycle:
  1. wait until Tctl <= COOLDOWN_C, so every sample starts from the same state
  2. run `y-cruncher stress -M:24G -D:180 -TL:180 VT3` under the watchdog and
     read the first-iteration Test Speed from its log
  3. wait for cooldown again (the VT3 run bakes the CPU)
  4. run memprobe and read latency/copy/scale/triad from its JSON

The VT3 part reuses tools/rycolab_controller.py accept, which applies the
all-core margin and resets to 0 afterwards, so the runs are directly comparable
with the earlier 9.21 / 7.93 / 8.78 / 8.75 / 8.74 figures.
"""
from __future__ import annotations

import argparse
import json
import re
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
PYTHON = sys.executable
CONTROLLER = ROOT / "tools" / "rycolab_controller.py"
MEMPROBE = ROOT / "tools" / "memprobe.exe"
HWINFO = ROOT / "tools" / "hwinfo_shared.py"
LOGS = ROOT / _paths.TASK_LOG_ROOT
VT3_PATTERN = re.compile(r"Running VT3: (Passed|Failed)\s+Test Speed:\s+([0-9.]+) \* 10\^09")
SESSION = "co-baseline-vt3-20261001"


def tctl() -> float | None:
    result = subprocess.run(
        [PYTHON, "-c",
         "import sys;sys.path.insert(0,r'%s');import hwinfo_shared;"
         "s=hwinfo_shared.read_snapshot();"
         "v=[r['value'] for r in s['readings'] if r['label']=='CPU (Tctl/Tdie)' and 'AMD Ryzen' in r['sensor']];"
         "print(round(v[0],1))" % (ROOT / "tools")],
        capture_output=True, text=True, errors="replace", check=False)
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def cooldown(limit: float, timeout_s: float = 600.0) -> float | None:
    deadline = time.time() + timeout_s
    value = tctl()
    while time.time() < deadline:
        value = tctl()
        if value is not None and value <= limit:
            return value
        time.sleep(10)
    return value


def run_vt3(index: int) -> dict:
    """One 180 s VT3 through the same accept path used for the earlier figures."""
    job = ROOT / "tools" / "co_job_accept.json"
    original = job.read_text(encoding="utf-8")
    payload = json.loads(original)
    payload["session"] = SESSION
    payload["testDuration"] = 180
    payload["_note"] = f"baseline series VT3 sample {index}"
    job.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    session_dir = ROOT / _paths.SESSION_ROOT / SESSION
    if session_dir.exists():
        import shutil
        shutil.rmtree(session_dir, ignore_errors=True)

    (ROOT / "tools" / "co_task_op.json").write_text('{"op":"accept"}\n', encoding="ascii")
    subprocess.run(["schtasks.exe", "/run", "/tn", "optimize-co-elevated"],
                   capture_output=True, check=False)

    deadline = time.time() + 60
    while time.time() < deadline and not (session_dir / "session.json").exists():
        time.sleep(1)
    if not (session_dir / "session.json").exists():
        return {"error": "accept never armed"}

    feed = subprocess.Popen(
        [PYTHON, "-X", "utf8", str(CONTROLLER), "feed", "--session", SESSION,
         "--interval", "5", "--report-interval", "120"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    deadline = time.time() + 600
    while time.time() < deadline:
        try:
            state = json.loads((session_dir / "status.json").read_text(encoding="utf-8")).get("state")
        except (OSError, ValueError):
            state = None
        if state and state != "running":
            break
        time.sleep(5)
    feed.terminate()
    try:
        feed.wait(timeout=10)
    except subprocess.TimeoutExpired:
        feed.kill()

    out = session_dir / "workload.stdout.log"
    text = out.read_text(encoding="utf-8", errors="replace") if out.exists() else ""
    match = VT3_PATTERN.search(text)
    job.write_text(original, encoding="utf-8")          # always restore the job file
    if not match:
        return {"error": "no VT3 line", "state": state}
    return {"verdict": match.group(1), "bits": float(match.group(2)), "state": state}


def run_memprobe(index: int) -> dict:
    result_path = LOGS / f"baseline_mem_{index}.json"
    subprocess.run([str(MEMPROBE), "--size-mib", "1024", "--stride", "4096",
                    "--reps", "2", "--core", "0", "--json", str(result_path)],
                   capture_output=True, check=False)
    if not result_path.exists():
        return {"error": "memprobe produced no json"}
    return json.loads(result_path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=4)
    parser.add_argument("--cooldown-c", type=float, default=58.0)
    parser.add_argument("--skip-vt3", action="store_true")
    parser.add_argument("--vt3-only", action="store_true",
                        help="skip memprobe, so a VT3 sample is not preceded by 3 GB of streaming traffic")
    args = parser.parse_args()

    LOGS.mkdir(parents=True, exist_ok=True)
    rows = []
    for cycle in range(1, args.cycles + 1):
        print(f"\n===== cycle {cycle}/{args.cycles} =====", flush=True)

        t = cooldown(args.cooldown_c)
        mem = None
        if not args.vt3_only:
            print(f"  cooled to Tctl={t} C (target <={args.cooldown_c})", flush=True)
            mem = run_memprobe(cycle)
            print(f"  memprobe: latency={mem.get('latencyNsMedian')} copy={mem.get('copyGBs')} "
                  f"scale={mem.get('scaleGBs')} triad={mem.get('triadGBs')} verified={mem.get('verified')}",
                  flush=True)

        vt3 = None
        if not args.skip_vt3:
            t = cooldown(args.cooldown_c)
            print(f"  cooled to Tctl={t} C before VT3", flush=True)
            vt3 = run_vt3(cycle)
            print(f"  vt3: {vt3}", flush=True)

        rows.append({"cycle": cycle, "coolTctl": t, "mem": mem, "vt3": vt3})
        (LOGS / "baseline_series.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- summary ----
    def values(key: str, sub: str = "mem"):
        out = []
        for row in rows:
            block = row.get(sub) or {}
            if isinstance(block, dict) and isinstance(block.get(key), (int, float)):
                out.append(float(block[key]))
        return out

    print("\n===== summary =====")
    for label, key, sub in (("latency ns", "latencyNsMedian", "mem"), ("copy GB/s", "copyGBs", "mem"),
                            ("scale GB/s", "scaleGBs", "mem"), ("triad GB/s", "triadGBs", "mem"),
                            ("VT3 bits/s", "bits", "vt3")):
        v = values(key, sub)
        if not v:
            continue
        print(f"  {label:12} n={len(v)} min={min(v):.3f} max={max(v):.3f} "
              f"spread={(max(v) - min(v)) / (sum(v) / len(v)) * 100:.2f}%  values={[round(x, 3) for x in v]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
