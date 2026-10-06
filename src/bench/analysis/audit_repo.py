"""Audit the repository: what is tracked, how big it is, and what external tools
the scripts depend on.

Written to answer three questions before reorganising:
  1. Which tracked files are source (worth sharing) vs generated logs/sessions
     (noise that a clone would inherit)?
  2. How much of the tracked tree is human-readable result docs, which are worth
     keeping as evidence even though they live next to machine logs?
  3. Which paths outside the repository do the scripts require? Those are the ones
     that need a documented source URL so someone else can install them.
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

TEXT_SUFFIXES = {".py", ".ps1", ".md", ".json", ".c", ".jsonl", ".txt"}

# Absolute Windows paths that are not inside the repo: these are external tools.
ABS_PATH = re.compile(r"[A-Za-z]:\\[^\s\"'`,;)\]]+")


def tracked() -> list[Path]:
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files"],
                         capture_output=True, text=True, errors="replace", check=False)
    return [ROOT / line.strip() for line in out.stdout.splitlines() if line.strip()]


def main() -> int:
    files = tracked()
    print(f"tracked files: {len(files)}")

    total = 0
    by_top: Counter[str] = Counter()
    by_ext: Counter[str] = Counter()
    size_by_top: defaultdict[str, int] = defaultdict(int)
    for path in files:
        if not path.exists():
            continue
        size = path.stat().st_size
        total += size
        top = path.relative_to(ROOT).parts[0]
        by_top[top] += 1
        size_by_top[top] += size
        by_ext[path.suffix.lower() or "(none)"] += 1

    print(f"tracked size: {total / 1024 / 1024:.1f} MB")
    print()
    print(f"{'top-level':26}{'files':>7}{'size':>12}")
    for top, count in by_top.most_common():
        print(f"{top:26}{count:>7}{size_by_top[top] / 1024 / 1024:>11.1f}M")
    print()
    print("by extension:")
    for ext, count in by_ext.most_common():
        print(f"  {ext:10}{count:>6}")

    # Which of the tracked .md files are inside generated run dirs?
    print()
    docs = [p for p in files if p.suffix.lower() == ".md" and p.exists()]
    inside_runs = [p for p in docs if "runs" in p.relative_to(ROOT).parts]
    print(f"tracked .md total: {len(docs)}   inside runs/: {len(inside_runs)}")

    # External tool paths referenced by scripts
    print()
    print("=== external tool paths referenced by scripts ===")
    refs: Counter[str] = Counter()
    for path in files:
        if path.suffix.lower() not in {".py", ".ps1", ".c"} or not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in ABS_PATH.findall(text):
            if match.lower().startswith(str(ROOT).lower()):
                continue
            # normalise to the tool root, keeping the drive and first dirs
            parts = match.split("\\")
            key = "\\".join(parts[:4])
            refs[key] += 1

    for key, count in refs.most_common(40):
        print(f"  {count:>3}x  {key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
