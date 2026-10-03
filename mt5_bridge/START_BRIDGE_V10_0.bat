@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY if exist "..\mt5_bridge\.venv\Scripts\python.exe" set "PY=..\mt5_bridge\.venv\Scripts\python.exe"
if not defined PY set "PY=python"
echo Checking Bridge Python environment...
"%PY%" -c "import flask,MetaTrader5,colorama,event_core; assert hasattr(colorama,'AnsiToWin32'); assert hasattr(event_core,'VERSION'); print('BRIDGE DEPS OK',event_core.BUILD)"
if errorlevel 1 (
  echo.
  echo Bridge environment check failed. The real Python error is shown above.
  echo Run INSTALL_R7_2.cmd from the full R7.2 package to restore program files and Colorama.
  pause
  exit /b 1
)
"%PY%" bridge_v10_0.py --host 0.0.0.0
pause
