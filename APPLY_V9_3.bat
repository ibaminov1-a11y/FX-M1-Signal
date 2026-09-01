@echo off
setlocal
cd /d "%~dp0"
set ROOT=%~1
if "%ROOT%"=="" set ROOT=%CD%

echo.
echo FX M1 BOT V9.3 LIVE updater
echo Project: %ROOT%
echo.

if exist "%ROOT%\mt5_bridge\bridge_v9_2.py" goto APPLY93

if exist "%ROOT%\mt5_bridge\bridge_v9_1.py" (
  echo V9.1 detected. Applying V9.2 base first...
  py "%~dp0APPLY_V9_2.py" "%ROOT%"
  if errorlevel 1 goto ERR
  goto APPLY93
)

echo ERROR: bridge_v9_1.py / bridge_v9_2.py not found.
goto ERR

:APPLY93
echo Applying V9.3 LIVE...
py "%~dp0APPLY_V9_3.py" "%ROOT%"
if errorlevel 1 goto ERR
echo.
echo DONE.
echo Start: mt5_bridge\START_BRIDGE_V9_3.bat
echo Build APK: gradle :app:assembleDebug
pause
exit /b 0

:ERR
echo.
echo Update stopped.
pause
exit /b 1
