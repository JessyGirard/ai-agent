#Requires -Version 5.1
<#
.SYNOPSIS
  Creates Windows shortcuts to Launch-Agent-UI.cmd (same venv path as the repo).

.DESCRIPTION
  Writes .lnk files that target cmd.exe with /c so "Start in" and quoting stay correct
  even when the repo path contains spaces. Use these shortcuts for "Pin to taskbar".

.PARAMETER Place
  Where to write shortcuts: StartMenu (Programs\ai-agent), Desktop, or Both (default).

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\Create-Agent-UI-Shortcut.ps1

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\Create-Agent-UI-Shortcut.ps1 -Place StartMenu
#>
param(
    [ValidateSet('StartMenu', 'Desktop', 'Both')]
    [string]$Place = 'Both'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = $PSScriptRoot
$Launcher = Join-Path -Path $RepoRoot -ChildPath 'Launch-Agent-UI.cmd'
if (-not (Test-Path -LiteralPath $Launcher)) {
    throw "Expected launcher at: $Launcher"
}

$ShortcutFileName = 'Mimi AI Agent UI.lnk'
$Wsh = New-Object -ComObject WScript.Shell

$destinations = @()
if ($Place -in @('StartMenu', 'Both')) {
    $startMenuDir = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\ai-agent'
    $destinations += (Join-Path $startMenuDir $ShortcutFileName)
}
if ($Place -in @('Desktop', 'Both')) {
    $desktop = [Environment]::GetFolderPath('Desktop')
    $destinations += (Join-Path $desktop $ShortcutFileName)
}

foreach ($dest in $destinations) {
    $parent = [System.IO.Path]::GetDirectoryName($dest)
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }

    $shortcut = $Wsh.CreateShortcut($dest)
    $shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\cmd.exe'
    $shortcut.Arguments = '/c "' + $Launcher + '"'
    $shortcut.WorkingDirectory = $RepoRoot
    $shortcut.WindowStyle = 1
    $shortcut.Description = 'ai-agent Streamlit UI (Launch-Agent-UI.cmd)'

    $venvPython = Join-Path -Path $RepoRoot -ChildPath '.venv-win\Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPython) {
        $shortcut.IconLocation = "$venvPython,0"
    }
    else {
        $shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,176"
    }

    $shortcut.Save()
    Write-Host "Created: $dest"
}

Write-Host ""
Write-Host "Next: right-click the shortcut -> Pin to taskbar (Windows pins shortcuts, not raw .cmd files)."
