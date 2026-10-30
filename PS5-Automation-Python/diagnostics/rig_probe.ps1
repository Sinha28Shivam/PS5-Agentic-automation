# rig_probe.ps1 - read-only snapshot of the PS5/DS4 rig before flashing.
# Changes nothing. Run:
#   powershell -ExecutionPolicy Bypass -File diagnostics\rig_probe.ps1

$ErrorActionPreference = "Continue"

Write-Host "=== 1. GIMX install ===" -ForegroundColor Cyan
$gimxCandidates = @(
    "C:\Program Files\GIMX\gimx.exe",
    "C:\Program Files (x86)\GIMX\gimx.exe",
    "$env:LOCALAPPDATA\Programs\GIMX\gimx.exe",
    "$env:ProgramData\GIMX\gimx.exe"
)
$gimxFound = $null
foreach ($g in $gimxCandidates) {
    if (Test-Path $g) { $gimxFound = $g; break }
}
if (-not $gimxFound) {
    Write-Host "  gimx.exe NOT found in the usual locations. Searching..." -ForegroundColor Yellow
    $hit = Get-ChildItem -Path "C:\" -Filter "gimx.exe" -Recurse -ErrorAction SilentlyContinue -Force |
           Select-Object -First 1
    if ($hit) { $gimxFound = $hit.FullName }
}
if ($gimxFound) {
    Write-Host "  FOUND: $gimxFound" -ForegroundColor Green
    $dir = Split-Path $gimxFound -Parent
    Write-Host "  dir  : $dir"
    foreach ($need in @("avrdude.exe", "avrdude.conf")) {
        $p = Join-Path $dir $need
        if (Test-Path $p) { Write-Host "  OK   : $need" -ForegroundColor Green }
        else { Write-Host "  MISS : $need (needed to flash)" -ForegroundColor Red }
    }
    $fw = Join-Path $dir "firmware"
    if (Test-Path $fw) {
        Write-Host "  firmware/:" -ForegroundColor Green
        Get-ChildItem $fw -Filter *.hex | ForEach-Object { Write-Host "      $($_.Name)" }
    } else {
        Write-Host "  MISS : firmware\ directory" -ForegroundColor Red
    }
} else {
    Write-Host "  gimx.exe NOT FOUND ANYWHERE." -ForegroundColor Red
}

Write-Host ""
Write-Host "=== 2. COM ports present ===" -ForegroundColor Cyan
$ports = [System.IO.Ports.SerialPort]::GetPortNames()
if ($ports) { Write-Host "  $($ports -join ', ')" -ForegroundColor Green }
else { Write-Host "  NONE present" -ForegroundColor Red }

Write-Host ""
Write-Host "=== 3. Port devices (-PresentOnly: ghosts excluded) ===" -ForegroundColor Cyan
$portDevs = Get-PnpDevice -PresentOnly -Class Ports -ErrorAction SilentlyContinue
if ($portDevs) {
    $portDevs | ForEach-Object {
        Write-Host ("  [{0}] {1}" -f $_.Status, $_.FriendlyName)
        Write-Host ("        {0}" -f $_.InstanceId) -ForegroundColor DarkGray
    }
} else { Write-Host "  none" -ForegroundColor Red }

Write-Host ""
Write-Host "=== 4. FTDI UART (expect VID_0403, should be COM8) ===" -ForegroundColor Cyan
$ftdi = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
        Where-Object { $_.InstanceId -match 'VID_0403' }
if ($ftdi) { $ftdi | ForEach-Object { Write-Host ("  [{0}] {1}" -f $_.Status, $_.FriendlyName) -ForegroundColor Green } }
else { Write-Host "  FTDI adapter NOT present" -ForegroundColor Red }

Write-Host ""
Write-Host "=== 5. Arduino / AVR boards (VID 2341/2A03/03EB/1B4F) ===" -ForegroundColor Cyan
$ard = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
       Where-Object { $_.InstanceId -match 'VID_(2341|2A03|03EB|1B4F)' }
if ($ard) {
    $ard | ForEach-Object {
        Write-Host ("  [{0}] {1} | {2}" -f $_.Status, $_.Class, $_.FriendlyName) -ForegroundColor Green
        Write-Host ("        {0}" -f $_.InstanceId) -ForegroundColor DarkGray
    }
} else {
    Write-Host "  No Arduino visible to the PC." -ForegroundColor Yellow
    Write-Host "  NOTE: this is EXPECTED if the Leonardo is plugged into the PS5 and" -ForegroundColor Yellow
    Write-Host "        already runs GIMX firmware. But flashing REQUIRES it on the PC." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== 6. Sony controller (VID_054C - DS4 auth pad) ===" -ForegroundColor Cyan
$sony = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
        Where-Object { $_.InstanceId -match 'VID_054C' }
if ($sony) {
    $sony | ForEach-Object {
        Write-Host ("  [{0}] {1} | {2}" -f $_.Status, $_.Class, $_.FriendlyName) -ForegroundColor Green
        Write-Host ("        {0}" -f $_.InstanceId) -ForegroundColor DarkGray
    }
    # PID_05C4 = DS4 v1, PID_09CC = DS4 v2, PID_0CE6 = DualSense
    if ($sony.InstanceId -match 'PID_0CE6') {
        Write-Host "  WARNING: that is a DUALSENSE. GIMX cannot use it to authenticate;" -ForegroundColor Red
        Write-Host "           a DualShock 4 (PID_05C4 or PID_09CC) is required." -ForegroundColor Red
    }
} else {
    Write-Host "  No Sony controller present on this PC." -ForegroundColor Red
}

Write-Host ""
Write-Host "=== 7. Is COM8 free? ===" -ForegroundColor Cyan
if ($ports -contains "COM8") {
    try {
        $sp = New-Object System.IO.Ports.SerialPort 'COM8',500000,'None',8,'One'
        $sp.Open(); Write-Host "  COM8 is FREE (openable)" -ForegroundColor Green; $sp.Close()
    } catch {
        Write-Host "  COM8 is BUSY: $($_.Exception.Message)" -ForegroundColor Yellow
        Write-Host "  (a running gimx.exe holding it is normal)" -ForegroundColor DarkGray
    }
} else {
    Write-Host "  COM8 is not in the present-port list." -ForegroundColor Red
}

Write-Host ""
Write-Host "=== 8. Running gimx processes ===" -ForegroundColor Cyan
$procs = Get-Process -Name gimx -ErrorAction SilentlyContinue
if ($procs) { $procs | ForEach-Object { Write-Host ("  PID {0}" -f $_.Id) -ForegroundColor Yellow } }
else { Write-Host "  none running" -ForegroundColor Green }

Write-Host ""
Write-Host "=== PROBE COMPLETE ===" -ForegroundColor Cyan
