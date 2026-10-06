#requires -Version 5.1
<#
  paths.ps1 - single source of truth for every path the launcher needs.

  Dot-source this from any script under src/:

      . "$PSScriptRoot\paths.ps1"          # when the script sits in src/elevated/
      . (Join-Path $PSScriptRoot '..\elevated\paths.ps1')

  It mirrors src/common/paths.py on purpose: the elevated PowerShell half and the
  non-elevated Python half must agree on where the artifact tree and the
  third-party tools live, otherwise the watchdog cannot find the session the
  controller armed. Precedence is the same on both sides:

      environment variable  ->  config/paths.json  ->  built-in default

  WHY THIS FILE EXISTS
  --------------------
  Every script here used to hardcode one machine's layout, including the author's
  user profile and download folder. That is precisely what makes a repository
  unusable to anyone else. Nothing below assumes a user name or a checkout path:
  the repository root is derived from this file's own location.

  DIRECTORY CONVENTIONS
  ---------------------
      <repo>/src/         source code           (tracked)
      <repo>/config/      settings + job files  (tracked)
      <repo>/docs/        documentation         (tracked)
      <repo>/artifacts/   ALL generated output  (NOT tracked)
#>

Set-StrictMode -Version Latest

# --------------------------------------------------------------------------- #
# Repository layout
# --------------------------------------------------------------------------- #
# This file is <repo>/src/elevated/paths.ps1, so the repo root is two levels up.
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path

$ScriptsRoot = Join-Path $RepoRoot 'src'
$ConfigRoot  = Join-Path $RepoRoot 'config'
$DocsRoot    = Join-Path $RepoRoot 'docs'

# Optional user-level config, so machine-specific tool locations never have to be
# committed. Deliberately OUTSIDE the repository: setting a user environment
# variable does not reach a process that is already running (a new child inherits
# its parent's environment block), which made environment variables unreliable
# for a scheduled task. A file is read fresh on every launch.
#
#   %APPDATA%\overclock-toolkit\paths.json     {"ryzenSmuCli": "...", "hwinfoExe": "..."}
#
# config/paths.local.json works too for a checkout-local override, but it must not
# be committed (see .gitignore).
$PathsConfig = @{}
$configCandidates = @(
  (Join-Path ([Environment]::GetFolderPath('ApplicationData')) 'overclock-toolkit\paths.json'),
  (Join-Path $ConfigRoot 'paths.local.json')
)
foreach ($candidate in $configCandidates) {
  if (-not (Test-Path -LiteralPath $candidate)) { continue }
  try {
    $loaded = Get-Content $candidate -Raw | ConvertFrom-Json -AsHashtable
    foreach ($key in $loaded.Keys) { $PathsConfig[$key] = $loaded[$key] }
  } catch {
    Write-Warning "could not parse ${candidate}: $($_.Exception.Message)"
  }
}

function Resolve-Setting {
  <#
    environment variable -> user config file -> default
    Kept as a function so the precedence rule lives in exactly one place.
    $Default may be an empty string, which signals "no default; caller decides".
  #>
  param(
    [Parameter(Mandatory)][string]$EnvName,
    [Parameter(Mandatory)][string]$ConfigKey,
    [AllowEmptyString()][string]$Default = ''
  )
  $fromEnv = [Environment]::GetEnvironmentVariable($EnvName)
  if ($fromEnv) { return $fromEnv }
  if ($PathsConfig.ContainsKey($ConfigKey) -and $PathsConfig[$ConfigKey]) { return $PathsConfig[$ConfigKey] }
  return $Default
}

# --------------------------------------------------------------------------- #
# Generated output (never tracked - see .gitignore)
# --------------------------------------------------------------------------- #
$ArtifactRoot  = Resolve-Setting 'OVERCLOCK_ARTIFACT_ROOT' 'artifactRoot' (Join-Path $RepoRoot 'artifacts')
$SessionRoot   = Join-Path $ArtifactRoot 'sessions'      # dead-man watchdog sessions
$RunRoot       = Join-Path $ArtifactRoot 'runs'          # per-run results and logs
$TaskLogRoot   = Join-Path $ArtifactRoot 'task_logs'     # launcher / scheduler logs
$BuildRoot     = Join-Path $ArtifactRoot 'build'         # compiled helpers

