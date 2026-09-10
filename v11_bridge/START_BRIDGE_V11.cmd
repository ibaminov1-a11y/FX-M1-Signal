@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo FX M1 V11 -- DEMO ONLY. Stop the old Bridge before starting this one.
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 bridge_v11.py
) else (
    python bridge_v11.py
)
echo.
echo Bridge has stopped. Read any error above. This launcher does not install or modify anything.
pause
