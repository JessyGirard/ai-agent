param()



$ErrorActionPreference = "Stop"



$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path



# LAUNCH-08: Desktop/taskbar shortcut opens ONLY Google Chrome in app mode.

# TargetPath = chrome.exe | Arguments = --app=http://localhost:8501

# Do NOT point this .lnk at any .cmd / .bat / .vbs / python (no black console from the shortcut).

# Start the server separately when needed: Start-Agent-Server.cmd (or Launch-Agent-UI-App.bat / launch_ui.py, etc.).

$ChromeCandidates = @(

    "C:\Program Files\Google\Chrome\Application\chrome.exe",

    (Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe")

)

$ChromeExe = $null

foreach ($c in $ChromeCandidates) {

    if ($c -and (Test-Path -LiteralPath $c)) {

        $ChromeExe = $c

        break

    }

}

if (-not $ChromeExe) {

    throw "Google Chrome not found at default paths. Install Chrome or edit ChromeCandidates in Create-Agent-UI-Shortcut.ps1 (LAUNCH-08)."

}



$ShortcutName = "Mimi AI Agent UI.lnk"

$Description = "ai-agent UI — Chrome app window http://localhost:8501 (LAUNCH-08; start Streamlit separately)"

$IconLocation = "$ChromeExe,0"

$AppArgs = "--app=http://localhost:8501"



$WshShell = New-Object -ComObject WScript.Shell



$Targets = @(

    (Join-Path ([Environment]::GetFolderPath("Desktop")) $ShortcutName),

    (Join-Path ([Environment]::GetFolderPath("Programs")) $ShortcutName)

)



foreach ($ShortcutPath in $Targets) {

    $ShortcutFolder = Split-Path -Parent $ShortcutPath

    if (-not (Test-Path -LiteralPath $ShortcutFolder)) {

        New-Item -ItemType Directory -Path $ShortcutFolder -Force | Out-Null

    }



    $Shortcut = $WshShell.CreateShortcut($ShortcutPath)

    $Shortcut.TargetPath = $ChromeExe

    $Shortcut.Arguments = $AppArgs

    $Shortcut.WorkingDirectory = $RepoRoot

    $Shortcut.Description = $Description

    $Shortcut.IconLocation = $IconLocation

    $Shortcut.Save()

}



Write-Host ""

Write-Host "Created shortcuts (LAUNCH-08: Chrome --app only, no server from .lnk):"

foreach ($ShortcutPath in $Targets) {

    Write-Host " - $ShortcutPath"

}

Write-Host ""

Write-Host "Target: $ChromeExe"

Write-Host "Arguments: $AppArgs"

Write-Host "Start in: $RepoRoot"

Write-Host ""

Write-Host "Start Streamlit on port 8501 first, e.g. double-click Start-Agent-Server.cmd (visible console) or Launch-Agent-UI-App.bat (silent)."

Write-Host "Next: re-run after pulls; unpin old .lnk then pin new one to taskbar if needed."

