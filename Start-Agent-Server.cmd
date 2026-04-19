@echo off

REM LAUNCH-08: manual Streamlit backend only (fixed port 8501). UI shortcut opens Chrome separately.

REM Resolve repo directory from this script location
set "REPO=%~dp0"

cd /d "%REPO%"

echo Starting Streamlit UI on port 8501...
echo.

.venv-win\Scripts\python.exe -m streamlit run app\ui.py --server.port 8501

pause
