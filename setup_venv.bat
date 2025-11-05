@echo off
echo [INFO] Criando e ativando venv...
py -m venv .venv
call .venv\Scripts\activate

echo [INFO] Instalando dependências...
call .venv\Scripts\python.exe -m pip install --upgrade pip
pip install -r requirements.txt

echo [INFO] Ambiente pronto!
echo Para executar: 
echo    .venv\Scripts\activate
echo    py meeting_alerts.py
pause
