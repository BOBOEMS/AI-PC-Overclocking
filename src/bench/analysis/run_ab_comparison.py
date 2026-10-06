"""Run the SSE3-vs-AVX-512 temperature comparison sequentially.

Both arms use the same core, the same 8 tests, the same 60 s per-test window,
the same 1 GiB, the same 480 s wall-clock budget, the same affinity (both SMT
siblings), the same 1 s-suspend-every-10 s cycling and the same HWiNFO sampling.
The ONLY difference is the engine binary:

  24-ZN5 ~ Komari  AVX-512 (Zen 5)   what rycolab uses to find errors
  04-P4P           SSE3              what rycolab uses for its light-load soak

They run one after the other on purpose: two engines at once would share the die
and defeat the comparison.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
# --- shared path resolution -------------------------------------------------
# This script lives under <repo>/src/, so the repository root is reached from
# this file rather than from the working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.common import paths as _paths  # noqa: E402

ROOT = _paths.REPO_ROOT
PYTHON = str(_paths.PYTHON_EXE)
CONTROLLER = ROOT / "tools" / "engine_ab_controller.py"

ARMS = [
    ("co-ab-zn5-20261001", "zn5", "AVX-512 (24-ZN5 ~ Komari)"),
    ("co-ab-p4p-20261001", "p4p", "SSE3 (04-P4P)"),
]


def main() -> int:
    failures = []
    for session, engine, label in ARMS:
        args = [
            PYTHON, "-X", "utf8", str(CONTROLLER), session,
            "--engine", engine,
            "--core", "0",
            "--tests", "BKT", "BBP", "SFTv4", "SNT", "SVT", "FFTv4", "N63", "VT3",
            "--seconds-per-test", "60",
            "--memory-mib", "1024",
            "--cpu-temp-stop", "95",
            "--cpu-temp-emergency", "100",
            "--dimm-temp-stop", "70",
            "--dimm-temp-emergency", "75",
            "--temp-strikes-required", "3",
            "--report-interval", "120",
        ]
        print(f"\n===== ARM {engine}: {label} =====", flush=True)
        result = subprocess.run(args, cwd=str(ROOT))
        print(f"===== ARM {engine} finished, exit={result.returncode} =====", flush=True)
        if result.returncode != 0:
            failures.append((session, result.returncode))

    if failures:
        print("AB RESULT: FAIL " + ", ".join(f"{s}={c}" for s, c in failures), flush=True)
        return 1
    print("AB RESULT: PASS - both arms completed; compare their sensor summaries", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
