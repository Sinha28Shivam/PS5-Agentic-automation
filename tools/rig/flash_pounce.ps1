# flash_pounce.ps1 - wait for the bootloader port, then run avrdude INLINE.
#
#   powershell -ExecutionPolicy Bypass -File tools\rig\flash_pounce.ps1
#
# Differences from flash_retry.ps1, both of which mattered in practice:
#
#  1. avrdude runs INLINE (call operator), not via Start-Process with
#     -RedirectStandardOutput. That redirection was silently producing EMPTY
#     log files, so the real error was invisible and we were guessing.
#
#  2. It polls GetPortNames() every 50 ms, not 150 ms, and does NOT open the
#     port to "verify" it - opening an AVR109 bootloader can end it.
#
#  3. -F (override signature check) is optional via -Force. The earlier
#     failures printed 'buffered memory access not supported... Maybe it isn't
#     a butterfly/AVR109 but a AVR910 device?' which avrdude itself suggests
#     overriding.
#
# Tap RESET when it says WAITING. Double-tap often holds the window open longer.

param(
    [string]$Firmware = "EMUPS4",
    [int]$WaitSeconds = 60,
    [switch]$Force,
    [int]$Baud = 57600
)

$gimxDir = "C:\Program Files\GIMX"
$avrdude = Join-Path $gimxDir "avrdude.exe"
$avrconf = Join-Path $gimxDir "avrdude.conf"
$hexFile = Join-Path $gimxDir ("firmware\{0}.hex" -f $Firmware)

foreach ($f in @($avrdude, $avrconf, $hexFile)) {
    if (-not (Test-Path $f)) { Write-Host "ERROR: missing $f" -ForegroundColor Red; exit 1 }
}

$known = @("COM3", "COM8")   # AMT + FTDI: never the board

Write-Host "=== flash_pounce: $Firmware ===" -ForegroundColor Cyan
Write-Host "  hex   : $hexFile"
Write-Host "  baud  : $Baud"
Write-Host "  force : $($Force.IsPresent)"
Write-Host ""
Write-Host "  WAITING for a new COM port - TAP RESET NOW (double-tap is better)" -ForegroundColor Yellow

$deadline = (Get-Date).AddSeconds($WaitSeconds)
$port = $null
while ((Get-Date) -lt $deadline) {
    foreach ($p in [System.IO.Ports.SerialPort]::GetPortNames()) {
        if ($known -notcontains $p) { $port = $p; break }
    }
    if ($port) { break }
    Start-Sleep -Milliseconds 50
}

if (-not $port) {
    Write-Host ""
    Write-Host "  No new port appeared in $WaitSeconds s. Board UNCHANGED." -ForegroundColor Red
    exit 2
}

Write-Host ""
Write-Host "  >>> $port IS LIVE - flashing this instant <<<" -ForegroundColor Green
Write-Host ""

$argList = @(
    "-C", $avrconf,
    "-p", "atmega32u4",
    "-c", "avr109",
    "-P", ("\\.\" + $port),
    "-b", "$Baud",
    "-D"
)
if ($Force) { $argList += "-F" }
$argList += @("-U", ("flash:w:" + $hexFile + ":i"))

Write-Host "  $avrdude $($argList -join ' ')" -ForegroundColor DarkGray
Write-Host ""

# INLINE so stdout+stderr reach this console. 2>&1 merges avrdude's progress
# output (which it writes to stderr) instead of discarding it.
$output = & $avrdude @argList 2>&1
$code = $LASTEXITCODE
$output | ForEach-Object { Write-Host "  $_" }

Write-Host ""
$joined = ($output | Out-String)
if ($code -eq 0 -and $joined -match 'flash verified') {
    Write-Host "SUCCESS: $Firmware flashed and VERIFIED." -ForegroundColor Green
    Write-Host ""
    Write-Host "NEXT: unplug from the PC, plug the Leonardo into the PS5." -ForegroundColor Cyan
    exit 0
}

Write-Host "FAILED (exit $code). The board is UNCHANGED." -ForegroundColor Red
if ($joined -match 'buffered memory access not supported') {
    Write-Host "  -> avrdude suggests overriding. Retry with -Force." -ForegroundColor Yellow
}
if ($joined -match 'cannot find the file|ser_open') {
    Write-Host "  -> the port vanished before avrdude opened it (window too short)." -ForegroundColor Yellow
}
if ($joined -match 'not responding') {
    Write-Host "  -> bootloader exited mid-handshake. Double-tap RESET next time." -ForegroundColor Yellow
}
exit 1
