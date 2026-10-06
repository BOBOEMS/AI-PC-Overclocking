"""Repoint every script at the shared paths module.

The directory reorganisation moved the scripts deeper (tools/ -> src/<area>/), so
every `Path(__file__).resolve().parents[1]` that used to mean "the repository
root" now means "the src directory". Rather than leave a second, subtly wrong
notion of where things live, each script is rewired to import src/common/paths.py.

This is a one-shot maintenance script; it is kept because doing the same edit by
hand across fourteen files is exactly where mistakes get made, and because the
"changed / not found / left alone" report is the evidence that none was.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(r"C:\bobo_document\temp\optimize_system")

# Bootstrap inserted after `from __future__ import annotations` (or after the
# module docstring when there is no __future__ import).
BOOTSTRAP = '''
# --- shared path resolution -------------------------------------------------
# This script lives under <repo>/src/, so the repository root is reached from
# this file rather than from the working directory. All machine-specific paths
# (third-party tools, artifact output) come from src/common/paths.py so that a
# clone works without editing source.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.common import paths as _paths  # noqa: E402
'''

# (file, [(regex, replacement), ...], must_match_all)
EDITS = {
    r"src\rycolab\rycolab_controller.py": [
        (r'^ROOT = Path\(__file__\)\.resolve\(\)\.parents\[1\]$',
         'ROOT = _paths.REPO_ROOT'),
        (r'^RYCOLAB_EXE = Path\(r"[^"]+"\)$',
         'RYCOLAB_EXE = _paths.RYCOLAB_EXE'),
        (r'^RYCOLAB_APPDATA = Path\(r"[^"]+"\)$',
         'RYCOLAB_APPDATA = _paths.RYCOLAB_APPDATA'),
        (r'^RYZEN_SMU_CLI = Path\(r"[^"]+"\)$',
         'RYZEN_SMU_CLI = _paths.RYZEN_SMU_CLI'),
        (r'^DEFAULT_YCRUNCHER_EXE = Path\(r"[^"]+"\)$',
         'DEFAULT_YCRUNCHER_EXE = _paths.YCRUNCHER_EXE'),
    ],
    r"src\engines\resolution_check.py": [
        (r'^ROOT = Path\(__file__\)\.resolve\(\)\.parents\[1\]$',
         'ROOT = _paths.REPO_ROOT'),
        (r'^SMU_CLI = Path\(r"[^"]+"\)$',
         'SMU_CLI = _paths.RYZEN_SMU_CLI'),
        (r'^RYCOLAB_BINARIES = Path\(r"[^"]+"\)$',
         'RYCOLAB_BINARIES = _paths.RYCOLAB_BINARIES'),
        (r'^PYTHON = Path\(sys\.executable\)$',
         'PYTHON = _paths.PYTHON_EXE'),
    ],
    r"src\rycolab\engine_runner.py": [
        (r'^RYCOLAB_BINARIES = Path\(r"[^"]+"\)$',
         'RYCOLAB_BINARIES = _paths.RYCOLAB_BINARIES'),
    ],
    r"src\rycolab\engine_ab_controller.py": [
        (r'^ROOT = Path\(__file__\)\.resolve\(\)\.parents\[1\]$',
         'ROOT = _paths.REPO_ROOT'),
        (r'^RYCOLAB_BINARIES = Path\(r"[^"]+"\)$',
         'RYCOLAB_BINARIES = _paths.RYCOLAB_BINARIES'),
    ],
    r"src\engines\ycruncher_controller.py": [
        (r'^ROOT = Path\(__file__\)\.resolve\(\)\.parents\[1\]$',
         'ROOT = _paths.REPO_ROOT'),
        (r'^DEFAULT_YCRUNCHER_DIR = Path\(r"[^"]+"\)$',
         'DEFAULT_YCRUNCHER_DIR = _paths.YCRUNCHER_DIR'),
    ],
    r"src\watchdog\deadman_watchdog.py": [
        (r'^WORKSPACE = Path\(__file__\)\.resolve\(\)\.parents\[1\]$',
         'WORKSPACE = _paths.REPO_ROOT'),
        (r'^SESSIONS = WORKSPACE / "watchdog_sessions"$',
         'SESSIONS = _paths.SESSION_ROOT'),
    ],
    r"src\common\archive_watchdog_session.py": [
        (r'^ROOT = Path\(__file__\)\.resolve\(\)\.parents\[1\]$',
         'ROOT = _paths.REPO_ROOT'),
    ],
}


def insert_bootstrap(text: str) -> str:
    if "_paths" in text:
        return text
    marker = "from __future__ import annotations\n"
    if marker in text:
        return text.replace(marker, marker + BOOTSTRAP, 1)
    # no __future__ import: put it after the closing docstring
    match = re.match(r'(\s*(?:#[^\n]*\n)*\s*(?:""".*?"""|\'\'\'.*?\'\'\')\s*\n)', text, re.S)
    if match:
        return text[:match.end()] + BOOTSTRAP + text[match.end():]
    return BOOTSTRAP + text


def main() -> int:
    for rel, edits in EDITS.items():
        path = ROOT / rel
        if not path.exists():
            print(f"MISSING  {rel}")
            continue
        text = path.read_text(encoding="utf-8")
        original = text
        applied, missed = [], []
        for pattern, replacement in edits:
            new_text, count = re.subn(pattern, replacement, text, flags=re.M)
            if count:
                text = new_text
                applied.append(replacement.split("=")[0].strip())
            else:
                missed.append(pattern)

        if text != original:
            text = insert_bootstrap(text)
            path.write_text(text, encoding="utf-8")
        status = "OK  " if applied else "SKIP"
        print(f"{status} {rel}")
        if applied:
            print(f"       rewired: {', '.join(applied)}")
        if missed:
            print(f"       NOT FOUND ({len(missed)}): {missed[0][:70]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
