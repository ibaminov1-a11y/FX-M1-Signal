FX M1 Bot V6.6.2 FIX

Исправлено:
1. WAIT снова фиолетовый.
2. Качество сетапа выделено фиолетовым.
3. Строка последнего анализа для WAIT выделена оранжевым.
4. Sparkline теперь сохраняется из фонового MonitoringService и восстанавливается в UI.
5. Адрес сервера, SERVER/MT5 snapshot и AUTO состояние не сбрасываются при возврате в приложение.
6. MainActivity переведена в singleTask — тап по уведомлению возвращает в уже открытую Activity.
7. Убраны отдельные BUY/SELL уведомления, которые могли группироваться Android как "More notifications".
8. Оставлено одно постоянное foreground notification с PAUSE/EMERGENCY и раскрываемым BigText.
9. Торговая логика и MT5 Bridge не менялись.

Bridge менять не нужно.
