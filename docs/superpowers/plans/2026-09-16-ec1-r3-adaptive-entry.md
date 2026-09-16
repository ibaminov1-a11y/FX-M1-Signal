# EC1 R3 Adaptive Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the R3 adaptive M5 entry engine with IMPULSE, CONTINUATION and classic PULLBACK paths while preserving DEMO-only execution, campaign-wide risk, no averaging down, and the current Android/Bridge architecture.

**Architecture:** Keep Bridge/EventCore authoritative. Extend the MT5 market snapshot so M5 decisions receive closed M5/M15/H1/M1 bars plus the current live M5 bar and current quote. Keep confirmed swing structure forward-only; add live IMPULSE and shallow CONTINUATION evaluation as separate deterministic paths, then expose structural overlays and the current path to Android without moving trading logic into the phone.

**Tech Stack:** Python 3.12 EventCore/Flask/MetaTrader5 adapter, unittest, Java Android app API 35, Gradle 8.9, Android instrumentation tests.

**Spec:** `docs/superpowers/specs/2026-09-16-ec1-r3-adaptive-entry-design.md`

## Global Constraints

- USD DEMO hedging only; REAL/CONTEST order paths stay blocked.
- M5 R3 only. Non-M5 timeframes keep the existing entry flow.
- IMPULSE thresholds: M5 body >= 0.70 ATR, range >= 1.00 ATR, body/range >= 0.65.
- IMPULSE requires confirmed M5 swing break, non-opposite H1/M15, a closed M1 confirmation beyond the level, and a live tick still beyond the break.
- CONTINUATION requires a shallow 0.10-0.35 ATR pause plus a fresh M1/tick continuation break.
- Classic PULLBACK remains >= 0.35 ATR.
- NORMAL setup lifetime becomes 3 M5 bars (15 minutes); the engine re-evaluates newer same-direction events instead of waiting out stale state.
- Additions remain event-driven, net-positive only, price-progress gated, campaign-budget limited; no fixed 10-position strategy cap.
- Existing risk, margin, spread, broker-SL, unknown-execution/recovery, Emergency and duplicate-event protections remain authoritative.
- Android renders real MT5 candles/levels only; never draw a future-price projection.

---

### Task 1: Extend the broker snapshot for live M5 + M1/M15/H1

**Files:**
- Modify: `mt5_bridge/event_core/mt5_adapter.py`
- Modify: `mt5_bridge/event_core/engine.py`
- Modify: `tests/event_core/fakes.py`
- Create: `tests/event_core/test_r3_market_snapshot.py`

**Interfaces:**
- Produces `MT5Broker.current_bar(symbol: str, tf: str) -> Bar` for the currently forming bar.
- Engine fields for M5 R3: `bars` (closed M5), `m1`, `m15`, `h1`, `live_bar`, `quote`.
- Existing `bars()` remains closed-bars-only and unchanged for structure calculations.

- [ ] **Step 1: Write failing snapshot tests**

```python
class R3MarketSnapshotTests(unittest.TestCase):
    def test_closed_history_never_contains_current_m5_bar(self):
        closed = broker.bars('EURUSD', 'M5')
        live = broker.current_bar('EURUSD', 'M5')
        self.assertLess(closed[-1].time, live.time)

    def test_engine_loads_m1_m5_m15_h1_and_live_m5(self):
        engine._refresh_market(now)
        self.assertTrue(engine.bars)
        self.assertTrue(engine.m1)
        self.assertTrue(engine.m15)
        self.assertTrue(engine.h1)
        self.assertIsNotNone(engine.live_bar)
```

- [ ] **Step 2: Run tests and confirm RED**

Run:
`PYTHONPATH=mt5_bridge:tests/event_core python -m unittest tests.event_core.test_r3_market_snapshot -v`

Expected: FAIL because `current_bar`, `m1`, `m15`, `h1`, or `live_bar` do not exist.

- [ ] **Step 3: Implement current-bar loading without polluting closed history**

In `MT5Broker.current_bar` request position 0 for one row, validate OHLC, and return it without adding it to `bars()`.

In `Engine.__init__` add:

```python
self.m1=[]; self.m15=[]; self.h1=[]; self.live_bar=None
```

For M5 only, `_refresh_market` refreshes closed M5/M1/M15/H1 plus `current_bar('M5')`. For other timeframes preserve the existing `bars/context` path.

