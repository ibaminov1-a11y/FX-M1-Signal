FX M1 BOT V6.3

ANDROID
- Removed the entire visible Background Mode block.
- START MONITORING now starts one foreground service automatically.
- The same monitoring keeps running when the APK is minimized or the screen is locked (subject to Android/OEM battery policy).
- STOP MONITORING stops the service and API polling.
- The elapsed label freezes after STOP.
- Switching symbol/timeframe shows WAIT without the previous symbol timestamp until fresh analysis arrives.
- UI source is LIVE/STOP instead of BG/MON.
- Local HTTP traffic is enabled for a LAN MT5 bridge.

MT5 BRIDGE
1. Install/open MetaTrader 5 desktop on the Windows PC.
2. Log into a DEMO account in MT5. Do not put your password into the APK or bridge files.
3. Run mt5_bridge\INSTALL_MT5_BRIDGE.bat once.
4. Run mt5_bridge\START_BRIDGE.bat.
5. On the phone, use the PC LAN address, e.g. http://192.168.1.10:8000, then press CHECK SERVER.
6. Expected status: SERVER CONNECTED / MT5 CONNECTED / DEMO.

SAFETY
- V6.3 bridge refuses order execution and CLOSE ALL on non-DEMO accounts.
- Risk size is calculated from equity, SL distance and the selected risk %. If calculated lot is below broker minimum, the order is rejected.
- AUTO should remain OFF until health/quote checks are confirmed.

FILES TO REPLACE IN REPO
app\src\main\java\com\openai\fxm1\MainActivity.java
app\src\main\java\com\openai\fxm1\MonitoringService.java
app\src\main\res\layout\activity_main.xml
app\src\main\AndroidManifest.xml

The mt5_bridge folder belongs on the Windows PC, not inside the Android app module.
