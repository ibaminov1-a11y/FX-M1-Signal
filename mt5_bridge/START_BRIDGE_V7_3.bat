@echo off
setlocal
cd /d "%~dp0"
title FX M1 MT5 Bridge - CURRENT

echo [FX M1] Starting CURRENT audited Bridge...

if not exist ".venv\Scripts\python.exe" (
    echo [FX M1] Creating local Python environment...
    python -m venv .venv
    if errorlevel 1 goto :PYERROR
)

".venv\Scripts\python.exe" -c "import flask, MetaTrader5" >nul 2>nul
if errorlevel 1 (
    echo [FX M1] Installing requirements...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :PIPERROR
)

echo [FX M1] Python environment OK.
echo [FX M1] Keep this window open while using the phone app.
echo.
".venv\Scripts\python.exe" bridge_v7_3.py
goto :END

:PYERROR
echo.
echo ERROR: Python/venv could not be created.
goto :END

:PIPERROR
echo.
echo ERROR: Bridge dependencies could not be installed.
goto :END

:END
echo.
pause
endlocal
