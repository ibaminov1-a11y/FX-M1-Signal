@echo off
setlocal
cd /d "%~dp0"
set ROOT=%~1
if "%ROOT%"=="" set ROOT=%CD%

echo.
echo FX M1 BOT V9.3 BRIDGE FIX
echo Project: %ROOT%
echo.

py "%~dp0FIX_BRIDGE_V9_3.py" "%ROOT%"
if errorlevel 1 goto ERR

echo.
echo DONE.
echo Now run: mt5_bridge\START_BRIDGE_V9_3.bat
pause
exit /b 0

:ERR
echo.
echo FIX STOPPED. bridge_v9_3.py was not replaced unless compile passed.
pause
exit /b 1
