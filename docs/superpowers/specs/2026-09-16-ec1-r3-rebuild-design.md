# EC1 R3 Rebuild Design

## Baseline

R3 rebuild starts from clean EventCore R2.5 commit `bc3cef9322685c290f3e88c17f08212bb72d6c4a` on branch `feature/ec1-r3-rebuild`.

No implementation code from the previous R3 attempt is copied into this branch. Previous R3 materials may be consulted only as requirements/test references.

R2.5 remains authoritative for execution and safety: DEMO-only trading, Emergency persistence, duplicate-event protection, broker SL checks, campaign-wide risk, margin checks, reconciliation, manual/V10 position isolation, AUTO background behavior, and no averaging into loss.

## Goal

Replace the single-path M5 entry behavior with an adaptive entry engine that can react to three distinct market situations without waiting through stale scenarios:

1. `IMPULSE` — enter during a genuinely large still-forming M5 candle when live continuation is confirmed.
2. `CONTINUATION` — enter when trend resumes after only a shallow pause, without requiring a deep NORMAL pullback.
3. `PULLBACK` — preserve the classic confirmed-structure -> pullback -> fresh trigger path.

The new logic must remain deterministic and explainable. It must not draw a future-price forecast and must not claim profitability.

## Architecture

Trading authority stays in Bridge/EventCore. Android remains presentation and control only.

For M5 decisions EventCore maintains independent market layers:

- H1: major directional context.
- M15: near-term context.
- M5 closed candles: primary structure and swing map.
- Current still-forming M5 candle: live impulse measurement only.
- M1 closed candles: confirmation inside the active M5 candle.
- Current tick: final live confirmation and no-chase check.

Closed-bar structure must never include the still-forming M5 candle.

## Structural map

EventCore builds its own non-repainting swing map from confirmed pivots. It may visually resemble ZigZag, but confirmed swing points are immutable and never depend on a repainting ZigZag indicator.

Recent confirmed pivots are labelled:

- `HH` — higher high
- `HL` — higher low
- `LH` — lower high
- `LL` — lower low

This swing map provides the M5 direction and the breakout/invalidation levels used by all entry paths.

## Entry path 1: IMPULSE

Purpose: catch a genuinely strong current M5 movement before the five-minute candle closes.

A live M5 candle may qualify for IMPULSE only when all of the following are true:

- body size >= 0.70 x M5 ATR(14);
- full high-low range >= 1.00 x M5 ATR(14);
- body/range ratio >= 0.65;
- price breaks the relevant confirmed M5 swing level;
- the last closed M1 candle confirms beyond the broken level in the same direction;
- the current tick remains beyond the level;
- H1 and M15 are not confirmed opposite to the proposed side;
- price has not exceeded the existing no-chase allowance;
- spread, account, commission, risk, margin and broker-SL checks all pass.

IMPULSE does not wait for the current M5 candle to close.

A large candle alone is never enough. If the movement spikes and immediately reverses, M1/tick confirmation fails and no entry occurs.

BUY and SELL are exact mirrors.

## Entry path 2: CONTINUATION

Purpose: avoid missing a strong trend that advances in steps but never gives a classic deep pullback.

A continuation candidate requires:

- confirmed M5 trend structure in the intended direction;
- H1 and M15 not confirmed opposite;
- a real shallow pause/retrace between 0.10 and 0.35 ATR;
- the pause contains at least one opposing or neutral micro-leg rather than one uninterrupted spike;
- a fresh local continuation break in the trend direction confirmed by M1 and the live tick;
- normal no-chase, spread, risk, margin and execution protections pass.

No pause means no CONTINUATION entry. A deep retrace >= 0.35 ATR belongs to the classic PULLBACK path.

## Entry path 3: PULLBACK

The classic NORMAL path remains:

confirmed M5 structure -> pullback/retest >= 0.35 ATR -> fresh trigger -> entry.

NORMAL setup lifetime becomes a maximum of 3 closed M5 candles (15 minutes), not 8 candles/40 minutes.

A stale PULLBACK setup does not lock the engine. A newer same-direction IMPULSE or CONTINUATION may supersede it immediately when the market accelerates.

