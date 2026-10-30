# port_watch.ps1 - watch COM ports appear/disappear in real time. Read-only.
#
# Proves whether a RESET tap actually produces a USABLE port, and for how long.
# It NEVER opens the port (see warning below), it only lists names.
#
#   powershell -ExecutionPolicy Bypass -File tools\rig\port_watch.ps1
#
# Tap RESET while this runs. Expect something like:
#   +COM9  (appeared)
#   -COM9  (gone after ~8s)
# If COM9 never appears in GetPortNames, the bootloader is not enumerating as a
# usable serial port and no amount of avrdude retrying will help.

param([int]$Seconds = 25)

$prev = [System.IO.Ports.SerialPort]::GetPortNames()
Write-Host "baseline: $($prev -join ', ')" -ForegroundColor Cyan
Write-Host "watching for $Seconds s - TAP RESET NOW (repeatedly is fine)" -ForegroundColor Yellow
Write-Host ""

$sw = [Diagnostics.Stopwatch]::StartNew()
$seen = @{}
while ($sw.Elapsed.TotalSeconds -lt $Seconds) {
    $now = [System.IO.Ports.SerialPort]::GetPortNames()
    foreach ($p in $now)  { if ($prev -notcontains $p) {
        Write-Host ("  [{0,6:N2}s] +{1}  APPEARED" -f $sw.Elapsed.TotalSeconds, $p) -ForegroundColor Green
        $seen[$p] = $sw.Elapsed.TotalSeconds
    } }
    foreach ($p in $prev) { if ($now  -notcontains $p) {
        $life = if ($seen.ContainsKey($p)) { "{0:N2}s alive" -f ($sw.Elapsed.TotalSeconds - $seen[$p]) } else { "unknown" }
        Write-Host ("  [{0,6:N2}s] -{1}  GONE  ({2})" -f $sw.Elapsed.TotalSeconds, $p, $life) -ForegroundColor Red
    } }
    $prev = $now
    Start-Sleep -Milliseconds 100
}

Write-Host ""
Write-Host "final: $($prev -join ', ')" -ForegroundColor Cyan
if ($seen.Count -eq 0) {
    Write-Host "NO new port ever appeared. The reset is not producing a serial device." -ForegroundColor Red
} else {
    Write-Host "Ports that appeared: $($seen.Keys -join ', ')" -ForegroundColor Green
}
