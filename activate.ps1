# Dot-source this script to activate the project's venv in any
# PowerShell session. One-time per terminal:
#
#   . .\activate.ps1
#
# Equivalent to:  . .\venv\Scripts\Activate.ps1
# but auto-detects whether the repo has venv\ or .venv\ on disk, and
# warns clearly if neither exists. On a fresh Windows box you may
# need to allow script execution once:
#
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned

if (Test-Path "venv\Scripts\Activate.ps1") {
    . .\venv\Scripts\Activate.ps1
    $pyver = (python --version) -replace '^Python\s*'
    Write-Host "[ok] venv activated  (Python $pyver)" -ForegroundColor Green
}
elseif (Test-Path ".venv\Scripts\Activate.ps1") {
    . .\.venv\Scripts\Activate.ps1
    $pyver = (python --version) -replace '^Python\s*'
    Write-Host "[ok] .venv activated  (Python $pyver)" -ForegroundColor Green
}
else {
    Write-Host "[X] No venv\ or .venv\ found in $(Get-Location)." -ForegroundColor Red
    Write-Host "  Create one:  py -3.12 -m venv venv ; .\venv\Scripts\Activate.ps1 ; pip install -e ."
}
