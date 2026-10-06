"""Final pass on the analysis scripts: old path segments and absolute ROOT values.

Left over after materialise_paths.py:
  * compare_temp_trajectory.py and compare_trfc_temps.py build paths like
    ROOT / "watchdog_sessions\\name", which pointed at the pre-move tree.
  * several files still define ROOT = Path(r"C:\\bobo_document\\...") instead of
    taking it from src/common/paths.py.

RUN_ROOT is the constant these want: it is <repo>/artifacts/runs, and the archived
per-run result documents under it are the evidence these comparison scripts read.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(r"C:\bobo_document\temp\optimize_system")
ANALYSIS = ROOT / "src" / "bench" / "analysis"
PROJ = r"C:\bobo_document\temp\optimize_system"

MAINTENANCE = {"rewire_paths.py", "port_finish.py", "materialise_paths.py",
               "bootstrap_order.py", "fix_hwinfo_imports.py", "final_paths.py"}

BOOTSTRAP = """
# --- shared path resolution -------------------------------------------------
# This script lives under <repo>/src/, so the repository root is reached from
# this file rather than from the working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.common import paths as _paths  # noqa: E402
""".strip("\n")


def ensure_bootstrap(text: str) -> tuple[str, bool]:
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
    header = "\n".join(lines[:index])
    extra = []
    if not re.search(r'^import sys\s*$', header, re.M):
        extra.append("import sys")
    if not re.search(r'^from pathlib import Path\s*$', header, re.M):
        extra.append("from pathlib import Path")
    inserted = extra + ([""] if extra else []) + BOOTSTRAP.split("\n")
    return "\n".join(lines[:index] + inserted + lines[index:]), True


def main() -> int:
    for path in sorted(ANALYSIS.glob("*.py")):
        if path.name in MAINTENANCE:
            continue
        text = path.read_text(encoding="utf-8")
        original = text
        notes = []

        # absolute repo path used as a value
        for pattern, replacement in (
            (re.escape(f'Path(r"{PROJ}")'), "_paths.REPO_ROOT"),
            (re.escape(f'Path("{PROJ}")'), "_paths.REPO_ROOT"),
            (re.escape(PROJ), None),
        ):
            if replacement is None:
                continue
            if pattern in text and re.search(rf'Path\(r?"{re.escape(PROJ)}"\)', text):
                text = re.sub(rf'Path\(r?"{re.escape(PROJ)}"\)', replacement, text)
                notes.append("absolute ROOT -> _paths.REPO_ROOT")

        # old directory segments
        if 'watchdog_sessions' in text or 'task_logs' in text:
            text = text.replace('"watchdog_sessions\\\\', '"sessions\\\\')
            text = text.replace("'watchdog_sessions\\\\", "'sessions\\\\")
            text = text.replace('watchdog_sessions/', 'sessions/')
            text = text.replace('"watchdog_sessions"', "_paths.SESSION_ROOT")
            text = text.replace("'watchdog_sessions'", "_paths.SESSION_ROOT")
            text = text.replace('"task_logs"', "_paths.TASK_LOG_ROOT")
            text = text.replace("'task_logs'", "_paths.TASK_LOG_ROOT")
            notes.append("old segment names -> artifacts layout")

        if "_paths." in text:
            text, inserted = ensure_bootstrap(text)
            if inserted:
                notes.append("bootstrap")

        if text != original:
            path.write_text(text, encoding="utf-8")
            print(f"{path.name}: {', '.join(notes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
