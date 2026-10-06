"""Move the shared-path bootstrap to AFTER the standard-library imports.

The first version of the rewrite inserted the bootstrap immediately after
`from __future__ import annotations`, which is BEFORE lines like `import sys` and
`from pathlib import Path`. The inserted code calls sys.path.insert(...) and
Path(__file__), so every rewritten script would have raised NameError on import -
the tools would have looked organised and been completely broken.

This script enforces the correct order instead:
    docstring -> __future__ -> stdlib imports -> bootstrap -> local imports

It is idempotent: running it again finds the bootstrap already in the right place
and reports UNCHANGED.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(r"C:\bobo_document\temp\optimize_system")

BOOTSTRAP_LINES = [
    "# --- shared path resolution -------------------------------------------------",
    "# This script lives under <repo>/src/, so the repository root is reached from",
    "# this file rather than from the working directory. All machine-specific paths",
    "# (third-party tools, artifact output) come from src/common/paths.py so that a",
    "# clone works without editing source.",
    "sys.path.insert(0, str(Path(__file__).resolve().parents[2]))",
    "from src.common import paths as _paths  # noqa: E402",
]

# Any line that belongs to an already-inserted bootstrap block.
BOOTSTRAP_PATTERNS = [
    re.compile(r'^sys\.path\.insert\(0, str\(Path\(__file__\)\.resolve\(\)\.parents\[2\]\)\)\s*$'),
    re.compile(r'^from src\.common import paths as _paths.*$'),
    re.compile(r'^from src\.common import hwinfo_shared.*$'),
    re.compile(r'^# --- shared path resolution.*$'),
    re.compile(r'^# This script lives under <repo>/src/.*$'),
    re.compile(r'^# this file rather than from the working directory.*$'),
    re.compile(r'^# \(third-party tools, artifact output\).*$'),
    re.compile(r'^# clone works without editing source\.$'),
]


def is_bootstrap_line(line: str) -> bool:
    return any(p.match(line.strip()) for p in BOOTSTRAP_PATTERNS)


def find_insert_index(lines: list[str]) -> int:
    """Index just past the last top-level stdlib/__future__ import."""
    index = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        # stop scanning once we hit real code (a def/class/assignment)
        if re.match(r'^(def |class |@|[A-Z_]+ = |if __name__)', stripped):
            break
        if stripped.startswith(("import ", "from ")):
            index = i + 1
    return index


def main() -> int:
    targets = sorted(ROOT.glob("src/**/*.py"))
    changed = 0
    for path in targets:
        rel = path.relative_to(ROOT)
        if "bench" in rel.parts and "analysis" in rel.parts and path.name.startswith(("rewire_", "fix_hwinfo", "bootstrap")):
            continue
        text = path.read_text(encoding="utf-8")
        if "_paths" not in text and "src.common import hwinfo_shared" not in text:
            continue

        lines = text.split("\n")
        body = [line for line in lines if not is_bootstrap_line(line)]
        # locate insertion point in the cleaned body
        index = find_insert_index(body)

        # does this file need hwinfo_shared?
        needs_hwinfo = "hwinfo_shared." in text
        block = list(BOOTSTRAP_LINES)
        if needs_hwinfo:
            block.append("from src.common import hwinfo_shared  # noqa: E402")

        new_lines = body[:index] + [""] + block + body[index:]
        new_text = "\n".join(new_lines)
        new_text = re.sub(r'\n{4,}', '\n\n\n', new_text)

        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            print(f"FIXED     {rel}  (bootstrap now at line {index + 2})")
            changed += 1
        else:
            print(f"UNCHANGED {rel}")
    print(f"\n{changed} file(s) rewritten")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
