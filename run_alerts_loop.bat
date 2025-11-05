@echo off
cd /d "%~dp0"
call .venv\Scripts\activate

echo [INFO] Iniciando monitoramento de reuniões (loop contínuo)...
:loop
python meeting_alerts.py
timeout /t 300 >nul  & REM aguarda 5 minutos (300 segundos)
goto loop