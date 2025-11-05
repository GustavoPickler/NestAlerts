# -*- coding: utf-8 -*-
"""
Meeting Alerts — versão robusta com Google Cloud TTS
----------------------------------------------------
• Alerta de reuniões 5 minutos antes (±1min), com logs e cache.
• Fala natural via Google Cloud TTS (voz Neural2-C).
• Fallback automático para Nest Hub local, caso o TTS falhe.
• Servidor Flask embutido para servir os arquivos de áudio.
• Em modo DEBUG, busca todas as reuniões até 10h e fala apenas a primeira.
"""

import os, sys, json, time, socket, logging, traceback, threading
from datetime import datetime, timedelta
from dateutil import tz
from pathlib import Path
from flask import Flask, send_from_directory, abort

# --- Auto-activate local venv (if not already active) ---
import os, sys
if not os.environ.get("VIRTUAL_ENV"):
    venv_dir = os.path.join(os.path.dirname(__file__), ".venv")
    activate_this = os.path.join(venv_dir, "Scripts", "activate_this.py" if os.name == "nt" else "bin/activate_this.py")
    if os.path.exists(activate_this):
        with open(activate_this) as f:
            code = compile(f.read(), activate_this, 'exec')
            exec(code, dict(__file__=activate_this))
        print("[INFO] Virtualenv ativado automaticamente.")
    else:
        print("[INFO] Virtualenv não encontrada. Execute 'setup_venv.bat' ou 'setup_venv.sh' primeiro.")
        sys.exit(1)

# ---- Configuração de debug -----------------------------------------------
try:
    from debug_config import (
        DEBUG_MODE,
        RESET_CACHE_ON_START,
        REPEAT_ALERTS,
        SHOW_LOGS_IN_CONSOLE,
        SHOW_EVENT_DELTA,
    )
except Exception:
    DEBUG_MODE = False
    RESET_CACHE_ON_START = False
    REPEAT_ALERTS = False
    SHOW_LOGS_IN_CONSOLE = False
    SHOW_EVENT_DELTA = False

# ---- .env opcional --------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ---- Caminhos base --------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
TTS_DIR = os.path.join(BASE_DIR, "tts")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(TTS_DIR, exist_ok=True)
CACHE_FILE = os.path.join(BASE_DIR, "alerts_seen.json")

# ---- Configurações padrão -------------------------------------------------
TZ_NAME = os.getenv("TZ", "America/Sao_Paulo")
CALENDAR_ID = os.getenv("CALENDAR_ID", "primary")
LEAD_MINUTES = int(os.getenv("LEAD_MINUTES", 5))
WINDOW_MINUTES = int(os.getenv("WINDOW_MINUTES", 10))
EXCLUDE_KEYWORDS = [k.strip().lower() for k in os.getenv(
    "EXCLUDE_KEYWORDS", "almoço,almoco,lunch").split(",") if k.strip()]

NEST_IP = os.getenv("NEST_IP", "192.168.15.172")
NEST_PORT = int(os.getenv("NEST_PORT", "8009"))
LOCAL_IP = os.getenv("LOCAL_IP", "192.168.15.6")
LOCAL_PORT = int(os.getenv("LOCAL_PORT", "8001"))
GOOGLE_TTS_KEY = os.path.join(BASE_DIR, "google_tts_key.json")

# ---- Logging --------------------------------------------------------------
LOG_FILE = os.path.join(LOG_DIR, f"alerts_{datetime.now().strftime('%Y-%m-%d')}.log")
logger = logging.getLogger("NestAlerts")
logger.setLevel(logging.DEBUG)
fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
fh.setFormatter(fmt)
fh.setLevel(logging.DEBUG)
logger.addHandler(fh)

