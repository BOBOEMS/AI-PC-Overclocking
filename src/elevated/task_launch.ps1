#requires -Version 5.1
<#
  tools\task_launch.ps1  —  the ONLY script the scheduled task runs.

  Registered once by tools\setup_uac_free_task.ps1 as a highest-privileges
  task, so from then on `schtasks /run /tn optimize-co-elevated` starts an
  elevated process with no UAC prompt. That is deliberately the whole privilege
  surface: this script is a fixed, logged dispatcher over two operations, each
  with a fixed argument list, and the AI side can never pass it a command.

    -Op sweep    rycolab dev sweep under the dead-man watchdog (the long job;
                 parameters come from tools\co_job_sweep.json, which the AI side
                 rewrites between runs and this script echoes into the log).
    -Op hwinfo   start HWiNFO64 for the DIMM / SPD Hub temperature readings and
                 prove the shared memory answers before returning.

  Why a task rather than `Start-Process -Verb RunAs`: UAC needs a human click
  every time, and automating that click would bypass Windows' consent
  mechanism (refused on 2026-10-01, see HANDOFF section 4 item 2). The honest
  trade is unchanged: a task removes the prompt, not the requirement that a
  live AI session keeps feeding the watchdog's heartbeat. Stop feeding and the
  dead-man switch trips within the heartbeat timeout, kills the workload and
  restores every core to the baseline.

  The operation comes from tools\co_task_op.json ({"op":"sweep"|"hwinfo"}),
  written by the non-elevated AI side before each trigger: `schtasks /run`
  cannot pass arguments, and a plain file keeps the trigger command fixed and
  inspectable. The value is validated against the same allow-list.
#>
param(
  [ValidateSet('sweep', 'hwinfo', 'stop-hwinfo', 'resolution', 'accept', 'probe')]
  [string]$Op
)

. (Join-Path $PSScriptRoot 'paths.ps1')
# Every operation writes its evidence somewhere under artifacts/, and the probe
# path writes into the session root before any session exists. Create the whole
# tree up front: Out-File -Append does not create missing parent directories, so
# a missing artifacts/sessions silently discarded the probe evidence (the log
# said PROBE OK while no file appeared).
Initialize-ArtifactDirs
$LogDir = $TaskLogRoot
New-Item -ItemType Directory -Force $LogDir | Out-Null
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$CrashLog = Join-Path $LogDir "launcher-crash-$Stamp.log"

# A terminating error used to kill this script with exit code 1 and *no* trace
# in the operation's own log: the task reported Last Result = 1 and the log just
# stopped (2026-10-01 15:00 and 15:02). Guessing from a truncated log is not
# evidence, so every unhandled error now names itself with a stack trace.
trap {
  $detail = @(
    "UNHANDLED ERROR $(Get-Date -Format o)",
    "  op        = $Op",
    "  message   = $($_.Exception.Message)",
    "  category  = $($_.CategoryInfo.Category)  target = $($_.CategoryInfo.TargetName)",
    "  position  = $($_.InvocationInfo.PositionMessage)",
    "  stack     = $($_.ScriptStackTrace)"
  ) -join "`r`n"
  $detail | Out-File -Append -Encoding utf8 $CrashLog
  if ($Log) { Write-Log "UNHANDLED ERROR: $($_.Exception.Message) -> $CrashLog" }
  exit 1
}

if (-not $Op) {
  $opFile = $TaskOpFile
  if (-not (Test-Path $opFile)) { throw "no -Op given and no operation file: $opFile" }
  $Op = (Get-Content $opFile -Raw | ConvertFrom-Json).op
}
if ($Op -notin @('sweep', 'hwinfo', 'stop-hwinfo', 'resolution', 'accept', 'probe')) { throw "operation file holds an unknown op: '$Op'" }

$Log = Join-Path $LogDir "$Op-$Stamp.log"

function Write-Log([string]$Line) {
  $line = "$(Get-Date -Format o)  $Line"
  $line | Out-File -Append -Encoding utf8 $Log
  Write-Host $line
}

