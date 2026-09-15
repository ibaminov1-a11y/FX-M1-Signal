@echo off
setlocal
cd /d "%~dp0"
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY if exist "..\mt5_bridge\.venv\Scripts\python.exe" set "PY=..\mt5_bridge\.venv\Scripts\python.exe"
if not defined PY set "PY=python"
"%PY%" -c "import flask, MetaTrader5" 2>nul
if errorlevel 1 (
  echo Required Python packages are missing for this interpreter.
  echo Run this ONCE in this folder, using the same Python:
  echo "%PY%" -m pip install -r requirements_event.txt
  echo If packages are already installed, run this diagnostic:
  echo "%PY%" -c "import flask, MetaTrader5; print('FLASK/MT5 OK')"
  pause
  exit /b 1
)
"%PY%" bridge_v10_0.py --host 0.0.0.0
pause
