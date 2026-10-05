@echo off
setlocal DisableDelayedExpansion
set "R732_ROOT=%~dp0"
set "R732_PY=%~dp0..\mt5_bridge\.venv\Scripts\python.exe"
if not exist "%R732_PY%" goto missing
pushd "%R732_ROOT%"
if errorlevel 1 goto failed
"%R732_PY%" -I -B -X utf8 "%R732_ROOT%ready_launcher.py" %*
set "R732_EXIT=%ERRORLEVEL%"
popd
if not "%R732_EXIT%"=="0" if not "%R7_NO_PAUSE%"=="1" pause
exit /b %R732_EXIT%
:missing
echo Existing Python not found. Put mt5_bridge_R732 next to mt5_bridge.
echo Do not remove the old .venv or event_state.
:failed
if not "%R7_NO_PAUSE%"=="1" pause
exit /b 1
