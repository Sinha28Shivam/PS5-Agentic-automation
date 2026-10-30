# manual_check.ps1 - the four things that must be true BEFORE you manually
# verify the signal by eye. Read-only; starts and stops nothing.
#
#   powershell -ExecutionPolicy Bypass -File tools\rig\manual_check.ps1

$blockers = @()

Write-Host "=== 1. DualShock 4 wired to THIS PC ===" -ForegroundColor Cyan
$ds4 = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
       Where-Object { $_.InstanceId -match 'VID_054C&PID_(05C4|09CC)' }
if ($ds4) {
    Write-Host "  OK - DS4 present (auth pass-through can work)" -ForegroundColor Green
} else {
    Write-Host "  BLOCKER - no DualShock 4 on this PC." -ForegroundColor Red
    Write-Host "    GIMX needs a REAL DS4 wired here to authenticate." -ForegroundColor Red
    Write-Host "    If it paired to the PS5 over Bluetooth it LEFT the PC:" -ForegroundColor Yellow
    Write-Host "    hold PS + SHARE until the light bar flashes to unpair," -ForegroundColor Yellow
    Write-Host "    then reconnect it to the laptop BY CABLE." -ForegroundColor Yellow
    $blockers += "DS4 not on PC"
}

Write-Host ""
Write-Host "=== 2. Capture card (NOT required for a manual eyeball test) ===" -ForegroundColor Cyan
# Deliberately NOT a blocker here. A manual test is watched on the TV, so the
# capture card plays no part. RECentralService is also only AVerMedia's
# background service - it is the RECentral GUI that grabs the device.
$running = Get-Process -ErrorAction SilentlyContinue |
           Select-Object -ExpandProperty ProcessName -Unique
$gui = $running | Where-Object { $_ -match '^RECentral$|^RECentral\s|obs64?$|^Zoom$|^WindowsCamera$' }
$svc = $running | Where-Object { $_ -match 'RECentralService' }
if ($gui) {
    Write-Host "  NOTE - capture GUI running: $($gui -join ', ')" -ForegroundColor Yellow
    Write-Host "    Fine (even useful) for watching the PS5 by eye." -ForegroundColor DarkGray
    Write-Host "    MUST be closed before any SCRIPTED test." -ForegroundColor Yellow
} elseif ($svc) {
    Write-Host "  NOTE - only RECentralService (background service) is running." -ForegroundColor Green
    Write-Host "    That alone does not usually hold the device." -ForegroundColor DarkGray
} else {
    Write-Host "  OK - nothing obviously holding the card" -ForegroundColor Green
}

Write-Host ""
Write-Host "=== 3. No stale gimx.exe holding COM8 ===" -ForegroundColor Cyan
$gimx = Get-Process -Name gimx -ErrorAction SilentlyContinue
if ($gimx) {
    Write-Host "  WARNING - gimx.exe running (PID $($gimx.Id -join ', '))" -ForegroundColor Yellow
    Write-Host "    A session started BEFORE the DS4 was connected can never" -ForegroundColor Yellow
    Write-Host "    authenticate, yet still reports 'reachable'. Stop it:" -ForegroundColor Yellow
    Write-Host "      python PS5-Automation-Python\gimx-session\gimx_session.py stop" -ForegroundColor White
    $blockers += "stale gimx.exe PID $($gimx.Id -join ', ')"
} else {
    Write-Host "  OK - COM8 free for a fresh session" -ForegroundColor Green
}

Write-Host ""
Write-Host "=== 4. FTDI adapter on COM8 ===" -ForegroundColor Cyan
$ftdi = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
        Where-Object { $_.InstanceId -match 'VID_0403' }
if ($ftdi) {
    Write-Host "  OK - FTDI present" -ForegroundColor Green
} else {
    Write-Host "  BLOCKER - FTDI adapter missing" -ForegroundColor Red
    $blockers += "FTDI missing"
}

Write-Host ""
Write-Host "================= VERDICT =================" -ForegroundColor Cyan
if ($blockers.Count -eq 0) {
    Write-Host " READY for a manual signal test." -ForegroundColor Green
    Write-Host ""
    Write-Host " 1. Put the PS5 on a menu with a VISIBLE HIGHLIGHT" -ForegroundColor White
    Write-Host "    (Settings list, or the home row of game tiles)." -ForegroundColor White
    Write-Host " 2. Start a session:" -ForegroundColor White
    Write-Host "      python PS5-Automation-Python\gimx-session\gimx_session.py start" -ForegroundColor Gray
    Write-Host " 3. When it prints 'Press the key/button assigned to PS.'" -ForegroundColor White
    Write-Host "    -> TAP PS ON THE WIRED DUALSHOCK 4." -ForegroundColor Yellow
    Write-Host " 4. Second terminal - send a visible pattern and WATCH THE TV:" -ForegroundColor White
    Write-Host "      python PS5-Automation-Python\test-controller\test_controller.py --console ps5 macro nav_test" -ForegroundColor Gray
    Write-Host ""
    Write-Host " The highlight MOVING is the proof. 'ok' in the terminal is not." -ForegroundColor Yellow
} else {
    Write-Host " NOT READY - $($blockers.Count) blocker(s):" -ForegroundColor Red
    foreach ($b in $blockers) { Write-Host "   - $b" -ForegroundColor Red }
}
