"""Inventory the external tool dependencies precisely.

Reports, for every script in the repo, the absolute paths it references that lie
outside the repository. These are the tools a new user must install, so each one
needs a source URL in the documentation.

Also lists which source files are currently NOT tracked by git, because a clone
that is missing source is the main thing that makes a repository unshareable.
"""
from __future__ import annotations

import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
import sys

# --- shared path resolution -------------------------------------------------
# This script lives under <repo>/src/, so the repository root is reached from
# this file rather than from the working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.common import paths as _paths  # noqa: E402

ROOT = _paths.REPO_ROOT
SOURCE_SUFFIXES = {".py", ".ps1", ".c", ".cs", ".js", ".sh"}
TEXT_SUFFIXES = SOURCE_SUFFIXES | {".md", ".json", ".ini", ".txt"}

# Any Windows absolute path. Pattern is deliberately loose: it must also catch
# paths inside string literals with escaped backslashes, which is how they appear
# in PowerShell.
ABS = re.compile(r"[A-Za-z]:[\\/](?:[^\\/:*?\"<>|\r\n]+[\\/])*[^\\/:*?\"<>|\r\n]*")


def tracked_set() -> set[str]:
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files"],
                         capture_output=True, text=True, errors="replace", check=False)
    return {line.strip().replace("/", "\\") for line in out.stdout.splitlines() if line.strip()}


def main() -> int:
    tracked = tracked_set()
    scripts = [p for p in ROOT.rglob("*") if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES]

    refs: Counter[str] = Counter()
    ref_files: defaultdict[str, list[str]] = defaultdict(list)
    for path in scripts:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            continue
        for match in ABS.findall(text):
            norm = match.replace("/", "\\").rstrip("\\")
            low = norm.lower()
            if low.startswith(str(ROOT).lower()):
                continue
            if low.startswith(r"c:\windows"):
                continue
            parts = norm.split("\\")
            # group by the executable or the tool root, whichever is deeper
            if len(parts) >= 2 and "." in parts[-1]:
                key = "\\".join(parts[:-1]) + "\\" + parts[-1]
            else:
                key = "\\".join(parts[:4])
            refs[key] += 1
            rel = str(path.relative_to(ROOT))
            if rel not in ref_files[key]:
                ref_files[key].append(rel)

    print("=== external tool paths referenced by repo scripts ===")
    print(f"(grouped; {len(refs)} distinct paths)\n")
    for key, count in refs.most_common(60):
        print(f"{count:>3}x  {key}")
        for f in ref_files[key][:3]:
            print(f"        used by: {f}")

    print()
    print("=== source files NOT tracked by git (a clone would be missing these) ===")
    missing = []
    for path in sorted(scripts):
        if path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        rel = str(path.relative_to(ROOT)).replace("/", "\\")
        if rel not in tracked:
            missing.append(rel)
    for rel in missing:
        print(f"  {rel}")
    print(f"  total: {len(missing)} source file(s) untracked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
