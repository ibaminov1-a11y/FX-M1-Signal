ПРИЧИНА BUILD #60 НАЙДЕНА ТОЧНО.

В GitHub FeatureEngine.java в formatTradeLog() были записаны реальные переносы
строки внутри Java-кавычек. Например:

    sb.append("
NET ")

Такой Java-код не компилируется.

ЧТО ДЕЛАТЬ:
1. Открой ZIP -> FX-M1-Signal.
2. Скопируй FIX_V9_4_ANDROID_BUILD.bat и FIX_V9_4_ANDROID_BUILD.py
   в корень:
   C:\Users\Hp\OneDrive\Documents\GitHub\FX-M1-Signal\
3. Запусти FIX_V9_4_ANDROID_BUILD.bat.
4. После DONE в GitHub обнови только файл:
   app\src\main\java\com\openai\fxm1\FeatureEngine.java
5. Запусти Actions APK V9.4 снова.

Bridge V9.4 не трогается.
MonitoringService не трогается.
MainActivity не трогается.
