КОПИРУЕШЬ ВСЁ ИЗ ЭТОЙ ПАПКИ FX-M1-Signal В:
C:\Users\Hp\OneDrive\Documents\GitHub\FX-M1-Signal\

Потом запускаешь В КОРНЕ:
APPLY_V9_4_STABLE.bat

Installer:
- берёт компилируемый V9.1 Bridge как чистую рабочую базу;
- сохраняет рабочую SCALP state-machine V9.1;
- делает MT5/позиции/P&L LIVE ~1 сек независимо от API;
- ставит SCALP max positions = 10;
- добавляет денежный торговый журнал NET +/- USD;
- делает bridge py_compile ДО установки;
- запускает Gradle build APK;
- если Android build падает, делает rollback;
- REAL не включает.

После DONE запускаешь:
mt5_bridge\START_BRIDGE_V9_4.bat
