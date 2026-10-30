# adapter_probe.ps1 - ask the GIMX adapter what firmware it is running.
#
#   powershell -ExecutionPolicy Bypass -File tools\rig\adapter_probe.ps1
#
# This is the ONLY honest proof that the EMUPS4 flash took. GIMX prints
#     GIMX adapter detected, controller type is: DS4
#     Firmware version: 8.0
# during server startup, BEFORE it needs a --config, so we can read the type
# without a launcher config existing yet.
#
# It starts gimx.exe briefly, captures the banner, then STOPS it again so COM8
# is released. It sends no input and changes no console state.
#
# NOTE: a mismatch warning here is the whole point. If it still says XOnePad,
# the flash did not take and every later "ok" would be a lie.

param(
    [string]$Type = "DS4",
    [string]$Port = "COM8",
    [int]$Seconds = 10
)

$gimx = "C:\Program Files\GIMX\gimx.exe"
if (-not (Test-Path $gimx)) { Write-Host "ERROR: gimx.exe not found" -ForegroundColor Red; exit 1 }

# Refuse to fight an existing session for the serial port.
$existing = Get-Process -Name gimx -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "A gimx.exe is already running (PID $($existing.Id -join ', '))." -ForegroundColor Yellow
    Write-Host "Stop it first, or it is holding $Port." -ForegroundColor Yellow
    exit 3
}

$outFile = Join-Path $env:TEMP "gimx-probe-out.txt"
$errFile = Join-Path $env:TEMP "gimx-probe-err.txt"
Remove-Item $outFile, $errFile -ErrorAction SilentlyContinue

# GIMX refuses to start without at least a config, an event, or a source
# IP:port, so pass --src to get far enough to print the adapter banner.
#
# ARGUMENT ORDER IS LOAD-BEARING. GIMX's docs: "A --bdaddr, --port or --dst
# argument finishes the current controller options." So --port MUST be last,
# or everything after it is applied to a non-existent controller #2 - which is
# exactly what the first probe attempt did.
#
# --nograb: never capture mouse/keyboard. An elevated GIMX once froze a whole
# PC by taking REALTIME priority and grabbing input - see gimx_session.py.
$argList = @("--type", $Type, "--nograb", "--src", "127.0.0.1:51914",
             "--port", $Port)

Write-Host "=== GIMX adapter probe ===" -ForegroundColor Cyan
Write-Host "  $gimx $($argList -join ' ')" -ForegroundColor DarkGray
Write-Host "  (no --config: we only want the startup banner)" -ForegroundColor DarkGray
Write-Host ""

$proc = Start-Process -FilePath $gimx -ArgumentList $argList -NoNewWindow -PassThru `
                      -RedirectStandardOutput $outFile -RedirectStandardError $errFile
try { $proc.PriorityClass = "Normal" } catch { }

Start-Sleep -Seconds $Seconds

if (-not $proc.HasExited) {
    Write-Host "  stopping probe session (releasing $Port)..." -ForegroundColor DarkGray
    try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch { }
}
Start-Sleep -Milliseconds 500

$text = ""
foreach ($f in @($outFile, $errFile)) {
    if (Test-Path $f) { $text += (Get-Content $f -Raw) }
}

Write-Host "--- GIMX output ---" -ForegroundColor Cyan
if ([string]::IsNullOrWhiteSpace($text)) {
    Write-Host "  (nothing captured)" -ForegroundColor Yellow
} else {
    $text -split "`r?`n" | Where-Object { $_.Trim() -ne "" } | ForEach-Object { Write-Host "  $_" }
}

Write-Host ""
Write-Host "--- verdict ---" -ForegroundColor Cyan
if ($text -match 'controller type is:\s*(\S+?)\.?\s*$' -or $text -match 'controller type is:\s*(\S+)') {
    $detected = $Matches[1].TrimEnd('.')
    if ($detected -eq "DS4") {
        Write-Host "  ADAPTER = DS4  -> EMUPS4 flash CONFIRMED" -ForegroundColor Green
    } elseif ($detected -eq "XOnePad") {
        Write-Host "  ADAPTER = XOnePad -> STILL XBOX FIRMWARE. Reflash EMUPS4." -ForegroundColor Red
    } else {
        Write-Host "  ADAPTER = $detected (expected DS4)" -ForegroundColor Yellow
    }
} else {
    Write-Host "  Could not read the controller type from the banner." -ForegroundColor Yellow
}

if ($text -match 'Firmware version:\s*(\S+)') {
    Write-Host ("  Firmware version: {0}" -f $Matches[1]) -ForegroundColor Green
}
if ($text -match 'pass-through device\s*(\S+)') {
    Write-Host ("  Auth pass-through: {0}" -f $Matches[1]) -ForegroundColor Green
}
if ($text -match 'no adapter detected|cannot open|No such file') {
    Write-Host "  Adapter NOT detected on $Port." -ForegroundColor Red
}

Write-Host ""
$still = Get-Process -Name gimx -ErrorAction SilentlyContinue
if ($still) {
    Write-Host "  WARNING: gimx.exe still running (PID $($still.Id -join ', '))" -ForegroundColor Yellow
} else {
    Write-Host "  probe session stopped; $Port released" -ForegroundColor Green
}
