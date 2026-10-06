# Smoke test: dot-source the shared paths module and print what it resolved.
# Exists because verifying a path module by hand is how a wrong default survives
# to a user's machine; this prints every value and whether it exists on disk.
. (Join-Path $PSScriptRoot 'paths.ps1')

$rows = [ordered]@{
  'repo root'      = $RepoRoot
  'artifacts'      = $ArtifactRoot
  'sessions'       = $SessionRoot
  'runs'           = $RunRoot
  'task logs'      = $TaskLogRoot
  'python'         = $PythonExe
  'rycolab'        = $RycolabExe
  'rycolab bins'   = $RycolabBinaries
  'ryzen-smu-cli'  = $RyzenSmuCli
  'y-cruncher'     = $YcruncherExe
  'hwinfo'         = $HwinfoExe
  'controller'     = $ControllerRycolab
  'resolution'     = $ControllerResolution
  'hwinfo_shared'  = $HwinfoShared
  'sidecar'        = $SidecarSensors
  'watchdog'       = $DeadmanWatchdog
  'task op file'   = $TaskOpFile
  'job accept'     = $JobAccept
  'task name'      = $TaskName
}

$noExistCheck = @('repo root', 'artifacts', 'sessions', 'runs', 'task logs', 'task name')
$missing = 0
foreach ($key in $rows.Keys) {
  $value = $rows[$key]
  $note = ''
  if ($key -notin $noExistCheck) {
    if (Test-Path -LiteralPath $value) { $note = '[ok]' } else { $note = '[MISSING]'; $missing++ }
  }
  '{0,-14} {1,-78} {2}' -f $key, $value, $note
}
''
"missing (excluding artifact dirs, which are created on demand): $missing"