- [ ] **Step 4: Make FakeBroker expose independent timeframe data**

Add `m1_data`, `m15_data`, `h1_data`, `live_m5` and return them by `tf`; keep old `bar_data/ctx_data` aliases so legacy tests do not break.

- [ ] **Step 5: Run snapshot and existing bar-loading tests**

Run:
`PYTHONPATH=mt5_bridge:tests/event_core python -m unittest tests.event_core.test_r3_market_snapshot tests.event_core.test_live_bar_loading tests.event_core.test_quote_clock_skew -v`

Expected: PASS.

---

### Task 2: Add deterministic R3 market-map primitives

**Files:**
- Modify: `mt5_bridge/event_core/model.py`
- Create: `tests/event_core/test_r3_market_map.py`

**Interfaces:**
- Add `swing_labels(bars) -> list[dict]` returning immutable confirmed pivots labelled `HH`, `HL`, `LH`, `LL`.
- Add `context_direction(bars) -> int` as a wrapper around confirmed pivots/direction.
- Extend `Decision` with `path: str = 'SEARCH'` and `structure: tuple = ()` while retaining existing fields and positional compatibility by appending new fields at the end.

- [ ] **Step 1: Write failing swing-label tests**

```python
def test_labels_are_based_only_on_confirmed_pivots(self):
    labels=swing_labels(self.bars)
    self.assertTrue(all(x['kind'] in ('HH','HL','LH','LL','H','L') for x in labels))
    self.assertTrue(all(x['known_at'] <= self.bars[-1].time for x in labels))

def test_neutral_context_is_zero(self):
    self.assertEqual(context_direction(self.range_bars), 0)
```

- [ ] **Step 2: Confirm RED, then implement helpers**

Use existing `pivots()`; never infer future pivots. Labels compare each confirmed high with the previous confirmed high and each low with the previous confirmed low.

- [ ] **Step 3: Add Decision path/structure serialization test**

```python
d=Decision(path='IMPULSE', structure=({'kind':'HH','price':1.2,'time':1},))
self.assertEqual(d.json()['path'],'IMPULSE')
```

- [ ] **Step 4: Run model + regression suites**

Run:
`PYTHONPATH=mt5_bridge:tests/event_core python -m unittest tests.event_core.test_r3_market_map tests.event_core.test_live_structure_regressions tests.event_core.test_model -v`

Expected: PASS.

---

### Task 3: Implement live IMPULSE entry before M5 close

**Files:**
- Modify: `mt5_bridge/event_core/strategy.py`
- Create: `tests/event_core/test_r3_impulse.py`

**Interfaces:**
- Change strategy call to accept R3 inputs without breaking non-M5:

```python
Strategy.update(bars, context, q, now, campaign_side=0, *, m1=None, m15=None, h1=None, live_bar=None)
```

- Add private helpers `_context_allows(side, m15, h1)`, `_impulse_candidate(...)`, `_entry_decision(...)`.
- IMPULSE events use stable ids derived from symbol/timeframe/live M5 opening time/side/path/broken level so repeated ticks cannot duplicate an order.

- [ ] **Step 1: Write RED tests for BUY and SELL live impulse**

Fixture requirements: closed M5 has confirmed swing level; live M5 body=0.75 ATR, range=1.05 ATR, body/range>0.65; last closed M1 closes beyond the broken swing; quote remains beyond level.

Assertions:

```python
self.assertEqual(d.phase,'ENTRY_READY')
self.assertEqual(d.path,'IMPULSE')
self.assertEqual(d.signal,'BUY')  # mirror for SELL
```

- [ ] **Step 2: Add blocking tests before implementation**

Cover: body <0.70 ATR; range <1.00 ATR; body ratio <0.65; missing M1 close; H1 opposite; M15 opposite; tick returned inside break; excessive no-chase distance. Every case must return WAIT/non-entry.

- [ ] **Step 3: Run IMPULSE tests and confirm RED**

Run:
`PYTHONPATH=mt5_bridge:tests/event_core python -m unittest tests.event_core.test_r3_impulse -v`

- [ ] **Step 4: Implement minimal IMPULSE path**

