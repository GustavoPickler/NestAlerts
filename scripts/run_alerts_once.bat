@echo off
:: Caminho absoluto para o diretório raiz do projeto
set ROOT_DIR=%~dp0..
cd /d "%ROOT_DIR%"

:: Ativa o ambiente virtual
call "%ROOT_DIR%\.venv\Scripts\activate"

:: Executa o script principal com caminho completo
py "%ROOT_DIR%\main.py"
exit
