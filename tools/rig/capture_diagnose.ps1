# capture_diagnose.ps1 - why can't the PC see the PS5? Read-only.
#
#   powershell -ExecutionPolicy Bypass -File tools\rig\capture_diagnose.ps1
#
# Separates the TWO very different capture faults:
#   A) DEVICE WON'T OPEN  -> another app holds it, or a driver fault.
#   B) DEVICE OPENS, FRAME BLANK -> HDCP, wrong HDMI input, or cabling.
# They need opposite fixes, so never guess between them.

Write-Host "=== 1. Capture hardware present? ===" -ForegroundColor Cyan
$cards = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
         Where-Object { $_.InstanceId -match 'VID_07CA' -or
                        $_.FriendlyName -match 'AVerMedia|ExtremeCap' }
if ($cards) {
    foreach ($c in $cards) {
        Write-Host ("  [{0}] {1} | {2}" -f $c.Status, $c.Class, $c.FriendlyName) -ForegroundColor Green
        Write-Host ("        {0}" -f $c.InstanceId) -ForegroundColor DarkGray
        if ($c.Problem -and $c.Problem -ne 'CM_PROB_NONE') {
            Write-Host ("        PROBLEM: {0}" -f $c.Problem) -ForegroundColor Red
        }
    }
} else {
    Write-Host "  NOT FOUND - card is unplugged or not enumerating" -ForegroundColor Red
}

Write-Host ""
Write-Host "=== 2. Driver error codes ===" -ForegroundColor Cyan
$wmi = Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue |
       Where-Object { $_.Name -match 'AVerMedia|ExtremeCap' -or $_.DeviceID -match 'VID_07CA' }
if ($wmi) {
    foreach ($w in $wmi) {
        $code = $w.ConfigManagerErrorCode
        $meaning = switch ($code) {
            0  { "OK" }
            10 { "CANNOT START" }
            22 { "DISABLED" }
            28 { "NO DRIVER INSTALLED" }
            43 { "DEVICE REPORTED A FAILURE (often cable/power)" }
            default { "code $code" }
        }
        $col = if ($code -eq 0) { "Green" } else { "Red" }
        Write-Host ("  {0}" -f $w.Name)
        Write-Host ("     ErrorCode {0} = {1}" -f $code, $meaning) -ForegroundColor $col
    }
} else { Write-Host "  (no WMI entry)" -ForegroundColor Yellow }

Write-Host ""
Write-Host "=== 3. Apps that can STEAL the device ===" -ForegroundColor Cyan
# Only ONE application may hold a capture device at a time.
$procs = Get-Process -ErrorAction SilentlyContinue |
         Where-Object { $_.ProcessName -match 'RECentral|AVer|obs|Camera|Zoom|Teams|Skype|Discord' }
if ($procs) {
    foreach ($p in $procs) {
        $isGui = $p.ProcessName -notmatch 'Service'
        $col = if ($isGui) { "Red" } else { "Yellow" }
        $tag = if ($isGui) { "HOLDS THE DEVICE - CLOSE IT" } else { "background service (usually harmless)" }
        Write-Host ("  PID {0,-6} {1,-24} {2}" -f $p.Id, $p.ProcessName, $tag) -ForegroundColor $col
    }
} else {
    Write-Host "  none running - the device should be free" -ForegroundColor Green
}

Write-Host ""
Write-Host "=== 4. Windows camera privacy policy ===" -ForegroundColor Cyan
# A capture card enumerates as a camera. If camera access is denied for
# desktop apps, OpenCV/ffmpeg get 'cannot open' with no useful error.
$roots = @(
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\webcam",
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\webcam"
)
foreach ($r in $roots) {
    $v = (Get-ItemProperty -Path $r -Name Value -ErrorAction SilentlyContinue).Value
    if ($v) {
        $col = if ($v -eq 'Allow') { "Green" } else { "Red" }
        Write-Host ("  {0,-5} {1}" -f $v, $r) -ForegroundColor $col
    }
}
$deskKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\webcam\NonPackaged"
$dv = (Get-ItemProperty -Path $deskKey -Name Value -ErrorAction SilentlyContinue).Value
if ($dv) {
    $col = if ($dv -eq 'Allow') { "Green" } else { "Red" }
    Write-Host ("  {0,-5} desktop apps (NonPackaged)" -f $dv) -ForegroundColor $col
    if ($dv -ne 'Allow') {
        Write-Host "    ^ THIS BLOCKS OpenCV/ffmpeg. Settings > Privacy & security" -ForegroundColor Red
        Write-Host "      > Camera > 'Let desktop apps access your camera' = ON" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "=== 5. ffmpeg device list (the names capture.py matches on) ===" -ForegroundColor Cyan
$ff = Get-Command ffmpeg -ErrorAction SilentlyContinue
if (-not $ff) {
    Write-Host "  ffmpeg not on PATH - name-based detection cannot work" -ForegroundColor Yellow
} else {
    $out = & ffmpeg -hide_banner -list_devices true -f dshow -i dummy 2>&1 | Out-String
    $out -split "`r?`n" | Where-Object { $_ -match '"' } |
        ForEach-Object { Write-Host ("  {0}" -f $_.Trim()) -ForegroundColor DarkGray }
}

Write-Host ""
Write-Host "=== VERDICT ===" -ForegroundColor Cyan
$gui = $procs | Where-Object { $_.ProcessName -notmatch 'Service' }
if ($gui) {
    Write-Host " FAULT A: an app is holding the card -> close: $($gui.ProcessName -join ', ')" -ForegroundColor Red
} elseif ($dv -and $dv -ne 'Allow') {
    Write-Host " FAULT A: Windows camera privacy is blocking desktop apps" -ForegroundColor Red
} else {
    Write-Host " No obvious holder. If capture.py still says 'cannot open',"  -ForegroundColor Yellow
    Write-Host " try FAULT B checks: HDCP off, correct HDMI IN, PS5 awake."   -ForegroundColor Yellow
}
