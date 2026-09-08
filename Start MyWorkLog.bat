@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo MyWorkLog is not installed yet.
    echo Run the installation commands in README.md first.
    pause
    exit /b 1
)

start "MyWorkLog" ".venv\Scripts\pythonw.exe" "%~dp0main.py"

