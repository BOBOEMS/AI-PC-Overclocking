"""Finish the port: fix a missing import and repoint analysis scripts at artifacts/.

Two separate problems, both consequences of moving files:

1. archive_watchdog_session.py got a bootstrap calling sys.path.insert, but that
   module never imported `sys` - it only imported argparse/datetime/gzip/json/
   pathlib/shutil. Moving the bootstrap after the stdlib imports is not enough if
   the name was never imported at all. Its own RUNS constant also still pointed at
   <repo>/runs, which is now <repo>/artifacts/runs.

2. The analysis scripts under src/bench/analysis/ were written when session data
   lived at <repo>/watchdog_sessions and raw logs at <repo>/task_logs. Those trees
   now live under <repo>/artifacts/, so their quoted path segments have to change
   or they silently report "missing sensor_samples.jsonl".

Both fixes are mechanical and this script prints what it changed.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(r"C:\bobo_document\temp\optimize_system")

BOOTSTRAP = '''
# --- shared path resolution -------------------------------------------------
# This script lives under <repo>/src/, so the repository root is reached from
# this file rather than from the working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.common import paths as _paths  # noqa: E402
'''.strip("\n")

SEGMENT_REPLACEMENTS = [
    ('"watchdog_sessions"', "_paths.SESSION_ROOT"),
    ("'watchdog_sessions'", "_paths.SESSION_ROOT"),
    ('"task_logs"', "_paths.TASK_LOG_ROOT"),
    ("'task_logs'", "_paths.TASK_LOG_ROOT"),
    ('runs', None),  # not touched: too ambiguous to rewrite safely
]


def ensure_bootstrap(text: str) -> tuple[str, bool]:
    """Insert the paths bootstrap if absent, after the stdlib imports."""
    if "from src.common import paths" in text:
        return text, False
    lines = text.split("\n")
    index = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r'^(def |class |@|[A-Z_]+ = |if __name__)', stripped):
            break
        if stripped.startswith(("import ", "from ")):
            index = i + 1
    # make sure `sys` and `Path` are imported, since the bootstrap uses both
    header = "\n".join(lines[:index])
    extra = []
    if not re.search(r'^import sys\s*$', header, re.M):
        extra.append("import sys")
    if not re.search(r'^from pathlib import Path\s*$', header, re.M):
        extra.append("from pathlib import Path")
    inserted = extra + ([""] if extra else []) + BOOTSTRAP.split("\n")
    return "\n".join(lines[:index] + inserted + lines[index:]), True


def main() -> int:
    # ---- 1. the missing `sys` import + stale RUNS constant -------------------
    canonical = ROOT / "src" / "common" / "archive_watchdog_session.py"
    text = canonical.read_text(encoding="utf-8")
    before = text
    if not re.search(r'^import sys\s*$', text, re.M):
        text = text.replace("import shutil\n", "import shutil\nimport sys\n", 1)
        print("archive_watchdog_session.py: added `import sys`")
    text = text.replace('RUNS = ROOT / "runs"', "RUNS = _paths.RUN_ROOT")
    if text != before:
        canonical.write_text(text, encoding="utf-8")
        print("archive_watchdog_session.py: RUNS -> artifacts/runs")

    # ---- 2. analysis scripts: artifact-relative paths -----------------------
    for path in sorted((ROOT / "src" / "bench" / "analysis").glob("*.py")):
        if path.name in {"rewire_paths.py", "fix_hwinfo_imports.py", "bootstrap_order.py",
                         "port_finish.py"}:
            continue
        text = path.read_text(encoding="utf-8")
        original = text
        changed = []

        for quoted, replacement in SEGMENT_REPLACEMENTS:
            if replacement is None:
                continue
            if quoted in text:
                text = text.replace(quoted, replacement)
                changed.append(quoted)

        if "_paths." in text:
            text, inserted = ensure_bootstrap(text)
            if inserted:
                changed.append("bootstrap")

        if text != original:
            path.write_text(text, encoding="utf-8")
            print(f"{path.name}: {', '.join(changed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