## Continuous re-evaluation

The engine re-evaluates the market every refresh rather than waiting for a timeout to finish before considering another path.

Allowed transitions include:

- SEARCH -> IMPULSE
- SEARCH -> CONTINUATION
- SEARCH -> PULLBACK
- PULLBACK -> IMPULSE
- PULLBACK -> CONTINUATION
- stale setup -> CANCELLED -> SEARCH

A newly confirmed opposite structural/context event cancels a pending new-entry setup immediately.

There is no 40-minute dead period after a missed setup.

## Context rules

H1 and M15 act as vetoes only when they are confirmed opposite. Neutral context does not block M5.

If H1 or M15 is confirmed opposite, a new entry is blocked. Existing EC1 positions continue to be managed by campaign logic; context does not bypass position-management rules.

## Campaign additions

Existing R2.5 pyramiding/risk rules stay authoritative.

An additional position requires:

- same-direction EC1 campaign;
- campaign net profit > 0;
- sufficient price progress from the last entry;
- a new IMPULSE, CONTINUATION or PULLBACK event;
- total stop risk plus fees remain inside campaign budget;
- margin and technical safeguards pass.

There is no strategy cap of 10 positions. Technical emergency fuses remain.

## Android presentation

The Android chart continues to display real MT5 candles only.

R3 adds deterministic overlays supplied by Bridge:

- recent confirmed swing path;
- HH/HL/LH/LL labels;
- breakout/continuation level;
- trigger level;
- invalidation level;
- current path: SEARCH / IMPULSE / CONTINUATION / PULLBACK / TRIGGER.

No future-price projection is drawn.

AUTO remains owned by Bridge. Activity recreation, switching to Telegram/Instagram, or temporary phone connectivity loss must not disable Bridge AUTO.

## Implementation boundaries

The rebuild must not use self-modifying CI patch scripts such as `apply.py`. Source changes are committed explicitly to the rebuild branch.

R2.5 `_entry()`, risk, reconciliation, Emergency, duplicate protection and REAL-blocking should be reused rather than rewritten unless a failing regression test proves a required change.

R3 logic should be isolated into small testable units: market snapshot, swing map, context evaluation, IMPULSE detector, CONTINUATION detector, PULLBACK state flow, and Android rendering.

## Test-first acceptance criteria

Before any production implementation for a component, its new behavior is first represented by a failing test.

Required strategy tests include:

- live large M5 BUY impulse enters before M5 close;
- mirrored SELL impulse;
- small/medium M5 candle never triggers IMPULSE;
- missing M1 confirmation blocks IMPULSE;
- opposite H1 or M15 blocks new entry;
- immediate spike reversal blocks entry;
- shallow 0.10-0.35 ATR pause can arm CONTINUATION;
- no pause does not create CONTINUATION;
- deep >=0.35 ATR retrace remains PULLBACK;
- NORMAL pending setup expires after 3 M5 candles;
- newer same-direction IMPULSE/CONTINUATION can supersede stale PULLBACK;
- same event cannot send a duplicate order;
- BUY/SELL behavior remains symmetrical.

Required execution/risk regressions include:

- no adding to a losing campaign;
- add requires price progress;
- campaign risk budget remains authoritative;
- old/manual/V10 positions do not become EC1-managed;
- unknown broker result does not retry automatically;
- REAL trading remains forbidden;
- Emergency remains latched;
- AUTO survives Activity recreation/temporary phone offline state.

Required Android tests include:

- real candles remain the chart source;
- swing/path overlays render without fake future candles;
- current R3 path is visible from Bridge state;
- AUTO UI reflects Bridge state and does not control Bridge from programmatic Switch restoration.

## Release gate

No R3 APK/Bridge is delivered until all of the following pass from one commit SHA:

1. Full Python EventCore suite.
2. Android debug APK build.
3. Android instrumentation/emulator suite.
4. Packaging of APK and Bridge from the same verified commit.
5. Build identity clearly reports R3 rebuild.

The release notes must distinguish mechanical/test verification from live-market profitability. No profitability guarantee is made.
