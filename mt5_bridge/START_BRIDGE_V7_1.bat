@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [FX M1 Bot] Creating Bridge V7.1 virtual environment...
  py -3 -m venv .venv
  if errorlevel 1 goto :fail
  call .venv\Scripts\activate.bat
  python -m pip install --upgrade pip
  pip install -r requirements.txt
  if errorlevel 1 goto :fail
) else (
  call .venv\Scripts\activate.bat
)
echo.
echo [FX M1 Bot] Starting MT5 Bridge V7.1 on port 8000...
echo Keep MetaTrader 5 open and logged into DEMO.
echo.
python bridge.py
pause
exit /b 0
:fail
echo.
echo Bridge setup failed. Check Python 3, internet access for package install, and MT5 installation.
pause
exit /b 1
