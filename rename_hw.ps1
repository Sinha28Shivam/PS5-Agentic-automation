# rename_hw.ps1 - Xbox-Automation-Python -> PS5-Automation-Python
#
# The folder name is the last Xbox reference in the hardware layer. Its CODE is
# already PS5 (DS4 profiles, EMUPS4, Dualshock4.xml) and hardware-verified, so
# it is kept - only the name changes.
#
# A plain rename fails with "Permission denied" while an ELEVATED gimx.exe holds
# the serial port with its CWD inside that tree. Stale __pycache__ handles do
# the same. This clears both, then retries.

$ErrorActionPreference = "Continue"
$src = "Xbox-Automation-Python"
$dst = "PS5-Automation-Python"

if (Test-Path $dst) { Write-Host "Already renamed." -ForegroundColor Green; exit 0 }
if (-not (Test-Path $src)) { Write-Host "Source missing." -ForegroundColor Red; exit 1 }

# 1. Any non-elevated gimx can be stopped from here.
$gimx = Get-Process -Name gimx -ErrorAction SilentlyContinue
foreach ($p in $gimx) {
    try {
        Stop-Process -Id $p.Id -Force -ErrorAction Stop
        Write-Host ("  stopped gimx.exe PID {0}" -f $p.Id) -ForegroundColor Green
    } catch {
        Write-Host ("  gimx.exe PID {0} is ELEVATED - close it from an admin" -f $p.Id) -ForegroundColor Yellow
        Write-Host  "  Task Manager, or the rename will keep failing." -ForegroundColor Yellow
    }
}

# 2. __pycache__ keeps file handles that block directory renames on Windows.
Get-ChildItem -LiteralPath $src -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    ForEach-Object {
        Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host ("  cleared {0}" -f $_.FullName.Replace((Get-Location).Path, '.')) -ForegroundColor DarkGray
    }

Start-Sleep -Seconds 2

# 3. Try the rename.
try {
    Rename-Item -LiteralPath $src -NewName $dst -ErrorAction Stop
    Write-Host ("  RENAMED {0} -> {1}" -f $src, $dst) -ForegroundColor Green
} catch {
    Write-Host ("  STILL BLOCKED: {0}" -f $_.Exception.Message) -ForegroundColor Red
    Write-Host ""
    Write-Host "  Something holds the folder. Most likely the elevated gimx.exe." -ForegroundColor Yellow
    Write-Host "  Close it, then re-run this script." -ForegroundColor Yellow
    exit 2
}
