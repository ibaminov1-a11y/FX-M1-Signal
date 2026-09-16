# EC1 R3 Adaptive Entry Design

## Goal

Replace the single-path M5 entry flow with an adaptive three-path entry engine that can enter a genuinely strong live M5 impulse without waiting for a full pullback, can enter a trend continuation after only a shallow pause, and can still use the existing classic pullback path. Preserve DEMO-only execution, campaign risk controls, no averaging into loss, and independent Bridge execution.

## Scope

R3 changes the entry decision architecture for **M5**. It does not enable REAL trading. It does not remove campaign risk, broker SL checks, margin checks, spread checks, order-rate fuses, emergency stop, or execution reconciliation. Existing non-M5 entry timeframes remain on the existing EventCore flow until separately validated.

The Android UI remains the same violet theme. The chart gains structural overlays so the user can see what EventCore is calculating.

## Market hierarchy

For M5 entries EventCore uses four layers:

- **H1**: major directional map.
- **M15**: near-term context.
- **M5**: primary swing/structure chart.
- **M1 + live tick**: final execution trigger inside the current M5 candle.

M5 structure is based on confirmed swing highs/lows and HH/HL/LH/LL relationships. The engine may use the same visual idea as ZigZag, but it must never depend on a repainting ZigZag indicator. Confirmed pivots are immutable once known.

## Entry paths

### 1. IMPULSE

Purpose: catch a genuinely large current M5 candle before it closes.

A live M5 candle may qualify only when all conditions hold:

- body size >= **0.70 x M5 ATR(14)**;
- full high-low range >= **1.00 x M5 ATR(14)**;
- body/range ratio >= **0.65**;
- price has broken the latest confirmed M5 swing high for BUY or swing low for SELL;
- M5 structural direction is the same side, or a fresh structural break establishes that side;
- H1 and M15 are either neutral or aligned; a confirmed opposite direction blocks IMPULSE;
- the most recent closed M1 candle confirms the same side beyond the broken M5 level;
- the live tick is still beyond the break and has not exceeded the existing no-chase limit;
- spread, account, risk, margin, commission and broker-SL checks pass.

IMPULSE does **not** wait for the M5 candle to close. It may open the first campaign position during that same large M5 candle.

A single price spike is not enough. The M1 close beyond the level plus the live tick beyond the level provides the continuation confirmation.

### 2. CONTINUATION

Purpose: enter a strong trend that advances in steps without giving the classic NORMAL pullback.

A continuation candidate requires:

- confirmed M5 trend structure on the intended side;
- H1 and M15 not confirmed opposite;
- a shallow pause/retrace of at least **0.10 ATR** and less than the classic NORMAL pullback threshold **0.35 ATR**;
- the pause must contain at least one M1 or M5 opposing/neutral micro-leg rather than one uninterrupted spike;
- a fresh M1/tick break of the local continuation level in the trend direction;
- no-chase, spread, risk, margin and execution checks still pass.

CONTINUATION does not wait for a deep 0.35 ATR pullback.

### 3. PULLBACK

The classic path remains:

confirmed structure -> pullback/retest >= **0.35 ATR** -> fresh trigger -> entry.

The maximum NORMAL setup lifetime is reduced from 8 M5 bars to **3 M5 bars (15 minutes)**. SCALP setup lifetime remains shorter and is not widened by R3.

## Continuous re-evaluation

The engine must not become stuck in one phase until timeout.

On every new closed M5 bar and on live market refresh:

- SEARCH may become IMPULSE, CONTINUATION or PULLBACK.
- PULLBACK may be superseded by a same-direction IMPULSE/CONTINUATION if the market accelerates before the classic pullback completes.
- A confirmed opposite structural event cancels the stale setup immediately.
- A confirmed opposite H1 or M15 context cancels a new-entry setup immediately.
- Existing campaign management remains separate from new-entry setup state.

There is no 40-minute dead period after a missed setup.

## Context rules

For an M5 entry:

- H1 direction is the major context.
- M15 direction is the near context.
- A context direction of 0 is neutral and does not block.
- If either H1 or M15 is confirmed opposite to the proposed side, a **new** entry is blocked.
- Existing EC1 positions are still managed even when context turns opposite; management/exit logic decides what to do with an existing campaign.

## Campaign additions

The current event-driven pyramiding remains.

There is no strategy cap of 10 positions. An additional position requires:

- an existing EC1 campaign in the same direction;
- the campaign to be in net profit;
- price to have advanced enough from the previous entry;
- a **new** IMPULSE, CONTINUATION or PULLBACK event, not a repeated tick from the same event;
- total stop risk plus commission to remain inside the campaign budget;
- margin and technical fuses to pass.

R3 does not average down.

## Chart overlays

The Android M5 chart continues to render real MT5 candles. Add only deterministic overlays from EventCore:

- a thin line joining the last confirmed swing pivots;
- labels for recent HH/HL/LH/LL points;
- breakout/continuation level;
- trigger level;
- invalidation level;
- current path label: SEARCH / IMPULSE / CONTINUATION / PULLBACK / TRIGGER.

Green remains BUY/up, red remains SELL/down, violet remains neutral/structure.

The chart must never draw a fake future-price projection.

## Data flow

Bridge is authoritative.

For M5 R3 the Bridge refreshes:

- closed M5 history;
- closed M15 history;
- closed H1 history;
- closed M1 history;
- the current live M5 bar from MT5;
- the current tick.

The strategy module receives closed bars for swing calculations and the live M5 bar/M1/tick only for IMPULSE/CONTINUATION execution confirmation. Closed-bar structure must never be polluted by the still-forming M5 candle.

## Safety and execution

R3 keeps all existing safety constraints:

- DEMO hedging USD account only;
- REAL disabled;
- explicit AUTO approval;
- commission must be known;
- broker-valid SL before volume calculation;
- no averaging into a losing campaign;
- campaign-wide risk budget;
- margin guard;
- spread guard;
- no duplicate event execution;
- unknown order result latches recovery and forbids retry;
- emergency state persists;
- manual/V10 positions are never managed by EC1;
- technical order/position fuses remain.

A faster entry path is permission to evaluate an entry sooner, not permission to bypass risk or execution checks.

## Required tests

### Strategy tests

1. Large live M5 BUY candle meeting 0.70 ATR body / 1.00 ATR range / 65% body ratio, aligned contexts, M1 close beyond swing high and live tick beyond level -> BUY ENTRY_READY before M5 close.
2. Mirror SELL impulse.
3. Large candle without M1 confirmation -> no entry.
4. Large candle with H1 or M15 confirmed opposite -> no entry.
5. Small live candle -> IMPULSE path must not fire.
6. Shallow 0.10-0.35 ATR pause plus fresh continuation break -> CONTINUATION entry path arms/triggers.
7. No pause at all -> CONTINUATION does not fire merely because price is moving.
8. Classic >=0.35 ATR pullback still works.
9. NORMAL setup expires after 3 M5 bars, not 8.
10. Same-direction acceleration can supersede a stale PULLBACK setup.
11. Opposite confirmed context cancels a pending new-entry setup.
12. Replaying the same event cannot produce a duplicate order.

### Risk/execution tests

13. Addition requires campaign net > 0.
14. Addition requires price progress from last entry.
15. No fixed 10-position cap; campaign budget and technical fuse remain authoritative.
16. REAL execution remains forbidden.
17. Unknown broker result never retries automatically.

### Android tests

18. Chart renders swing path and labels without changing candle source.
19. Current path text updates to IMPULSE/CONTINUATION/PULLBACK/TRIGGER from Bridge state.
20. Background/offline Activity recreation still does not disable Bridge AUTO.

## Acceptance criteria

R3 is acceptable only when all new tests pass together with the full existing Python and Android suites, the APK builds successfully, and the Bridge package is built from the same verified commit. The release notes must state that execution logic is verified in tests but profitability is not guaranteed or claimed.