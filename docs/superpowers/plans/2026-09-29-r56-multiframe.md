# R5.6 independent timeframe forecasts and visible live state

User request: verify the apparently unchanged forecast and positions; provide independent forecasts for M1/M5/M15/M30/H1 and higher frames which complement each other; remove M10 from selectable frames.

## Design and constraints

- Selectable frames: M1, M5, M15, M30, H1, H4, D1, W1, MN1. Preserve legacy M10 history and open campaigns; never reinterpret saved index 2 as another trading frame without migration. REAL remains disabled. No new order or risk relaxation is authorized.
- Each forecast uses that frame's own closed bars, forming bar, independent ScenarioCore state and normalized MT5 clock. No rescaled M5 chart. Selected trade frame remains the only executable decision owner. Other frames are observation-only; viewing one cannot send a config/AUTO/order command.
- Maintain independent observer forecasts in the Engine loop, bounded refresh work, isolated by account/symbol/clock/mode. Existing selected-frame path stays compatible. A failure in a remote frame is shown for that frame and must not fabricate candles or erase valid unrelated data.
- Return `timeframes` overview rows in state: `timeframe`, `available`, `side`, `stage`, `title`, `next_event`, `data_asof`, `analysis_time`, `reason`. Add read-only `/ec/forecast?tf=FRAME` returning a standard chart-state shape (`config.timeframe`, `bars`, `live_bar`, `live_structure`, `forecast`, `decision`, `market_scope`, `market_history_generation`, account/source identity) plus `view_only=true`, `trade_timeframe`. Unavailable responses must retain frame identity and an explicit reason. Selected frame endpoint may use the actual selected engine snapshot.
- Chart viewing frame is local UI state, separate from the trade-entry selector. Main and enlarged charts share robust source/account/symbol/clock/frame guards. Cross-frame overview explains support/opposition/neutrality using independently computed data; does not manufacture probabilities or silently change execution gates.
- LIVE structure on all frames. Show actual data time and scenario stage/next event so an unchanged hypothesis is distinguishable from stale prices. For v3 charts remove misleading generic BUY/SELL triggers when they do not belong to the displayed scenario. Preserve archived snapshots and actual timestamps.
- Screenshot evidence: 18:17 ->18:26 candles and provisional structure changed, score64->62, same false-break-return hypothesis awaits1.13584; positions0, equity=balance99843.59, today2closed/+1.52. This is not proof of engine freeze or failed order. Verify entry chain, don't force trade.

## Work and ownership

1. Backend: model/adapter frame support, Engine observer bank and endpoint; RED→GREEN tests for M30, independent series/scenarios, per-frame updates, LIVE payload, stale-data isolation, account/profile/clock changes, no extra order commands. Files mt5_bridge/event_core and backend tests (avoid UI fixture unless coordinated).
2. Android: stable named frame choices and old-index migration, independent chart viewer and context overview using agreed payload; guards and native interaction tests. Files app/ and new tests. Do not change ScenarioMapRenderer (root owns its annotations).
3. Root: chart annotations, inspect entry/positions chain and add substantive regression if uncovered, integrate fixture, release metadata/build925/R5.6, source/signature packaging.
4. Verification: full backend suite, all existing Android tests plus new native MTF switching tests on API35, inspect actual screenshots of M1/M5/M15/M30/H1 graphs with distinct datasets. Fresh final code review. Resolve important findings before package.
5. Deliver complete matching APK+Bridge archive, hashes, exact source and evidence; preserve event_state/.venv and broker-clock.json.

## Rulings and progress

- Existing user authorization covers implementing requested fixes and routine isolated feature work. No extra confirmation is needed for these reversible project changes.
- Independent backend and Android implementation tasks have a fixed contract above; use parallel-agent skill for these disjoint files, then integrate and review.
- Base:81f4bdb (R5.5 source tree matches deployed release). Working directory:/workspace/scratch/2435d8025773/r56.
