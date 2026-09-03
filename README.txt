FX M1 BOT V10.0 — APK builder with Android SDK fix

1) Скопируй BUILD_APK_V10_SDK.py в корень:
   C:\Users\Hp\OneDrive\Documents\GitHub\FX-M1-Signal
2) Запусти:
   python BUILD_APK_V10_SDK.py
3) Скрипт сам:
   - использует уже скачанные Java 17 и Gradle 8.9;
   - ищет Android SDK;
   - если SDK нет, скачивает Google command-line tools;
   - принимает licenses;
   - ставит platform-tools, compileSdk platform и build-tools;
   - создаёт local.properties с sdk.dir;
   - собирает app-debug.apk.

Готовый APK:
app\build\outputs\apk\debug\app-debug.apk
