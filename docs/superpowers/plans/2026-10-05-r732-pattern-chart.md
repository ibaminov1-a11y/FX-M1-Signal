# R7.3.2 Pattern Chart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. An independent reviewer is useful when available; do not claim an independent review unless it actually occurred.

**Goal:** Довести согласованные 19 вариантов фигур до распознавания и разметки на свечах MT5, исправить APK и выдать совместимые APK + полный Bridge без ручного ремонта установки.

**Architecture:** Отделить данные для просмотра фигур от торговых кандидатов. Добавить совместимое поле `forecast.pattern_chart`, построенное из уже полученной истории, подтверждённых экстремумов и явно предварительного последнего экстремума. Android отвечает за выбор отображения и сохранение масштаба; Engine остаётся единственным владельцем исполнения.

**Tech Stack:** Существующие Python/EventCore/Flask/SQLite и Java/Android Canvas; Java 17, Gradle 8.9, Android API35. Без новых платных API, VPS и библиотек распознавания.

**Spec:** `docs/superpowers/specs/2026-10-05-r73-pattern-chart-design.md`, commit `a3fca55b5eba24d077f30cae7e4c872ed318c33f`. Пользователь подтвердил документ сообщением «да все четко» после его выдачи. Этот план уточняет порядок реализации, а не расширяет ТЗ.

**Статус:** План для проверки перед реализацией. Отметки ниже — ещё не выполненные работы. Новый APK, исправление и результаты новых тестов этим документом не заявляются.

## Global Constraints

- Поддерживаются все девять выбираемых периодов: M1, M5, M15, M30, H1, H4, D1, W1, MN1.
- M10 сохраняется как прежняя совместимость движка, но не объявляется новым пунктом интерфейса.
- REAL остаётся заблокированным в производственном адаптере.
- Публичный протокол остаётся `fxm1.event.v1`; новые данные разметки добавляются совместимо, без подмены существующих полей исполнения.
- Планируемая версия: `10.9-EC1-R7.3.2`, Android versionCode 933. Перед сборкой повторно проверить, что номер не занят более поздней работой. Android applicationId: `com.openai.fxm1.ec1`.
- Сохраняется исходная подпись APK; ожидаемый SHA-256 сертификата: `3d55a491046e661664f99c2a3e4a51338a794b313beb3e32d7ed88181a7a1885`.
- Пользователь получает APK и полный Bridge. Старые `.venv`, `event_state`, база, WAL/SHM, ключ сопряжения и брокерские часы не удаляются и не перезаписываются установщиком.
- Сохраняются NORMAL/SCALP, BUY/SELL, несколько профилей, scale-in, сопровождение, close-before-reverse, неизвестное исполнение и восстановление кампании.
- Прибыльность, точность будущей цены и исполнение у конкретного брокера этим не доказываются.

## Review Focus

1. Запрет аналогового прогноза теряется при копировании снимка или пересоздании экрана; проверять итоговый Canvas и сохранённый выбор, а не только JSON сервера. Владельцы: задачи 1–2, 6.
2. Формирующийся экстремум превращается в подтверждённый задним числом; проверять префиксы истории, неоднозначную outside-свечу и отсутствие торговых команд. Владельцы: задачи 3–4.
3. Один бар содержит и цель, и отмену; без порядка тиков нельзя сообщать успешный исход. В отображении — неопределённость, в исполнении — прежние защитные правила. Владелец: задача 4.
4. MN1, брокерский суффикс, старый ответ другого счёта и исправленная история могут перепутать идентичность фигуры. Владельцы: задачи 3–6.
5. Новый каталог программы может случайно открыть пустой `event_state` или импортировать старый `event_core`; существующий Python не означает правильную программу и базу. Владелец: задача 7.

---

## Исходники, изоляция и порядок

База реализации: `a3fca55b5eba24d077f30cae7e4c872ed318c33f`, включая исходный GRAPH Bridge `b19e16e95e3179edb465db2f4e18e12b4f7b5ebb` и утверждённое ТЗ. План сохраняется на существующей документационной ветке `spec/r73-patterns-complete-20261005`.

На этапе исполнения создать отдельную рабочую ветку `feature/r732-pattern-chart-20261005` от коммита с утверждённым планом. Рабочие ветки пользователя не перезаписывать. Прежнюю `repair/r73-scenario-map-20261005` использовать только для сравнения; не переносить её целиком и не считать versionCode 932 готовым выпуском.

