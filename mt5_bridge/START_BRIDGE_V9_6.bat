@echo off
cd /d "%~dp0"
echo Starting FX M1 MT5 Bridge V9.6...
echo 100ms runtime - strict pullback entry - pyramiding - micro peak lock
.venv\Scripts\python.exe bridge_v9_6.py
pause
