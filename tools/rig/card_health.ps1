# card_health.ps1 - is the CARD ITSELF (or its USB link) the fault? Read-only.
#
#   powershell -ExecutionPolicy Bypass -File tools\rig\card_health.ps1
#
# The AVerMedia ExtremeCap UVC (BU110, VID_07CA PID_0110) is a USB 3.0 device.
# On a USB 2.0 port it STILL ENUMERATES and still appears healthy in Device
# Manager, but it cannot carry 1080p and will sit at a low fallback format
# producing empty frames - which looks exactly like "no HDMI signal".
#
# That is the single most common way a working card behaves like a dead one,
# so check it before blaming the card or the console.

Write-Host "=== 1. USB link speed of the capture card ===" -ForegroundColor Cyan

$card = Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue |
        Where-Object { $_.DeviceID -match 'VID_07CA&PID_0110' }

if (-not $card) {
    Write-Host "  Card not found on USB." -ForegroundColor Red
} else {
    foreach ($c in $card) {
        Write-Host ("  {0}" -f $c.Name)
        Write-Host ("     {0}" -f $c.DeviceID) -ForegroundColor DarkGray
    }
}

Write-Host ""
Write-Host "  USB controllers on this machine:" -ForegroundColor Cyan
Get-CimInstance Win32_USBController -ErrorAction SilentlyContinue |
    ForEach-Object {
        $is3 = $_.Name -match '3\.|XHCI|eXtensible'
        $col = if ($is3) { "Green" } else { "Yellow" }
        Write-Host ("    {0}" -f $_.Name) -ForegroundColor $col
    }

Write-Host ""
Write-Host "  NOTE: 'USB Composite Device' under a USB 2.0 hub = the card is" -ForegroundColor DarkGray
Write-Host "  running at 480 Mbps and CANNOT do 1080p. Move it to a BLUE (3.0)" -ForegroundColor DarkGray
Write-Host "  port, directly on the laptop, no hub." -ForegroundColor DarkGray

Write-Host ""
Write-Host "=== 2. Formats offered (reveals the negotiated capability) ===" -ForegroundColor Cyan
$opts = & ffmpeg -hide_banner -f dshow -list_options true `
                 -i "video=AVerMedia ExtremeCap UVC" 2>&1 | Out-String
$sizes = [regex]::Matches($opts, 'max s=(\d{3,4})x(\d{3,4})') |
         ForEach-Object { "{0}x{1}" -f $_.Groups[1].Value, $_.Groups[2].Value } |
         Select-Object -Unique
if ($sizes) {
    Write-Host ("  offers: {0}" -f ($sizes -join ', ')) -ForegroundColor DarkGray
    if ($sizes -contains "1920x1080") {
        Write-Host "  1920x1080 IS offered -> the USB link can carry 1080p." -ForegroundColor Green
        Write-Host "  So a 640x480 negotiated stream means NO INPUT, not a USB limit." -ForegroundColor Yellow
    } else {
        Write-Host "  1080p NOT offered -> USB bandwidth or driver problem." -ForegroundColor Red
    }
} else {
    Write-Host "  could not read the option list" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== 3. Does the card report ANY input right now? ===" -ForegroundColor Cyan
$probe = & ffmpeg -hide_banner -f dshow -rtbufsize 100M `
                  -i "video=AVerMedia ExtremeCap UVC" -t 0.4 -f null - 2>&1 | Out-String
$res = [regex]::Match($probe, '(\d{3,4})x(\d{3,4})')
$empty = $probe -match 'No JPEG data|EOI before any SOF'
Write-Host ("  negotiated : {0}" -f $(if ($res.Success) { $res.Groups[0].Value } else { "unknown" }))
Write-Host ("  carries data: {0}" -f $(if ($empty) { "NO" } else { "yes" })) `
           -ForegroundColor $(if ($empty) { "Red" } else { "Green" })
