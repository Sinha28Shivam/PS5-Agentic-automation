# free_capture.ps1 - release the capture card, then confirm it is really free.
#
#   powershell -ExecutionPolicy Bypass -File diagnostics\free_capture.ps1          # report only
#   powershell -ExecutionPolicy Bypass -File diagnostics\free_capture.ps1 -Close   # actually close them
#
# Only ONE application may hold a capture device at a time. RECentral 4 is the
# usual culprit: it is genuinely useful for eyeballing the PS5 and for checking
# the input RESOLUTION, but it must be closed before anything scripted runs.
#
# Teams is included because it grabs camera devices on launch and keeps them.
#
# RECentralService (the background service) is deliberately LEFT ALONE - it does
# not hold the device and killing it achieves nothing.

param([switch]$Close)

# GUI apps that take exclusive ownership. Service processes excluded on purpose.
$targets = Get-Process -ErrorAction SilentlyContinue | Where-Object {
    $_.ProcessName -match 'RECentral|ms-teams|^Teams$|obs64?$|^Zoom$|WindowsCamera|^Camera$|Skype|Discord' -and
    $_.ProcessName -notmatch 'Service'
}

if (-not $targets) {
    Write-Host "Nothing is holding the capture card." -ForegroundColor Green
} else {
    Write-Host "These hold (or can hold) the capture device:" -ForegroundColor Yellow
    foreach ($t in $targets) {
        Write-Host ("  PID {0,-6} {1}" -f $t.Id, $t.ProcessName) -ForegroundColor Yellow
    }
    if (-not $Close) {
        Write-Host ""
        Write-Host "Re-run with -Close to stop them, or close them by hand." -ForegroundColor Cyan
    } else {
        Write-Host ""
        foreach ($t in $targets) {
            try {
                Stop-Process -Id $t.Id -Force -ErrorAction Stop
                Write-Host ("  stopped {0} (PID {1})" -f $t.ProcessName, $t.Id) -ForegroundColor Green
            } catch {
                Write-Host ("  COULD NOT stop {0} (PID {1}): {2}" -f `
                            $t.ProcessName, $t.Id, $_.Exception.Message) -ForegroundColor Red
            }
        }
        Start-Sleep -Seconds 2
    }
}

Write-Host ""
Write-Host "=== Can ffmpeg open the device now? ===" -ForegroundColor Cyan
# A 1-frame probe is the only real proof the handle was released.
$probe = & ffmpeg -hide_banner -loglevel error -f dshow -rtbufsize 100M `
                  -i "video=AVerMedia ExtremeCap UVC" -frames:v 1 -f null - 2>&1 | Out-String

if ($probe -match 'in use|Could not run graph|I/O error') {
    Write-Host "  STILL HELD by something." -ForegroundColor Red
    Write-Host "  Check the system tray - RECentral minimises there instead of exiting." -ForegroundColor Yellow
} elseif ($probe -match 'No JPEG data|EOI before any SOF') {
    Write-Host "  Device is FREE, but carries NO SIGNAL (empty frames)." -ForegroundColor Yellow
    Write-Host "  That is the HDMI side: HDCP, wrong input, or unsupported mode." -ForegroundColor Yellow
} else {
    Write-Host "  Device is FREE and accepting reads." -ForegroundColor Green
}
