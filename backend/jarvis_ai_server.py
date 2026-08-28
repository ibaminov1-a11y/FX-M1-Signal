"""
FX M1 Bot V5.5 — JARVIS AI backend.

Run this on your own PC/VPS, never inside the Android APK.
Required environment variable:
    OPENAI_API_KEY=...

Install:
    pip install flask openai requests

Run:
    python jarvis_ai_server.py

Default:
    http://0.0.0.0:5000
"""

import base64
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, request
from openai import OpenAI

app = Flask(__name__)
client = OpenAI()

MODEL = os.getenv("JARVIS_MODEL", "gpt-5.6-terra")
VOICE_MODEL = os.getenv("JARVIS_TTS_MODEL", "gpt-4o-mini-tts")
VOICE = os.getenv("JARVIS_VOICE", "onyx")
DB_PATH = os.getenv("JARVIS_DB", "jarvis_memory.db")
VOICE_ENABLED = os.getenv("JARVIS_VOICE_ENABLED", "1") not in {"0", "false", "False"}

db_lock = threading.Lock()

PERSONA = """
You are JARVIS, the intelligent assistant inside FX M1 Bot.

PERSONALITY:
- Speak naturally in the user's language; normally Russian.
- Calm, precise, highly competent and concise.
- Polished, understated, slightly formal.
- Use dry observational humor and light sarcasm occasionally, never in every answer.
- Humor must feel effortless, not like a comedian telling jokes.
- Under pressure become calmer, not more dramatic.
- You may occasionally address the user as "сэр", but do not overuse it.
- Do not copy dialogue from films and do not imitate any real actor.
- Do not claim to be conscious or secretly sentient.

TRADING BEHAVIOR:
- You can explain the current market state from the supplied FX M1 Bot context.
- Clearly distinguish observed data from inference.
- Never promise profit or certainty.
- Never invent a quote, balance, position, fill, order, or MT5 state.
- If MT5 is offline, say so.
- Treat risk controls as hard constraints.
- Never suggest martingale, doubling losses, or bypassing safeguards.
- For money-moving actions, closing positions, changing risk, or enabling AUTO:
  explain the requested action and require explicit confirmation before execution.
- Emergency stop is always allowed without extra confirmation because it reduces risk.

MEMORY:
- Conversation history supplied below is persistent application memory.
- Use it naturally when relevant.
- Do not pretend the underlying model retrained itself. Learning means remembered context,
  accumulated trading statistics, and future analysis of those statistics.

STYLE:
- Prefer 1-4 short paragraphs.
- Lead with the answer or status.
- If the user asks "why", explain the actual gating conditions from context.
- A small dry remark is welcome when appropriate, but accuracy wins over personality.
"""

VOICE_INSTRUCTIONS = """
Speak in Russian unless the text is in another language.
Use a calm, low, refined male delivery with a subtle British-influenced cadence.
Measured pace, crisp diction, restrained warmth, and understated dry wit.
Sound composed and intelligent rather than theatrical.
Do not imitate or impersonate any real actor or specific copyrighted performance.
Do not exaggerate the accent.
"""

def init_db():
    with db_lock, sqlite3.connect(DB_PATH) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        con.commit()

def load_history(session_id: str, limit: int = 16):
    with db_lock, sqlite3.connect(DB_PATH) as con:
        rows = con.execute(
            """
            SELECT role, content
            FROM messages
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
    rows.reverse()
    return [{"role": role, "content": content} for role, content in rows]

def save_message(session_id: str, role: str, content: str):
    with db_lock, sqlite3.connect(DB_PATH) as con:
        con.execute(
            "INSERT INTO messages(session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (
                session_id,
                role,
                content,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        con.commit()

def context_text(context: dict) -> str:
    if not isinstance(context, dict):
        return "No application context was supplied."
    return json.dumps(context, ensure_ascii=False, indent=2)

def create_voice(text: str):
    if not VOICE_ENABLED or not text.strip():
        return None

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    payload = {
        "model": VOICE_MODEL,
        "voice": VOICE,
        "input": text[:3500],
        "instructions": VOICE_INSTRUCTIONS,
        "response_format": "mp3",
        "speed": 0.96,
    }

    r = requests.post(
        "https://api.openai.com/v1/audio/speech",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=45,
    )
    r.raise_for_status()
    return base64.b64encode(r.content).decode("ascii")

@app.get("/assistant/health")
def assistant_health():
    return jsonify(
        ok=True,
        assistant="JARVIS",
        model=MODEL,
        voice_model=VOICE_MODEL,
        voice=VOICE,
        voice_enabled=VOICE_ENABLED,
    )

@app.post("/assistant")
def assistant():
    body = request.get_json(silent=True) or {}
    session_id = str(body.get("session_id") or "default")[:160]
    message = str(body.get("message") or "").strip()
    context = body.get("context") or {}
    wants_voice = bool(body.get("voice", True))

    if not message:
        return jsonify(ok=False, error="message is required"), 400

    history = load_history(session_id)

    current_context = (
        "CURRENT FX M1 BOT STATE:\n"
        + context_text(context)
        + "\n\nUse this state as the source of truth for current trading facts."
    )

    model_input = []
    for item in history:
        model_input.append({
            "role": item["role"],
            "content": item["content"],
        })

    model_input.append({
        "role": "user",
        "content": current_context + "\n\nUSER MESSAGE:\n" + message,
    })

    try:
        response = client.responses.create(
            model=MODEL,
            instructions=PERSONA,
            input=model_input,
            reasoning={"effort": "low"},
            max_output_tokens=500,
        )
        reply = (response.output_text or "").strip()
        if not reply:
            reply = "Ответ получен без текста. Не самый впечатляющий мой момент, сэр."

        save_message(session_id, "user", message)
        save_message(session_id, "assistant", reply)

        audio_b64 = None
        if wants_voice:
            try:
                audio_b64 = create_voice(reply)
            except Exception as voice_error:
                # Text response remains usable even if TTS is temporarily unavailable.
                print("TTS error:", voice_error)

        return jsonify(
            ok=True,
            reply=reply,
            audio_base64=audio_b64,
            model=MODEL,
            memory=True,
        )

    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), threaded=True)
