"""Repoint the two watchdog guides at the new layout.

Unlike AGENT.md, these documents are current operating instructions rather than a
dated record, so every command in them has to work as written. They still refer
to tools/<script>.py and watchdog_sessions/ from before the reorganisation.

The long handoff document (docs/HANDOFF_20261001-CPU负压.md) is deliberately left
alone: it is a point-in-time record of one session, and rewriting the paths inside
it would misrepresent what was actually done on that date. A dated banner is added
to it instead so a reader is not misled into looking for old directories.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(r"C:\bobo_document\temp\optimize_system")

SCRIPT_MOVES = [
    ("tools\\co_arm_elevated.ps1", "src\\elevated\\co_arm_elevated.ps1"),
    ("tools\\rycolab_controller.py", "src\\rycolab\\rycolab_controller.py"),
    ("tools\\deadman_watchdog.py", "src\\watchdog\\deadman_watchdog.py"),
    ("tools\\archive_watchdog_session.py", "src\\common\\archive_watchdog_session.py"),
    ("tools\\sidecar_sensors.py", "src\\watchdog\\sidecar_sensors.py"),
    ("tools\\co_task_op.json", "config\\co_task_op.json"),
    ("tools\\task_launch.ps1", "src\\elevated\\task_launch.ps1"),
]

SEGMENT_MOVES = [
    ("watchdog_sessions/", "artifacts/sessions/"),
    ("watchdog_sessions\\", "artifacts\\sessions\\"),
    ("task_logs/", "artifacts/task_logs/"),
    ("<repo root>/watchdog_sessions/", "<repo root>/artifacts/sessions/"),
]

HANDOFF_BANNER = """> **注意：这是一份日期为 2026-10-01 的历史交接记录，不是当前说明。**
> 其中的 `tools\\...`、`watchdog_sessions\\`、`task_logs\\` 路径是当时的事实，
> **故意保留未改写**。目录已在 2026-10-02 重构：源码在 `src/`，运行产物在
> `artifacts/`。当前结构与用法见 `README.md`、`docs/ARCHITECTURE.md`、
> `docs/CONFIGURATION.md`。
"""


def main() -> int:
    for rel in ("docs\\CO_WATCHDOG_README.md", "docs\\WATCHDOG_README.md"):
        path = ROOT / rel
        if not path.exists():
            print(f"MISSING {rel}")
            continue
        text = path.read_text(encoding="utf-8")
        original = text
        for old, new in SCRIPT_MOVES + SEGMENT_MOVES:
            if old in text:
                text = text.replace(old, new)
        if text != original:
            path.write_text(text, encoding="utf-8")
            print(f"updated {rel}")
        else:
            print(f"unchanged {rel}")

    # Banner on the dated handoff, without touching its content.
    handoff = ROOT / "docs" / "HANDOFF_20261001-CPU负压.md"
    if handoff.exists():
        text = handoff.read_text(encoding="utf-8")
        if "历史交接记录" not in text:
            lines = text.split("\n")
            at = 1 if lines and lines[0].startswith("# ") else 0
            text = "\n".join(lines[:at] + ["", HANDOFF_BANNER] + lines[at:])
            handoff.write_text(text, encoding="utf-8")
            print("banner added to HANDOFF_20261001-CPU负压.md")
        else:
            print("HANDOFF already carries the banner")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
