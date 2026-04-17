@echo off
REM One-click Streamlit UI — same venv convention as Open-DevShell.cmd (.\.venv-win)
REM Double-click from Explorer, or run from repo root:  Launch-Agent-UI
set "REPO=%~dp0"
cd /d "%REPO%"

if not exist ".venv-win\Scripts\python.exe" (
  echo.
  echo [Launch-Agent-UI] Missing ".venv-win\Scripts\python.exe"
  echo Create the venv at "%REPO%.venv-win" or use Open-DevShell.cmd then:  python -m streamlit run app\ui.py
  echo.
  pause
  exit /b 1
)

title ai-agent Streamlit UI
echo.
echo Starting Streamlit  (repo: %REPO%)
echo Browser should open to the app. Stop with Ctrl+C in this window.
echo.

".venv-win\Scripts\python.exe" -m streamlit run "%REPO%app\ui.py"
set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" (
  echo.
  echo Streamlit exited with code %EXITCODE%.
  pause
)
