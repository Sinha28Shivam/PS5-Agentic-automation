# arduino_state.ps1 - what is the Leonardo doing RIGHT NOW? Read-only.
#
#   powershell -ExecutionPolicy Bypass -File tools\rig\arduino_state.ps1
#
# Three possible states:
#   BOOTLOADER  - VID_2341&PID_0036 on a COM port. Flashable for ~8 seconds.
#   SKETCH/FW   - a VID_2341 device that is NOT PID_0036. Can be pushed into
#                 the bootloader with a 1200-baud touch.
#   GIMX ADAPTER- already running GIMX firmware: presents as a USB gamepad,
#                 NOT a COM port. Its absence from the port list is CORRECT.

Write-Host "PORTS: " -NoNewline
$ports = [System.IO.Ports.SerialPort]::GetPortNames()
if ($ports) { Write-Host ($ports -join ', ') } else { Write-Host "(none)" }

Write-Host ""
Write-Host "--- any Arduino/AVR device ---"
$all = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
       Where-Object { $_.InstanceId -match 'VID_(2341|2A03|03EB|1B4F)' }
if ($all) {
    $all | ForEach-Object {
        Write-Host ("  [{0}] {1} | {2}" -f $_.Status, $_.Class, $_.FriendlyName)
        Write-Host ("        {0}" -f $_.InstanceId) -ForegroundColor DarkGray
    }
} else {
    Write-Host "  none present" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "--- verdict ---"
$boot = $all | Where-Object { $_.InstanceId -match 'PID_0036' }
if ($boot) {
    Write-Host "  BOOTLOADER ACTIVE - flash NOW (window ~8s)" -ForegroundColor Green
} elseif ($all) {
    Write-Host "  Board present but NOT in bootloader." -ForegroundColor Yellow
    Write-Host "  A 1200-baud touch or a RESET tap will open the bootloader." -ForegroundColor Yellow
} else {
    Write-Host "  No Arduino visible to this PC." -ForegroundColor Yellow
    Write-Host "  Either it is unplugged from the PC, or it already runs GIMX" -ForegroundColor Yellow
    Write-Host "  firmware and is enumerating as a USB GAMEPAD (not a COM port)." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "--- HID gamepads (a flashed GIMX adapter shows up here) ---"
$hid = Get-PnpDevice -PresentOnly -Class HIDClass -ErrorAction SilentlyContinue |
       Where-Object { $_.FriendlyName -match 'game controller|gamepad|HID-compliant game' }
if ($hid) {
    $hid | ForEach-Object {
        Write-Host ("  [{0}] {1}" -f $_.Status, $_.FriendlyName)
        Write-Host ("        {0}" -f $_.InstanceId) -ForegroundColor DarkGray
    }
} else { Write-Host "  none" }