Порядок: **1 → 2 → 3 → 4 → 5 → 6 → 7 → 8**. Задачи завершаются отдельными проверяемыми коммитами. Пакеты между задачами — внутренние артефакты, не очередные установочные «исправления» для пользователя.

Во всех задачах цикл одинаков: написать тест → подтвердить падение по нужной причине → изменить минимальный необходимый участок → повторить тест и регрессии → проверить diff → commit. Сбой из-за опечатки, импорта или отсутствия SDK не считается воспроизведением дефекта.

Команда полной серверной регрессии из корня проекта:

```bash
PYTHONPATH=mt5_bridge:tests/event_core TERM=xterm python -m unittest discover -s tests/event_core -p 'test_*.py' -v
```

Команда конкретного Android-класса в запущенном API35-эмуляторе:

```bash
gradle --no-daemon :app:connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.class=com.openai.fxm1.R732ChartStateUiTest
```

Последний аргумент заменяется точным классом соответствующей задачи. Все новые Android-тесты затем входят в полный актуальный набор, а не заменяют его.

## Договор данных между задачами

Создать `mt5_bridge/event_core/scenarios/pattern_view.py`. Его публичный объект:

`PatternCatalog.update(bars, live_bar, *, symbol, timeframe, mode, scope, clock_generation, now, scenarios) -> dict`.

`scenarios` — текущие записи существующего ScenarioCore, переданные только для чтения. Результат присоединяется к `forecast.pattern_chart`, не к списку кандидатов исполнения.

Обязательные поля `pattern_chart`:

| Поле | Значение |
|---|---|
| `version` | `1` |
| `scope`, `symbol`, `timeframe`, `mode`, `history_clock` | Идентичность полученных данных; смена любого поля изолирует каталог |
| `data_asof`, `source_revision` | Время наблюдения и хеш фактически использованных OHLC, включая поправки истории |
| `available`, `reason` | При отсутствии пригодных данных — явная причина, без синтетических фигур |
| `patterns` | Не более 32 записей текущего каталога: актуальные и последние отменённые; без бессрочного накопления |

Запись фигуры: `view_id`, `execution_pattern_id` либо null, `family`, `variant`, `title`, `geometry_state`, `first_seen_at`, `confirmed_at` либо null, `updated_at`, `reason`, `anchors`, `segments`, `start_at`, `end_at`, `scenario_ids`.

`geometry_state`: `FORMING`, `DETECTED`, `INVALIDATED` или `EXPIRED`. Геометрический статус не заменяет стадию сценарной ветки. `view_id` сохраняется при движении последнего предварительного экстремума и его подтверждении; при смене семейства/варианта или подтверждённого опорного префикса создаётся другая запись, а не переименовывается прежняя.

Опорная точка: `time`, `price`, `kind`, `role`, `provisional`, `observed_at`, `confirmed_at` либо null. Роли: `TOUCH_HIGH`, `TOUCH_LOW`, `LEFT_SHOULDER`, `HEAD`, `RIGHT_SHOULDER`, `NECK`, `TOP_1..3`, `BOTTOM_1..3`, `POLE_START`, `POLE_END`.

Отрезок: `role`, `from_time`, `from_price`, `to_time`, `to_price`, `provisional`. Роли: `UPPER`, `LOWER`, `NECKLINE`, `STRUCTURE`, `POLE`. Цена — наблюдавшаяся либо значение подписанной геометрической линии; нельзя выдавать интерполированную линию за OHLC. Время геометрии не выходит в ненаблюдавшееся будущее.

Сценарные ветки и условные будущие узлы остаются в существующем `forecast.scenarios`: их идентификаторы, `remaining_path()`, цели и условия не создаются заново ради картинки. Дополнительные поля результата/пояснения — только для чтения, вне входных фильтров и управления позицией.

### Задача 1. Проверяемая база и работоспособная подписанная Android-проверка

**Файлы:** создать `.github/workflows/r732-check.yml`, `tools/run_r732_native.sh`, `app/src/androidTest/java/com/openai/fxm1/R732ChartStateUiTest.java`. Прочитать, но не подменять старые `tools/run_r7_native.sh`, `app/build.gradle` и успешный signing workflow.

**Интерфейсы:** принимает закреплённый `source_sha`; выдаёт отчёты Python, JUnit XML, результаты установки APK и идентификатор реально проверенного commit. Это ещё не release-пакет.

