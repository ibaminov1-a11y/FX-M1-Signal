@echo off
cd /d "%~dp0"
if "%OPENAI_API_KEY%"=="" (
  echo OPENAI_API_KEY is not set in this terminal.
  echo Example: set OPENAI_API_KEY=sk-...
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
python jarvis_ai_server.py
pause
