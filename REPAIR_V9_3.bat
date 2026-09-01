@echo off
setlocal
cd /d "%~dp0"
set ROOT=%~1
if "%ROOT%"=="" set ROOT=%CD%

echo.
echo FX M1 BOT V9.3 REPAIR
echo Project: %ROOT%
echo.

py "%~dp0REPAIR_AND_APPLY_V9_3.py" "%ROOT%"
if errorlevel 1 goto ERR

echo.
echo DONE.
echo Next: mt5_bridge\START_BRIDGE_V9_3.bat
pause
exit /b 0

:ERR
echo.
echo REPAIR STOPPED.
pause
exit /b 1