Rules in code are exactly the spec thresholds. Use ATR from **closed M5 bars**; measure the forming candle from `live_bar`; H1/M15 use confirmed pivots only; require latest closed M1 close beyond the M5 break. Compute stop from the most recent confirmed opposite swing/invalidation and existing pad, then emit `ENTRY_READY` only after all conditions hold.

- [ ] **Step 5: Verify no immediate duplicate on repeated ticks**

Call update repeatedly with the same live M5/event; after `consume(event_id)`, later identical ticks return WAIT/already processed.

- [ ] **Step 6: Run IMPULSE + existing entry tests**

Run:
`PYTHONPATH=mt5_bridge:tests/event_core python -m unittest tests.event_core.test_r3_impulse tests.event_core.test_full_flow tests.event_core.test_pullback_bootstrap -v`

Expected: PASS.

---

### Task 4: Implement CONTINUATION, preserve PULLBACK, reduce stale waiting

**Files:**
- Modify: `mt5_bridge/event_core/model.py`
- Modify: `mt5_bridge/event_core/strategy.py`
- Create: `tests/event_core/test_r3_continuation.py`
- Modify: `tests/event_core/test_pullback_bootstrap.py`

**Interfaces:**
- NORMAL `Profile.setup_bars` becomes `3`.
- CONTINUATION uses a confirmed M5 trend, retrace >=0.10 ATR and <0.35 ATR, at least one opposing/neutral M1 or M5 leg, then fresh continuation break.
- Existing PULLBACK >=0.35 ATR remains valid.

- [ ] **Step 1: Write RED tests for shallow continuation**

Test both sides. Verify a 0.20 ATR pause arms `CONTINUATION/TRIGGER`, and a fresh later tick crossing produces `ENTRY_READY` with `path='CONTINUATION'`.

- [ ] **Step 2: Write negative continuation tests**

No pause, pause <0.10 ATR, pause >=0.35 ATR (must use PULLBACK instead), opposite H1/M15, and same event replay must not create continuation entry.

- [ ] **Step 3: Write timeout and supersession tests**

```python
self.assertEqual(PROFILES['NORMAL'].setup_bars,3)
```

Advance beyond 3 M5 bars: stale setup cancels. Also test a pending PULLBACK being superseded by a new same-direction valid IMPULSE/CONTINUATION rather than waiting to expiry.

- [ ] **Step 4: Implement CONTINUATION and continuous re-evaluation**

Do not weaken PULLBACK. Re-evaluate R3 fast paths before returning a stale pending setup; cancel immediately on confirmed opposite context/structure.

- [ ] **Step 5: Run all strategy tests**

Run:
`PYTHONPATH=mt5_bridge:tests/event_core python -m unittest tests.event_core.test_r3_continuation tests.event_core.test_r3_impulse tests.event_core.test_pullback_bootstrap tests.event_core.test_live_structure_regressions tests.event_core.test_full_flow -v`

Expected: PASS.

---

### Task 5: Wire R3 decisions through Engine and preserve campaign/risk semantics

**Files:**
- Modify: `mt5_bridge/event_core/engine.py`
- Modify: `tests/event_core/fakes.py`
- Create: `tests/event_core/test_r3_engine_flow.py`
- Modify: `tests/event_core/test_risk_engine.py` only where fixture construction needs the new Decision fields.

**Interfaces:**
- For M5, `Engine.step()` calls Strategy with `m1`, `m15`, `h1`, `live_bar`.
- Non-M5 calls remain existing behavior.
- Snapshot exposes decision `path`, `structure`, and existing `levels`.
- `_entry()` remains the only order-sending gateway.

- [ ] **Step 1: Write end-to-end Engine tests**

Test actual Engine + FakeBroker: enable DEMO AUTO, feed a qualifying live IMPULSE and assert exactly one broker send before M5 close. Mirror SELL. Repeat same event/ticks and assert no duplicate.

- [ ] **Step 2: Test additions remain safe**

Create existing campaign/position. Verify new R3 event cannot add when campaign net <=0, cannot add without price progress, can add after a fresh event when net positive and risk budget permits, and 10 positions is not a strategy stop.

- [ ] **Step 3: Test legacy safety gates**

REAL blocked; unknown result latches recovery; foreign/manual positions are not managed; Emergency remains higher priority than R3 signal.

- [ ] **Step 4: Implement wiring only after RED tests exist**

