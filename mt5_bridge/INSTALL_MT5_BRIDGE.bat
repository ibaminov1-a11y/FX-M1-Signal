@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ===============================================
echo FX M1 Bot V6.3 - MT5 Bridge installer
echo ===============================================
echo.
where py >nul 2>nul
if errorlevel 1 (
  echo Python not found. Installing Python 3.13 via winget...
  winget install -e --id Python.Python.3.13 --accept-package-agreements --accept-source-agreements
  if errorlevel 1 (
    echo ERROR: Python installation failed.
    pause
    exit /b 1
  )
)

echo Creating isolated environment...
py -3.13 -m venv .venv
if errorlevel 1 py -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
  echo ERROR: Package installation failed.
  pause
  exit /b 1
)

echo.
echo Installation complete.
echo IMPORTANT: Open MetaTrader 5 and log into a DEMO account first.
echo Then run START_BRIDGE.bat
pause
