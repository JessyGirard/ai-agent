# One-time: adds a global function "op" so you can type just:  op
# Run from repo root (path with spaces is OK):
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\Register-Op.ps1

$ErrorActionPreference = 'Stop'
$repo = $PSScriptRoot
$opScript = Join-Path $repo 'op.ps1'
if (-not (Test-Path -LiteralPath $opScript)) {
    throw "Missing $opScript"
}

$escaped = $opScript.Replace("'", "''")
$marker = '# --- ai-agent: global op ---'
$block = @"
$marker
function global:op {
    . '$escaped'
}
"@

$prof = $PROFILE
$dir = Split-Path -Parent $prof
if (-not (Test-Path -LiteralPath $dir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
}
if (-not (Test-Path -LiteralPath $prof)) {
    New-Item -ItemType File -Path $prof -Force | Out-Null
}

$existing = Get-Content -LiteralPath $prof -Raw -ErrorAction SilentlyContinue
if ($existing -and $existing.Contains($marker)) {
    Write-Host "Already registered (marker found in profile). Nothing to do."
    Write-Host "Profile: $prof"
    exit 0
}

Add-Content -LiteralPath $prof -Value "`n$block`n"
Write-Host "Registered global function 'op' -> $opScript"
Write-Host "Profile updated: $prof"
Write-Host "Open a new PowerShell window, or run:  . `$PROFILE"