Do not move sizing/risk checks into Strategy. Strategy emits intent; Engine `_entry` and `plan_order` keep final authority.

- [ ] **Step 5: Run full Python suite**

Run:
`python -m compileall -q mt5_bridge/event_core tests/event_core && PYTHONPATH=mt5_bridge:tests/event_core python -m unittest discover -s tests/event_core -p 'test_*.py' -v`

Expected: all tests pass, zero skips caused by R3.

---

### Task 6: Render the actual structure/path in Android

**Files:**
- Modify: `app/src/main/java/com/openai/fxm1/EventClient.java`
- Modify: `app/src/main/java/com/openai/fxm1/SparklineView.java`
- Modify: `app/src/main/java/com/openai/fxm1/MainActivity.java` only where state is passed to the chart/status.
- Modify: `app/src/androidTest/java/com/openai/fxm1/EventCoreUiTest.java`
- Modify: `tests/event_core/ui_fixture.py`

**Interfaces:**
- `EventClient.phaseName` recognizes `IMPULSE`, `CONTINUATION`, `PULLBACK`, `TRIGGER`.
- `SparklineView.setMarket(bars, levels, positions, structure, path)` receives only Bridge-computed overlays.
- Swing overlay elements contain `kind`, `time`, `price`; the view joins consecutive confirmed swing points and labels HH/HL/LH/LL.

- [ ] **Step 1: Write failing Android rendering test**

Feed deterministic candles + structure JSON and render `SparklineView` to Bitmap. Assert candle colors still exist and violet structure pixels/labels/path are rendered without a future bar.

- [ ] **Step 2: Add state text test**

Fixture returns decision `path='IMPULSE'`; assert UI context displays `IMPULSE`/Russian path text and still shows MT5 as source.

- [ ] **Step 3: Implement overlays**

Keep candle source unchanged. Draw thin violet structure lines, HH/HL/LH/LL labels, existing red invalidation/green trigger/violet level, and a small path label. No projected point after the last known/live candle.

- [ ] **Step 4: Preserve AUTO/background regression test**

Keep `transientOfflineAndActivityReturnDoNotDisableBridgeAuto` and notification/emergency tests unchanged and passing.

- [ ] **Step 5: Run Android build + emulator tests**

Run:
`gradle --no-daemon :app:assembleDebug :app:assembleDebugAndroidTest`

Then:
`bash tools/run_ec1_qa.sh`

Expected: build success and all instrumentation tests pass.

---

### Task 7: Version, docs, CI and verified release artifact

**Files:**
- Modify: `mt5_bridge/event_core/__init__.py`
- Modify: `docs/EVENT_CORE_RU.md`
- Modify: `docs/INSTALL_EC1_RU.md`
- Create or modify: `.github/workflows/ec1-r3-check.yml`
- Modify: `tools/package_ec1.py` only for R3 naming/provenance if required.

**Interfaces:**
- Keep protocol/version compatibility contract `VERSION='10.9-EC1'` unless API compatibility actually changes.
- Set build identity to `10.9-EC1-R3`.
- Artifact metadata records exact commit and APK SHA-256.

- [ ] **Step 1: Update documentation to remove stale R2/$100/40-minute wording**

Document the three paths, H1/M15/M5/M1 hierarchy, live M5 impulse thresholds, 15-minute NORMAL setup lifetime, actual MT5 account risk base, dynamic additions, and phone/Bridge responsibilities.

- [ ] **Step 2: Add R3 CI workflow**

Trigger on `feature/ec1-r3-adaptive-entry` and manual dispatch. Run full Python suite, signed debug APK build, API-35 emulator tests, packaging, build identity grep, SHA-256, artifact upload.

- [ ] **Step 3: Run CI from the exact final commit**

Do not package from a commit different from the one tested.

- [ ] **Step 4: Inspect job logs, not only workflow conclusion**

Confirm Python count/failures, Android test count/failures, `BUILD SUCCESSFUL`, packaging step success, and artifact presence.

- [ ] **Step 5: Download and inspect the workflow artifact**

Verify APK, Bridge folder, source/provenance, install notes, and no `event_state`, token, credentials or signing key are included.

- [ ] **Step 6: Release to the user only after verification**

Report exact commit, test counts, APK hash, what was emulator-tested, and that a physical Xiaomi/real-market profitability test is not implied.
