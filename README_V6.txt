FX M1 BOT V6 — JARVIS SERVER VOICE

V6 fixes all three current tracks:

1) ONE SIGNAL CARD
MON and BG now publish to one canonical state_*.
There is no separate WAIT/BUY/SELL card logic anymore.

2) RUSSIAN JARVIS
Android SpeechRecognizer is no longer the primary Russian STT.
The app records M4A and sends it to /voice.
Server pipeline:
gpt-transcribe -> Russian text
gpt-5.6-terra -> reasoning/reply
gpt-4o-mini-tts -> MP3 voice
The phone language pack is no longer required for this path.

3) JARVIS FROM NOTIFICATION
The JARVIS action now starts JarvisVoiceService directly.
It does not force-open MainActivity.
It records about 6.5 seconds, sends to server, then plays the reply.
MUTE is respected.

4) MONITORING AND BACKGROUND REMAIN INDEPENDENT.
If both are enabled, BG remains the data source to avoid duplicate Twelve Data usage.

ANDROID FILES:
app/src/main/java/com/openai/fxm1/MainActivity.java
app/src/main/java/com/openai/fxm1/MonitoringService.java
app/src/main/java/com/openai/fxm1/JarvisVoiceService.java
app/src/main/res/layout/activity_main.xml
app/src/main/AndroidManifest.xml

SERVER:
backend/jarvis_ai_server.py
backend/requirements.txt
backend/SETUP_WINDOWS.bat
backend/RUN_SERVER.bat

FIRST SERVER TEST:
1. Install Python.
2. Run backend/SETUP_WINDOWS.bat.
3. Open CMD in backend.
4. set OPENAI_API_KEY=YOUR_KEY
5. RUN_SERVER.bat
6. Open http://127.0.0.1:5000/health on the PC.
7. In the APK enter the PC LAN address, e.g. 192.168.1.20:5000.
   For the first test phone and PC should be on the same network.

Do NOT put the OpenAI API key into the APK.
Do NOT expose Flask directly to the public internet without TLS/auth.
For remote access later, use a private VPN/Tailscale or a secured Windows VPS.

COMMIT:
V6 Jarvis server voice unified signal
