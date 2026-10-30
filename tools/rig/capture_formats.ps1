# capture_formats.ps1 - what the card actually offers, and does ANY of it
# carry pixels right now? Read-only.
#
#   powershell -ExecutionPolicy Bypass -File tools\rig\capture_formats.ps1
#
# The first ffmpeg grab failed with "No JPEG data found in image" while still
# WRITING a frame. That means the device opened fine but its MJPEG pin carried
# no data - i.e. no incoming HDMI signal, not a driver or holder problem.
#
# This tries the alternative pixel format (YUY2/raw) and a couple of smaller
# resolutions, so we can tell "card offers nothing usable" from "card offers
# plenty but the HDMI side is dark".

param([string]$Device = "AVerMedia ExtremeCap UVC")

$outDir = Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) `
                    "artifacts\rig\capture-check"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

Write-Host "=== 1. Formats the card advertises ===" -ForegroundColor Cyan
$list = & ffmpeg -hide_banner -f dshow -list_options true -i ("video=" + $Device) 2>&1 | Out-String
$lines = $list -split "`r?`n" | Where-Object { $_ -match 'vcodec|pixel_format|min s=' }
if ($lines) {
    $lines | ForEach-Object { Write-Host ("  {0}" -f $_.Trim()) -ForegroundColor DarkGray }
} else {
    Write-Host "  (could not read option list)" -ForegroundColor Yellow
    $list -split "`r?`n" | Select-Object -First 15 |
        ForEach-Object { Write-Host ("  {0}" -f $_.Trim()) -ForegroundColor DarkGray }
}

Write-Host ""
Write-Host "=== 2. Try each format for ACTUAL PIXELS ===" -ForegroundColor Cyan

$attempts = @(
    @{ Name = "mjpeg 1920x1080";  Args = @("-vcodec","mjpeg","-video_size","1920x1080") },
    @{ Name = "yuyv422 1920x1080"; Args = @("-pixel_format","yuyv422","-video_size","1920x1080") },
    @{ Name = "yuyv422 1280x720";  Args = @("-pixel_format","yuyv422","-video_size","1280x720") },
    @{ Name = "default (no hints)"; Args = @() }
)

foreach ($a in $attempts) {
    $tag = ($a.Name -replace '[^a-zA-Z0-9]','-')
    $out = Join-Path $outDir ("fmt-{0}.png" -f $tag)
    Remove-Item $out -ErrorAction SilentlyContinue

    $ffArgs = @("-hide_banner","-loglevel","error","-f","dshow","-rtbufsize","100M")
    $ffArgs += $a.Args
    $ffArgs += @("-i", ("video=" + $Device), "-frames:v","5","-update","1","-y",$out)

    $err = & ffmpeg @ffArgs 2>&1 | Out-String
    if (Test-Path $out) {
        $len = (Get-Item $out).Length
        $verdict = if ($len -gt 40000) { "REAL CONTENT"; } elseif ($len -gt 12000) { "faint/uncertain" } else { "BLACK / flat" }
        $col = if ($len -gt 40000) { "Green" } elseif ($len -gt 12000) { "Yellow" } else { "Red" }
        Write-Host ("  {0,-22} {1,9:N0} bytes  {2}" -f $a.Name, $len, $verdict) -ForegroundColor $col
    } else {
        $reason = "no frame"
        if ($err -match 'in use|Could not run graph') { $reason = "DEVICE HELD BY ANOTHER APP" }
        elseif ($err -match 'Could not set video options|not supported') { $reason = "format unsupported" }
        Write-Host ("  {0,-22} {1}" -f $a.Name, $reason) -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "=== 3. Interpretation ===" -ForegroundColor Cyan
Write-Host "  If EVERY format wrote only small/black frames, the card and its" -ForegroundColor White
Write-Host "  driver are FINE and the problem is upstream on HDMI:" -ForegroundColor White
Write-Host ""
Write-Host "    1. HDCP  - PS5 encrypts its system UI. This is the #1 cause." -ForegroundColor Yellow
Write-Host "       Settings > System > HDMI > Enable HDCP  ->  OFF  (reboots UI)" -ForegroundColor Yellow
Write-Host "    2. Wrong socket - PS5 HDMI OUT must go to the card's HDMI IN," -ForegroundColor Yellow
Write-Host "       not HDMI OUT (passthrough)." -ForegroundColor Yellow
Write-Host "    3. PS5 asleep / in rest mode - wake it." -ForegroundColor Yellow
Write-Host "    4. 4K/120 or VRR output the card cannot ingest - set the PS5 to" -ForegroundColor Yellow
Write-Host "       1080p 60Hz while bringing the rig up." -ForegroundColor Yellow
Write-Host ""
Write-Host ("  Frames: {0}" -f $outDir) -ForegroundColor Cyan
