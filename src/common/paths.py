"""Single source of truth for every path this toolkit needs.

WHY THIS MODULE EXISTS
----------------------
The scripts originally hardcoded absolute Windows paths belonging to the author's
machine (a specific checkout location, a Python install, a user profile, and a
download folder for third-party tools). That makes the repository unusable for
anyone else. Everything machine-specific is now resolved here, in one place, and
can be overridden with an environment variable instead of editing source.

PRECEDENCE
----------
Every setting is: environment variable -> config/paths.json -> built-in default.
The defaults assume the tools are installed under a single root; point
OVERCLOCK_TOOLS_ROOT at wherever you actually put them, or override individually.

DIRECTORY CONVENTIONS
---------------------
    <repo>/src/            source code          (tracked)
    <repo>/config/         settings + job files (tracked)
    <repo>/docs/           documentation        (tracked)
    <repo>/artifacts/      ALL generated output (NOT tracked - see .gitignore)

ARTIFACT_ROOT is deliberately separate from the source tree: a run writes session
logs, sensor samples and result documents there, so a fresh clone stays clean and
`git status` never fills up with megabytes of jsonl.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# --------------------------------------------------------------------------- #
# Repository layout
# --------------------------------------------------------------------------- #
# This file lives at <repo>/src/common/paths.py, so the repo root is three
# levels up. Resolved from __file__ rather than the working directory so the
# tools behave the same no matter where they are invoked from.
REPO_ROOT = Path(__file__).resolve().parents[2]

SRC_ROOT = REPO_ROOT / "src"
CONFIG_ROOT = REPO_ROOT / "config"
DOCS_ROOT = REPO_ROOT / "docs"


def _load_config() -> dict:
    """Merge user-level and checkout-local configuration.

    Deliberately read from OUTSIDE the repository first. Setting a user
    environment variable does not reach a process that is already running (a new
    child inherits its parent's environment block), which made environment
    variables unreliable for a scheduled task; a file is read fresh each launch.

        %APPDATA%\\overclock-toolkit\\paths.json    machine-specific tool locations
        <repo>/config/paths.local.json              optional checkout-local override

    Neither is committed, so a clone carries no trace of anyone's install paths.
    """
    merged: dict = {}
    candidates = [
        Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
        / "overclock-toolkit" / "paths.json",
        Path(__file__).resolve().parents[2] / "config" / "paths.local.json",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            merged.update(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    return merged


_CONFIG = _load_config()


def _resolve(env_name: str, config_key: str, default: Path) -> Path:
    """environment variable -> config/paths.json -> default."""
    raw = os.environ.get(env_name) or _CONFIG.get(config_key)
    return Path(raw).expanduser() if raw else default


# --------------------------------------------------------------------------- #
# Generated output (never tracked)
# --------------------------------------------------------------------------- #
ARTIFACT_ROOT = _resolve("OVERCLOCK_ARTIFACT_ROOT", "artifactRoot", REPO_ROOT / "artifacts")

SESSION_ROOT = ARTIFACT_ROOT / "sessions"          # dead-man watchdog sessions
RUN_ROOT = ARTIFACT_ROOT / "runs"                  # per-run results and logs
TASK_LOG_ROOT = ARTIFACT_ROOT / "task_logs"        # launcher / scheduler logs
BUILD_ROOT = ARTIFACT_ROOT / "build"               # compiled helpers


def ensure_artifact_dirs() -> None:
    """Create the output tree. Safe to call repeatedly."""
    for directory in (ARTIFACT_ROOT, SESSION_ROOT, RUN_ROOT, TASK_LOG_ROOT, BUILD_ROOT):
        directory.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# Interpreter
# --------------------------------------------------------------------------- #
# Used when a scheduled task or elevated script has to re-invoke Python by path.
PYTHON_EXE = _resolve("OVERCLOCK_PYTHON", "pythonExe", Path(sys.executable))


# --------------------------------------------------------------------------- #
# Third-party tools (see docs/EXTERNAL_DEPENDENCIES.md for sources and licences)
# --------------------------------------------------------------------------- #
# Root that the defaults below hang off, so one override relocates everything.
TOOLS_ROOT = _resolve("OVERCLOCK_TOOLS_ROOT", "toolsRoot", Path(r"C:\Tools"))

# rycolab - AMD Curve Optimizer sweep harness (runtime-installed copy)
#   https://github.com/ryancdotorg/rycolab
RYCOLAB_APPDATA = _resolve("RYCOLAB_APPDATA", "rycolabAppData",
                           Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "rycolab")
RYCOLAB_EXE = _resolve("RYCOLAB_EXE", "rycolabExe", RYCOLAB_APPDATA / "bin" / "rycolab.exe")
# rycolab ships its y-cruncher engine builds under tools/y-cruncher/Binaries.
RYCOLAB_BINARIES = _resolve("RYCOLAB_BINARIES", "rycolabBinaries",
                            RYCOLAB_APPDATA / "tools" / "y-cruncher" / "Binaries")

# ryzen-smu-cli - direct SMU access (read/write Curve Optimizer margins)
#   https://github.com/amkillam/ryzen-smu-cli
RYZEN_SMU_CLI = _resolve("RYZEN_SMU_CLI", "ryzenSmuCli", TOOLS_ROOT / "ryzen-smu-cli" / "ryzen-smu-cli.exe")

# y-cruncher - the stress-test engine
#   http://www.numberworld.org/y-cruncher/
# The 0.8.5 build is pinned on purpose: the historical throughput figures in the
# result documents were all produced with it, and 0.8.7 reports differently, so
# mixing versions makes before/after comparisons meaningless.
YCRUNCHER_DIR = _resolve("YCRUNCHER_DIR", "ycruncherDir", TOOLS_ROOT / "y-cruncher")
YCRUNCHER_EXE = _resolve("YCRUNCHER_EXE", "ycruncherExe", YCRUNCHER_DIR / "y-cruncher.exe")

# HWiNFO - the temperature/telemetry source, read through shared memory
#   https://www.hwinfo.com/
HWINFO_EXE = _resolve("HWINFO_EXE", "hwinfoExe", TOOLS_ROOT / "HWiNFO" / "HWiNFO64.exe")

# memprobe - built from src/bench/memprobe.c, so it lives in the build tree
MEMPROBE_EXE = _resolve("MEMPROBE_EXE", "memprobeExe", BUILD_ROOT / "memprobe.exe")


# --------------------------------------------------------------------------- #
# Scheduled task identity
# --------------------------------------------------------------------------- #
# The elevated half of the design runs as a scheduled task with HighestAvailable
# privileges. InteractiveToken + HighestAvailable is what avoids a UAC prompt.
TASK_NAME = os.environ.get("OVERCLOCK_TASK_NAME") or _CONFIG.get("taskName") or "optimize-co-elevated"


def describe() -> str:
    """Human-readable resolution report - handy when a path is wrong."""
    rows = [
        ("repo root", REPO_ROOT),
        ("artifacts", ARTIFACT_ROOT),
        ("sessions", SESSION_ROOT),
        ("runs", RUN_ROOT),
        ("python", PYTHON_EXE),
        ("rycolab", RYCOLAB_EXE),
        ("rycolab binaries", RYCOLAB_BINARIES),
        ("ryzen-smu-cli", RYZEN_SMU_CLI),
        ("y-cruncher", YCRUNCHER_EXE),
        ("HWiNFO", HWINFO_EXE),
        ("memprobe", MEMPROBE_EXE),
        ("scheduled task", TASK_NAME),
    ]
    width = max(len(name) for name, _ in rows)
    lines = []
    for name, value in rows:
        exists = ""
        if isinstance(value, Path) and name not in {"repo root", "artifacts", "sessions", "runs"}:
            exists = "  [ok]" if value.exists() else "  [MISSING]"
        lines.append(f"  {name:<{width}}  {value}{exists}")
    return "\n".join(lines)


if __name__ == "__main__":
    print("resolved paths (environment -> config/paths.json -> default):")
    print(describe())
