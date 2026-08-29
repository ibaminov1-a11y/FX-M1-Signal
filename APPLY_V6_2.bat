@echo off
setlocal
if not exist "app\src\main\java\com\openai\fxm1" (
  echo ERROR: Run this file from the FX-M1-Signal repository root.
  pause
  exit /b 1
)
if exist "app\src\main\java\com\openai\fxm1\JarvisVoiceService.java" del /F /Q "app\src\main\java\com\openai\fxm1\JarvisVoiceService.java"
if exist "backend" rmdir /S /Q "backend"
echo JARVIS files removed. V6.2 source files in this package should already be copied over the repo.
echo Done.
pause
