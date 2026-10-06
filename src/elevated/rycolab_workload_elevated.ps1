#requires -Version 5.1
<#
  tools\rycolab_workload_elevated.ps1

  The workload the dead-man watchdog starts. It runs under the watchdog's Job
  Object (KILL_ON_JOB_CLOSE) together with everything it spawns, so whatever it
  leaves running here dies with the workload.

  Why a wrapper instead of handing rycolab.exe straight to the watchdog:
    * the per-core effective frequency is the only usable criterion in the light
      band (rounds 3-5 of CPU_CO_RESULT.md), and `rycolab dev sweep --plain`
      prints no frequency column. `ryzen-smu-cli --stream-system-telemetry`
      does, and starting it from *inside* the workload keeps it inside the Job
      Object.
    * the rycolab argv arrives as JSON (-JobFile), not as command-line tokens.
      PowerShell binds each "--cores"-style token as a parameter name, so an argv
      array cannot cross a command line at all ("NamedParameterNotFound -cores",
      2026-10-01 14:54) — and a malformed call would look like a workload that
      ran. The file is echoed into the log before anything starts, so the log
      still says exactly what ran (the 09-30 false-success lesson).

  Output goes to watchdog_sessions\<session>\workload.stdout.log (the watchdog's
  own redirect) and, for the parts this wrapper controls, to
  watchdog_sessions\<session>\workload.wrapper.log.
#>
param(
  [Parameter(Mandatory = $true)][string]$Workspace,
  [Parameter(Mandatory = $true)][string]$Session,
  [Parameter(Mandatory = $true)][string]$JobFile,
  [switch]$PerCore,
  [string]$PerCoreTargets = '0:0,0:1',
  [string]$TelemetryTargets = '0:0,0:1,0:2,0:3,0:4,0:5,0:6,0:7,0:8,0:9,0:10,0:11,0:12,0:13,0:14,0:15'
)
$ErrorActionPreference = 'Continue'

if (-not (Test-Path -LiteralPath $JobFile)) { throw "workload job file missing: $JobFile" }
$Job = Get-Content -LiteralPath $JobFile -Raw | ConvertFrom-Json
$RycolabExe = [string]$Job.rycolabExe
$RycolabArgs = @($Job.rycolabArgs | ForEach-Object { [string]$_ })
$RyzenSmuCli = [string]$Job.ryzenSmuCli
$StreamIntervalMs = [int]$Job.streamIntervalMs
$NoStream = [bool]$Job.noStream
$Cores = if ($Job.coreList) { [string]$Job.coreList } else { 'all' }
. (Join-Path $PSScriptRoot 'paths.ps1')
$sessionDir = Join-Path $SessionRoot $Session
New-Item -ItemType Directory -Force $sessionDir | Out-Null
$log = Join-Path $sessionDir 'workload.wrapper.log'
$telemetryPath = Join-Path $sessionDir 'smu_telemetry.jsonl'
$telemetryErr = Join-Path $sessionDir 'smu_telemetry.stderr.log'
$sensorPath = Join-Path $sessionDir 'sensor_feed.json'
$sensorErr = Join-Path $sessionDir 'sidecar_sensors.stderr.log'
$sidecar = $SidecarSensors
$python = $PythonExe

function Write-Log([string]$Line) {
  "$(Get-Date -Format o)  $Line" | Out-File -Append -Encoding utf8 $log
}

Write-Log "WRAPPER START pid=$PID"
Write-Log "  jobFile    = $JobFile"
Write-Log "  workspace  = $Workspace"
Write-Log "  session    = $Session"
Write-Log "  cores      = $Cores"
Write-Log "  rycolabExe = $RycolabExe  (exists=$([bool](Test-Path $RycolabExe)))"
Write-Log "  rycolabArgv= $($RycolabArgs -join ' ')"
Write-Log "  stream     = $(-not $NoStream)  intervalMs=$StreamIntervalMs"
Write-Log "  smuCli     = $RyzenSmuCli  (exists=$([bool](Test-Path $RyzenSmuCli)))"
Write-Log "  hwinfo     = $([bool]$Job.hwinfo)  (merged from the non-elevated side; provides DDR5 SPD Hub temps)"

