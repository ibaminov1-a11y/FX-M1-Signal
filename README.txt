V9.6 CONSOLIDATED
Copy APPLY_V9_6.py to FX-M1-Signal root and run it.
After DONE:
1) stop Bridge V9.5
2) run mt5_bridge\START_BRIDGE_V9_6.bat
3) gradlew.bat --no-daemon :app:assembleDebug
4) install app\build\outputs\apk\debug\app-debug.apk

Changes: strict pullback/rejection/resume/micro-break first entry; no peak chasing; no early_probe; every scale-in requires a new pullback cycle and positive basket; micro profit lock arms early; Android direction 18/28 and network 1s/2s are preserved; REAL stays disabled.
