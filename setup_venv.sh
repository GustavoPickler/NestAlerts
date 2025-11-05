#!/bin/bash
echo "[INFO] Criando e ativando venv..."
python3 -m venv .venv
source .venv/bin/activate

echo "[INFO] Instalando dependências..."
pip install --upgrade pip
pip install -r requirements.txt

echo "[INFO] Ambiente pronto!"
echo "Para executar:"
echo "   source .venv/bin/activate"
echo "   python meeting_alerts.py"
