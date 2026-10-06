$s = 'co-find-all-quick-20261001'
. (Join-Path $PSScriptRoot 'paths.ps1')
$d = Join-Path $SessionRoot $s
$wl = $d + '\workload.stdout.log'
$err = $d + '\workload.stderr.log'
$offset = 0
$seen = 0
$lastBeat = [datetime]::MinValue

while ($true) {
  $st = $null
  if (Test-Path ($d + '\status.json')) {
    try { $st = Get-Content ($d + '\status.json') -Raw | ConvertFrom-Json } catch { }
  }

  if ($st -and (Get-Date) - $lastBeat -gt [timespan]::FromSeconds(60)) {
    $lastBeat = Get-Date
    $tctl = $null
    $mos = $null
    $dimm = $null
    foreach ($p in $st.last_temperatures.PSObject.Properties) {
      if ($null -eq $tctl -and $p.Name -match 'Tctl') { $tctl = $p.Value }
      if ($null -eq $mos -and $p.Name -match '\|\s*MOS') { $mos = $p.Value }
      if ($null -eq $dimm -and $p.Name -match 'SPD') { $dimm = $p.Value }
    }
    $line = 'STATE=' + $st.state + ' elapsed=' + [math]::Round($st.elapsed_seconds) + 's hb=' + $st.heartbeat_age_seconds + 's Tctl=' + $tctl + ' MOS=' + $mos + ' DIMM=' + $dimm
    $reason = $st.reason
    if ($reason) { $line = $line + ' reason=' + $reason }
    Write-Output $line
  }

  if (Test-Path $wl) {
    $bytes = (Get-Item $wl).Length
    if ($bytes -gt $offset) {
      $lines = @(Get-Content $wl -Encoding UTF8)
      if ($lines.Count -gt $seen) {
        $take = $lines[$seen..($lines.Count - 1)]
        $seen = $lines.Count
        foreach ($l in $take) {
          if ($l -match 'core |margin|CLEAN|ERROR|error|limit|Estimate|Campaign|Positives|Proposed|profile|reboot|hang|positive') {
            Write-Output ('WL: ' + $l.Trim())
          }
        }
      }
      $offset = $bytes
    }
  }

  if ($st -and $st.state -ne 'running') {
    Write-Output ('TERMINAL: ' + $st.state + ' reason=' + $st.reason)
    break
  }
  Start-Sleep -Seconds 15
}
