# deep_capture_test.ps1 - the decisive capture test. Read-only.
#
#   powershell -ExecutionPolicy Bypass -File tools\rig\deep_capture_test.ps1
#
# Earlier probes were short (0.4-0.5 s). controls.yaml records that this card
# needs ~1.05 s before real content arrives, and the first ~2 reads come back
# perfectly flat while it locks onto HDMI. A brief probe can therefore MISS a
# signal that is actually present.
#
# This runs a sustained capture at each plausible mode and counts how many real
# frames (non-empty JPEGs) come back. If a longer read still yields nothing at
# any mode, the conclusion is sound rather than a timing artefact.

$outDir = Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) `
                    "artifacts\rig\capture-check"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

Write-Host "=== Sustained capture test (3 s per mode) ===" -ForegroundColor Cyan
Write-Host "  A short probe can miss a slow HDMI lock - this gives it time." -ForegroundColor DarkGray
Write-Host ""

$modes = @("1920x1080", "1280x720", "1680x1050", "640x480")
$anyGood = $false

foreach ($m in $modes) {
    $out = Join-Path $outDir ("deep-{0}.png" -f $m)
    Remove-Item $out -ErrorAction SilentlyContinue

    # 3 seconds of capture, keep the LAST frame: skips the flat warm-up reads.
    $err = & ffmpeg -hide_banner -loglevel info -f dshow -rtbufsize 200M `
                    -video_size $m -framerate 30 `
                    -i "video=AVerMedia ExtremeCap UVC" `
                    -t 3 -update 1 -y $out 2>&1 | Out-String

    $decoded = [regex]::Matches($err, 'frame=\s*(\d+)')
    $frames = 0
    if ($decoded.Count -gt 0) {
        $frames = [int]$decoded[$decoded.Count - 1].Groups[1].Value
    }
    $emptyCount = ([regex]::Matches($err, 'No JPEG data found')).Count

    $size = 0
    if (Test-Path $out) { $size = (Get-Item $out).Length }

    $verdict = "NO DATA"
    $col = "Red"
    if ($size -gt 60000) { $verdict = "REAL CONTENT"; $col = "Green"; $anyGood = $true }
    elseif ($size -gt 15000) { $verdict = "faint - inspect"; $col = "Yellow"; $anyGood = $true }

    Write-Host ("  {0,-11} frames={1,-5} emptyJPEG={2,-4} png={3,8:N0}B  {4}" -f `
                $m, $frames, $emptyCount, $size, $verdict) -ForegroundColor $col

    if ($err -match 'in use|Could not run graph') {
        Write-Host "      DEVICE IN USE - close RECentral/Teams" -ForegroundColor Red
        break
    }
}

Write-Host ""
Write-Host "=== Conclusion ===" -ForegroundColor Cyan
if ($anyGood) {
    Write-Host "  The card DID produce image data at one or more modes." -ForegroundColor Green
    Write-Host "  Open the PNGs and confirm you are seeing the PS5 (not a webcam):" -ForegroundColor Cyan
    Write-Host ("    {0}" -f $outDir) -ForegroundColor White
} else {
    Write-Host "  Every mode returned EMPTY frames over a sustained 3 s read." -ForegroundColor Red
    Write-Host "  This is NOT a timing artefact. Nothing is arriving on HDMI IN." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Remaining possibilities, in order:" -ForegroundColor Yellow
    Write-Host "   1. PS5 is in the card's HDMI OUT, not HDMI IN (monitor would" -ForegroundColor Yellow
    Write-Host "      still work perfectly via passthrough - matches the symptom)" -ForegroundColor Yellow
    Write-Host "   2. The HDMI cable into the card is faulty or not fully seated" -ForegroundColor Yellow
    Write-Host "   3. The card's HDMI input stage is dead (RMA)" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  PROVE IT IS THE CARD, NOT THE PS5:" -ForegroundColor Cyan
    Write-Host "   Unplug the PS5 and feed the card from THIS LAPTOP's HDMI out" -ForegroundColor White
    Write-Host "   (or any other HDMI source - a phone with an adapter works)." -ForegroundColor White
    Write-Host "   Re-run this script. Still empty from a known-good source =" -ForegroundColor White
    Write-Host "   the card is faulty and no amount of PS5 settings will fix it." -ForegroundColor White
}
