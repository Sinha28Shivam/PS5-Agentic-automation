# grab_by_name.ps1 - grab ONE frame straight from the card with ffmpeg.
#
#   powershell -ExecutionPolicy Bypass -File tools\rig\grab_by_name.ps1
#
# Bypasses OpenCV entirely and addresses the device BY NAME, so it cannot be
# fooled by index shuffling (the webcam-instead-of-console trap recorded in
# controls.yaml, 2026-08-14).
#
# Reading the result:
#   frame written, non-trivial size  -> the card works; OpenCV's problem is a
#                                       holder (Teams/RECentral) or indexing.
#   "Could not run graph"/"in use"   -> another app owns the device.
#   frame written but pure black     -> device fine, NO SIGNAL: HDCP or the
#                                       wrong HDMI input.

param(
    [string]$Device = "AVerMedia ExtremeCap UVC",
    [string]$Size   = "1920x1080"
)

$outDir = Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) `
                    "artifacts\rig\capture-check"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$out = Join-Path $outDir ("ffmpeg-{0}.png" -f (Get-Date -Format "HHmmss"))

Write-Host "=== ffmpeg direct grab ===" -ForegroundColor Cyan
Write-Host "  device : $Device"
Write-Host "  size   : $Size"
Write-Host "  out    : $out"
Write-Host ""

# -rtbufsize guards against the card outpacing ffmpeg's buffer.
# 3 frames, keep the last: the first frames after open are flat while the
# card locks onto the HDMI signal (measured ~1.05 s to real content).
# -t 3 (NOT -frames:v 3). Frame-count limits finish before the card has even
# locked on: controls.yaml measured real content arriving at ~1.05 s, and a
# 3-frame grab at 30 fps ends after 0.1 s. That produced a false "no signal"
# on 2026-10-30. Capture for 3 SECONDS and keep the last frame instead.
$ffArgs = @(
    "-hide_banner", "-loglevel", "warning",
    "-f", "dshow",
    "-video_size", $Size,
    "-framerate", "30",
    "-rtbufsize", "200M",
    "-i", ("video=" + $Device),
    "-t", "3",
    "-update", "1",
    "-y", $out
)

$res = & ffmpeg @ffArgs 2>&1 | Out-String
if ($res.Trim()) {
    Write-Host "--- ffmpeg said ---" -ForegroundColor DarkGray
    $res -split "`r?`n" | Where-Object { $_.Trim() } |
        ForEach-Object { Write-Host ("  {0}" -f $_.Trim()) -ForegroundColor DarkGray }
    Write-Host ""
}

if (Test-Path $out) {
    $len = (Get-Item $out).Length
    Write-Host ("  FRAME WRITTEN: {0:N0} bytes" -f $len) -ForegroundColor Green
    if ($len -lt 20000) {
        Write-Host "  Very small file - likely a FLAT/BLACK frame (no signal)." -ForegroundColor Yellow
        Write-Host "  Check: HDCP OFF, correct HDMI IN on the card, PS5 awake." -ForegroundColor Yellow
    } else {
        Write-Host "  Size suggests real image content." -ForegroundColor Green
    }
    Write-Host ""
    Write-Host "  OPEN IT AND LOOK. A picture settles in one second what" -ForegroundColor Cyan
    Write-Host "  statistics only suggest - especially whether you are seeing" -ForegroundColor Cyan
    Write-Host "  the PS5 or your own webcam." -ForegroundColor Cyan
    Write-Host ("  {0}" -f $out) -ForegroundColor White
} else {
    Write-Host "  NO FRAME WRITTEN." -ForegroundColor Red
    if ($res -match 'in use|Could not run graph|I/O error|Device or resource busy') {
        Write-Host "  -> Another application is holding the device." -ForegroundColor Red
        Write-Host "     Close Microsoft Teams and the RECentral GUI, then retry." -ForegroundColor Red
    }
}
