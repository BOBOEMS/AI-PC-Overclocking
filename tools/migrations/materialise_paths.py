"""Replace the remaining hardcoded author-machine paths in the analysis scripts.

These scripts were written against one machine's layout, so they contain literals
like r"C:\\bobo_document\\temp\\optimize_system\\watchdog_sessions". That absolute
prefix is exactly what makes a repository unusable to anyone else, and it also
still points at the OLD location now that sessions live under artifacts/.

Each literal is rewritten to the corresponding constant from src/common/paths.py,
and the bootstrap is inserted where a file does not already import it.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(r"C:\bobo_document\temp\optimize_system")
ANALYSIS = ROOT / "src" / "bench" / "analysis"

PROJ = r"C:\bobo_document\temp\optimize_system"

# Order matters: the longer, more specific prefixes first.
REPLACEMENTS = [
    (f'Path(r"{PROJ}\\watchdog_sessions")', "_paths.SESSION_ROOT"),
    (f'Path(r"{PROJ}\\task_logs")', "_paths.TASK_LOG_ROOT"),
    (f'Path(r"{PROJ}\\watchdog_sessions\\', '(_paths.SESSION_ROOT / "'),
    (f'Path(r"{PROJ}\\task_logs\\', '(_paths.TASK_LOG_ROOT / "'),
    (f'r"{PROJ}\\watchdog_sessions\\', 'r"'),
    (f'r"{PROJ}\\task_logs\\', 'r"'),
    (f'"{PROJ}\\watchdog_sessions\\', '"'),
    (f'"{PROJ}\\task_logs\\', '"'),
    ('ROOT / "watchdog_sessions/', 'ROOT / "sessions/'),
    ('ROOT / "task_logs/', 'ROOT / "task_logs/'),
]

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
        # maintenance scripts carry these literals as pattern data on purpose
        if path.name in {"rewire_paths.py", "port_finish.py", "materialise_paths.py",
                         "bootstrap_order.py", "fix_hwinfo_imports.py"}:
            continue
        text = path.read_text(encoding="utf-8")
        original = text
        applied = []

        for old, new in REPLACEMENTS:
            if old in text:
                text = text.replace(old, new)
                applied.append(old[:52])

        # close the parenthesis opened by the `(_paths.X / "name")` rewrite
        text = re.sub(r'(\(_paths\.(?:SESSION_ROOT|TASK_LOG_ROOT) / ")([^"]+)("\))',
                      r'\1\2\3', text)

        if "_paths." in text:
            text, inserted = ensure_bootstrap(text)
            if inserted:
                applied.append("bootstrap")

        if text != original:
            path.write_text(text, encoding="utf-8")
            print(f"{path.name}: {len(applied)} change(s)")
            for item in applied:
                print(f"    {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
