#Requires -Version 5.1
<#
.SYNOPSIS
  Start the Streamlit UI without a persistent console window (Windows).

.DESCRIPTION
  UI-08: Starts Streamlit with **pythonw.exe** when present (GUI subsystem — no console
  allocation for the Python process). Falls back to **python.exe** + CreateNoWindow if
  pythonw is missing.

  **Demo taskbar shortcuts** from Create-Agent-UI-Shortcut.ps1 target pythonw **directly**
  (no PowerShell in the chain) so Windows should not show a console/terminal thumbnail.

  For a visible console (logs, Ctrl+C), use Launch-Agent-UI.cmd instead.

  Optional: bookmark the app URL with ?ui_surface=Agent (or API, Prompt, Regression, Terminal)
  so the browser always opens on that surface after load.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File .\Launch-Agent-UI-Silent.ps1
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = $PSScriptRoot
$PythonwExe = Join-Path -Path $RepoRoot -ChildPath '.venv-win\Scripts\pythonw.exe'
$PythonExe = Join-Path -Path $RepoRoot -ChildPath '.venv-win\Scripts\python.exe'
$PythonLaunch = if (Test-Path -LiteralPath $PythonwExe) { $PythonwExe } else { $PythonExe }
$UiPath = Join-Path -Path $RepoRoot -ChildPath 'app\ui.py'

if (-not (Test-Path -LiteralPath $PythonExe)) {
    Add-Type -AssemblyName System.Windows.Forms
    [void][System.Windows.Forms.MessageBox]::Show(
        "Missing .venv-win\Scripts\python.exe`n`nCreate the venv at the repo root or run Open-DevShell.cmd first.",
        'ai-agent — Launch UI',
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    )
    exit 1
}

if (-not (Test-Path -LiteralPath $UiPath)) {
    Add-Type -AssemblyName System.Windows.Forms
    [void][System.Windows.Forms.MessageBox]::Show(
        "Missing app\ui.py under:`n$RepoRoot",
        'ai-agent — Launch UI',
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    )
    exit 1
}

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $PythonLaunch
$psi.Arguments = '-m streamlit run "' + $UiPath + '"'
$psi.WorkingDirectory = $RepoRoot
$psi.UseShellExecute = $false
# pythonw: no console; python.exe fallback: hide child window
$psi.CreateNoWindow = $true
$null = [System.Diagnostics.Process]::Start($psi)
