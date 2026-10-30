# flash_retry.ps1 - beat the Leonardo's ~8 second bootloader window.
#
# WHY THIS EXISTS
# ---------------
# The first EMUPS4 attempt reached the board but avrdude got garbage:
#     Found programmer: Id = "?"
#     error: buffered memory access not supported
# That is the signature of the bootloader EXITING MID-HANDSHAKE. The AVR109
# bootloader lives ~8 s after a reset and then hands control to whatever
# firmware is already on the chip, so a flash started even slightly late
# talks to a device that is no longer a programmer.
#
# The fix is not to press RESET faster by hand - it is to have avrdude already
# waiting. This script polls every 150 ms and launches the instant the
# bootloader VID/PID appears, then retries the whole cycle if it still loses.
#
#   powershell -ExecutionPolicy Bypass -File tools\rig\flash_retry.ps1
#
# Press RESET on the Leonardo when prompted (or just replug it).

param(
    [string]$Firmware = "EMUPS4",
    [int]$Attempts    = 5,
    [int]$WaitSeconds = 45
)

$ErrorActionPreference = "Continue"

$gimxDir = "C:\Program Files\GIMX"
$avrdude = Join-Path $gimxDir "avrdude.exe"
$avrconf = Join-Path $gimxDir "avrdude.conf"
$hexFile = Join-Path $gimxDir ("firmware\{0}.hex" -f $Firmware)

foreach ($f in @($avrdude, $avrconf, $hexFile)) {
    if (-not (Test-Path $f)) { Write-Host "ERROR: missing $f" -ForegroundColor Red; exit 1 }
}

Write-Host "=== Leonardo flash (retry loop): $Firmware ===" -ForegroundColor Cyan
Write-Host "firmware : $hexFile"
Write-Host ""

function Test-PortReal($port) {
    # Get-PnpDevice reports bootloader ports that are NOT openable: Windows
    # keeps the node as CM_PROB_PHANTOM after the ~8 s window closes, so
    # avrdude fails with 'can't open device "\\.\COMx": cannot find the file'.
    #
    # DO NOT OPEN THE PORT TO TEST IT. An earlier version of this function
    # opened it at 57600 and closed it again; on an atmega32u4 that open/close
    # can itself terminate the AVR109 bootloader, so the "check" destroyed the
    # very window it was verifying and avrdude then met a dead device.
    # GetPortNames() is enough: a phantom never appears there.
    return ([System.IO.Ports.SerialPort]::GetPortNames() -contains $port)
}

function Get-BootloaderPort {
    # PID_0036 = Leonardo bootloader, PID_0037 = Micro bootloader. Both are
    # atmega32u4 and both are flashed identically - this rig's device history
    # shows BOTH, so matching only 0036 (as flash_leonardo.ps1 does) can miss
    # the board entirely.
    $dev = Get-PnpDevice -PresentOnly -Class Ports -ErrorAction SilentlyContinue |
           Where-Object { $_.InstanceId -match 'VID_(2341|2A03)&PID_003[67]' -or
                          $_.FriendlyName -match 'bootloader' }
    foreach ($d in $dev) {
        if ($d.FriendlyName -match '\((COM\d+)\)') {
            if (Test-PortReal $Matches[1]) { return $Matches[1] }
        }
    }
    # Fall back to any genuinely-new usable port that is not the FTDI/AMT pair.
    foreach ($p in [System.IO.Ports.SerialPort]::GetPortNames()) {
        if ($p -ne "COM3" -and $p -ne "COM8") { return $p }
    }
    return $null
}

function Get-SketchPort {
    # The board in normal (non-bootloader) mode, e.g. already running GIMX fw.
    $dev = Get-PnpDevice -PresentOnly -Class Ports -ErrorAction SilentlyContinue |
           Where-Object { $_.InstanceId -match 'VID_(2341|2A03)' -and
                          $_.InstanceId -notmatch 'PID_0036' }
    foreach ($d in $dev) {
        if ($d.FriendlyName -match '\((COM\d+)\)') { return $Matches[1] }
    }
    return $null
}

function Invoke-Touch1200($port) {
    # Opening at 1200 baud is the Leonardo "magic reset" into the bootloader.
    try {
        $sp = New-Object System.IO.Ports.SerialPort $port, 1200, 'None', 8, 'One'
        $sp.Open(); Start-Sleep -Milliseconds 200; $sp.Close()
        return $true
    } catch { return $false }
}

for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
    Write-Host "--- attempt $attempt of $Attempts ---" -ForegroundColor Cyan

    # Try to induce the bootloader ourselves so we are not waiting on a human.
    $sketch = Get-SketchPort
    if ($sketch) {
        Write-Host "  board in sketch mode on $sketch - 1200-baud touch..." -ForegroundColor Yellow
        [void](Invoke-Touch1200 $sketch)
    } else {
        Write-Host "  TAP THE RESET BUTTON on the Leonardo now (or replug it)." -ForegroundColor Yellow
    }

    Write-Host "  polling for bootloader (up to $WaitSeconds s)..." -ForegroundColor DarkGray
    $port = $null
    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    while ((Get-Date) -lt $deadline) {
        $port = Get-BootloaderPort
        if ($port) { break }
        Start-Sleep -Milliseconds 150
    }

    if (-not $port) {
        Write-Host "  no bootloader port appeared." -ForegroundColor Red
        continue
    }

    Write-Host "  >>> bootloader on $port - launching avrdude IMMEDIATELY <<<" -ForegroundColor Green

    $outLog = Join-Path $env:TEMP "avrdude-out.txt"
    $errLog = Join-Path $env:TEMP "avrdude-err.txt"
    $args = @(
        "-C", "`"$avrconf`"",
        "-p", "atmega32u4",
        "-c", "avr109",
        "-P", ("\\.\" + $port),
        "-b", "57600",
        "-D",
        "-U", "`"flash:w:$hexFile`:i`""
    )

    $proc = Start-Process -FilePath $avrdude -ArgumentList $args -NoNewWindow -Wait -PassThru `
                          -RedirectStandardOutput $outLog -RedirectStandardError $errLog
    $code = $proc.ExitCode

    $text = ""
    foreach ($lf in @($outLog, $errLog)) {
        if (Test-Path $lf) { $text += (Get-Content $lf -Raw) }
    }

    if ($code -eq 0 -and $text -match 'flash verified') {
        Write-Host ""
        Write-Host "SUCCESS: $Firmware flashed and VERIFIED." -ForegroundColor Green
        $text -split "`n" | Where-Object { $_ -match 'bytes of flash verified|writing flash' } |
            ForEach-Object { Write-Host "  $($_.Trim())" -ForegroundColor Green }
        Write-Host ""
        Write-Host "NEXT: unplug the Leonardo from the PC and plug it into the PS5." -ForegroundColor Cyan
        exit 0
    }

    Write-Host "  attempt $attempt failed (exit $code)." -ForegroundColor Red
    if ($text -match 'programmer is not responding|buffered memory access') {
        Write-Host "  -> bootloader window closed mid-handshake; retrying." -ForegroundColor Yellow
    }
    Start-Sleep -Milliseconds 600
}

Write-Host ""
Write-Host "FAILED after $Attempts attempts. The board is UNCHANGED." -ForegroundColor Red
Write-Host "Try: a different DATA usb cable, a direct port (no hub)," -ForegroundColor Red
Write-Host "and double-tap RESET to hold the bootloader open longer." -ForegroundColor Red
exit 1