- [ ] Сравнить текущие HEAD с закреплённой базой; записать отличия в `docs/verification/R732_BASELINE.md`. Запустить полные базовые Python- и Android-наборы. Не приписывать этой работе прежние результаты.
- [ ] Написать `serverForbidsAnalogueAfterRefresh`: создать реальный `SparklineView`, передать корректный forecast с `show_price_forecast=false`, повторить `setMarket()`, проверить `displayedForecast()` и отсутствие синего пути. На старой базе тест обязан поймать принудительное включение; на ветке с уже убранным renderer отдельно проверяется ошибочный итоговый флаг.
- [ ] Исполнить regression на старом исходном commit `61bfe866…` и сохранить RED-лог; тестовое изменение не выдавать за изменение старого релиза.
- [ ] Сначала проверить доступ к прежней подписи: восстановить ключ только в доверенном контексте CI и проверить указанный сертификат. Для существующего branch-scoped кэша использовать разрешённый контекст, например same-repository PR в ветку-владелец `feature/r4-compute-rebuild`, с checkout точного `head.sha`, а не неявного merge commit. PR не сливать. Не повторять заведомый cache-miss на соседней ветке.
- [ ] Если ключ действительно отсутствует, остановить выпуск: не создавать заменяющий сертификат и не объявлять готовым Bridge-only. Не выгружать ключ в artifacts, репозиторий или чат; не создавать новые копии секрета в публичном кэше.
- [ ] В новом runner сохранить код завершения тестов отдельно от необязательного `adb logcat`; timeout/ошибка logcat не превращаются ни в провал пройденных тестов, ни в успех проваленных. PNG приёмки и XML обязательны; отсутствие их блокирует выпуск.
- [ ] Проверить runner отдельным тестом на провал Gradle, отсутствующий XML/PNG и ошибку logcat. Commit: `test(r732): reproduce graph reset and pin native verification`.

Минимальная проверка в `serverForbidsAnalogueAfterRefresh` после двух вызовов `setMarket()`:

```java
assertFalse(chart.displayedForecast().optBoolean("show_price_forecast", true));
assertEquals("Исходный снимок не изменён", serverSnapshotBefore, serverSnapshot.toString());
```

### Задача 2. Единый выбор отображения в APK

**Файлы:** изменить `SparklineView.java`, `ScenarioUi.java`, `PriceForecastPlot.java`; создать `ChartDisplayState.java`; расширить `R732ChartStateUiTest.java`. Java-пути здесь и далее относительны `app/src/main/java/com/openai/fxm1/`, тестовые — `app/src/androidTest/java/com/openai/fxm1/`.

**Интерфейсы:** `ChartDisplayState.load(SharedPreferences, String scopeKey)` и `save(SharedPreferences, String scopeKey)`; состояние `mode` = `PATTERNS` или `CANDLES`, `selectedPatternId`, `selectedScenarioIds`, `manualViewport`, `visibleBars`, `rightEdgeTime`, `followingLive`. Ключ — хеш адреса Bridge, аккаунта, инструмента, режима, периода и history_clock; токен в ключ/лог не писать.

- [ ] Написать тесты `defaultIsPatterns`, `serverFalseCannotBeOverriddenByRefresh`, `recreationRestoresMode`, `newInstrumentDoesNotInheritSelection`, `twoSurfacesUseOneChoice`. Проверять настоящий объект графика и Activity recreation; не только копию JSON.
- [ ] Подтвердить RED. Локальный `true` больше не имеет права перезаписывать запрет сервера.
- [ ] Реализовать основной режим фигур и режим чистых свечей. Существующую кнопку «ПРОГНОЗ» направить на условные структурные сценарии; кнопки «СЦЕНАРИИ»/«ВЕТКИ» сохраняют свой доступ к веткам. Аналоговые исследования остаются в Bridge/API и не рисуются поверх основного графика. Подписи и accessibility описывают реально выбранный режим.
- [ ] Проверить обновление, background/foreground, поворот и пересоздание Activity, открытие полноэкранного графика, отсутствие API-команд при переключении. Данные server snapshot не мутировать.
- [ ] Запустить новый класс и прежние `R7ReleaseUiTest`, `R73ChartUiTest`, тесты отображения сценариев. Устаревшие требования «веер должен быть виден в WAIT» заменить явным новым договором, сохранив проверки идентичности и свежести. Commit: `fix(android): make pattern display state authoritative`.

