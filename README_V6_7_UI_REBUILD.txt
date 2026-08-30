FX M1 Bot V6.7 — UI REBUILD

Основа: V6.6.2. Торговый Bridge и DEMO-only защита не менялись.

Что изменено:
- Полная перестройка главного экрана под согласованный dashboard, без удаления текущих функций.
- Сохранены: инструмент, API key save/change, MARKET OPEN/CLOSED, режим сигнала,
  monitoring start/stop, торговый модуль/server, MT5, AUTO, risk, max positions,
  max drift, close all, emergency stop, journal.
- Таймфреймы: M1, M5, M15, H1, H4, D1, W1, MN1.
- BUY green / SELL red / WAIT purple.
- Качество сигнала: число + 10-сегментная шкала.
- Sparkline: до 48 точек, typical price (H+L+C)/3, сглаженная линия, динамический масштаб.
- Отдельные карточки: account/execution, AUTO TRADING, current signal, positions MT5,
  system/trading module, journal.
- Bottom navigation прокручивает к соответствующим секциям экрана.
- Новый dark-space background.
- Notification rebuilt with custom compact + expanded RemoteViews:
  logo only inside custom card (large right-side app icon removed), symbol/TF/mode/signal/quality,
  balance, positions, risk, expanded quality/API price/last analysis/system status,
  PAUSE and EMERGENCY STOP actions.
- Server/API saved-state logic kept from V6.6.2.

Важно:
- Bridge менять не требуется.
- Weekend/market-closed data can remain flat because quotes are not moving; chart never invents prices.
- Exact notification chrome/outer margins still depend on Android/MIUI/HyperOS.
