# driver_check.ps1 - is the Leonardo bootloader DRIVER healthy? Read-only.
#
#   powershell -ExecutionPolicy Bypass -File tools\rig\driver_check.ps1
#
# A bootloader that enumerates in Device Manager but cannot be opened is
# usually a DRIVER problem, not a timing problem. ConfigManagerErrorCode tells
# us which. 0 = working. 28 = no driver installed. 10 = cannot start.

Write-Host "=== Arduino devices (including non-present / ghosts) ===" -ForegroundColor Cyan
$devs = Get-PnpDevice -ErrorAction SilentlyContinue |
        Where-Object { $_.InstanceId -match 'VID_(2341|2A03)' }
if (-not $devs) {
    Write-Host "  No Arduino device nodes at all (not even remembered ones)." -ForegroundColor Yellow
} else {
    foreach ($d in $devs) {
        $flag = if ($d.Present) { "PRESENT" } else { "ghost" }
        Write-Host ("  [{0}] {1} | {2} | {3}" -f $d.Status, $flag, $d.Class, $d.FriendlyName)
        Write-Host ("        {0}" -f $d.InstanceId) -ForegroundColor DarkGray
        if ($d.Problem) {
            Write-Host ("        PROBLEM: {0}" -f $d.Problem) -ForegroundColor Red
        }
    }
}

Write-Host ""
Write-Host "=== WMI view: driver error codes ===" -ForegroundColor Cyan
$wmi = Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue |
       Where-Object { $_.DeviceID -match 'VID_2341|VID_2A03' }
if (-not $wmi) {
    Write-Host "  none" -ForegroundColor Yellow
} else {
    foreach ($w in $wmi) {
        Write-Host ("  {0}" -f $w.Name)
        Write-Host ("     DeviceID : {0}" -f $w.DeviceID) -ForegroundColor DarkGray
        Write-Host ("     Status   : {0}" -f $w.Status)
        $code = $w.ConfigManagerErrorCode
        $meaning = switch ($code) {
            0  { "OK - driver loaded and running" }
            10 { "CANNOT START - driver present but device won't start" }
            18 { "Reinstall drivers" }
            19 { "Registry/config corrupt" }
            22 { "DISABLED" }
            28 { "NO DRIVER INSTALLED  <-- this blocks avrdude entirely" }
            31 { "Driver failed to load" }
            43 { "Device reported a failure (often bad cable/port)" }
            default { "code $code" }
        }
        $colour = if ($code -eq 0) { "Green" } else { "Red" }
        Write-Host ("     ErrorCode: {0} = {1}" -f $code, $meaning) -ForegroundColor $colour
    }
}

Write-Host ""
Write-Host "=== Live serial port names ===" -ForegroundColor Cyan
$names = [System.IO.Ports.SerialPort]::GetPortNames()
Write-Host ("  {0}" -f ($(if ($names) { $names -join ', ' } else { "(none)" })))

Write-Host ""
Write-Host "=== USB controllers / hubs in play ===" -ForegroundColor Cyan
Get-CimInstance Win32_USBHub -ErrorAction SilentlyContinue |
    Select-Object -First 12 |
    ForEach-Object { Write-Host ("  {0}" -f $_.Name) -ForegroundColor DarkGray }
