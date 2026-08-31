@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ===============================================
echo FX M1 Bot - CURRENT MT5 Bridge installer
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

if exist .venv rmdir /s /q .venv
py -3.13 -m venv .venv
if errorlevel 1 py -m venv .venv
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo ERROR: Package installation failed.
  pause
  exit /b 1
)

echo.
echo Installation complete. Open MT5 DEMO, then run START_BRIDGE_V7_3.bat.
pause
