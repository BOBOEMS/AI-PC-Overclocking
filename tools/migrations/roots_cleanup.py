"""Point the analysis scripts' own ROOT/PYTHON constants at the shared paths module.

Last hardcoded values in the Python tree: each analysis script defined its own
absolute ROOT (the author's checkout) and some defined PYTHON (the author's
interpreter). Both now come from src/common/paths.py, so a clone resolves them
from wherever it happens to live.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = _paths.REPO_ROOT
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


REPLACEMENTS = [
    (f'ROOT = Path(r"{PROJ}")', "ROOT = _paths.REPO_ROOT"),
    (f'ROOT = Path("{PROJ}")', "ROOT = _paths.REPO_ROOT"),
    ('PYTHON = r"C:\\bobo_worktool\\Python312\\python.exe"', "PYTHON = str(_paths.PYTHON_EXE)"),
    ('PYTHON = Path(r"C:\\bobo_worktool\\Python312\\python.exe")', "PYTHON = _paths.PYTHON_EXE"),
    ('ROUND5_STREAM = Path(r"C:\\bobo_worktool\\ryzen-smu-cli\\ab4-light-repeat\\stream_r2_m0.jsonl")',
     'ROUND5_STREAM = _paths.RYZEN_SMU_CLI.parent / "ab4-light-repeat" / "stream_r2_m0.jsonl"'),
    ('sys.path.insert(0, r"C:\\bobo_document\\temp\\optimize_system\\tools")',
     'sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))'),
    (f'Path(r"{PROJ}\\runs\\', '(_paths.RUN_ROOT / "'),
]


def main() -> int:
    for path in sorted(ANALYSIS.glob("*.py")):
        if path.name in MAINTENANCE:
            continue
        text = path.read_text(encoding="utf-8")
        original = text
        notes = []
        for old, new in REPLACEMENTS:
            if old in text:
                text = text.replace(old, new)
                notes.append(old.split("=")[0].strip())
        if "_paths." in text:
            text, inserted = ensure_bootstrap(text)
            if inserted:
                notes.append("bootstrap")
        if text != original:
            path.write_text(text, encoding="utf-8")
            print(f"{path.name}: {', '.join(dict.fromkeys(notes))}")
        else:
            print(f"{path.name}: (unchanged)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
