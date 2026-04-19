' LAUNCH-04: fully silent launch (no cmd, no PowerShell window) via WScript.Shell.Run windowStyle 0.
Set WshShell = CreateObject("WScript.Shell")

repo = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)

' Quote pythonw path so spaces in repo path are safe: "repo\.venv-win\Scripts\pythonw.exe" -m streamlit ...
command = """" & repo & "\.venv-win\Scripts\pythonw.exe" & """" & " -m streamlit run app\ui.py --server.port 8501"

WshShell.CurrentDirectory = repo
WshShell.Run command, 0, False
