# watch_signal.ps1 - poll the capture input while you change PS5 settings.
#
#   powershell -ExecutionPolicy Bypass -File tools\rig\watch_signal.ps1
#
# Leave this running on the laptop while you re-seat the HDMI cable or walk
# through Screen and Video settings on the console. It reports the geometry
# the card negotiates every few seconds, so you see the moment a real signal
# appears instead of guessing.
#
#   640x480 + "no data"  = card's no-signal fallback (nothing on HDMI IN)
#   1920x1080 + data     = what we want

param(
    [int]$Seconds  = 180,
    [int]$Interval = 5
)

Write-Host "Watching the capture input for $Seconds s (every $Interval s)." -ForegroundColor Cyan
Write-Host "Change PS5 settings / re-seat the HDMI cable now. Ctrl+C to stop." -ForegroundColor Yellow
Write-Host ""
Write-Host ("  {0,-10} {1,-12} {2,-9} {3}" -f "time", "resolution", "fps", "data?") -ForegroundColor DarkGray
Write-Host ("  " + ("-" * 52)) -ForegroundColor DarkGray

$sw = [Diagnostics.Stopwatch]::StartNew()
$last = ""

while ($sw.Elapsed.TotalSeconds -lt $Seconds) {
    $out = & ffmpeg -hide_banner -f dshow -rtbufsize 100M `
                    -i "video=AVerMedia ExtremeCap UVC" -t 0.4 -f null - 2>&1 | Out-String

    if ($out -match 'in use|Could not run graph') {
        $line = "{0,-10} {1}" -f ("{0:N0}s" -f $sw.Elapsed.TotalSeconds), "DEVICE IN USE - close RECentral/Teams"
        Write-Host ("  " + $line) -ForegroundColor Red
        Start-Sleep -Seconds $Interval
        continue
    }

    $res = [regex]::Match($out, '(\d{3,4})x(\d{3,4})')
    $fps = [regex]::Match($out, '([\d.]+)\s*fps')
    $empty = $out -match 'No JPEG data|EOI before any SOF'

    $resText = if ($res.Success) { $res.Groups[0].Value } else { "unknown" }
    $fpsText = if ($fps.Success) { $fps.Groups[1].Value } else { "-" }
    $dataText = if ($empty) { "NO DATA" } else { "DATA OK" }

    $colour = "Red"
    if (-not $empty -and $resText -eq "1920x1080") { $colour = "Green" }
    elseif (-not $empty) { $colour = "Yellow" }

    $line = "{0,-10} {1,-12} {2,-9} {3}" -f `
            ("{0:N0}s" -f $sw.Elapsed.TotalSeconds), $resText, $fpsText, $dataText
    Write-Host ("  " + $line) -ForegroundColor $colour

    $sig = "$resText|$dataText"
    if ($sig -ne $last -and $last -ne "") {
        Write-Host ("      ^ CHANGED (was {0})" -f ($last -replace '\|', ' ')) -ForegroundColor Cyan
    }
    $last = $sig

    if ($colour -eq "Green") {
        Write-Host ""
        Write-Host "  SIGNAL GOOD - 1080p with real data. Stopping." -ForegroundColor Green
        Write-Host "  Next: powershell -File tools\rig\grab_by_name.ps1" -ForegroundColor Cyan
        exit 0
    }

    Start-Sleep -Seconds $Interval
}

Write-Host ""
Write-Host "Watch window ended without a good 1080p signal." -ForegroundColor Yellow
Write-Host "See docs\hardware\FIX_CAPTURE.md" -ForegroundColor Yellow
