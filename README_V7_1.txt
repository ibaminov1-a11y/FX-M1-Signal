FX M1 Bot V7.1 + MT5 Bridge V7.1
================================

ВАЖНО
- V7.1 остаётся DEMO-only для открытия/изменения/закрытия позиций.
- Android-сборку окончательно подтверждает GitHub Actions вашего репозитория.
- Реальное поведение expanded/custom notification зависит от оболочки Android. В V7.1 есть одновременно custom compact/expanded UI + системные action-кнопки PAUSE/EMERGENCY + foreground watchdog.

СОХРАНЕНО ИЗ ПРЕДЫДУЩИХ ВЕРСИЙ
- Инструмент + ручное добавление инструмента.
- Twelve Data API key: сохранить / изменить / скрыть после сохранения.
- TF: M1 / M5 / M15 / H1 / H4 / D1 / W1 / MN1.
- Режимы: CONSERVATIVE / NORMAL / AGGRESSIVE.
- Динамический MARKET OPEN / MARKET CLOSED на America/New_York -> Asia/Tashkent, даты меняются автоматически.
- Запустить/остановить мониторинг.
- WAIT / BUY / SELL, sparkline, качество, Entry/SL/TP1/TP2, контекст.
- AUTO TRADING, риск, максимум позиций, max drift, CLOSE ALL, EMERGENCY STOP.
- Счёт / баланс / equity / API Price / MT5 Bid/Ask / позиции / P&L.
- Сервер + MT5 connection; адрес вводится отдельным диалогом, http:// добавляется автоматически.
- Журнал.
- Космический тёмно-фиолетовый фон.
- Нижняя неработающая навигация остаётся скрытой.

НОВОЕ В V7.1
1. Smart Risk Manager: дневной loss limit, equity drawdown, серия убытков.
2. Break Even по R.
3. Trailing Stop по R.
4. Частичное закрытие по R.
5. Управление каждой MT5-позицией из APK: CLOSE / BREAK EVEN / PARTIAL 50%.
6. Торговая статистика: trades, win rate, Profit Factor, avg trade, daily realized P/L.
7. История сигналов отдельно от истории сделок.
8. Причина SKIP/WAIT и причины входа.
9. Разбивка качества по компонентам.
10. Multi-pair watchlist/radar.
11. Получение списка символов прямо из MT5 Bridge.
12. Spread filter.
13. Slippage logging.
14. Manual News Guard / blackout window (автоматический календарь новостей пока намеренно не подключён без проверенного источника).
15. Market sessions: ASIA / LONDON / NEW YORK для контекста.
16. Execution modes: SIGNALS_ONLY / SEMI_AUTO / FULL_AUTO.
17. Ручное подтверждение входов ниже заданного quality threshold.
18. Cooldown после выхода по инструменту.
19. Bridge heartbeat/uptime + risk-state snapshot.
20. Снимок причины входа: signal, quality, components, why, API/MT5 price, spread, drift, risk.

УВЕДОМЛЕНИЕ
- Foreground notification обязано существовать, пока мониторинг ON.
- Watchdog обновляет его каждые 15 секунд.
- Compact: сигнал, pair/TF/mode/quality, market/server/MT5 + видимые PAUSE и STOP, если OEM допускает custom compact layout.
- Expanded: баланс, позиции, риск/AUTO, quality, API Price, последний анализ, status + PAUSE / EMERGENCY STOP.
- Дополнительно добавлены системные Android actions PAUSE/PLAY и EMERGENCY STOP — это fallback, если оболочка телефона урезает RemoteViews.

BRIDGE V7.1
Новые endpoints:
GET  /health
GET  /symbols
GET  /quote?symbol=EURUSD
GET  /positions
GET  /stats?days=30
GET  /risk-state
GET  /trade-log?limit=100
POST /signal
POST /manage-positions
POST /position-action
POST /close-all

УСТАНОВКА
1. Файлы из app/ заменить в GitHub репозитории поверх текущих app/src/main/... .
2. Commit + Push -> GitHub Actions -> Build debug APK.
3. Папку bridge/ скопировать на Windows ПК (или позже на VPS).
4. MT5 desktop должен быть открыт и залогинен в DEMO.
5. Запустить bridge/START_BRIDGE_V7_1.bat.
6. В APK ввести только IP:PORT, например 192.168.1.8:8000.

ПРОВЕРКИ ПЕРЕД УПАКОВКОЙ
- bridge.py: python -m py_compile: OK.
- XML: все Android XML успешно распарсены.
- Java: баланс фигурных/круглых скобок OK; javac parser не нашёл синтаксических ошибок до отсутствующих Android SDK classes.
- Проверка R.id: все app R.id, используемые Java, существуют в XML.
- Проверка R.drawable: все app drawables, используемые Java, присутствуют.
- Дубли onDestroy/методов верхнего уровня: не обнаружены.
- ZIP integrity: проверяется перед выдачей.
