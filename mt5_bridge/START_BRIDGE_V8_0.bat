@echo off
cd /d "%~dp0"
echo Starting FX M1 MT5 Bridge V8.0...
if exist ".venv\Scripts\python.exe" (
  .venv\Scripts\python.exe bridge_v8_0.py
) else (
  python bridge_v8_0.py
)
pause