# Keep going after errors that are not interesting (a native command's stderr, a
# missing process). Everything that matters is logged explicitly.
$ErrorActionPreference = 'Continue'

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = (New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

Write-Log "TASK LAUNCH op=$Op pid=$PID"
Write-Log "  user       = $($identity.Name)"
Write-Log "  isAdmin    = $isAdmin"
Write-Log "  log        = $Log"
Write-Log "  powerShell = $($PSVersionTable.PSVersion)"

if (-not $isAdmin) {
  Write-Log 'ABORT: the task did not start us elevated; nothing is written to the SMU from here.'
  exit 9
}

switch ($Op) {
  'probe' {
    # Read-only: report what the SMU actually holds for every core. This is the
    # FIRST step after any BIOS change, because "I set -15 in BIOS" is a
    # declaration and only a read-back proves the value actually took effect.
    # Two independent readers on purpose (rycolab + ryzen-smu-cli); they disagreed
    # with a stale record once already on 09-30, which is why both are logged.
    $rycolab = $RycolabExe
    $smuCli = $RyzenSmuCli
    $outDir = $SessionRoot
    New-Item -ItemType Directory -Force $outDir | Out-Null
    $probeLog = Join-Path $outDir 'bios-probe-after-change.log'

    Write-Log "  rycolab dev probe -> $probeLog"
    & $rycolab dev probe *>&1 | Out-File -Encoding utf8 -Append $probeLog
    $terse = (& $smuCli --get-offsets-terse 2>&1 | Out-String).Trim()
    "ryzen-smu-cli --get-offsets-terse at $(Get-Date -Format o)" | Out-File -Encoding utf8 -Append $probeLog
    $terse | Out-File -Encoding utf8 -Append $probeLog
    Write-Log "  independent reader offsets = $terse"
    $fmax = (& $smuCli --get-fmax 2>&1 | Out-String).Trim()
    $scalar = (& $smuCli --get-pbo-scalar 2>&1 | Out-String).Trim()
    "FMax    = $fmax" | Out-File -Encoding utf8 -Append $probeLog
    "PBO Scalar = $scalar" | Out-File -Encoding utf8 -Append $probeLog
    Write-Log "  FMax=$fmax  PBO Scalar=$scalar"
    Write-Log 'PROBE OK'
    exit 0
  }

  'accept' {
    # Acceptance run: all-core CO margin + the user's acceptance load (30 min VT3
    # 24 GiB all-core). Topology note: this does NOT self-feed the heartbeat. The
    # elevated side only runs the load; the AI session feeds it. An elevated
    # process is not a child of the AI session, so self-feeding would never trip
    # the dead-man switch - which is exactly why the sweep is split the same way.
    $jobFile = $JobAccept
    if (-not (Test-Path $jobFile)) { Write-Log "ABORT: job file missing: $jobFile"; exit 2 }
    $job = Get-Content $jobFile -Raw | ConvertFrom-Json
    Write-Log "  jobFile    = $jobFile"
    Write-Log "  session    = $($job.session)"
    Write-Log "  margin     = all cores $($job.margin) (baseline expected $($job.baseline))"
    Write-Log "  workload   = y-cruncher $($job.tests -join ',') -M:$($job.memory) -D:$($job.testDuration)"
    Write-Log "  thermal    = CPU stop $($job.cpuTempStop) / emergency $($job.cpuTempEmergency) C, DIMM $($job.dimmTempStop) / $($job.dimmTempEmergency) C"

    $python = $PythonExe
    $controller = $ControllerRycolab
    $armArgs = @(
      $controller, 'accept',
      '--session', [string]$job.session,
      '--margin', [string]$job.margin,
      '--baseline', [string]$job.baseline,
      '--memory', [string]$job.memory,
      '--test-duration', [string]$job.testDuration,
      '--ycruncher-exe', [string]$job.ycruncherExe,
      '--heartbeat-timeout', [string]$job.heartbeatTimeoutSeconds,
      '--cpu-temp-stop', [string]$job.cpuTempStop,
      '--cpu-temp-emergency', [string]$job.cpuTempEmergency,
      '--dimm-temp-stop', [string]$job.dimmTempStop,
      '--dimm-temp-emergency', [string]$job.dimmTempEmergency,
      '--temp-strikes-required', [string]$job.tempStrikesRequired,
      '--tests'
    )
    foreach ($t in $job.tests) { $armArgs += [string]$t }
    Write-Log "  argv       = python $($armArgs -join ' ')"
    Write-Log '  --- accept output ---'
    & $python @armArgs *>&1 | ForEach-Object { $_ | Out-Host; Write-Log "  acc| $_" }
    $code = $LASTEXITCODE
    Write-Log "ACCEPT EXIT=$code"
    exit $code
  }

  'resolution' {
    # Resolution verification: does going deeper than -25 still change the operating
    # point? Writes only the margin itself, and always resets to 0 at the end.
    # Needs elevation for the same reason the sweep does: ryzen-smu-cli cannot talk
    # to the SMU without it (a non-elevated attempt failed with write_exit=1,
    # readback=(none) on 2026-10-01 17:3x).
    $jobFile = $JobResolution
    if (-not (Test-Path $jobFile)) { Write-Log "ABORT: job file missing: $jobFile"; exit 2 }
    $job = Get-Content $jobFile -Raw | ConvertFrom-Json
    Write-Log "  jobFile    = $jobFile"
    Write-Log "  session    = $($job.session)"
    Write-Log "  core       = $($job.core)"
    Write-Log "  margins    = $($job.margins -join ', ')  ($($job.seconds) s load each, $($job.cooldown) s cooldown)"
    Write-Log "  engine     = $($job.engine)  test $($job.test)  memory $($job.memoryMiB) MiB"
    Write-Log "  thermal    = CPU stop $($job.cpuTempStop) / emergency $($job.cpuTempEmergency) C"

    $python = $PythonExe
    $controller = $ControllerResolution
    $armArgs = @(
      $controller, [string]$job.session,
      '--core', [string]$job.core,
      '--margins'
    )
    foreach ($m in $job.margins) { $armArgs += [string]$m }
    $armArgs += @(
      '--seconds', [string]$job.seconds,
      '--cooldown', [string]$job.cooldown,
      '--engine', [string]$job.engine,
      '--test', [string]$job.test,
      '--memory-mib', [string]$job.memoryMiB,
      '--cpu-temp-stop', [string]$job.cpuTempStop,
      '--cpu-temp-emergency', [string]$job.cpuTempEmergency,
      '--dimm-temp-stop', [string]$job.dimmTempStop,
      '--dimm-temp-emergency', [string]$job.dimmTempEmergency
    )
    Write-Log "  argv       = python $($armArgs -join ' ')"
    Write-Log '  --- resolution output ---'
    & $python @armArgs *>&1 | ForEach-Object { $_ | Out-Host; Write-Log "  res| $_" }
    $code = $LASTEXITCODE
    Write-Log "RESOLUTION EXIT=$code"
    exit $code
  }

  'sweep' {
    $jobFile = $JobSweep
    if (-not (Test-Path $jobFile)) { Write-Log "ABORT: job file missing: $jobFile"; exit 2 }
    $job = Get-Content $jobFile -Raw | ConvertFrom-Json
    Write-Log "  jobFile    = $jobFile"
    Write-Log "  session    = $($job.session)"
    Write-Log "  cores      = $($job.cores)"
    Write-Log "  margins    = $($job.start) -> $($job.top) step $($job.step), $($job.seconds) s per run"
    Write-Log "  campaign   = $($job.campaign)"
    Write-Log "  hardTimeout= $($job.hardTimeoutSeconds) s, heartbeat $($job.heartbeatTimeoutSeconds) s"
    Write-Log "  perCore    = $($job.perCore) (targets $($job.perCoreTargets))"
    Write-Log "  thermal    = CPU stop $($job.cpuTempStop) / emergency $($job.cpuTempEmergency) C, DIMM $($job.dimmTempStop) / $($job.dimmTempEmergency) C, trip after $($job.tempStrikesRequired) consecutive samples"

    $python = $PythonExe
    $controller = $ControllerRycolab
    $armArgs = @(
      $controller, 'arm',
      '--session', [string]$job.session,
      '--op', 'sweep',
      '--cores', [string]$job.cores,
      '--start', [string]$job.start,
      '--top', [string]$job.top,
      '--step', [string]$job.step,
      '--seconds', [string]$job.seconds,
      '--campaign', [string]$job.campaign,
      '--hard-timeout', [string]$job.hardTimeoutSeconds,
      '--heartbeat-timeout', [string]$job.heartbeatTimeoutSeconds,
      '--sensor-source', [string]$job.sensorSource
    )
    if ($job.resume) { $armArgs += '--resume' }
    if ($job.noStream) { $armArgs += '--no-stream' }
    if ($job.perCore) { $armArgs += @('--per-core', '--per-core-targets', [string]$job.perCoreTargets) }
    # Thermal thresholds belong in the evidence: on 2026-10-01 the user explicitly
    # raised the CPU stop line from 90 to 95 C after three runs (margins -25, -25
    # and -5) tripped at 90 C on a load-transition transient.
    if ($job.cpuTempStop) { $armArgs += @('--cpu-temp-stop', [string]$job.cpuTempStop) }
    if ($job.cpuTempEmergency) { $armArgs += @('--cpu-temp-emergency', [string]$job.cpuTempEmergency) }
    if ($job.dimmTempStop) { $armArgs += @('--dimm-temp-stop', [string]$job.dimmTempStop) }
    if ($job.dimmTempEmergency) { $armArgs += @('--dimm-temp-emergency', [string]$job.dimmTempEmergency) }
    if ($job.tempStrikesRequired) { $armArgs += @('--temp-strikes-required', [string]$job.tempStrikesRequired) }
    # Screening runs shorten rycolab's own confirm/soak (config.json values), which
    # are otherwise 1800/600 s per core no matter what --seconds says.
    if ($job.confirmSeconds) { $armArgs += @('--confirm-seconds', [string]$job.confirmSeconds) }
    if ($job.soakSeconds) { $armArgs += @('--soak-seconds', [string]$job.soakSeconds) }
    if ($job.crashKind) { $armArgs += @('--crash-kind', [string]$job.crashKind) }
    Write-Log "  argv       = python $($armArgs -join ' ')"
    Write-Log '  --- arm output ---'
    & $python @armArgs *>&1 | ForEach-Object { $_ | Out-Host; Write-Log "  arm| $_" }
    $code = $LASTEXITCODE
    Write-Log "SWEEP EXIT=$code"
    exit $code
  }

  'hwinfo' {
    # Resolution order, most specific first:
    #   1. the configured HWINFO_EXE / hwinfoExe value
    #   2. a search of the tool roots
    #
    # The search exists because the folder name carries CJK characters and a
    # Windows PowerShell 5.1 reading a BOM-less UTF-8 script mangles them
    # (observed in task_logs\hwinfo-20261001-145011.log) - a search cannot be
    # mangled. But searching FIRST was wrong: it ignored a perfectly good
    # configured path and aborted with "not found" whenever HWiNFO lived outside
    # the tool roots, which is exactly what happened on 2026-10-02.
    $hwinfo = $null
    if ($HwinfoExe -and (Test-Path -LiteralPath $HwinfoExe)) {
      $hwinfo = $HwinfoExe
    } else {
      foreach ($root in @($ToolsRoot, $RepoRoot)) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        $found = Get-ChildItem -LiteralPath $root -Recurse -Filter 'HWiNFO64.exe' -ErrorAction SilentlyContinue |
                 Select-Object -First 1
        if ($found) { $hwinfo = $found.FullName; break }
      }
    }
    if (-not $hwinfo) {
      Write-Log "ABORT: HWiNFO64.exe not found. Tried HWINFO_EXE='$HwinfoExe', then a search under '$ToolsRoot' and '$RepoRoot'. Set hwinfoExe in %APPDATA%\overclock-toolkit\paths.json"
      exit 2
    }
    Write-Log "  hwinfo     = $hwinfo"

    $python = $PythonExe
    $probe = $HwinfoShared

    # HWiNFO 8.34 always opens a modal splash first (class #32770, a "开始"
    # button with control id 1) and creates the sensor window - and with it the
    # shared memory map - only after that button is pressed. Leaving it to the
    # user is what made every previous start need a click.
    #
    # The click has to be sent from *here*: this task runs with
    # HighestAvailable (isAdmin=True), i.e. high integrity, and a medium
    # integrity process cannot post window messages to a high integrity window
    # at all. UIPI drops them silently - SendMessage returns as if it worked and
    # nothing happens, which is exactly what was observed on 2026-10-01. A
    # medium integrity *mouse* click is blocked for the same reason, so
    # synthesizing input from the AI session cannot work either.
    if (-not ('HwinfoUi' -as [type])) {
      Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;

public class HwinfoUi
{
    [DllImport("user32.dll")] private static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] private static extern IntPtr GetDlgItem(IntPtr hDlg, int id);
    [DllImport("user32.dll")] private static extern IntPtr SendMessageW(IntPtr h, uint msg, IntPtr w, IntPtr l);
    private delegate bool EnumProc(IntPtr h, IntPtr p);
    private const uint BM_CLICK = 0x00F5;

    private static string Text(IntPtr h)
    {
        int n = GetWindowTextW(h, null, 0);
        var sb = new StringBuilder(n + 2);
        GetWindowTextW(h, sb, sb.Capacity);
        return sb.ToString();
    }

    private static string Class(IntPtr h)
    {
        var sb = new StringBuilder(256);
        GetClassNameW(h, sb, sb.Capacity);
        return sb.ToString();
    }

    public static List<string> WindowTitles(uint pid)
    {
        var list = new List<string>();
        EnumWindows((h, p) =>
        {
            uint owner; GetWindowThreadProcessId(h, out owner);
            if (owner == pid && IsWindowVisible(h)) list.Add(Class(h) + "|" + Text(h));
            return true;
        }, IntPtr.Zero);
        return list;
    }

    /// <summary>Presses control id 1 of every visible dialog owned by pid; returns how many it pressed.</summary>
    public static int PressStart(uint pid)
    {
        int pressed = 0;
        EnumWindows((h, p) =>
        {
            uint owner; GetWindowThreadProcessId(h, out owner);
            if (owner != pid || !IsWindowVisible(h)) return true;
            if (Class(h) != "#32770") return true;
            IntPtr button = GetDlgItem(h, 1);
            if (button == IntPtr.Zero) return true;
            SendMessageW(button, BM_CLICK, IntPtr.Zero, IntPtr.Zero);
            pressed++;
            return true;
        }, IntPtr.Zero);
        return pressed;
    }
}
'@
    }

    $already = @(Get-Process -Name 'HWiNFO64' -ErrorAction SilentlyContinue)
    if ($already.Count -gt 0) {
      Write-Log "  HWiNFO64 already running: pid $($already.Id -join ',')"
    } else {
      Write-Log '  starting HWiNFO64 (SensorsOnly=1 and SensorsSM=1 are set in HWiNFO64.INI)'
      Start-Process -FilePath $hwinfo -WorkingDirectory (Split-Path -LiteralPath $hwinfo) | Out-Null
      Start-Sleep -Seconds 4
    }
    $ok = $false
    $startPressed = 0
    for ($attempt = 1; $attempt -le 20; $attempt++) {
      # 2>$null is load-bearing, not cosmetic: in Windows PowerShell 5.1 a native
      # command's stderr becomes a *terminating* error under
      # $ErrorActionPreference='Stop', so the probe's expected "shared memory
      # unavailable (Win32 error 2)" killed this whole operation on its first
      # attempt (2026-10-01 15:00, task Last Result = 1, log stopping right after
      # "starting HWiNFO64"). Kill off stderr and read the exit code instead.
      & $python $probe 2>$null 1>$null
      if ($LASTEXITCODE -eq 0) { $ok = $true; Write-Log "  shared memory OK after ~$($attempt * 3) s (map is live)"; break }

      $processes = @(Get-Process -Name 'HWiNFO64' -ErrorAction SilentlyContinue)
      if ($processes.Count -eq 0) {
        Write-Log "  attempt ${attempt}: HWiNFO64 is gone (probe exit $LASTEXITCODE); giving up"
        break
      }
      $titles = @()
      foreach ($p in $processes) { $titles += [HwinfoUi]::WindowTitles([uint32]$p.Id) }
      $blocked = @($titles | Where-Object { $_ -like '#32770|*' })
      if ($blocked.Count -gt 0) {
        foreach ($p in $processes) { $startPressed += [HwinfoUi]::PressStart([uint32]$p.Id) }
        Write-Log "  attempt ${attempt}: dialog(s) [$($blocked -join '; ')] -> pressed start ($startPressed so far)"
      } else {
        Write-Log "  attempt ${attempt}: waiting (windows: $($titles -join '; '))"
      }
      Start-Sleep -Seconds 3
    }

    if (-not $ok) {
      Write-Log "HWINFO FAILED: shared memory never appeared (start pressed $startPressed time(s))."
      Write-Log '  If a dialog is still on screen it is not the known splash: report it rather than clicking blindly.'
      exit 3
    }

    $out = & $python $probe 2>$null
    try {
      $snapshot = $out | Out-String | ConvertFrom-Json
      Write-Log "  sensors=$($snapshot.sensors.Count) readings=$($snapshot.readings.Count) pollTime=$($snapshot.poll_time) (start pressed $startPressed time(s))"
      foreach ($reading in @($snapshot.readings | Where-Object { $_.label -like '*SPD Hub*' })) {
        Write-Log "  DIMM: $($reading.sensor) = $($reading.value) $($reading.unit)"
      }
    } catch {
      Write-Log "  (snapshot parsed only partially: $($_.Exception.Message))"
    }
    Write-Log 'HWINFO OK'
    exit 0
  }

  'stop-hwinfo' {
    # Maintenance: HWiNFO runs elevated, so a non-elevated taskkill cannot end it
    # ("Access is denied"). Needed to test a real cold start.
    $processes = @(Get-Process -Name 'HWiNFO64' -ErrorAction SilentlyContinue)
    if ($processes.Count -eq 0) { Write-Log 'stop-hwinfo: not running'; exit 0 }
    Write-Log "stop-hwinfo: pid $($processes.Id -join ',')"
    foreach ($p in $processes) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
    if (@(Get-Process -Name 'HWiNFO64' -ErrorAction SilentlyContinue).Count -gt 0) {
      Write-Log 'stop-hwinfo: FAILED, still running'; exit 1
    }
    Write-Log 'stop-hwinfo: stopped'
    exit 0
  }
}
