@echo off
echo === FX M1 Bot Bridge V7.1 health ===
curl http://127.0.0.1:8000/health
echo.
echo.
echo === Symbols sample ===
curl "http://127.0.0.1:8000/symbols"
echo.
pause
