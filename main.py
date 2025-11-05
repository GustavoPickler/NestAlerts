# -*- coding: utf-8 -*-
"""
Meeting Alerts — Google Calendar + Google Cloud TTS
---------------------------------------------------
• Alerta de reuniões 5 minutos antes (com tolerância de ±1min).
• Fala natural via Google Cloud TTS (com fallback via Google Translate TTS).
• Servidor Flask interno para servir os MP3 gerados.
• Modo DEBUG amplia o range de busca (12h à frente) e fala o 1º evento.
"""

import os
import sys
import json
import time
import math
import socket
import logging
import traceback
import threading
from datetime import datetime, timedelta
from pathlib import Path

from dateutil import tz
from flask import Flask, send_from_directory, abort

# =============================================================================
# Estrutura de pastas e arquivos
# =============================================================================
ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
LOG_DIR = ROOT_DIR / "logs"
TTS_DIR = ROOT_DIR / "tts"

CREDENTIALS_FILE = DATA_DIR / "credentials.json"
TOKEN_FILE = DATA_DIR / "token.json"
CACHE_FILE = DATA_DIR / "alerts_seen.json"
GOOGLE_TTS_KEY = DATA_DIR / "google_tts_key.json"

for p in (DATA_DIR, LOG_DIR, TTS_DIR):
    p.mkdir(parents=True, exist_ok=True)

# =============================================================================
# Auto-ativar venv local (se não ativo)
# =============================================================================
if not os.environ.get("VIRTUAL_ENV"):
    venv_dir = ROOT_DIR / ".venv"
    activate_this = venv_dir / ("Scripts/activate_this.py" if os.name == "nt" else "bin/activate_this.py")
    if activate_this.exists():
        exec(compile(activate_this.read_text(encoding="utf-8"), str(activate_this), "exec"),
             dict(__file__=str(activate_this)))
        print("[INFO] Virtualenv ativado automaticamente.")
    else:
        print("[INFO] Virtualenv não encontrada. Execute 'setup_venv.bat' ou 'setup_venv.sh' primeiro.")
        sys.exit(1)

# =============================================================================
# Flags de debug (opcionais)
# =============================================================================
try:
    from debug_config import (
        DEBUG_MODE,
        RESET_CACHE_ON_START,
        REPEAT_ALERTS,
        SHOW_LOGS_IN_CONSOLE,
    )
except Exception:
    DEBUG_MODE = False
    RESET_CACHE_ON_START = False
    REPEAT_ALERTS = False
    SHOW_LOGS_IN_CONSOLE = False

# =============================================================================
# .env (opcional)
# =============================================================================
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT_DIR / ".env")
except Exception:
    pass

# =============================================================================
# Config
# =============================================================================
TZ_NAME = os.getenv("TZ", "America/Sao_Paulo")
CALENDAR_ID = os.getenv("CALENDAR_ID", "primary")
LEAD_MINUTES = int(os.getenv("LEAD_MINUTES", 5))
EXCLUDE_KEYWORDS = [k.strip().lower() for k in os.getenv(
    "EXCLUDE_KEYWORDS", "almoço,almoco,lunch"
).split(",") if k.strip()]

LOCAL_IP = os.getenv("LOCAL_IP", "127.0.0.1")
LOCAL_PORT = int(os.getenv("LOCAL_PORT", "8001"))
NEST_IP = os.getenv("NEST_IP", "192.168.15.172")
NEST_PORT = int(os.getenv("NEST_PORT", "8009"))

ALERT_PHRASE = os.getenv(
    "ALERT_PHRASE",
    'Gustavo, você tem uma reunião "{summary}" às {hora}, em {lead}.'
)

# =============================================================================
# Logging
# =============================================================================
LOG_FILE = LOG_DIR / f"alerts_{datetime.now().strftime('%Y-%m-%d')}.log"
logger = logging.getLogger("NestAlerts")
logger.setLevel(logging.DEBUG)

fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
fh.setFormatter(fmt)
fh.setLevel(logging.DEBUG)
logger.addHandler(fh)

