@echo off
cd /d "%~dp0"
start "" /min cmd /c "call .venv\Scripts\activate && python meeting_alerts.py"
exit