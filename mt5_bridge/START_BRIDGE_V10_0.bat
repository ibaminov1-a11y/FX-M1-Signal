@echo off
setlocal DisableDelayedExpansion
pushd "%~dp0"
if errorlevel 1 exit /b 1
set "PYTHONUTF8=1"
set "R7_PY="
set "R7_EXTRA="
if exist ".venv\Scripts\python.exe" set "R7_PY=.venv\Scripts\python.exe"
if defined R7_PY goto run
py -3 -c "import sys; assert sys.version_info >= (3,10)" >nul 2>&1
if not errorlevel 1 (
 set "R7_PY=py"
 set "R7_EXTRA=-3"
 goto run
)
python -c "import sys; assert sys.version_info >= (3,10)" >nul 2>&1
if not errorlevel 1 (
 set "R7_PY=python"
 goto run
)
echo Python 3.10+ was not found. Install Python 3.12 x64, then run INSTALL_R7_3.cmd.
set "R7_EXIT=1"
goto failed
:run
if not exist "bridge_startup.py" (
 echo R7.3 startup helper is missing. Run INSTALL_R7_3.cmd from the complete package.
 set "R7_EXIT=1"
 goto failed
)
"%R7_PY%" %R7_EXTRA% -B "bridge_startup.py" %*
set "R7_EXIT=%ERRORLEVEL%"
if not "%R7_EXIT%"=="0" goto failed
goto done
:failed
if not exist "event_state" mkdir "event_state"
echo Launcher stopped with exit code %R7_EXIT%.>>"event_state\bridge-startup.log"
echo Bridge did not start or stopped. See event_state\bridge-startup.log and bridge-runtime.log.
echo Read-only connection diagnosis: START_BRIDGE_V10_0.bat --diagnose
:done
if not "%R7_NO_PAUSE%"=="1" pause
popd
exit /b %R7_EXIT%
