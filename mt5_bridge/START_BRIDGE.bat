@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Bridge is not installed yet. Run INSTALL_MT5_BRIDGE.bat first.
  pause
  exit /b 1
)
echo Starting FX M1 MT5 Bridge V6.3...
echo Keep this window open while using the phone APK.
.venv\Scripts\python.exe bridge.py
pause