Проверка после пересоздания Activity в `recreationRestoresMode`:

```java
assertEquals("PATTERNS", ChartDisplayState.load(prefs, scopeKey).mode);
assertFalse(recreatedChart.displayedForecast().optBoolean("show_price_forecast", true));
```

### Задача 3. Каталог 19 фигур, включая предварительную разметку

**Файлы:** создать `scenarios/pattern_view.py`, `tests/event_core/pattern_fixtures_r732.py`, `tests/event_core/test_r732_pattern_catalog.py`; изменить только необходимое выделение общих вычислений в `scenarios/structure.py`. Все Python-пути производственного кода относительны `mt5_bridge/event_core/`.

**Интерфейсы:** реализует `PatternCatalog.update(...)` по договору выше. Существующий `detect_patterns(...)` сохраняет геометрические критерии и результат для подтверждённых данных. Общие чистые функции принимают явные точки и время наблюдения; никаких вызовов MT5 внутри каталога.

- [ ] Зафиксировать fixtures для точных пар: TRIANGLE/{ASCENDING,DESCENDING,SYMMETRIC}, FLAG/{BULL,BEAR}, PENNANT/{BULL,BEAR}, CHANNEL/{RISING,FALLING}, RANGE/HORIZONTAL, WEDGE/{RISING,FALLING}, BROADENING/EXPANDING, MULTI_EXTREME/{DOUBLE_TOP,TRIPLE_TOP,DOUBLE_BOTTOM,TRIPLE_BOTTOM}, HEAD_SHOULDERS/{TOP,INVERSE}. Ровно 19, каждую пару учитывать отдельно в отчёте.
- [ ] Для каждого варианта написать `positive_geometry`, `near_miss_rejected`, `prefix_visibility`. Использовать числовую историю, не заранее подставленный ответ детектора. Отрицательные примеры: отсутствующий флагшток, равные голова/плечи, неверное чередование, несходящиеся клинья, неравные вершины вне прежнего допуска, монотонная и плоская история.
- [ ] Написать `forming_last_anchor_is_provisional`, `confirmed_at_not_before_right_bars_close`, `outside_bar_does_not_invent_intrabar_order`, `moving_candidate_keeps_identity`, `history_correction_starts_new_revision`. RED должен выявлять недостающую разметку/статусы, не отсутствие fixture-файла.
- [ ] Построить подтверждённый каталог из существующего детектора. Для предварительного варианта использовать только последний уже наблюдавшийся H/L из `model.live_structure`, исключить точку `LIVE` и неоднозначный порядок двух экстремумов одной свечи. Повторно применить те же геометрические проверки к подтверждённому префиксу и одному предварительному концу; не генерировать ненаблюдавшееся плечо или касание.
- [ ] Предварительную запись никогда не передавать в `create_scenarios`, `_rank`, направление или риск. Присвоить роли точкам и сегментам для каждого семейства, включая настоящий POLE_START/END. Если полная геометрия по наблюдаемым точкам ещё не проходит — показать отсутствие подходящей фигуры, а не ослаблять пороги ради постоянной картинки.
- [ ] Проверить все fixtures при двух направлениях, преобразованиях цены EURUSD/USDJPY/XAUUSD/BTCUSD и календарных TF. Запустить `test_r732_pattern_catalog` и полную серверную регрессию. Commit: `feat(chart): expose causal confirmed and forming pattern geometry`.

Проверки результата `catalog.update(...)` на fixture с последним неподтверждённым экстремумом:

```python
self.assertEqual(view["geometry_state"], "FORMING")
self.assertIsNone(view["confirmed_at"])
self.assertEqual(view["scenario_ids"], [])
self.assertTrue(view["anchors"][-1]["provisional"])
self.assertLessEqual(view["anchors"][-1]["observed_at"], now)
```

### Задача 4. Данные фигур, стадии веток и неизменное исполнение

**Файлы:** изменить `scenarios/core.py`, `engine.py`, `observers.py`; при необходимости дополнить read-only представление в `scenarios/pattern_view.py`; создать `tests/event_core/test_r732_pattern_integration.py`, `tests/event_core/test_r732_pattern_replay.py`. Существующие `scenarios/lifecycle.py`, `Store.save_scenario_snapshot()` и протокол торговых команд использовать как источник, не переписывать торговый автомат ради визуализации.