# --------------------------------------------------------------------------- #
# Interpreter
# --------------------------------------------------------------------------- #
# A scheduled task does not inherit an interactive PATH, so "python" alone is not
# a safe default: it resolved to bare `python.exe` on the machine this was
# reorganised on, which the task then could not launch. Probe the places a Python
# actually lives, in order of preference, and only fall back to the bare name.
function Resolve-PythonExe {
  $override = Resolve-Setting 'OVERCLOCK_PYTHON' 'pythonExe' ''
  if ($override) { return $override }

  $candidates = @()
  # Whatever is running us right now is the most reliable answer when the caller
  # is itself PowerShell hosting Python-style tooling.
  $candidates += (Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Programs\Python')
  $candidates += 'C:\Python312', 'C:\Python311', 'C:\Python310'
  foreach ($base in $candidates) {
    if (-not (Test-Path -LiteralPath $base)) { continue }
    $found = Get-ChildItem -LiteralPath $base -Recurse -Filter 'python.exe' -ErrorAction SilentlyContinue |
             Where-Object { $_.FullName -notmatch '\\Scripts\\' } | Select-Object -First 1
    if ($found) { return $found.FullName }
  }

  $onPath = Get-Command python -ErrorAction SilentlyContinue
  if ($onPath) { return $onPath.Source }

  $launcher = Get-Command py -ErrorAction SilentlyContinue
  if ($launcher) { return $launcher.Source }

  return 'python.exe'
}

$PythonExe = Resolve-PythonExe

# --------------------------------------------------------------------------- #
# Third-party tools (sources and licences: docs/EXTERNAL_DEPENDENCIES.md)
# --------------------------------------------------------------------------- #
# One root the defaults hang off, so a single override relocates everything.
$ToolsRoot = Resolve-Setting 'OVERCLOCK_TOOLS_ROOT' 'toolsRoot' 'C:\Tools'

$LocalAppData = [Environment]::GetFolderPath('LocalApplicationData')

# rycolab - AMD Curve Optimizer sweep harness
#   https://github.com/ryancdotorg/rycolab
$RycolabAppData  = Resolve-Setting 'RYCOLAB_APPDATA' 'rycolabAppData' (Join-Path $LocalAppData 'rycolab')
$RycolabExe      = Resolve-Setting 'RYCOLAB_EXE' 'rycolabExe' (Join-Path $RycolabAppData 'bin\rycolab.exe')
$RycolabBinaries = Resolve-Setting 'RYCOLAB_BINARIES' 'rycolabBinaries' (Join-Path $RycolabAppData 'tools\y-cruncher\Binaries')

# ryzen-smu-cli - direct SMU access (read/write Curve Optimizer margins)
#   https://github.com/amkillam/ryzen-smu-cli
$RyzenSmuCli = Resolve-Setting 'RYZEN_SMU_CLI' 'ryzenSmuCli' (Join-Path $ToolsRoot 'ryzen-smu-cli\ryzen-smu-cli.exe')

# y-cruncher - the stress-test engine
#   http://www.numberworld.org/y-cruncher/
$YcruncherExe = Resolve-Setting 'YCRUNCHER_EXE' 'ycruncherExe' (Join-Path $ToolsRoot 'y-cruncher\y-cruncher.exe')

# HWiNFO - temperature/telemetry source, read through shared memory
#   https://www.hwinfo.com/
$HwinfoExe = Resolve-Setting 'HWINFO_EXE' 'hwinfoExe' (Join-Path $ToolsRoot 'HWiNFO\HWiNFO64.exe')

# --------------------------------------------------------------------------- #
# Scheduled task identity and job/operation files
# --------------------------------------------------------------------------- #
$TaskName    = Resolve-Setting 'OVERCLOCK_TASK_NAME' 'taskName' 'optimize-co-elevated'
$TaskOpFile  = Join-Path $ConfigRoot 'co_task_op.json'
$JobSweep    = Join-Path $ConfigRoot 'co_job_sweep.json'
$JobAccept   = Join-Path $ConfigRoot 'co_job_accept.json'
$JobResolution = Join-Path $ConfigRoot 'co_job_resolution.json'

# --------------------------------------------------------------------------- #
# Source layout
# --------------------------------------------------------------------------- #
$ControllerRycolab   = Join-Path $ScriptsRoot 'rycolab\rycolab_controller.py'
$ControllerResolution = Join-Path $ScriptsRoot 'engines\resolution_check.py'
$HwinfoShared        = Join-Path $ScriptsRoot 'common\hwinfo_shared.py'
$SidecarSensors      = Join-Path $ScriptsRoot 'watchdog\sidecar_sensors.py'
$DeadmanWatchdog     = Join-Path $ScriptsRoot 'watchdog\deadman_watchdog.py'

function Initialize-ArtifactDirs {
  <# Create the output tree. Safe to call repeatedly. #>
  foreach ($dir in @($ArtifactRoot, $SessionRoot, $RunRoot, $TaskLogRoot, $BuildRoot)) {
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
  }
}
