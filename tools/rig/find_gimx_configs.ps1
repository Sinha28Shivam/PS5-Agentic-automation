# find_gimx_configs.ps1 - locate GIMX launcher configs (.xml). Read-only.
#
#   powershell -ExecutionPolicy Bypass -File tools\rig\find_gimx_configs.ps1
#
# controls.yaml needs ps5.config_file set to one of these filenames. GIMX
# stores user configs under the per-user gimx folder, not Program Files.

Write-Host "=== GIMX install contents ===" -ForegroundColor Cyan
Get-ChildItem "C:\Program Files\GIMX" -ErrorAction SilentlyContinue |
    ForEach-Object {
        $kind = if ($_.PSIsContainer) { "<DIR> " } else { "      " }
        Write-Host ("  {0}{1}" -f $kind, $_.Name)
    }

Write-Host ""
Write-Host "=== Candidate config locations ===" -ForegroundColor Cyan
$roots = @(
    (Join-Path $env:APPDATA  "gimx"),
    (Join-Path $env:LOCALAPPDATA "gimx"),
    (Join-Path $env:USERPROFILE "gimx"),
    (Join-Path $env:USERPROFILE "Documents\gimx"),
    "C:\Program Files\GIMX\config",
    "C:\Program Files\GIMX\configs"
)
foreach ($r in $roots) {
    if (Test-Path $r) {
        Write-Host ("  EXISTS: {0}" -f $r) -ForegroundColor Green
        Get-ChildItem $r -Recurse -ErrorAction SilentlyContinue |
            Select-Object -First 40 |
            ForEach-Object { Write-Host ("      {0}" -f $_.FullName) -ForegroundColor DarkGray }
    } else {
        Write-Host ("  missing: {0}" -f $r) -ForegroundColor DarkGray
    }
}

Write-Host ""
Write-Host "=== GIMX executables (launcher = the GUI that creates configs) ===" -ForegroundColor Cyan
Get-ChildItem "C:\Program Files\GIMX" -Filter *.exe -ErrorAction SilentlyContinue |
    ForEach-Object { Write-Host ("  {0}" -f $_.Name) -ForegroundColor Green }
