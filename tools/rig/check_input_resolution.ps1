# check_input_resolution.ps1 - what resolution is the PS5 ACTUALLY sending?
#
#   powershell -ExecutionPolicy Bypass -File tools\rig\check_input_resolution.ps1
#
# "Set the PS5 to 1080p" is only half the job - what matters is what the CARD
# RECEIVES. This asks ffmpeg to open the card with NO size hints and report the
# stream geometry it negotiates, which reflects the real incoming signal.
#
# The device must be FREE first (close RECentral 4 / Teams), or this reports a
# device-in-use error instead of a resolution.

Write-Host "=== Incoming signal geometry ===" -ForegroundColor Cyan
Write-Host "  (no -video_size hint: let the card report what it is fed)" -ForegroundColor DarkGray
Write-Host ""

# MUST be >= ~1.05 s. controls.yaml (measured 2026-08-12): the first ~2 reads
# after opening come back perfectly flat while the card locks onto HDMI, and
# real content only arrives at ~1.05 s. A 0.5 s probe reports "no signal" on a
# perfectly working card - which is exactly the false alarm this script raised
# on 2026-10-30 before a 3 s read proved the signal was fine all along.
#
# ALSO: with no -video_size hint, DirectShow hands back the card's DEFAULT pin
# format (640x480), NOT the incoming HDMI geometry. That is a property of the
# driver's pin enumeration, not a statement about the source. To learn whether
# 1080p actually arrives we must REQUEST 1080p and see if real frames decode.
$out = & ffmpeg -hide_banner -f dshow -rtbufsize 200M `
                -video_size 1920x1080 -framerate 30 `
                -i "video=AVerMedia ExtremeCap UVC" -t 3 -f null - 2>&1 | Out-String

if ($out -match 'in use|Could not run graph') {
    Write-Host "  DEVICE IN USE - close RECentral 4 / Teams first:" -ForegroundColor Red
    Write-Host "    powershell -File tools\rig\free_capture.ps1 -Close" -ForegroundColor White
    exit 2
}

# ffmpeg prints e.g.  Stream #0:0: Video: mjpeg ..., yuvj422p(pc, bt470bg/bt709/unknown), 1920x1080, 60 fps
$res  = [regex]::Match($out, '(\d{3,4})x(\d{3,4})')
$fps  = [regex]::Match($out, '([\d.]+)\s*fps')
$codec= [regex]::Match($out, 'Video:\s*(\w+)')

if ($res.Success) {
    $w = [int]$res.Groups[1].Value
    $h = [int]$res.Groups[2].Value
    Write-Host ("  RESOLUTION : {0}x{1}" -f $w, $h) -ForegroundColor Green
    if ($fps.Success)   { Write-Host ("  FRAME RATE : {0} fps" -f $fps.Groups[1].Value) -ForegroundColor Green }
    if ($codec.Success) { Write-Host ("  CODEC      : {0}" -f $codec.Groups[1].Value) -ForegroundColor Green }

    Write-Host ""
    if ($w -eq 1920 -and $h -eq 1080) {
        Write-Host "  CORRECT - 1080p, exactly what controls.yaml expects." -ForegroundColor Green
    } elseif ($w -ge 3840) {
        Write-Host "  TOO HIGH - the card is a 1080p-class device." -ForegroundColor Red
        Write-Host "  PS5: Settings > Screen and Video > Video Output >" -ForegroundColor Yellow
        Write-Host "       Resolution -> 1080p" -ForegroundColor Yellow
    } elseif ($w -eq 1280 -and $h -eq 720) {
        Write-Host "  720p. Works, but controls.yaml expects 1920x1080 -" -ForegroundColor Yellow
        Write-Host "  either raise the PS5 to 1080p or lower capture.width/height." -ForegroundColor Yellow
    } else {
        Write-Host ("  UNEXPECTED {0}x{1} - controls.yaml expects 1920x1080." -f $w,$h) -ForegroundColor Yellow
    }
} else {
    Write-Host "  Could not determine a resolution." -ForegroundColor Red
    if ($out -match 'No JPEG data|EOI before any SOF') {
        Write-Host "  The stream is EMPTY - no HDMI signal is arriving." -ForegroundColor Red
        Write-Host "  Check HDCP is OFF and the cable is in the card's HDMI IN." -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "--- raw ffmpeg stream lines ---" -ForegroundColor DarkGray
$out -split "`r?`n" | Where-Object { $_ -match 'Stream|Input #|Duration|No JPEG|SOF' } |
    ForEach-Object { Write-Host ("  {0}" -f $_.Trim()) -ForegroundColor DarkGray }