$streamProcess = $null
$perCoreProcess = $null
if (-not $NoStream) {
  if (Test-Path $RyzenSmuCli) {
    if (Test-Path $telemetryPath) { Remove-Item $telemetryPath -Force -ErrorAction SilentlyContinue }
    $streamArgs = @('--stream-system-telemetry', '--interval-ms', "$StreamIntervalMs", '--targets', $TelemetryTargets)
    Write-Log "  starting telemetry: $RyzenSmuCli $($streamArgs -join ' ')"
    $streamProcess = Start-Process -FilePath $RyzenSmuCli -ArgumentList $streamArgs -PassThru -NoNewWindow `
      -RedirectStandardOutput $telemetryPath -RedirectStandardError $telemetryErr
    Write-Log "  telemetry pid=$($streamProcess.Id)"

    # A second stream covering only the swept cores. The aggregate targets above
    # exist for the per-core effective clocks that *found* the light-band
    # criterion (rounds 3-5), but reading 16 targets at 500 ms is what makes
    # acquisition overrun the interval ("acquisition exceeded half of the
    # requested sampling interval"). That was suspected of driving the CPU hot
    # on 2026-10-01 (Tctl 70 -> 90.5 C in 6 s) while the *sum* of per-core
    # activity was invisible. The narrow stream is the control: same workload,
    # two targets, continuous clocks, so "the measurement heated the CPU" and
    # "the workload heated the CPU" can be told apart.
    if ($PerCore) {
      $perCorePath = Join-Path $sessionDir 'smu_telemetry_percore.jsonl'
      $perCoreErr = Join-Path $sessionDir 'smu_telemetry_percore.stderr.log'
      $perCoreArgs = @('--stream-system-telemetry', '--interval-ms', '500', '--targets', $PerCoreTargets)
      Write-Log "  starting per-core telemetry: $RyzenSmuCli $($perCoreArgs -join ' ')"
      $perCoreProcess = Start-Process -FilePath $RyzenSmuCli -ArgumentList $perCoreArgs -PassThru -NoNewWindow `
        -RedirectStandardOutput $perCorePath -RedirectStandardError $perCoreErr
      Write-Log "  per-core telemetry pid=$($perCoreProcess.Id) -> $perCorePath"
    }
  } else {
    Write-Log '  telemetry SKIPPED: ryzen-smu-cli not found (frequency evidence will be missing)'
  }
}

# The sidecar owns the watchdog's sensor file. It has to exist before the
# watchdog's own startup read, and it has to keep being rewritten while the
# telemetry child's stdout is block-buffered (that buffering killed a healthy
# run at 14:55 with "sensor source stale for 15.5s"). It runs inside this
# process, hence inside the watchdog's Job Object, so it dies with the workload.
$sensorProcess = $null
if ((Test-Path $sidecar) -and (Test-Path $python)) {
  $sidecarArgs = @($sidecar, '--telemetry', $telemetryPath, '--out', $sensorPath, '--interval', '2', '--telemetry-stale-trip', '20')
  if ($Job.hwinfo) { $sidecarArgs += '--hwinfo' }
  Write-Log "  starting sidecar: $python $($sidecarArgs -join ' ')"
  $sensorProcess = Start-Process -FilePath $python -ArgumentList $sidecarArgs -PassThru -NoNewWindow `
    -RedirectStandardError $sensorErr
  Write-Log "  sidecar pid=$($sensorProcess.Id)"
} else {
  Write-Log '  sidecar SKIPPED: script or python missing; the watchdog would read the raw telemetry file'
}

$rycolabExit = 999
try {
  Write-Log "  rycolab start $(Get-Date -Format o)"
  # -NoNewWindow inherits the watchdog's stdout/stderr redirect, so rycolab's
  # own lines land in workload.stdout.log / workload.stderr.log untouched.
  # -PassThru has no output redirection, so nothing is piped or reformatted.
  $proc = Start-Process -FilePath $RycolabExe -ArgumentList $RycolabArgs -NoNewWindow -Wait -PassThru
  $rycolabExit = $proc.ExitCode
  Write-Log "  rycolab exit=$rycolabExit"
} catch {
  Write-Log "  rycolab THREW: $($_.Exception.Message)"
} finally {
  foreach ($child in @($streamProcess, $perCoreProcess, $sensorProcess)) {
    if ($child) {
      try {
        Stop-Process -Id $child.Id -Force -ErrorAction SilentlyContinue
        Write-Log "  stopped pid=$($child.Id)"
      } catch {
        Write-Log "  stop pid=$($child.Id) failed: $($_.Exception.Message)"
      }
    }
  }
}

foreach ($pair in @(@('telemetry', $telemetryPath), @('sensor feed', $sensorPath))) {
  if (Test-Path $pair[1]) {
    $lines = @(Get-Content $pair[1] -ErrorAction SilentlyContinue).Count
    Write-Log "  $($pair[0]) lines=$lines -> $($pair[1])"
  } else {
    Write-Log "  $($pair[0]) file MISSING -> $($pair[1])"
  }
}
if (Test-Path $sensorPath) {
  try {
    $last = Get-Content $sensorPath -Raw | ConvertFrom-Json
    Write-Log "  last sensor sample: age=$($last.source_age_seconds)s hwinfo=$($last.hwinfo_available) temps=$($last.temperatures.PSObject.Properties.Count)"
  } catch {
    Write-Log "  last sensor sample unreadable: $($_.Exception.Message)"
  }
}

Write-Log "WRAPPER END exit=$rycolabExit"
exit $rycolabExit
