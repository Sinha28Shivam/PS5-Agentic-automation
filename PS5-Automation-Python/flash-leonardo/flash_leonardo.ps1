# flash_leonardo.ps1 - flash GIMX firmware (default EMUPS4 for PS5/PS4) onto
# the Arduino Leonardo adapter.
#
#   powershell -ExecutionPolicy Bypass -File flash-leonardo\flash_leonardo.ps1
#   powershell -ExecutionPolicy Bypass -File flash-leonardo\flash_leonardo.ps1 -Force
#
# 1. Plug the Leonardo's USB into the PC (not the PS5).
# 2. Run this; when it prints WAITING, TAP RESET (double-tap holds it longer).
# 3. On SUCCESS, plug the Leonardo back into the PS5 and run adapter_probe.ps1.
#
# Why it is written this way (see docs/FLASH_NOTES.md - each one cost a failed
# flash):
#  * The bootloader lives only ~8 s and is killed by opening its port, so we
#    NEVER open it - we only poll GetPortNames() every 50 ms (that also ignores
#    phantom CM_PROB_PHANTOM nodes that Get-PnpDevice still reports).
#  * avrdude runs INLINE with 2>&1. Start-Process redirection produced empty
#    logs and hid every real error.
#  * Success requires avrdude to print "flash verified"; exit code 0 alone is
#    not trusted.

param(
    [string]$Firmware    = "EMUPS4",   # must match controls.yaml consoles.ps5.firmware
    [string]$GimxDir     = "C:\Program Files\GIMX",
    [int]$TimeoutSeconds = 60,
    [string]$ForcePort   = "",         # e.g. "COM9" to skip waiting
    [switch]$Force,                    # avrdude -F; only if avrdude asks for it
    [int]$Baud           = 57600
)

$avrdude = Join-Path $GimxDir "avrdude.exe"
$avrconf = Join-Path $GimxDir "avrdude.conf"
$hexFile = Join-Path $GimxDir ("firmware\{0}.hex" -f $Firmware)

foreach ($f in @($avrdude, $avrconf, $hexFile)) {
    if (-not (Test-Path $f)) { Write-Host "ERROR: missing $f" -ForegroundColor Red; exit 1 }
}

$gimx = Get-Process -Name gimx -ErrorAction SilentlyContinue
if ($gimx) {
    Write-Host "gimx.exe is running (PID $($gimx.Id -join ', ')). Stop it first:" -ForegroundColor Yellow
    Write-Host "  python gimx-session\gimx_session.py stop" -ForegroundColor White
    exit 3
}

Write-Host "=== GIMX Leonardo flasher: $Firmware ===" -ForegroundColor Cyan
Write-Host "  hex   : $hexFile"
Write-Host "  baud  : $Baud   force: $($Force.IsPresent)"
Write-Host ""

$port = $ForcePort
if (-not $port) {
    # Whatever exists now (FTDI, AMT, ...) is never the bootloader.
    $known = @([System.IO.Ports.SerialPort]::GetPortNames())
    Write-Host ("  existing ports ignored: {0}" -f ($(if ($known) { $known -join ', ' } else { 'none' }))) -ForegroundColor DarkGray
    Write-Host "  WAITING for the bootloader - TAP RESET NOW (double-tap is better)" -ForegroundColor Yellow

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline -and -not $port) {
        foreach ($p in [System.IO.Ports.SerialPort]::GetPortNames()) {
            if ($known -notcontains $p) { $port = $p; break }
        }
        if (-not $port) { Start-Sleep -Milliseconds 50 }
    }
    if (-not $port) {
        Write-Host ""
        Write-Host "  No new port in $TimeoutSeconds s. Board UNCHANGED." -ForegroundColor Red
        Write-Host "  Check: Leonardo on the PC (not the PS5), DATA cable, no hub, RESET tapped." -ForegroundColor Yellow
        exit 2
    }
}

Write-Host ""
Write-Host "  >>> $port is live - flashing now <<<" -ForegroundColor Green

$argList = @("-C", $avrconf, "-p", "atmega32u4", "-c", "avr109",
             "-P", ("\\.\" + $port), "-b", "$Baud", "-D")
if ($Force) { $argList += "-F" }
$argList += @("-U", ("flash:w:" + $hexFile + ":i"))
Write-Host "  $avrdude $($argList -join ' ')" -ForegroundColor DarkGray
Write-Host ""

$output = & $avrdude @argList 2>&1
$code = $LASTEXITCODE
$output | ForEach-Object { Write-Host "  $_" }
$joined = ($output | Out-String)

Write-Host ""
if ($code -eq 0 -and $joined -match 'flash verified') {
    Write-Host "SUCCESS: $Firmware flashed and VERIFIED." -ForegroundColor Green
    Write-Host "NEXT: plug the Leonardo into the PS5, then run flash-leonardo\adapter_probe.ps1" -ForegroundColor Cyan
    Write-Host "      (it must report 'controller type is: DS4')." -ForegroundColor Cyan
    exit 0
}

Write-Host "FAILED (exit $code). The board is UNCHANGED." -ForegroundColor Red
if ($joined -match 'buffered memory access not supported') {
    Write-Host "  -> avrdude suggests overriding. Retry with -Force." -ForegroundColor Yellow
}
if ($joined -match 'cannot find the file|ser_open') {
    Write-Host "  -> the port vanished before avrdude opened it. Tap RESET again." -ForegroundColor Yellow
}
if ($joined -match 'not responding') {
    Write-Host "  -> bootloader exited mid-handshake. Double-tap RESET next time." -ForegroundColor Yellow
}
exit 1