**Интерфейсы:** `ScenarioCore.evaluate()` добавляет `forecast.pattern_chart`. `Engine.snapshot()` и `ForecastObservers.frame()` возвращают его согласованную копию. Архивный `forecast` сохраняет разметку того же снимка. У веток добавляется read-only `display_outcome` = `PENDING`, `TARGET_REACHED`, `INVALIDATED`, `EXPIRED`, `UNKNOWN`, с `evidence_time` и `reason`; это не меняет `status`, `entry_ready` или заявку.

- [ ] Написать `pattern_visible_when_entry_waits`, `viewer_reads_do_not_change_execution`, `observer_cannot_contaminate_trade_archive`, `snapshot_deep_copy`, `expired_branch_is_not_current`, `same_bar_target_and_cancel_is_unknown_without_ticks`. На двух независимых прогонах сравнить торговые event_id, заявки, объёмы и причины блокировки с включённым и отключённым дополнительным отображением.
- [ ] Проверить точные последовательности: DIRECT_BREAKOUT без ретеста; BREAKOUT_RETEST только после возврата; FALSE_BREAK_RETURN после выхода и возврата; CHANNEL_REJECTION/RANGE_ROTATION после касания и реакции. Их пути обязаны различаться. Первая котировка за уровнем и движение самой линии не создают пробой.
- [ ] Присоединить каталог независимо от `_rank(active)`. Связать найденную фигуру с реальными scenario_id, а не создавать ложную альтернативу. Для предварительной фигуры scenario_ids пуст. Отменённые записи оставить с причиной для просмотра, не возвращать в кандидаты исполнения.
- [ ] Сохранять добавленную разметку в существующем архиве торгового периода при первом появлении, изменении стадии и новой закрытой свече; не писать всю историю на каждый тик. Снимок входа и уже сохранённые записи не перерисовывать. Независимые TF-наблюдатели не пишут торговый архив.
- [ ] Replay проверяет начало наблюдения, переходы, пропущенные тики, перезапуск, чужой аккаунт и поправку OHLC. Цель считается наблюдавшейся после подтверждения соответствующей ветки. При недостатке порядка событий — `UNKNOWN`, не успешная сделка задним числом. Календари MN1 брать из `bar_close_time`, не из 30×24 часов.
- [ ] Проверить `/ec/state`, `/ec/forecast?tf=...`, архив: read-only контракт, корректную scope/clock идентичность, stale/offline и отсутствие дополнительных брокерских чтений. Выполнить новые тесты и полную серверную регрессию. Commit: `feat(bridge): publish pattern views independently of entry gates`.

Проверки после обычных read-only запросов в `viewer_reads_do_not_change_execution`:

```python
self.assertEqual(broker.sent, sent_before)
self.assertEqual(engine.auto, auto_before)
self.assertEqual(store.load("engine"), saved_engine_before)
self.assertTrue(response["forecast"]["pattern_chart"]["patterns"])
```

### Задача 5. Реальная разметка Canvas и согласованные пояснения

**Файлы:** создать `PatternOverlayRenderer.java`, `PatternChartModel.java`, `R732PatternRendererUiTest.java` и тестовый `PatternTestCanvas.java` (запись текста, координат, штриховки и цветов без изменений production Canvas); изменить `ScenarioMapRenderer.java`, `SparklineView.java`, `ScenarioUi.java`, `TimeframeViewer.java`.

**Интерфейсы:** `PatternChartModel.fromSnapshot(JSONObject state)` валидирует `pattern_chart`; `PatternOverlayRenderer.draw(Canvas, PatternChartModel, ChartTransform, String selectedId)` рисует только геометрию. Создать `ChartTransform.java` с `x(long time)`, `y(double price)`, `plotBounds()`; тот же transform используется свечами и разметкой. Границы не получают другой масштаб, чем OHLC.

