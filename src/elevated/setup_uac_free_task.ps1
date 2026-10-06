#requires -Version 5.1
<#
  tools\setup_uac_free_task.ps1  —  run ONCE, elevated, by the user.

  Creates the highest-privileges scheduled task that lets later runs start
  elevated with no UAC prompt:

      schtasks /run /tn optimize-co-elevated /i <op>

  Cost model, stated up front:

    * This is the only UAC click in the whole workflow. It is needed because
      creating a highest-privileges task requires administrator rights, and
      nothing else is allowed to do it (automating the UAC dialog itself was
      explicitly refused — it bypasses the Windows consent mechanism).
    * Registering the task changes the machine, so it is the user's call and
      the user's click. Everything before and after this is unattended.
    * The task runs tools\task_launch.ps1, which is a fixed two-operation
      dispatcher ('sweep', 'hwinfo'). No command line is ever accepted through
      the task beyond that operation name.
    * `net session` succeeds inside the task, which is the same elevation test
      rycolab_controller.py's arm path uses.

  Usage (elevated PowerShell):
      powershell -NoProfile -ExecutionPolicy Bypass -File tools\setup_uac_free_task.ps1
      ... -SkipHwinfo                 register only, do not smoke-test HWiNFO
      ... -UseWindowsPowerShell       force the task to run Windows PowerShell 5.1
      ... -Unregister                 delete the task and stop

  The task runs PowerShell 7 (pwsh.exe) when it is installed, because the two
  failures that cost real time on 2026-10-01 are Windows PowerShell 5.1
  behaviours:
    * 5.1 reads a BOM-less UTF-8 .ps1 as ANSI, mangling CJK path components
      ("综合检测" -> "缁煎悎妫€娴媆", HWiNFO reported "not found");
    * under $ErrorActionPreference='Stop' a native command's stderr becomes a
      TERMINATING error, which killed a whole hwinfo operation on a probe that
      legitimately failed with "Win32 error 2".
  Verified on 7.6.6 before switching: a BOM-less CJK script decodes correctly,
  $PSNativeCommandUseErrorActionPreference defaults to False, a BOM'd script
  still decodes correctly, and task_launch.ps1 parses under PS7's stricter
  parser. -UseWindowsPowerShell keeps the 5.1 fallback one flag away.

  The task action uses -WindowStyle Minimized, deliberately NOT Hidden: the user
  reported that hidden PowerShell execution is blocked by Huorong (火绒). A
  visible-but-minimized window neither disappears (which is what a HIPS treats
  as evasion) nor steals focus from a running benchmark. The task registration
  itself is also visible (<Hidden>false</Hidden>). Verified: PS7 supports
  -WindowStyle (including Hidden), so Minimized is safe on both interpreters.
#>
param(
  [string]$TaskName = 'optimize-co-elevated',
  [switch]$SkipHwinfo,
  [switch]$Unregister,
  [switch]$UseWindowsPowerShell
)

$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'paths.ps1')
$Launcher = Join-Path $PSScriptRoot 'task_launch.ps1'
$WindowsPowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$PowerShell7 = Join-Path $env:ProgramFiles 'PowerShell\7\pwsh.exe'

if ($UseWindowsPowerShell) {
  $PowerShell = $WindowsPowerShell
  Write-Host 'task interpreter: Windows PowerShell 5.1 (forced with -UseWindowsPowerShell)'
} elseif (Test-Path -LiteralPath $PowerShell7) {
  $PowerShell = $PowerShell7
  Write-Host "task interpreter: PowerShell 7 ($PowerShell7)"
} else {
  $PowerShell = $WindowsPowerShell
  Write-Host "task interpreter: Windows PowerShell 5.1 (PowerShell 7 not found at $PowerShell7)"
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = (New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Write-Host "setup_uac_free_task: user=$($identity.Name) isAdmin=$isAdmin"

if (-not $isAdmin) {
  Write-Host 'ABORT: run this from an elevated PowerShell (right-click -> Run as administrator).' -ForegroundColor Red
  exit 9
}
if (-not (Test-Path -LiteralPath $Launcher)) { Write-Host "ABORT: launcher missing: $Launcher" -ForegroundColor Red; exit 2 }

if ($Unregister) {
  schtasks /delete /tn $TaskName /f | Out-Host
  Write-Host "task '$TaskName' removed"
  exit 0
}

# The account that must own the task: the human's account only, never a service
# account, and only when it is the interactive one.
$userId = $identity.Name

# A one-time trigger far in the future: the task is run on demand with
# `schtasks /run`, never by its own schedule.
$startBoundary = (Get-Date).AddYears(10).ToString('yyyy-MM-ddTHH:mm:ss')

$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>optimize_system: highest-privileges launcher for the Curve Optimizer sweep and the HWiNFO sensor start. Registered once by the user; triggered with schtasks /run.</Description>
    <Author>$userId</Author>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <StartBoundary>$startBoundary</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$userId</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>false</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$PowerShell</Command>
      <Arguments>-NoProfile -ExecutionPolicy Bypass -WindowStyle Minimized -File "$Launcher"</Arguments>
      <WorkingDirectory>$RepoRoot</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

$xmlPath = Join-Path $env:TEMP "optimize-co-elevated.xml"
$xml | Out-File -Encoding unicode $xmlPath
Write-Host "registering task '$TaskName' for $userId (RunLevel=HighestAvailable, no time limit)"

schtasks /create /tn $TaskName /xml $xmlPath /f | Out-Host
if ($LASTEXITCODE -ne 0) { Write-Host 'ABORT: schtasks /create failed' -ForegroundColor Red; exit $LASTEXITCODE }
Remove-Item $xmlPath -Force -ErrorAction SilentlyContinue

Write-Host ''
Write-Host "--- task '$TaskName' ---"
schtasks /query /tn $TaskName /fo LIST /v | Select-String -Pattern 'TaskName|Run As User|Logon Mode|Run Level|Task To Run|Start In|Status|Schedule Type' | ForEach-Object { $_.Line }

$registered = schtasks /query /tn $TaskName /fo LIST /v | Out-String
if ($registered -notmatch 'Highest') {
  Write-Host 'WARNING: the task does not report Highest run level; check it in Task Scheduler.' -ForegroundColor Yellow
}

Write-Host ''
Write-Host 'Next, the AI side triggers it (no UAC) with:'
Write-Host "   (write config\co_task_op.json = {""op"":""hwinfo""}) ; schtasks /run /tn $TaskName"
Write-Host ''
Write-Host 'Re-run this script after MOVING or RENAMING the repository: the task stores'
Write-Host 'an absolute path to task_launch.ps1 and does not follow the tree.'
Write-Host ''

if (-not $SkipHwinfo) {
  Write-Host 'Smoke test: starting HWiNFO64 through the task (no UAC expected)...'
  '{"op":"hwinfo"}' | Out-File -Encoding ascii $TaskOpFile
  schtasks /run /tn $TaskName | Out-Host
  Start-Sleep -Seconds 5
  $logDir = $TaskLogRoot
  $latest = $null
  for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 3
    $latest = Get-ChildItem $logDir -Filter 'hwinfo-*.log' -ErrorAction SilentlyContinue |
              Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($latest -and ((Get-Content $latest.FullName -Raw) -match 'HWINFO (OK|FAILED)')) { break }
  }
  if ($latest) {
    Write-Host "--- $($latest.FullName) ---"
    Get-Content $latest.FullName | ForEach-Object { Write-Host "   $_" }
  } else {
    Write-Host 'no hwinfo task log appeared; trigger it by hand and check artifacts\task_logs\' -ForegroundColor Yellow
  }
}
