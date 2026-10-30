# flash_ps4_guided.ps1 - guided EMUPS4 flash for the PS5 (DualShock 4) rig.
#
# Wraps flash_leonardo.ps1 with the checks that actually block a flash, because
# the failure mode is a silent timeout that looks like a broken board.
#
#   powershell -ExecutionPolicy Bypass -File tools\rig\flash_ps4_guided.ps1
#
# THE ONE THING PEOPLE GET WRONG
# ------------------------------
# The Leonardo must be plugged into the *PC* to be flashed, NOT the console.
# While it is in the PS5 it is powered by the PS5 and presents itself as a
# gamepad - the PC cannot see it at all, so avrdude has nothing to talk to.

param(
    [int]$WaitSeconds = 120
)

$ErrorActionPreference = "Continue"
$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$flasher  = Join-Path $repoRoot "PS5-Automation-Python\flash-leonardo\flash_leonardo.ps1"

function Get-ArduinoDev {
    Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
        Where-Object { $_.InstanceId -match 'VID_(2341|2A03|03EB|1B4F)' } |
        Select-Object -First 1
}

Write-Host "=== PS5 rig: flash Leonardo with EMUPS4 ===" -ForegroundColor Cyan
Write-Host ""

# --- preflight -----------------------------------------------------------
$hex = "C:\Program Files\GIMX\firmware\EMUPS4.hex"
if (-not (Test-Path $hex)) {
    Write-Host "ERROR: EMUPS4.hex not found at $hex" -ForegroundColor Red
    exit 1
}
Write-Host "  firmware   : EMUPS4.hex  (DualShock 4 emulation)" -ForegroundColor Green

$gimx = Get-Process -Name gimx -ErrorAction SilentlyContinue
if ($gimx) {
    Write-Host "  WARNING: gimx.exe is running and may hold the serial port." -ForegroundColor Yellow
    Write-Host "           Stop it first:  python PS5-Automation-Python\gimx-session\gimx_session.py stop" -ForegroundColor Yellow
}

$ds4 = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
       Where-Object { $_.InstanceId -match 'VID_054C&PID_(05C4|09CC)' } | Select-Object -First 1
if ($ds4) {
    Write-Host "  auth pad   : DualShock 4 detected on the PC" -ForegroundColor Green
} else {
    $ds5 = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
           Where-Object { $_.InstanceId -match 'VID_054C&PID_0CE6' } | Select-Object -First 1
    if ($ds5) {
        Write-Host "  auth pad   : DUALSENSE found - GIMX CANNOT use it. Connect a DualShock 4." -ForegroundColor Red
    } else {
        Write-Host "  auth pad   : no DualShock 4 on the PC (needed later, not for flashing)" -ForegroundColor Yellow
    }
}

# --- the blocking requirement --------------------------------------------
Write-Host ""
$dev = Get-ArduinoDev
if (-not $dev) {
    Write-Host "  Leonardo   : NOT visible to the PC" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  ------------------------------------------------------------" -ForegroundColor Yellow
    Write-Host "   ACTION REQUIRED - the board cannot be flashed where it is." -ForegroundColor Yellow
    Write-Host "   ------------------------------------------------------------" -ForegroundColor Yellow
    Write-Host "   1. UNPLUG the Leonardo's USB from the PS5." -ForegroundColor White
    Write-Host "   2. PLUG it into this PC with a DATA USB cable" -ForegroundColor White
    Write-Host "      (charge-only cables enumerate nothing)." -ForegroundColor DarkGray
    Write-Host "   3. Leave the FTDI adapter on COM8 exactly as it is." -ForegroundColor White
    Write-Host ""
    Write-Host "   Waiting up to $WaitSeconds s for the board to appear..." -ForegroundColor Cyan

    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    while ((Get-Date) -lt $deadline) {
        $dev = Get-ArduinoDev
        if ($dev) { break }
        Start-Sleep -Milliseconds 400
    }
    if (-not $dev) {
        Write-Host ""
        Write-Host "   Still nothing. Nothing was flashed - the board is unchanged." -ForegroundColor Red
        Write-Host "   Re-run this script once the Leonardo is on the PC." -ForegroundColor Red
        exit 2
    }
    Write-Host ""
}
Write-Host "  Leonardo   : $($dev.FriendlyName)" -ForegroundColor Green

# --- hand over to the real flasher ---------------------------------------
Write-Host ""
Write-Host "Handing over to flash_leonardo.ps1 ..." -ForegroundColor Cyan
Write-Host ""
& powershell -ExecutionPolicy Bypass -NoProfile -File $flasher -Firmware EMUPS4 -TimeoutSeconds 90
$code = $LASTEXITCODE

Write-Host ""
if ($code -eq 0) {
    Write-Host "=== FLASHED. NEXT STEPS ===" -ForegroundColor Green
    Write-Host " 1. Unplug the Leonardo from the PC and plug it back into the PS5." -ForegroundColor White
    Write-Host " 2. Keep the DualShock 4 wired to this PC (it supplies auth)." -ForegroundColor White
    Write-Host " 3. A DS4 GIMX launcher config is still REQUIRED before input can" -ForegroundColor White
    Write-Host "    be sent - controls.yaml ps5.config_file is still null, and" -ForegroundColor White
    Write-Host "    gimx_session.py will refuse to start until it is set." -ForegroundColor Yellow
    Write-Host " 4. Disable HDCP on the PS5 or the capture card returns blank frames." -ForegroundColor Yellow
} else {
    Write-Host "=== FLASH FAILED (exit $code) ===" -ForegroundColor Red
    Write-Host " Most common cause: the ~8 s bootloader window closed." -ForegroundColor Red
    Write-Host " Tap RESET on the board and re-run this script immediately." -ForegroundColor Red
}
exit $code