class ColorFormatter(logging.Formatter):
    COLORS = {
        "INFO": "\033[94m",
        "WARNING": "\033[93m",
        "ERROR": "\033[91m",
        "DEBUG": "\033[90m",
    }
    RESET = "\033[0m"
    def format(self, record):
        color = self.COLORS.get(record.levelname, "")
        return f"{color}{super().format(record)}{self.RESET}"

ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.INFO if SHOW_LOGS_IN_CONSOLE or DEBUG_MODE else logging.ERROR)
ch.setFormatter(ColorFormatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
logger.addHandler(ch)

def log_start_end(tag, start=True):
    bar = "─" * 60
    logger.info(f"{bar}\n{'▶ START' if start else '■ END'} {tag}\n{bar}")

# ---- Servidor Flask embutido ---------------------------------------------
app = Flask(__name__)
TTS_PATH = (Path(__file__).with_name("tts")).resolve()

@app.get("/tts/_ls")
def tts_list():
    items = sorted(p.name for p in TTS_PATH.glob("*.mp3"))
    logger.info(f"[HTTP] /tts/_ls => {len(items)} arquivos")
    return "\n".join(items) + ("\n" if items else ""), 200, {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "no-store",
    }

@app.get("/tts/<path:filename>")
def serve_tts(filename: str):
    try:
        resp = send_from_directory(
            directory=str(TTS_PATH),
            path=filename,
            mimetype="audio/mpeg",
            max_age=0
        )
        logger.info(f"[HTTP] 200 /tts → {(TTS_PATH / filename).resolve()}")
        return resp
    except Exception as e:
        logger.warning(f"[HTTP] 404 /tts → {(TTS_PATH / filename).resolve()} ({e})")
        abort(404)

@app.get("/healthz")
def healthz():
    return "ok", 200

def start_flask_server():
    def run():
        app.run(host="0.0.0.0", port=LOCAL_PORT, debug=False, use_reloader=False)
    t = threading.Thread(target=run, daemon=True)
    t.start()

    import requests
    base = f"http://127.0.0.1:{LOCAL_PORT}/healthz"
    for _ in range(50):
        try:
            r = requests.get(base, timeout=0.3, proxies={"http": None, "https": None})
            if r.status_code == 200:
                break
        except Exception:
            time.sleep(0.1)

    logger.info(f"[HTTP] Flask ON. TTS_PATH={TTS_PATH}")
    logger.info(f"[HTTP] Acesse: http://{LOCAL_IP}:{LOCAL_PORT}/tts/_ls")

# ---- Google Calendar Auth -------------------------------------------------
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
def get_calendar_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    token_path = os.path.join(BASE_DIR, "token.json")
    cred_path = os.path.join(BASE_DIR, "credentials.json")
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(cred_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return build("calendar", "v3", credentials=creds, cache_discovery=False)

# ---- Utilitários ----------------------------------------------------------
def tz_now(): return datetime.now(tz.gettz(TZ_NAME))

def load_seen():
    if not os.path.exists(CACHE_FILE): return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        today = tz_now().date().isoformat()
        return {k: v for k, v in data.items() if v.get("date") == today}
    except Exception:
        return {}

def save_seen(seen):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)

def mark_alerted(seen, key):
    seen[key] = {"date": tz_now().date().isoformat(), "time": tz_now().strftime("%H:%M:%S")}
    save_seen(seen)

def _tcp_open(ip, port, timeout=3):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex((ip, port)) == 0
    finally:
        s.close()

# ---- TTS via Google Cloud + Fallback -------------------------------------
def speak(text: str) -> None:
    try:
        from google.cloud import texttospeech
        import pychromecast, requests
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GOOGLE_TTS_KEY
        os.environ.setdefault("NO_PROXY", f"127.0.0.1,localhost,{LOCAL_IP}")
        os.environ.setdefault("no_proxy", f"127.0.0.1,localhost,{LOCAL_IP}")

        client = texttospeech.TextToSpeechClient()
        synthesis_input = texttospeech.SynthesisInput(text=text)
        voice = texttospeech.VoiceSelectionParams(
            language_code="pt-BR",
            name="pt-BR-Standard-B",
            ssml_gender=texttospeech.SsmlVoiceGender.MALE
        )
        audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
        response = client.synthesize_speech(
            input=synthesis_input, voice=voice, audio_config=audio_config
        )

        filename = f"speech_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp3"
        filepath = os.path.join(TTS_DIR, filename)
        with open(filepath, "wb") as out:
            out.write(response.audio_content)
            out.flush()
            os.fsync(out.fileno())

        logger.info(f"[TTS] Gravado: {filepath} ({os.path.getsize(filepath)} bytes)")

        url_public = f"http://{LOCAL_IP}:{LOCAL_PORT}/tts/{filename}"
        url_self   = f"http://127.0.0.1:{LOCAL_PORT}/tts/{filename}"

        try:
            r = requests.get(url_self, timeout=3, proxies={"http": None, "https": None})
            logger.info(f"[HTTP] Self-check ({r.status_code}): {url_self}")
        except Exception as e:
            logger.warning(f"[HTTP] Self-check falhou: {e}")

        if not _tcp_open(NEST_IP, NEST_PORT):
            logger.warning("Nest Hub inacessível.")
            _speak_fallback(text)
            return

        try:
            host_info = (NEST_IP, NEST_PORT, None, "Google Nest Hub", "Google Nest Hub")
            cast = pychromecast.get_chromecast_from_host(host_info)
            cast.wait()
            cast.media_controller.play_media(url_public, "audio/mp3")
            cast.media_controller.block_until_active(timeout=5)
            cast.media_controller.play()
            logger.info(f"🔈 Falando (Google TTS): {text}")
            time.sleep(5)
        except Exception as e:
            logger.warning(f"[Cast] Falhou tocar MP3 local ({e}). Usando fallback…")
            _speak_fallback(text)
    except Exception as e:
        logger.error(f"Erro no Google TTS: {e}")
        _speak_fallback(text)

def _speak_fallback(text: str):
    try:
        import pychromecast
        from urllib.parse import quote_plus
        if not _tcp_open(NEST_IP, NEST_PORT):
            logger.warning("Nest Hub inacessível (fallback).")
            return
        host_info = (NEST_IP, NEST_PORT, None, "Google Nest Hub", "Google Nest Hub")
        cast = pychromecast.get_chromecast_from_host(host_info)
        cast.wait()
        tts_url = f"https://translate.google.com/translate_tts?ie=UTF-8&q={quote_plus(text)}&tl=pt-BR&client=tw-ob"
        cast.media_controller.play_media(tts_url, "audio/mp3")
        cast.media_controller.block_until_active()
        cast.media_controller.play()
        logger.info(f"🔈 Falando (fallback): {text}")
        time.sleep(4)
    except Exception as e:
        logger.error(f"Erro no fallback speak(): {e}")

# ---- Execução principal ---------------------------------------------------
def run_once():
    start_flask_server()
    log_start_end("MeetingAlerts Run", start=True)
    try:
        hours_ahead = 12 if DEBUG_MODE else 2
        logger.info(f"Config: LEAD={LEAD_MINUTES}min TZ={TZ_NAME} RANGE={hours_ahead}h DEBUG={DEBUG_MODE}")

        service = get_calendar_service()
        seen = load_seen()
        if RESET_CACHE_ON_START and DEBUG_MODE:
            seen = {}
            logger.info("[DEBUG] Cache resetado – todos os alertas serão repetidos.")

        # Busca eventos futuros
        events = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=tz_now().isoformat(),
            timeMax=(tz_now() + timedelta(hours=hours_ahead)).isoformat(),
            singleEvents=True,
            orderBy="startTime"
        ).execute().get("items", [])
        logger.info(f"Eventos obtidos: {len(events)}")

        for e in events:
            if e.get("status") == "cancelled":
                continue

            start_str = e["start"].get("dateTime")
            if not start_str:
                continue

            start = datetime.fromisoformat(start_str).astimezone(tz.gettz(TZ_NAME))
            summary = e.get("summary", "(sem título)")
            delta_min = (start - tz_now()).total_seconds() / 60

           # 🧪 DEBUG: usa a mesma frase do modo normal, mas ignora a janela de tempo
            if DEBUG_MODE:
                delta_min_rounded = int(round((start - tz_now()).total_seconds() / 60))
                if delta_min_rounded < 1:
                    lead_str = "menos de um minuto"
                elif delta_min_rounded == 1:
                    lead_str = "1 minuto"
                else:
                    lead_str = f"{delta_min_rounded} minutos"

                hora = start.strftime('%H:%M')
                agora = tz_now().strftime('%H:%M')

                frase_base = os.getenv(
                    "ALERT_PHRASE",
                    "Agora são {agora}. Gustavo, sua próxima reunião '{summary}' começa às {hora}, em {lead}."
                )
                msg = frase_base.format(summary=summary, hora=hora, lead=lead_str, agora=agora)

                logger.info(f"[DEBUG] {msg} (delta={delta_min_rounded} min)")
                speak(msg)
                break

            # 🔔 Normal: alerta se estiver dentro da janela configurada
            if 0 <= delta_min <= LEAD_MINUTES:
                if not REPEAT_ALERTS and summary in seen:
                    continue

                # Converte minutos para frase natural
                delta_min_rounded = int(round(delta_min))
                if delta_min < 1:
                    lead_str = "menos de um minuto"
                elif delta_min_rounded == 1:
                    lead_str = "1 minuto"
                else:
                    lead_str = f"{delta_min_rounded} minutos"

                hora = start.strftime('%H:%M')
                agora = tz_now().strftime('%H:%M')
                frase_base = os.getenv(
                    "ALERT_PHRASE",
                    "Agora são {agora}. Gustavo, sua próxima reunião '{summary}' começa às {hora}, em {lead}."
                )
                msg = frase_base.format(summary=summary, hora=hora, lead=lead_str, agora=agora)

                logger.info(f"[Aviso emitido] {msg} (delta={delta_min:.1f} min)")
                speak(msg)
                mark_alerted(seen, summary)
                break

    except Exception as e:
        logger.error(f"Erro geral: {e}")
        logger.debug(traceback.format_exc())
    finally:
        log_start_end("MeetingAlerts Run", start=False)

if __name__ == "__main__":
    run_once()