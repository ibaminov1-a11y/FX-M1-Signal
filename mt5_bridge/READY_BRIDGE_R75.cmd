@echo off
setlocal DisableDelayedExpansion
set "R75_ROOT=%~dp0"
set "R75_PY=%~dp0..\mt5_bridge\.venv\Scripts\python.exe"
if not exist "%R75_PY%" goto missing
pushd "%R75_ROOT%"
if errorlevel 1 goto failed
"%R75_PY%" -I -B -X utf8 "%R75_ROOT%ready_launcher.py" %*
set "R75_EXIT=%ERRORLEVEL%"
popd
if not "%R75_EXIT%"=="0" if not "%R7_NO_PAUSE%"=="1" pause
exit /b %R75_EXIT%
:missing
echo Existing Python not found. Put mt5_bridge_R75 next to mt5_bridge.
echo Do not remove the old .venv or event_state.
:failed
if not "%R7_NO_PAUSE%"=="1" pause
exit /b 1
