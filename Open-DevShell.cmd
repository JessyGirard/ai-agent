@echo off
REM Bypass + venv — logic lives in op.ps1
REM
REM   PowerShell (needs .\ because cwd is not on PATH):
REM       .\op          .\op.cmd    .\Open-DevShell.cmd
REM   Bare "op" in any folder (after one-time setup):
REM       powershell -NoProfile -ExecutionPolicy Bypass -File .\Register-Op.ps1
REM       then new window, or:  . $PROFILE
REM
REM   cmd.exe (cwd = repo):  op    Open-DevShell
REM   Explorer: double-click op.cmd or Open-DevShell.cmd

set "REPO=%~dp0"
cd /d "%REPO%"

if not exist ".venv-win\Scripts\Activate.ps1" (
  echo.
  echo [Open-DevShell] Missing ".venv-win\Scripts\Activate.ps1"
  echo Create the venv at "%REPO%.venv-win" or edit this script to match your path.
  echo.
  pause
  exit /b 1
)

title ai-agent dev shell
powershell.exe -NoProfile -ExecutionPolicy Bypass -NoExit -File "%REPO%op.ps1"