- [ ] Написать параметризованные native-тесты 19 вариантов. Проверять точные подписи, попадание концов линий в ожидаемые координаты, пунктир предварительной части, линию шеи и флагшток. Записывающий Canvas и проверка пикселей дополняют друг друга; строки JSON не считаются нарисованной фигурой.
- [ ] Написать `no_blue_band_even_with_research_data`, `wait_with_detected_pattern_has_specific_reason`, `position_levels_keep_broker_values`, `wrong_scope_hides_overlay_not_candles`, `future_nodes_are_conditional`. Реализовать разметку после RED.
- [ ] На основном графике показывать выбранную фигуру и не более двух связанных условных веток. Подготовка — нейтральный пунктир, условный путь после подтверждения — цвет ветки; фактическое исполнение MT5 — отдельные Entry/SL/тикет/P&L. Не рисовать T2, отсутствующий в данных. Структурные этапы не подписывать как точное ETA.
- [ ] Заголовок, summary TimeframeViewer, подробности и accessibility строить из одного принятого снимка и выбранной фигуры. `FORMING`/`DETECTED` при WAIT не получают «нет ясной структуры». Отсутствие нового поля у старого Bridge — совместимый показ прежней карты либо явное «разметка недоступна», не сбой.
- [ ] На ширинах 320/360/412 dp и увеличенном системном шрифте проверять цену без обрезания, пересечения подписей и читаемость плеч/шеи. Непоместившиеся пояснения доступны через подробности; подписи не исчезают молча.
- [ ] Выполнить новый класс и полную актуальную Android-регрессию. Сохранить native PNG с указанием fixture и source_sha. Commit: `feat(android): draw labelled market patterns on MT5 candles`.

`PatternTestCanvas.hasText(String)` проверяет фактически вызванную отрисовку текста; пример для обычной головы и плеч:

```java
assertTrue(canvas.hasText("Левое плечо"));
assertTrue(canvas.hasText("Голова"));
assertTrue(canvas.hasText("Правое плечо"));
assertTrue(canvas.hasText("Линия шеи"));
```

### Задача 6. Вся фигура, периоды, история и сохранение выбора

**Файлы:** изменить `ChartViewport.java`, `ChartDisplayState.java`, `SparklineView.java`, `ScenarioUi.java`, `TimeframeViewer.java`; создать `R732PatternNavigationUiTest.java`.

**Интерфейсы:** `ChartViewport.fitRange(long firstTime, long lastTime)`; `snapshotState()`/`restoreState(JSONObject)` для видимого количества свечей, правой временной границы и LIVE. Кнопка `ВСЯ ФИГУРА` вызывает fitRange по `start_at/end_at`, включая флагшток. `ФИГУРЫ` выбирает запись каталога, существующие `ВЕТКИ` выбирают сценарии.

- [ ] RED-тесты `fitIncludesPoleAndLastAnchor`, `newTicksDoNotResetManualViewport`, `recreationRestoresExactHistoryEdge`, `frameSwitchRestoresOwnSelection`, `expiredSelectedPatternShowsReason`, `embeddedAndFullscreenKeepSelection`.
- [ ] Fit выполняется по явному действию, не при каждом refresh. Использовать весь уже загруженный диапазон, включая более 240 свечей при необходимости. При недостающих свечах — существующая загрузка истории и явный прогресс; запрещено сжимать фигуру в точку или тайно подставлять другой период.
- [ ] Возврат в LIVE не включает AUTO. Прокрутка, масштаб, выбор фигуры/ветки, полноэкранное окно и чтение архива не вызывают команды торговли. Старый ответ A после переключения на B не изменяет график, даже если символ записан с другим форматированием.
- [ ] Матрица: девять выбираемых TF × четыре инструмента; отдельно EUR/USD ↔ EURUSD, подтверждённый broker alias, W1/MN1, другой account/clock, offline/reconnect и повторное открытие приложения. Архив не получает сегодняшние фигуры поверх вчерашних свечей.
- [ ] Выполнить новые и все актуальные Android-тесты, включая кнопки, уведомления, журнал, позиции, AUTO/PAUSE/Emergency. Commit: `feat(chart): preserve scoped navigation and fit complete patterns`.

Пример проверки `newTicksDoNotResetManualViewport`, где `savedEdge` и `savedCount` взяты после ручной прокрутки:

```java
viewport.merge(newBars);
assertEquals(savedEdge, viewport.edge());
assertEquals(savedCount, viewport.visible());
assertFalse(viewport.live());
```

### Задача 7. Полный Bridge без разрушительного установщика

**Файлы:** создать `mt5_bridge/ready_launcher.py`, `tools/package_r732.py`, `tools/windows_r732_gate.py`, `tests/event_core/test_r732_ready_package.py`; изменить выпускаемую копию `START_BRIDGE_V10_0.bat` и версии в `event_core/__init__.py`, `app/build.gradle`. Старые архивы/установщики не подменять файлами с тем же названием.

