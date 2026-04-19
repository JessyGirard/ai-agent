$repo = Split-Path -Parent $MyInvocation.MyCommand.Path

Start-Process "$repo\.venv-win\Scripts\pythonw.exe" `
    -ArgumentList "-m streamlit run app\ui.py --server.port 8501" `
    -WorkingDirectory $repo `
    -WindowStyle Hidden
