@echo off
setlocal
cd /d "%~dp0"
echo ==========================================
echo FX M1 BOT V9.4 STABLE INSTALLER
echo ==========================================
py "%~dp0APPLY_V9_4_STABLE.py" "%CD%"
if errorlevel 1 goto ERR
echo.
echo UPDATE COMPLETE.
echo Start: mt5_bridge\START_BRIDGE_V9_4.bat
if exist FX-M1-Signal-V9.4-DEMO.apk echo APK: FX-M1-Signal-V9.4-DEMO.apk
pause
exit /b 0
:ERR
echo.
echo UPDATE FAILED. Rollback requested automatically.
pause
exit /b 1