**Интерфейсы:** `resolve_runtime(root: Path) -> RuntimePaths` возвращает проверенные `python`, `program_root`, `state_dir`; `check_runtime(paths) -> dict` не подключается к торговле; `launch(paths, server_args: list[str]) -> int`. Папка выпуска `mt5_bridge_R732`; существующая sibling `mt5_bridge` — источник среды и состояния, не источник кода.

- [ ] RED-тесты: недоступный `old/event_core/.../__pycache__`; недоступный кэш Colorama при исправном импорте; путь с пробелами/кириллицей/`!`; отсутствие либо неоднозначность состояния; сломанная среда; другая папка запуска; отравляющий PYTHONPATH; занятая общая runtime.lock.
- [ ] Разрешение пути использует только явно заданную рабочую пару или подтверждённую sibling-папку. При отсутствии существующего состояния — остановка, не `mkdir event_state`. Не сканировать рекурсивно домашние папки и не выбирать найденную базу по дате.
- [ ] Запускать существующий 64-битный Python, без установки/копирования Colorama при исправном импорте. `event_core` обязан происходить из новой папки; `__file__` проверяется. Не удалять старые каталоги, не копировать `.venv`, не изменять базу/ключ/часы в preflight; сохранить действующую общую блокировку. Не выключать защитное ПО и не повышать права автоматически.
- [ ] Проверить на native Windows CMD: `--check`, `--diagnose`, `--help`, код возврата, несовместимую версию Python и сохранность контрольных байтов состояния. Реальный торговый сервер не включать в тест ради запуска.
- [ ] `package_r732.py` собирает из одного закреплённого commit полный runtime с launcher, зависимостями, действительно нужными конфигурациями/ресурсами и APK. Пользовательские данные, кэши и ключ подписи исключены. Хеши вычисляются после последней записи BUILD.json; проверка архивов выполняется после распаковки, не по исходной папке.
- [ ] Приёмка выпуска проверяет 933, versionName, applicationId и сертификат. Если 933 уже занят другой работой, выпуск остановить для согласования номера, не переименовывать старые байты. Commit: `fix(delivery): preserve existing runtime and package exact R732 sources`.

Пример `missing_state_never_creates_a_new_history`: `old_state` отсутствует, `package_root` и существующий Python созданы в тестовой временной папке:

```python
with self.assertRaises(RuntimeError):
    resolve_runtime(package_root)
self.assertFalse(old_state.exists())
```

### Задача 8. Сквозная приёмка и выдача тех же проверенных файлов

**Файлы:** дополнить `.github/workflows/r732-check.yml`, `tools/run_r732_native.sh`, `tools/package_r732.py`; создать `tools/r732_acceptance_report.py`, `docs/verification/R732_ACCEPTANCE.md`, `tests/event_core/test_r732_acceptance_report.py`. Исходные тесты функциональности не отключать для зелёной сборки.

**Интерфейсы:** `build_report(evidence_dir: Path, expected_sha: str) -> dict` читает логи Python, JUnit XML, Windows JSON, PNG и provenance; выдаёт `R732_RESULT.json` с полями `release_allowed` и `gates` (24 gate_id со статусами PASS/FAIL/NOT_RUN). Отсутствие evidence — NOT_RUN и запрет выпуска, не PASS. Список 19 вариантов берётся из фиксированного перечня задачи 3.

- [ ] Написать RED-тесты самого отчёта: один отсутствующий вариант, пропущенный тест, нулевое число Android-тестов, неверный SHA, APK после пересборки, отсутствующий PNG, ошибка подписи и различие runtime внутри ZIP.
- [ ] Запустить весь Python-набор, весь актуальный EventCore Android-набор на API35 и Windows-проверки на финальном commit. Единственное прежнее исключение `V108RepairTest` документируется как удалённый протокол, не как пройденный тест. Каждый иной skip перечисляется и не закрывает обязательную проверку.
- [ ] Выгрузить результаты реального PatternCatalog из числовых OHLC fixtures в тестовый сервер; показать их через обычный путь приложения. Не подменять весь forecast вручную ради итоговых картинок. Для всех 19 вариантов получить реальные Android-снимки; дополнительно — полный экран Activity с формированием, отсутствием фигуры, stale/offline, архивом и фактической тестовой позицией.
- [ ] Визуально просмотреть PNG, записать результат по каждой группе. Отдельно проверить что строки «голова/плечи», «линия шеи», «флагшток» действительно видны и привязаны к соответствующим свечам. Изображения, сгенерированные художником или image_gen, не являются проверкой APK.
- [ ] Повторно распаковать готовые архивы, сверить SHA каждого runtime-файла с закреплённым исходником и APK с тем бинарником, на котором прошёл Android-набор. После тестов APK не пересобирать. Отдельно поставить именно эти байты поверх предыдущего APK 931 на эмуляторе, проверить сохранённые настройки и выключенный AUTO.
- [ ] Завершить отчёт ограничений: имитатор брокера ≠ живой терминал; Windows CI ≠ компьютер пользователя; эмулятор ≠ физический телефон. Не заявлять измеренную доходность/точность, которых нет.
- [ ] Выдать `FXM1_R7_3_2.apk` и `FXM1_R7_3_2_Bridge.zip`; при желании пользователя — один общий ZIP с теми же файлами. Исходники и evidence доступны отдельным архивом, но не требуют дополнительных шагов установки. Проверить существование ссылок. Commit отчёта не меняет идентичность исходного tested commit: provenance содержит отдельно source_sha и report_commit.