class ColorFormatter(logging.Formatter):
    COLORS = {"INFO": "\033[94m", "WARNING": "\033[93m", "ERROR": "\033[91m", "DEBUG": "\033[90m"}
    RESET = "\033[0m"
    def format(self, record):
        color = self.COLORS.get(record.levelname, "")
        return f"{color}{super().format(record)}{self.RESET}"

ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.INFO if (SHOW_LOGS_IN_CONSOLE or DEBUG_MODE) else logging.ERROR)
ch.setFormatter(ColorFormatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
logger.addHandler(ch)

def log_start_end(tag: str, start: bool = True) -> None:
    bar = "─" * 60
    logger.info(f"{bar}\n{'▶ START' if start else '■ END'} {tag}\n{bar}")

# =============================================================================
# Flask (serve MP3)
# =============================================================================
app = Flask(__name__)

@app.get("/tts/_ls")
def tts_list():
    items = sorted(p.name for p in TTS_DIR.glob("*.mp3"))
    logger.info(f"[HTTP] /tts/_ls => {len(items)} arquivos")
    return "\n".join(items) + ("\n" if items else ""), 200, {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "no-store",
    }

@app.get("/tts/<path:filename>")
def serve_tts(filename: str):
    try:
        resp = send_from_directory(directory=str(TTS_DIR), path=filename, mimetype="audio/mpeg", max_age=0)
        logger.info(f"[HTTP] 200 /tts → {(TTS_DIR / filename).resolve()}")
        return resp
    except Exception as e:
        logger.warning(f"[HTTP] 404 /tts → {(TTS_DIR / filename).resolve()} ({e})")
        abort(404)

@app.get("/healthz")
def healthz():
    return "ok", 200

def start_flask_server():
    def run():
        app.run(host="0.0.0.0", port=LOCAL_PORT, debug=False, use_reloader=False)
    threading.Thread(target=run, daemon=True).start()

    # espera subir
    import requests
    url = f"http://127.0.0.1:{LOCAL_PORT}/healthz"
    for _ in range(50):
        try:
            r = requests.get(url, timeout=0.3, proxies={"http": None, "https": None})
            if r.status_code == 200:
                break
        except Exception:
            time.sleep(0.1)
    logger.info(f"[HTTP] Flask ON. TTS_DIR={TTS_DIR}")
    logger.info(f"[HTTP] Acesse: http://{LOCAL_IP}:{LOCAL_PORT}/tts/_ls")

# =============================================================================
# Google Calendar
# =============================================================================
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

def get_calendar_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")

    return build("calendar", "v3", credentials=creds, cache_discovery=False)

# =============================================================================
# Utilitários
# =============================================================================
def tz_now() -> datetime:
    return datetime.now(tz.gettz(TZ_NAME))

def load_seen() -> dict:
    if not CACHE_FILE.exists():
        return {}
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        today = tz_now().date().isoformat()
        return {k: v for k, v in data.items() if v.get("date") == today}
    except Exception:
        return {}

def save_seen(seen: dict) -> None:
    CACHE_FILE.write_text(json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8")

def mark_alerted(seen: dict, key: str) -> None:
    seen[key] = {"date": tz_now().date().isoformat(), "time": tz_now().strftime("%H:%M:%S")}
    save_seen(seen)

def _tcp_open(ip: str, port: int, timeout: float = 3) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex((ip, port)) == 0
    finally:
        s.close()

# =============================================================================
# TTS (Google Cloud) + Fallback
# =============================================================================
def speak(text: str) -> None:
    try:
        from google.cloud import texttospeech
        import pychromecast, requests

        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(GOOGLE_TTS_KEY)
        os.environ.setdefault("NO_PROXY", f"127.0.0.1,localhost,{LOCAL_IP}")
        os.environ.setdefault("no_proxy", f"127.0.0.1,localhost,{LOCAL_IP}")

        client = texttospeech.TextToSpeechClient()
        synthesis_input = texttospeech.SynthesisInput(text=text)
        voice = texttospeech.VoiceSelectionParams(language_code="pt-BR", name="pt-BR-Standard-B")
        audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
        response = client.synthesize_speech(input=synthesis_input, voice=voice, audio_config=audio_config)

        filename = f"speech_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp3"
        filepath = TTS_DIR / filename
        filepath.write_bytes(response.audio_content)

        logger.info(f"[TTS] Gravado: {filepath} ({filepath.stat().st_size} bytes)")

        url_public = f"http://{LOCAL_IP}:{LOCAL_PORT}/tts/{filename}"
        url_self   = f"http://127.0.0.1:{LOCAL_PORT}/tts/{filename}"

        try:
            import requests
            r = requests.get(url_self, timeout=3, proxies={"http": None, "https": None})
            logger.info(f"[HTTP] Self-check ({r.status_code}): {url_self}")
        except Exception as e:
            logger.warning(f"[HTTP] Self-check falhou: {e}")

        if not _tcp_open(NEST_IP, NEST_PORT):
            logger.warning("Nest Hub inacessível.")
            _speak_fallback(text); return

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

def _speak_fallback(text: str) -> None:
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

# =============================================================================
# Helpers de frase
# =============================================================================
def _humanize_timedelta(seconds: float) -> str:
    """Converte delta em segundos numa frase (pt-BR), arredondando para cima."""
    secs = max(0, int(math.ceil(seconds)))
    mins = math.ceil(secs / 60)

    if mins < 1:
        return "menos de um minuto"
    if mins == 1:
        return "1 minuto"
    if mins < 60:
        return f"{mins} minutos"

    horas, resto = divmod(mins, 60)
    if resto == 0:
        return f"{horas} {'hora' if horas == 1 else 'horas'}"
    if horas == 1:
        return f"1 hora e {resto} {'minuto' if resto == 1 else 'minutos'}"
    return f"{horas} horas e {resto} {'minuto' if resto == 1 else 'minutos'}"

def _build_alert_message(summary: str, start_dt: datetime) -> str:
    agora_dt = tz_now()
    lead_str = _humanize_timedelta((start_dt - agora_dt).total_seconds())
    return ALERT_PHRASE.format(
        summary=summary,
        hora=start_dt.strftime("%H:%M"),
        lead=lead_str,
        agora=agora_dt.strftime("%H:%M"),
    )

# =============================================================================
# Execução principal (uma passada)
# =============================================================================
def run_once():
    start_flask_server()
    log_start_end("MeetingAlerts Run", start=True)

    try:
        hours_ahead = 12 if DEBUG_MODE else 2
        logger.info(f"Config: LEAD={LEAD_MINUTES}min TZ={TZ_NAME} RANGE={hours_ahead}h DEBUG={DEBUG_MODE}")

        service = get_calendar_service()

        # cache diário
        seen = load_seen()
        if RESET_CACHE_ON_START and DEBUG_MODE and CACHE_FILE.exists():
            CACHE_FILE.unlink(missing_ok=True)
            seen = {}
            logger.info("[DEBUG] Cache resetado.")

        # eventos
        events = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=tz_now().isoformat(),
            timeMax=(tz_now() + timedelta(hours=hours_ahead)).isoformat(),
            singleEvents=True,
            orderBy="startTime"
        ).execute().get("items", [])

        logger.info(f"Eventos obtidos: {len(events)}")
        evento_alertado = False

        for e in events:
            if e.get("status") == "cancelled":
                continue

            start_str = e.get("start", {}).get("dateTime")
            if not start_str:
                continue

            start = datetime.fromisoformat(start_str).astimezone(tz.gettz(TZ_NAME))
            summary = e.get("summary", "(sem título)")
            if any(k in summary.lower() for k in EXCLUDE_KEYWORDS):
                logger.info(f"[Ignorado por palavra-chave] '{summary}'")
                continue

            delta_sec = (start - tz_now()).total_seconds()
            logger.info(f"→ '{summary}' às {start.strftime('%H:%M')} (delta={delta_sec/60:.2f} min)")

            # DEBUG: fala o primeiro evento
            if DEBUG_MODE:
                msg = _build_alert_message(summary, start)
                logger.info(f"[DEBUG] {msg}")
                speak(msg)
                evento_alertado = True
                break

            # janela de aviso (LEAD ± 60s)
            lead_window = LEAD_MINUTES * 60
            tolerance = 60
            if -tolerance <= delta_sec <= (lead_window + tolerance):
                if not REPEAT_ALERTS and summary in seen:
                    logger.info(f"[Ignorado - já alertado hoje] '{summary}'")
                    continue
                msg = _build_alert_message(summary, start)
                logger.info(f"[Aviso emitido] {msg}")
                speak(msg)
                mark_alerted(seen, summary)
                evento_alertado = True
                break

        if not events:
            logger.info("Nenhum evento encontrado no intervalo configurado.")
        elif not evento_alertado:
            logger.info("Há eventos futuros, mas nenhum dentro da janela de aviso (≤ %d min).", LEAD_MINUTES)

    except Exception as e:
        logger.error(f"Erro geral: {e}")
        logger.debug(traceback.format_exc())
    finally:
        log_start_end("MeetingAlerts Run", start=False)

# =============================================================================
# Entrypoint
# =============================================================================
if __name__ == "__main__":
    run_once()