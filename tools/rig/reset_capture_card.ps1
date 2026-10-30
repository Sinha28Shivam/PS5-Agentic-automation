# reset_capture_card.ps1 - power-cycle the capture card without unplugging it.
#
#   powershell -ExecutionPolicy Bypass -File tools\rig\reset_capture_card.ps1
#   (needs an ADMIN PowerShell to actually disable/enable the device)
#
# A UVC capture device can get wedged: it keeps enumerating, keeps reporting
# CM_PROB_NONE, and keeps handing out empty frames at its lowest fallback mode
# even after the HDMI source is fixed. It has latched a stale EDID/HDCP state.
#
# Disabling and re-enabling the PnP node forces a fresh HDMI handshake. That is
# the software equivalent of unplugging the USB cable, and it is the cheapest
# thing to try before suspecting dead hardware.
#
# PHYSICAL ALTERNATIVE (no admin needed, equally effective):
#   1. unplug the card's USB from the laptop
#   2. unplug the HDMI from the card
#   3. wait 10 seconds
#   4. HDMI back in FIRST, then USB
# Order matters: the card reads the source EDID when HDMI appears.

$ErrorActionPreference = "Continue"

$isAdmin = ([Security.Principal.WindowsPrincipal] `
            [Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

Write-Host "=== Capture card reset ===" -ForegroundColor Cyan

$nodes = Get-PnpDevice -ErrorAction SilentlyContinue |
         Where-Object { $_.InstanceId -match 'VID_07CA&PID_0110' -and $_.Present }

if (-not $nodes) {
    Write-Host "  Card not present - nothing to reset." -ForegroundColor Red
    exit 1
}

Write-Host "  Found:" -ForegroundColor Green
$nodes | ForEach-Object { Write-Host ("    {0}" -f $_.FriendlyName) -ForegroundColor DarkGray }

if (-not $isAdmin) {
    Write-Host ""
    Write-Host "  NOT RUNNING AS ADMIN - cannot disable/enable the device." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Do the physical reset instead (just as good):" -ForegroundColor Cyan
    Write-Host "    1. unplug the card's USB from the laptop" -ForegroundColor White
    Write-Host "    2. unplug the HDMI from the card" -ForegroundColor White
    Write-Host "    3. wait 10 seconds" -ForegroundColor White
    Write-Host "    4. plug HDMI back in FIRST, then USB" -ForegroundColor White
    Write-Host ""
    Write-Host "  (The card reads the source EDID when HDMI appears, so HDMI" -ForegroundColor DarkGray
    Write-Host "   before USB gives it something to latch onto.)" -ForegroundColor DarkGray
    exit 3
}

# Only the composite parent needs cycling; children follow.
$parent = $nodes | Where-Object { $_.InstanceId -notmatch '&MI_' } | Select-Object -First 1
if (-not $parent) { $parent = $nodes | Select-Object -First 1 }

Write-Host ""
Write-Host ("  Disabling {0} ..." -f $parent.FriendlyName) -ForegroundColor Yellow
Disable-PnpDevice -InstanceId $parent.InstanceId -Confirm:$false -ErrorAction Continue
Start-Sleep -Seconds 3

Write-Host "  Re-enabling ..." -ForegroundColor Yellow
Enable-PnpDevice -InstanceId $parent.InstanceId -Confirm:$false -ErrorAction Continue
Start-Sleep -Seconds 5

Write-Host ""
Write-Host "=== Signal after reset ===" -ForegroundColor Cyan
$probe = & ffmpeg -hide_banner -f dshow -rtbufsize 100M `
                  -i "video=AVerMedia ExtremeCap UVC" -t 0.5 -f null - 2>&1 | Out-String
$res = [regex]::Match($probe, '(\d{3,4})x(\d{3,4})')
$empty = $probe -match 'No JPEG data|EOI before any SOF'

$resText = if ($res.Success) { $res.Groups[0].Value } else { "unknown" }
Write-Host ("  negotiated  : {0}" -f $resText)
if ($empty) {
    Write-Host "  carries data: NO - still no HDMI input" -ForegroundColor Red
} else {
    Write-Host "  carries data: YES" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Grab a picture: powershell -File tools\rig\grab_by_name.ps1" -ForegroundColor Cyan
}
