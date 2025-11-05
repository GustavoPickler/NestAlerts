# 📢 NestAlerts — Alertas de Reunião por Voz (Google Calendar → Google Nest Hub)

**NestAlerts** anuncia suas reuniões do **Google Calendar** em voz alta no **Google Nest Hub** usando **Google Cloud Text-to-Speech**. 
Um **servidor Flask** embutido serve os arquivos MP3 para a rede local.

---

## ✨ Recursos

- 🔔 Alerta automático antes do horário da reunião (janela e antecedência configuráveis).
- 🗣️ Voz natural em pt-BR (Google Cloud TTS).
- 🔄 **Fallback**: usa `translate_tts` se o TTS oficial falhar.
- 🌐 Servidor HTTP (Flask) interno que hospeda os MP3 na sua LAN.
- 🧪 Modo DEBUG com logs detalhados e repetição de alertas.
- 🧹 Limpeza automática da pasta `tts/`.
- 🛟 Setup 100% automatizado com **venv** (Windows `.bat`, Linux/macOS `.sh`).

---

## 🧱 Estrutura do Projeto

NestAlerts/
├── meeting_alerts.py        # Script principal
├── requirements.txt          # Dependências do Python
├── setup_venv.bat            # Cria/Configura o venv (Windows)
├── setup_venv.sh             # Cria/Configura o venv (Linux/macOS)
├── run_alerts.bat            # Ativa o venv e executa o script (Windows)
├── .env                      # Variáveis de ambiente (NÃO commit)
├── credentials.json          # OAuth do Google Calendar (NÃO commit)
├── google_tts_key.json       # Service Account do Cloud TTS (NÃO commit)
├── token.json / token.pickle # Token OAuth gerado (NÃO commit)
├── logs/                     # Logs diários
├── tts/                      # MP3 gerados (e assets opcionais, ex: background.jpg)

> Arquivos “NÃO commit” já devem estar no `.gitignore` do repositório.

---

## 🔐 Pré-requisitos

1. **Python 3.10+** (recomendado 3.13).  
   - Windows: `py --version`  
   - Linux/macOS: `python3 --version`
2. Estar na **mesma rede** do seu **Google Nest Hub** (Wi-Fi/LAN).
3. **APIs e credenciais:**
   - **Google Calendar API**  
     - No Google Cloud Console, crie um **OAuth Client** do tipo **Desktop** e baixe `credentials.json`.
   - **Cloud Text-to-Speech API**  
     - Crie uma **Service Account**, gere uma **key em JSON** e salve como `google_tts_key.json`.

Copie `credentials.json` e `google_tts_key.json` para a **raiz do projeto**.

---

## ⚙️ Configuração (.env)

Crie o arquivo **`.env`** na raiz com as variáveis:

```ini
TZ=America/Sao_Paulo

# Google Nest Hub
NEST_IP=192.168.15.172
NEST_PORT=8009

# Servidor Flask interno (IP da sua máquina na LAN)
LOCAL_IP=192.168.15.6
LOCAL_PORT=8001

# Janela/Antecedência
LEAD_MINUTES=5
WINDOW_MINUTES=10

# Calendar
CALENDAR_ID=primary

# Ignore eventos que contenham estas palavras (minúsculas, separado por vírgula)
EXCLUDE_KEYWORDS=almoço,almoco,lunch
Dica: confirme seu IP local com ipconfig (Windows) ou ip addr (Linux/macOS).

🚀 Instalação
Windows
bat
Copiar código
setup_venv.bat
O script:

cria .venv

instala requirements

exibe o comando de execução

Linux/macOS
bash
Copiar código
chmod +x setup_venv.sh
./setup_venv.sh
▶️ Execução
Rápido (Windows)
bat
Copiar código
run_alerts.bat
Manual
bash
Copiar código
# Windows
.\.venv\Scripts\activate
python meeting_alerts.py

# Linux/macOS
source .venv/bin/activate
python meeting_alerts.py
Na primeira execução, será aberta uma janela do Google pedindo permissão para acessar o Calendar.
Um token.json/token.pickle será salvo e reutilizado nas próximas execuções.

🔧 Personalização rápida
Voz do TTS: altere name="pt-BR-Standard-B" em meeting_alerts.py (pode usar vozes Neural2).

Filtro de eventos: edite EXCLUDE_KEYWORDS no .env.

Janela/antecedência: ajuste WINDOW_MINUTES / LEAD_MINUTES no .env.

Logs: arquivos diários em logs/.

🧪 Modo DEBUG (opcional)
Crie debug_config.py (na raiz):

python
Copiar código
DEBUG_MODE = True
RESET_CACHE_ON_START = True
REPEAT_ALERTS = True
SHOW_LOGS_IN_CONSOLE = True
SHOW_EVENT_DELTA = True
Com DEBUG_MODE=True, o script busca mais eventos e pode repetir alertas para teste.

🩺 Troubleshooting
1) “python não é reconhecido” (Windows)
Use py ou execute via run_alerts.bat (ele ativa a venv automaticamente).

2) Erro de dependência (No matching distribution)
Use o requirements.txt deste repo. Ele é compatível com Python 3.13:

google-cloud-texttospeech >= 2.33.0

pychromecast >= 14.0.9

3) Nest não toca / não encontra dispositivo

Confira NEST_IP e NEST_PORT.

Desative VPN / ajuste firewall (mDNS/SSDP podem ser bloqueados).

Verifique se PC e Nest estão na mesma rede (sem isolamento de clientes).

4) Servidor Flask retorna 404 para o MP3

Verifique se o MP3 existe em tts/.

Acesse http://LOCAL_IP:LOCAL_PORT/tts/_ls para listar arquivos.

Teste o MP3 direto: http://LOCAL_IP:LOCAL_PORT/tts/<arquivo>.mp3.

5) Problema de permissão no Calendar

Delete token.json/token.pickle e rode novamente para refazer o OAuth.

Confirme que credentials.json é do tipo Desktop App.

📦 Dependências
Flask

python-dotenv

python-dateutil

google-api-python-client

google-auth / google-auth-oauthlib

google-cloud-texttospeech

pychromecast

Instaladas automaticamente pelos scripts de setup.

🔒 Segurança
NÃO comitar: .env, credentials.json, google_tts_key.json, token.*, logs/, tts/.

O .gitignore do projeto deve proteger esses arquivos.

📝 Licença
MIT © 2025 — Gustavo Pickler