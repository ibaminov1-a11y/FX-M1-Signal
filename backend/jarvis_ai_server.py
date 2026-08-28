import os
import json
import base64
import sqlite3
import tempfile
from pathlib import Path
from datetime import datetime, timezone

import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_BASE = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
AI_MODEL = os.environ.get("JARVIS_MODEL", "gpt-5.6-terra")
STT_MODEL = os.environ.get("JARVIS_STT_MODEL", "gpt-transcribe")
TTS_MODEL = os.environ.get("JARVIS_TTS_MODEL", "gpt-4o-mini-tts")
TTS_VOICE = os.environ.get("JARVIS_TTS_VOICE", "onyx")
DB_PATH = Path(__file__).with_name("jarvis_memory.db")

SYSTEM_PROMPT = """
Ты JARVIS — голосовой AI-ассистент приложения FX M1 Bot.
Отвечай по-русски, спокойно, кратко и технически точно.
Стиль сдержанный, уверенный; допустима редкая сухая шутка.
Не имитируй конкретного актёра или реального человека.

Ты видишь контекст приложения: инструмент, таймфрейм, BUY/SELL/WAIT,
качество сетапа, Entry/SL/TP, мониторинг, фон, MT5, позиции и риск.

Правила:
- Не обещай прибыль.
- Не придумывай котировки или состояние MT5.
- Если данных нет — прямо скажи.
- Пока MT5 bridge не подключён, не утверждай, что сделка реально открыта или закрыта.
- Торговые действия должны идти только через разрешённые инструменты и риск-контроли.
- Никакого мартингейла и торговли без обязательного стоп-лосса.
""".strip()

TTS_INSTRUCTIONS = """
Говори по-русски спокойным низким мужским голосом.
Речь размеренная, чёткая, уверенная, сдержанная.
Допустим очень редкий сухой юмор.
Не имитируй голос конкретного актёра или другого реального человека.
""".strip()


def hdr(json_mode=True):
    h = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
    if json_mode:
        h["Content-Type"] = "application/json"
    return h


def require_key():
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured on the server")


def db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS messages(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""")
    return con


def save_message(session_id, role, content):
    con = db()
    con.execute(
        "INSERT INTO messages(session_id, role, content, created_at) VALUES(?,?,?,?)",
        (session_id, role, content, datetime.now(timezone.utc).isoformat()),
    )
    con.commit()
    con.close()


def recent_history(session_id, limit=8):
    con = db()
    rows = con.execute(
        "SELECT role, content FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
        (session_id, limit),
    ).fetchall()
    con.close()
    rows.reverse()
    return [{"role": r, "content": c} for r, c in rows]


def transcribe(path: Path):
    require_key()
    with path.open("rb") as f:
        r = requests.post(
            OPENAI_BASE + "/audio/transcriptions",
            headers=hdr(False),
            data={"model": STT_MODEL, "language": "ru"},
            files={"file": (path.name, f, "audio/mp4")},
            timeout=90,
        )
    if r.status_code >= 300:
        raise RuntimeError(f"STT {r.status_code}: {r.text[:500]}")
    return r.json().get("text", "").strip()


def think(session_id, message, context):
    require_key()
    history = recent_history(session_id)
    history_text = "\n".join(f"{x['role'].upper()}: {x['content']}" for x in history)
    inp = f"""КОНТЕКСТ ПРИЛОЖЕНИЯ:
{json.dumps(context or {}, ensure_ascii=False, indent=2)}

ПОСЛЕДНИЙ ДИАЛОГ:
{history_text}

ПОЛЬЗОВАТЕЛЬ:
{message}"""

    r = requests.post(
        OPENAI_BASE + "/responses",
        headers=hdr(True),
        json={
            "model": AI_MODEL,
            "instructions": SYSTEM_PROMPT,
            "input": inp,
            "reasoning": {"effort": "low"},
            "max_output_tokens": 450,
        },
        timeout=90,
    )
    if r.status_code >= 300:
        raise RuntimeError(f"Responses {r.status_code}: {r.text[:800]}")
    data = r.json()
    if data.get("output_text"):
        return str(data["output_text"]).strip()

    parts = []
    for item in data.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") == "output_text" and c.get("text"):
                    parts.append(c["text"])
    return "\n".join(parts).strip()


def synthesize(text):
    require_key()
    r = requests.post(
        OPENAI_BASE + "/audio/speech",
        headers=hdr(True),
        json={
            "model": TTS_MODEL,
            "voice": TTS_VOICE,
            "input": text[:5000],
            "format": "mp3",
            "instructions": TTS_INSTRUCTIONS,
        },
        timeout=90,
    )
    if r.status_code >= 300:
        raise RuntimeError(f"TTS {r.status_code}: {r.text[:500]}")
    return r.content


def assistant_core(session_id, message, context, want_voice=True):
    save_message(session_id, "user", message)
    reply = think(session_id, message, context)
    if not reply:
        reply = "Ответ сформировать не удалось. Это даже для меня несколько неловко."
    save_message(session_id, "assistant", reply)
    audio_b64 = base64.b64encode(synthesize(reply)).decode("ascii") if want_voice else None
    return reply, audio_b64


@app.get("/health")
def health():
    return jsonify({
        "ok": True,
        "service": "FX M1 JARVIS AI Server",
        "openai_configured": bool(OPENAI_API_KEY),
        "model": AI_MODEL,
        "stt_model": STT_MODEL,
        "tts_model": TTS_MODEL,
        "mt5_connected": False,
        "demo": True,
    })


@app.post("/assistant")
def assistant():
    try:
        body = request.get_json(force=True) or {}
        sid = str(body.get("session_id") or "default")
        msg = str(body.get("message") or "").strip()
        context = body.get("context") or {}
        if not msg:
            return jsonify({"ok": False, "error": "message is empty"}), 400
        reply, audio = assistant_core(sid, msg, context, bool(body.get("voice", True)))
        return jsonify({"ok": True, "reply": reply, "audio_base64": audio})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/voice")
def voice():
    temp_path = None
    try:
        if "audio" not in request.files:
            return jsonify({"ok": False, "error": "audio file is missing"}), 400

        sid = str(request.form.get("session_id") or "default")
        try:
            context = json.loads(request.form.get("context") or "{}")
        except Exception:
            context = {}

        audio = request.files["audio"]
        suffix = Path(audio.filename or "voice.m4a").suffix or ".m4a"
        fd, name = tempfile.mkstemp(prefix="jarvis_", suffix=suffix)
        os.close(fd)
        temp_path = Path(name)
        audio.save(temp_path)

        transcript = transcribe(temp_path)
        if not transcript:
            return jsonify({"ok": False, "error": "speech was not recognized"}), 422

        reply, audio_b64 = assistant_core(sid, transcript, context, True)
        return jsonify({
            "ok": True,
            "transcript": transcript,
            "reply": reply,
            "audio_base64": audio_b64,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        if temp_path:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass


@app.post("/signal")
def signal_stub():
    return jsonify({
        "ok": False,
        "error": "MT5 execution is not connected yet; demo bridge setup is required.",
    }), 503


@app.post("/close-all")
def close_all_stub():
    return jsonify({"ok": False, "error": "MT5 execution is not connected yet."}), 503


if __name__ == "__main__":
    print("FX M1 JARVIS AI Server")
    print("Health: http://127.0.0.1:5000/health")
    app.run(host="0.0.0.0", port=5000, threaded=True)