Проверка отчёта при удалении одного обязательного native PNG из тестового evidence:

```python
report = build_report(evidence_dir, expected_sha)
self.assertFalse(report["release_allowed"])
self.assertNotEqual(report["gates"]["22"]["status"], "PASS")
```

## Покрытие всех 24 пунктов приёмки

| Gate | Задачи | Какое доказательство обязательно |
|---|---|---|
| 01 | 1–2 | RED старого графика и GREEN нового итогового флага/Canvas |
| 02 | 2, 6 | Запрет сервера, refresh, recreation, смена поверхности |
| 03 | 3, 8 | Положительный, отрицательный и префиксный случай каждой из 19 пар |
| 04 | 3, 5 | Флагшток, плечи/голова и прочие специальные условия + native-разметка |
| 05 | 3–4 | FORMING виден, а число торговых заявок от него не меняется |
| 06 | 3, 5 | Предварительный экстремум, confirmed_at=null и пунктир |
| 07 | 3, 5 | Роли, времена, цены и координаты Canvas |
| 08 | 3–4 | Replay без будущих данных; сохранённый снимок не изменяется |
| 09 | 4 | Независимые этапы и исходы каждой ветки |
| 10 | 4–5 | Разные последовательности direct/retest/false-break/rejection |
| 11 | 3–5 | Отрицательные примеры, пустая альтернатива, отсутствующий T2 |
| 12 | 5 | Заголовок, summary, план входа и фигура из одного снимка |
| 13 | 6 | Fit целой фигуры, флагшток, неизменный manual viewport |
| 14 | 6, 8 | LIVE/history/fullscreen/archive/выбор на реальном приложении |
| 15 | 3–4, 6 | Девять TF и календарные W1/MN1 |
| 16 | 3, 5–6 | Четыре инструмента, digits и подтверждённые broker aliases |
| 17 | 4–6 | Чужие/старые ответы, stale/offline/reconnect |
| 18 | 5, 8 | Фактические Entry/SL/тикет/P&L отдельно от сценария |
| 19 | 2, 4, 6 | Сравнение команд, профиля, AUTO, риска и кампании |
| 20 | 4, 8 | Полный Python-лог, явные skips и торговые регрессии |
| 21 | 8 | Полный актуальный Android JUnit без скрытых пропусков |
| 22 | 5, 8 | Native PNG всех вариантов + полные экраны Activity, визуальный просмотр |
| 23 | 7 | Native Windows CMD и неизменность старых файлов |
| 24 | 1, 7–8 | Сертификат, versions, исходный commit, распаковка и все хеши |

## Проверка самого плана и следующий шаг

Проверить ссылки задач на договор данных, покрытие 01–24 и отсутствие обещаний о ещё не выполненных тестах. Кодовую реализацию начинать после проверки этого плана пользователем.

Предлагаемый способ исполнения: последовательно в этой сессии через имеющиеся инструменты, с отдельным коммитом и результатом проверки на каждую задачу. Независимый агент-рецензент здесь не считается доступным и его проверка не обещается. Самопроверка diff и автоматизированные проверки обязательны; при появлении отдельного рецензента его замечания фиксируются отдельно.

Технические источники для плана: ограничения доступа к Actions cache — GitHub Docs, `https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching`; совместимость подписи обновлений — Android Developers, `https://developer.android.com/studio/publish/app-signing`. Проверены 05.10.2026. Доступность прежнего ключа устанавливается фактическим CI, а не выводится из документации.
