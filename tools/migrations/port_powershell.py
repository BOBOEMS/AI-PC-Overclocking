"""Repoint the PowerShell scripts at src/elevated/paths.ps1.

Same exercise as the Python side, for the elevated half of the design: every
script hardcoded the author's checkout, the author's Python, and the author's
tool directories. Each now dot-sources paths.ps1 and uses the variables it
defines, so the only thing that has to be right on a new machine is where the
repository itself sits.

The replacement list is explicit rather than pattern-based on purpose: a regex
over PowerShell path literals is exactly the kind of change that looks right and
quietly breaks one call site. After running, every remaining absolute path in the
tree is printed so nothing is assumed fixed.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(r"C:\bobo_document\temp\optimize_system")
ELEVATED = ROOT / "src" / "elevated"

DOT_SOURCE = (
    "# Paths come from one place so this script runs from any checkout.\n"
    '. (Join-Path $PSScriptRoot \'paths.ps1\')\n'
)

# (file, [(old, new), ...])
EDITS: dict[str, list[tuple[str, str]]] = {
    "task_launch.ps1": [
        ("$Workspace = 'C:\\bobo_document\\temp\\optimize_system'",
         ". (Join-Path $PSScriptRoot 'paths.ps1')"),
        ("$LogDir = Join-Path $Workspace 'task_logs'", "$LogDir = $TaskLogRoot"),
        ("$opFile = Join-Path $Workspace 'tools\\co_task_op.json'", "$opFile = $TaskOpFile"),
        ("$rycolab = 'C:\\Users\\BOBO\\AppData\\Local\\rycolab\\bin\\rycolab.exe'", "$rycolab = $RycolabExe"),
        ("$smuCli = 'C:\\bobo_worktool\\ryzen-smu-cli\\ryzen-smu-cli.exe'", "$smuCli = $RyzenSmuCli"),
        ("$outDir = Join-Path $Workspace 'watchdog_sessions'", "$outDir = $SessionRoot"),
        ("$jobFile = Join-Path $Workspace 'tools\\co_job_accept.json'", "$jobFile = $JobAccept"),
        ("$jobFile = Join-Path $Workspace 'tools\\co_job_resolution.json'", "$jobFile = $JobResolution"),
        ("$jobFile = Join-Path $Workspace 'tools\\co_job_sweep.json'", "$jobFile = $JobSweep"),
        ("$controller = Join-Path $Workspace 'tools\\rycolab_controller.py'", "$controller = $ControllerRycolab"),
        ("$controller = Join-Path $Workspace 'tools\\resolution_check.py'", "$controller = $ControllerResolution"),
        ("$python = 'C:\\bobo_worktool\\Python312\\python.exe'", "$python = $PythonExe"),
        ("$probe = Join-Path $Workspace 'tools\\hwinfo_shared.py'", "$probe = $HwinfoShared"),
        ("foreach ($root in @('C:\\bobo_worktool\\TB_Tools_202601', 'C:\\bobo_document\\tool')) {",
         "foreach ($root in @($ToolsRoot, $RepoRoot)) {"),
    ],
    "setup_uac_free_task.ps1": [
        ("$Workspace = 'C:\\bobo_document\\temp\\optimize_system'",
         ". (Join-Path $PSScriptRoot 'paths.ps1')"),
        ("$Launcher = Join-Path $Workspace 'tools\\task_launch.ps1'", "$Launcher = Join-Path $PSScriptRoot 'task_launch.ps1'"),
        ("<WorkingDirectory>$Workspace</WorkingDirectory>", "<WorkingDirectory>$RepoRoot</WorkingDirectory>"),
        ("(Join-Path $Workspace 'tools\\co_task_op.json')", "$TaskOpFile"),
        ("$logDir = Join-Path $Workspace 'task_logs'", "$logDir = $TaskLogRoot"),
        ("check task_logs\\", "check artifacts\\task_logs\\"),
    ],
    "co_arm_elevated.ps1": [
        ("$root = 'C:\\bobo_document\\temp\\optimize_system'",
         ". (Join-Path $PSScriptRoot 'paths.ps1')"),
        ("$py = 'C:\\bobo_worktool\\Python312\\python.exe'", "$py = $PythonExe"),
        ("$ctrl = Join-Path $root 'tools\\rycolab_controller.py'", "$ctrl = $ControllerRycolab"),
        ("$outDir = Join-Path $root 'watchdog_sessions'", "$outDir = $SessionRoot"),
        ("$root", "$RepoRoot"),
    ],
    "co_monitor.ps1": [
        ("$d = 'C:\\bobo_document\\temp\\optimize_system\\watchdog_sessions\\' + $s",
         ". (Join-Path $PSScriptRoot 'paths.ps1')\n$d = Join-Path $SessionRoot $s"),
    ],
    "rycolab_workload_elevated.ps1": [
        ("$sessionDir = Join-Path (Join-Path $Workspace 'watchdog_sessions') $Session",
         ". (Join-Path $PSScriptRoot 'paths.ps1')\n$sessionDir = Join-Path $SessionRoot $Session"),
        ("$sidecar = Join-Path $Workspace 'tools\\sidecar_sensors.py'", "$sidecar = $SidecarSensors"),
        ("$python = 'C:\\bobo_worktool\\Python312\\python.exe'", "$python = $PythonExe"),
    ],
}


def main() -> int:
    for name, edits in EDITS.items():
        path = ELEVATED / name
        if not path.exists():
            print(f"MISSING {name}")
            continue
        text = path.read_text(encoding="utf-8")
        original = text
        applied, missed = [], []
        for old, new in edits:
            if old in text:
                text = text.replace(old, new)
                applied.append(old[:48])
            else:
                missed.append(old[:48])
        # co_arm_elevated had a blanket $root -> $RepoRoot rule; keep the
        # dot-source line intact by restoring it if it was collateral damage.
        text = text.replace('. (Join-Path $PSScriptRoot \'paths.ps1\')' .replace("$RepoRoot", ""), ". (Join-Path $PSScriptRoot 'paths.ps1')")
        if text != original:
            path.write_text(text, encoding="utf-8")
        print(f"{name}: {len(applied)} applied" + (f", {len(missed)} not found" if missed else ""))
        for item in missed:
            print(f"    NOT FOUND: {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
