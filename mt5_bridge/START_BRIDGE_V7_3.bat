@echo off
setlocal
cd /d "%~dp0"
title FX M1 MT5 Bridge V7.3

echo [FX M1] Starting Bridge V7.3...

if not exist ".venv\Scripts\python.exe" (
    echo [FX M1] Creating local Python environment...
    python -m venv .venv
    if errorlevel 1 goto :PYERROR
)

".venv\Scripts\python.exe" -c "import flask, MetaTrader5" >nul 2>nul
if errorlevel 1 (
    echo [FX M1] Installing Flask and MetaTrader5...
    ".venv\Scripts\python.exe" -m pip install flask MetaTrader5
    if errorlevel 1 goto :PIPERROR
)

echo [FX M1] Bridge Python environment OK.
echo [FX M1] Keep this window open while using the phone app.
echo.
".venv\Scripts\python.exe" bridge_v7_3.py
goto :END

:PYERROR
echo.
echo ERROR: Python/venv could not be created.
echo Check that Python is installed and available as "python".
goto :END

:PIPERROR
echo.
echo ERROR: Flask/MetaTrader5 installation failed.
echo Try moving the project outside OneDrive if Windows blocks package files.
goto :END

:END
echo.
pause
endlocal
