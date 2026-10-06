param(
  [string]$Session = '',
  [string]$Cores = '0-7',
  [int]$HeartbeatTimeout = 45,
  [int]$HardTimeout = 14400
)

$ErrorActionPreference = 'Stop'
if ($Session -eq '') { $Session = 'co-find-all-quick-' + (Get-Date -Format 'yyyyMMdd-HHmmss') }

. (Join-Path $PSScriptRoot 'paths.ps1')
$py = $PythonExe
$ctrl = $ControllerRycolab
$outDir = $SessionRoot
New-Item -ItemType Directory -Force $outDir | Out-Null
$log = Join-Path $outDir ($Session + '.arm-launcher.log')

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
"START $(Get-Date -Format o)  session=$Session  cores=$Cores  isAdmin=$isAdmin" | Out-File -Encoding utf8 $log
if (-not $isAdmin) {
  'ABORT: this launcher must run elevated (rycolab needs the SMU).' | Out-File -Append -Encoding utf8 $log
  exit 9
}

& $py $ctrl arm --session $Session --cores $Cores `
  --heartbeat-timeout $HeartbeatTimeout --hard-timeout $HardTimeout *>&1 |
  Out-File -Append -Encoding utf8 $log

$code = $LASTEXITCODE
"ARM_EXIT=$code $(Get-Date -Format o)" | Out-File -Append -Encoding utf8 $log
exit $code
