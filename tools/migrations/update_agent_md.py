"""Update AGENT.md for the reorganized tree.

AGENT.md is the operating manual, so its commands have to actually run. It
referenced the old layout in ~30 places (tools/<script>.py, watchdog_sessions/,
task_logs/, runs/<run>). Each is repointed at the new location, and a note at the
top tells a reader that the layout changed - otherwise someone following the
historical sections would look for directories that no longer exist.

Deliberately NOT rewritten: the C:\\bobo... references. Those appear inside a
chronological record of what was done on specific dates, and editing them would
falsify that record. A migration note is added instead.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(r"C:\bobo_document\temp\optimize_system")
TARGET = ROOT / "AGENT.md"

BOOT_NOTE = """
> **目录结构已于 2026-10-02 重构。** 源码全部移入 `src/`，所有运行产物移入
> `artifacts/`（该目录**不入 git**）。本文档中的命令与路径已同步更新；但**第 4 节
> 及更早的历史记录里出现的 `C:\\bobo_...` 绝对路径是当时的事实，故意保留不改**，
> 以免篡改历史记录。当前布局见 `README.md`，路径解析见 `docs/CONFIGURATION.md`。
"""

# Script moves: old -> new relative path
SCRIPT_MOVES = [
    ("tools\\deadman_watchdog.py", "src\\watchdog\\deadman_watchdog.py"),
    ("tools\\sidecar_sensors.py", "src\\watchdog\\sidecar_sensors.py"),
    ("tools\\rycolab_controller.py", "src\\rycolab\\rycolab_controller.py"),
    ("tools\\engine_runner.py", "src\\rycolab\\engine_runner.py"),
    ("tools\\engine_ab_controller.py", "src\\rycolab\\engine_ab_controller.py"),
    ("tools\\ycruncher_controller.py", "src\\engines\\ycruncher_controller.py"),
    ("tools\\resolution_check.py", "src\\engines\\resolution_check.py"),
    ("tools\\hwinfo_shared.py", "src\\common\\hwinfo_shared.py"),
    ("tools\\read_memory_timings.py", "src\\common\\read_memory_timings.py"),
    ("tools\\archive_watchdog_session.py", "src\\common\\archive_watchdog_session.py"),
    ("tools\\task_launch.ps1", "src\\elevated\\task_launch.ps1"),
    ("tools\\setup_uac_free_task.ps1", "src\\elevated\\setup_uac_free_task.ps1"),
    ("tools\\co_arm_elevated.ps1", "src\\elevated\\co_arm_elevated.ps1"),
    ("tools\\rycolab_workload_elevated.ps1", "src\\elevated\\rycolab_workload_elevated.ps1"),
    ("tools\\co_monitor.ps1", "src\\elevated\\co_monitor.ps1"),
    # job parameter files moved to config/
    ("tools\\co_job_accept.json", "config\\co_job_accept.json"),
    ("tools\\co_job_sweep.json", "config\\co_job_sweep.json"),
    ("tools\\co_job_resolution.json", "config\\co_job_resolution.json"),
    ("tools\\co_workload_sweep.json", "config\\co_workload_sweep.json"),
    ("tools\\co_task_op.json", "config\\co_task_op.json"),
]

# Forward-slash / bare-directory forms
DIR_MOVES = [
    ("tools/deadman_watchdog.py", "src/watchdog/deadman_watchdog.py"),
    ("tools/sidecar_sensors.py", "src/watchdog/sidecar_sensors.py"),
    ("tools/rycolab_controller.py", "src/rycolab/rycolab_controller.py"),
    ("tools/resolution_check.py", "src/engines/resolution_check.py"),
    ("tools/task_launch.ps1", "src/elevated/task_launch.ps1"),
    ("tools/hwinfo_shared.py", "src/common/hwinfo_shared.py"),
    ("`tools/`", "`src/`"),
    ("watchdog_sessions/", "artifacts/sessions/"),
    ("task_logs/", "artifacts/task_logs/"),
    ("`runs/`", "`artifacts/runs/`"),
    ("runs/CURRENT_RUN.txt", "artifacts/runs/CURRENT_RUN.txt"),
]


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    original = text
    counts = {"script": 0, "dir": 0}

    for old, new in SCRIPT_MOVES:
        if old in text:
            counts["script"] += text.count(old)
            text = text.replace(old, new)

    for old, new in DIR_MOVES:
        if old in text:
            counts["dir"] += text.count(old)
            text = text.replace(old, new)

    # The tools\ prefix for anything not covered above (e.g. a script mentioned
    # only by bare name) - map remaining tools\<something>.py to src\ by area.
    def relocate(match: re.Match[str]) -> str:
        name = match.group(1)
        for area in ("watchdog", "rycolab", "engines", "common"):
            if (ROOT / "src" / area / name).exists():
                return f"src\\{area}\\{name}"
        return match.group(0)

    text = re.sub(r"tools\\([A-Za-z_][A-Za-z0-9_]*\.py)", relocate, text)

    # Insert the layout note right after the H1 line.
    if "目录结构已于" not in text:
        lines = text.split("\n")
        insert_at = 1
        for i, line in enumerate(lines[:6]):
            if line.startswith("# "):
                insert_at = i + 1
                break
        text = "\n".join(lines[:insert_at] + [BOOT_NOTE] + lines[insert_at:])

    if text != original:
        TARGET.write_text(text, encoding="utf-8")
        print(f"AGENT.md updated: {counts['script']} script path(s), {counts['dir']} directory path(s)")
    else:
        print("AGENT.md: unchanged")

    # report anything still pointing at a directory that no longer exists
    print()
    print("remaining references to the old layout:")
    for pattern in ("tools\\\\", "watchdog_sessions", "task_logs"):
        hits = [m.start() for m in re.finditer(pattern, TARGET.read_text(encoding="utf-8"))]
        print(f"  {pattern:22} {len(hits)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
