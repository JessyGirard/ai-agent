import os
import subprocess

repo = os.path.dirname(os.path.abspath(__file__))

cmd = [
    os.path.join(repo, ".venv-win", "Scripts", "pythonw.exe"),
    "-m",
    "streamlit",
    "run",
    "app/ui.py",
    "--server.port",
    "8501"
]

subprocess.Popen(
    cmd,
    cwd=repo,
    creationflags=subprocess.CREATE_NO_WINDOW
)
