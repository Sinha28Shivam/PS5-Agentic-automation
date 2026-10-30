# cleanup_dead_code.ps1 - remove files that are dead after the Xbox wipe.
#
#   powershell -ExecutionPolicy Bypass -File cleanup_dead_code.ps1
#
# Only removes things proven dead, not merely "unused-looking":
#   * temp_code_test/agentic/* - every file imports the DELETED Xbox agentic
#     layer (from core.config, from tools.registry, from agents.base ...) and
#     cannot run at all now.
#   * temp_code_test/docs/verify_docs.py - validated the deleted docs/ tree.
#   * __pycache__ - regenerated on demand; also holds stale handles that block
#     directory renames on Windows.
#   * .commitmsg / one-shot migration scripts - consumed, not part of the repo.
#
# KEPT: everything in temp_code_test/hardware (PS5 rig tooling, verified
# working) and temp_code_test/artifacts (proof frames = evidence the rig ran).

$ErrorActionPreference = "Continue"
$removed = 0

function Kill-Path($path, $why) {
    if (-not (Test-Path $path)) { return }
    $n = 1
    if ((Get-Item -LiteralPath $path -Force).PSIsContainer) {
        $n = (Get-ChildItem -LiteralPath $path -Recurse -File -Force -ErrorAction SilentlyContinue).Count
    }
    try {
        Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction Stop
        Write-Host ("  removed {0,-46} {1,4} file(s)  {2}" -f $path, $n, $why) -ForegroundColor Green
        $script:removed += $n
    } catch {
        Write-Host ("  FAILED  {0}  {1}" -f $path, $_.Exception.Message) -ForegroundColor Red
    }
}

Write-Host "=== 1. Dead Xbox-agentic probe scripts ===" -ForegroundColor Cyan
Kill-Path "temp_code_test\agentic" "imports the deleted agent layer"
Kill-Path "temp_code_test\docs"    "validated the deleted docs/ tree"

Write-Host ""
Write-Host "=== 2. One-shot migration scripts (already run) ===" -ForegroundColor Cyan
Kill-Path "wipe_xbox.ps1"       "wipe completed"
Kill-Path "backup_rig_tools.ps1" "backup completed"
Kill-Path ".commitmsg"           "commit made"

Write-Host ""
Write-Host "=== 3. Bytecode caches ===" -ForegroundColor Cyan
$pyc = Get-ChildItem -Path . -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
       Where-Object { $_.FullName -notmatch '\\venv\\' }
foreach ($d in $pyc) {
    $rel = $d.FullName.Replace((Get-Location).Path + '\', '')
    Kill-Path $rel "regenerated on demand"
}

Write-Host ""
Write-Host "=== 4. Stale pytest cache ===" -ForegroundColor Cyan
Get-ChildItem -Path . -Recurse -Directory -Filter ".pytest_cache" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch '\\venv\\' } |
    ForEach-Object { Kill-Path $_.FullName.Replace((Get-Location).Path + '\', '') "stale" }

Write-Host ""
Write-Host ("=== Removed {0} file(s) ===" -f $removed) -ForegroundColor Cyan
Write-Host ""
Write-Host "Kept deliberately:" -ForegroundColor Yellow
Write-Host "  temp_code_test\hardware\   - PS5 rig tooling (verified working)" -ForegroundColor DarkGray
Write-Host "  temp_code_test\artifacts\  - proof frames, evidence the rig ran" -ForegroundColor DarkGray
Write-Host "  rename_hw.ps1              - STILL NEEDED (rename not done yet)" -ForegroundColor DarkGray
Write-Host "  venv\                      - your environment (gitignored)" -ForegroundColor DarkGray
