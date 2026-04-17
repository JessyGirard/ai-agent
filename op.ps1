# Repo-local venv + process-scope Bypass. Used by Open-DevShell.cmd and (optionally) profile function "op".
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force | Out-Null
$activate = Join-Path $PSScriptRoot '.venv-win\Scripts\Activate.ps1'
if (-not (Test-Path -LiteralPath $activate)) {
    Write-Host "[op] Missing: $activate" -ForegroundColor Red
    exit 1
}
. $activate
