FX M1 Bot V6.2 — NO JARVIS / BACKGROUND FIX / LIVE TIMER / PAUSE-PLAY / DOUBLE-TAP EMERGENCY

Что изменено:
1. JARVIS удалён полностью: UI, голос, микрофон, сервис, backend и разрешения.
2. Из фонового уведомления удалён значок голоса/JARVIS.
3. Фоновый режим запускается через MonitoringService с обработкой ошибки, без голосового foreground service.
4. «прошло» обновляется каждую секунду локальным UI ticker; Twelve Data запросы от этого не увеличиваются.
5. PAUSE = запрет НОВЫХ входов. Анализ и сопровождение уже открытых позиций продолжаются.
6. PLAY = снова разрешить новые входы.
7. EMERGENCY = двойное нажатие в течение 2.5 сек. После второго нажатия AUTO выключается, отправляется CLOSE ALL в MT5 bridge (если сервер доступен), затем фон останавливается.
8. Торговый модуль и адрес сервера сохранены — это будущий bridge APK -> сервер -> MT5, а не JARVIS.

Заменить в репозитории:
- app/src/main/java/com/openai/fxm1/MainActivity.java
- app/src/main/java/com/openai/fxm1/MonitoringService.java
- app/src/main/res/layout/activity_main.xml
- app/src/main/AndroidManifest.xml

Удалить из репозитория:
- app/src/main/java/com/openai/fxm1/JarvisVoiceService.java
- папку backend/ целиком (если она ещё есть).

После замены: GitHub Desktop -> commit -> Push origin -> Actions -> собрать APK.
