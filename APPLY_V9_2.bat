@echo off
setlocal
cd /d "%~dp0"
echo ==========================================
echo FX M1 BOT - APPLY V9.2
echo ==========================================
python APPLY_V9_2.py "%CD%"
if errorlevel 1 (
  echo UPDATE FAILED
  pause
  exit /b 1
)
echo.
echo V9.2 applied.
echo Bridge: mt5_bridge\START_BRIDGE_V9_2.bat
echo.
if exist gradlew.bat (
  echo Building APK...
  call gradlew.bat --no-daemon :app:assembleDebug
  if not errorlevel 1 echo APK: app\build\outputs\apk\debug\app-debug.apk
)
pause
