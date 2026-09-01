@echo off
setlocal
cd /d "%~dp0"
echo ============================================
echo FX M1 BOT V9.5 FINAL
echo ============================================
echo.
py "%~dp0APPLY_V9_5_FINAL.py" "%CD%"
if errorlevel 1 goto ERR
echo.
echo UPDATE COMPLETE.
echo Start Bridge: mt5_bridge\START_BRIDGE_V9_5.bat
pause
exit /b 0
:ERR
echo.
echo UPDATE STOPPED.
pause
exit /b 1
