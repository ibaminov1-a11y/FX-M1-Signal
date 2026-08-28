@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python not found. Install Python and enable Add to PATH.
  pause
  exit /b 1
)
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
echo.
echo READY.
echo Next: set OPENAI_API_KEY=YOUR_KEY
echo Then run RUN_SERVER.bat
pause
