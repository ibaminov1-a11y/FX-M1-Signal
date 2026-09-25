# Scenario Map and verified close-before-reverse

Basis: the user's 25 September approval of the in-chat design and supplied final R3 discussion.
Integration base: upstream `feature/r4-compute-rebuild` at `6af6acfe1e3e48586dbce57e801b7b216655246c`.

## User outcome
A large structural primary and opposite alternative scenario share their trigger/invalidation levels with ComputeCore. The chart reserves a future zone, separates real candles from hypothetical paths, and shows WAIT with levels rather than inventing a direction. Scores are uncalibrated model weights, not measured success probabilities. Range is a separate weight, not a replacement for the opposite alternative.

An invalidated campaign closes independently of the opposite entry. A valid, enabled DEMO campaign may retain a 20-second nonrenewable reversal intent. Close the old owned positions/orders, confirm full closing volume in MT5 history, recompute the candidate on fresh data and recheck normal risk/margin/spread/no-chase guards before sending the opposite order. No overlap, averaging down, trading on unavailable data, or guarantee of loss-free exits.

## Boundaries
Bridge remains the only decision/execution owner; Android only renders and commands control state. Preserve existing UI controls, notifications, money journal, protective SL, risk limits, own-position isolation, and the adapter's DEMO-only execution gate. No REAL activation or market order will be sent during development.

## Cases
1. Invalidation without SELL: close BUY, wait for independently confirmed SELL; expiry cancels the exceptional cooldown bypass.
2. Confirmed SELL while BUY exists: queue once, close first; partial/unknown results never prove flat.
3. Repeated SELL does not extend expiry; lost signal, stale data, pause, disable, emergency, account/config change or restart cancels the intent.
4. First quote or changed structural frame only arms observation; no backward entry from price already beyond the level. Continuation must relate to an observed crossing.
5. Freeze forecast/levels at entry and first exit cause for audit. Subsequent LIVE recomputation does not rewrite the entry record.
6. Shared map levels exist before the crossing; display their structural source. A measured-range extension is labeled as an extension, not a known resistance/support target.
