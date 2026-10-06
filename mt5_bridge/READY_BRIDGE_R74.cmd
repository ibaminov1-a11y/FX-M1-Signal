@echo off
setlocal DisableDelayedExpansion
set "R74_ROOT=%~dp0"
set "R74_PY=%~dp0..\mt5_bridge\.venv\Scripts\python.exe"
if not exist "%R74_PY%" goto missing
pushd "%R74_ROOT%"
if errorlevel 1 goto failed
"%R74_PY%" -I -B -X utf8 "%R74_ROOT%ready_launcher.py" %*
set "R74_EXIT=%ERRORLEVEL%"
popd
if not "%R74_EXIT%"=="0" if not "%R7_NO_PAUSE%"=="1" pause
exit /b %R74_EXIT%
:missing
echo Existing Python not found. Put mt5_bridge_R74 next to mt5_bridge.
echo Do not remove the old .venv or event_state.
:failed
if not "%R7_NO_PAUSE%"=="1" pause
exit /b 1
