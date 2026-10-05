# R7.3 trading audit

Audit date: 2026-10-05. Baseline: R7.2 `f3a6ba35dc551f2ae8ac1ad8025b4e19c1d52cd0`.
The tests run the real Python engines, scenario state machines, risk calculations,
SQLite persistence and reconciliation. Only the external MT5 transport is simulated.
They verify behavior, not source-text strings. No trade was sent to a live broker.

## Defects reproduced before repair

| Defect | Observed RED result | Repair and regression |
| --- | --- | --- |
| Scale-in ignored realized campaign losses when requiring net profit | BUY and SELL both accepted an addition with +2 open P/L and -3 realized P/L | `plan_order` includes realized net P/L; `CampaignNetRiskTests.test_realized_loss_must_be_recovered_before_either_side_can_scale_in` rejects the losing campaign and accepts the same confirmation only after net recovery. |
| A leg could close between history polls, leaving stale realized P/L at the actual add boundary | Full-leg disappearance and partial close both left realized P/L at zero after one second and allowed `Engine._entry`; delayed exit history also allowed additions | Owned identity/volume decrease now forces immediate history refresh. Every addition refreshes history and reconciles realized money before risk sizing. Per-position opening-minus-closing volume must match current live volume; incomplete evidence blocks additions. Three temporal tests each cover full and partial close, including recovery only after complete history and positive campaign net. |
| Reconciliation omitted opening commission/fees of closed volume | Fully closed volume showed +2 instead of -2; half closed volume showed +1 instead of -1 | `realized_net` allocates opening expenses proportionally to closed volume, with remaining volume covered by its existing fee reserve; `test_closed_volume_retains_its_opening_commission_and_fees`. |
| Selected market accepted a live candle overlapping its closed history | Entry gate remained open on all nine public frames | Engine rejects the overlapping candle, matching observer safeguards; `test_forming_candle_must_follow_closed_history_on_every_selected_frame` now covers all nine public frames plus legacy M10. |
| Monthly selected history and monthly weekly-context history bypassed freshness validation | W1 and MN1 entry gates remained open with three missing monthly candles | Engine uses the calendar-aware close time for both selected and context freshness; `test_old_monthly_history_blocks_selected_month_and_weekly_context`. |
| Broker suffix cancelled a valid close-and-reverse | `EUR/USD` resolving to `EURUSD.pro` closed its BUY but never entered the still-valid SELL after flat/history confirmation | Engine compares the pending reversal to the currently resolved broker symbol; `test_broker_suffix_does_not_cancel_valid_reversal_for_the_selected_alias` uses real ComputeCore crossings and verifies one reverse order only. |
| Brief feed failure repainted an already issued forecast minute | After an unconfirmed tick, the same minute acquired a different origin, horizons and snapshot | Unavailable responses retain the immutable internal issued snapshot; restored validated input reuses it. `test_brief_feed_failure_cannot_rewrite_an_already_issued_minute`. |

## Verified coverage matrix

| Area | Exercised behavior | Evidence |
| --- | --- | --- |
| NORMAL/SCALP, BUY/SELL, selected timeframe | 40 engine combinations: both modes × both directions × nine public frames (M1/M5/M15/M30/H1/H4/D1/W1/MN1) plus legacy M10. M10 is not an Android UI choice. Each opens from observed progress/pullback/crossing, manages without inventing an add or loosening the stop, restarts with AUTO off and frozen entry forecast, emergency-closes, and reconciles exactly one closed position. | `test_r7_release_runtime.R7RuntimeTests.test_both_modes_all_native_frames_first_buy_sell` |
| Favorable scale-in | New observed events for second/third positions, fixed entry forecast, shared campaign budget; no adds for uninterrupted drift, losses, disabled adds, exhausted budget, missed crossing, completed source, pause or feed gap. | `test_r7_release_runtime`, `test_r53_scale_in`, `test_r57_scalp`, `test_r73_trading_safety` |
| Instrument conventions | Synthetic EURUSD.pro, USDJPY.a, XAUUSD.pro and BTCUSD.pro specifications × both sides: native tick-aligned stop, positive size, capped monetary risk; FX pip spread limit applies with suffixes and JPY digits without incorrectly restricting metals/crypto. | `test_r73_trading_safety.CampaignNetRiskTests.test_fx_suffix_jpy_metal_and_crypto_keep_native_price_and_risk_rules` |
| Broker suffix reversal | Existing BUY closes, actual history confirms flat, still-valid SELL opens once; no same-cycle hedge or consumed-event duplicate. | `test_compute_reversal_integration` |
| Multiple profiles | Separate symbols, ownership and position IDs; per-symbol persisted settings; selected view does not transfer AUTO; aggregate risk and pending-unknown guard; account-wide emergency closes both profiles. | `test_r7_profiles` |
| Restart and reconnect | No restored AUTO or ephemeral reversal, no reuse of armed setup/add; unknown execution persists; stale/unconfirmed quotes cannot trade or contaminate native market history. | `test_risk_engine`, `test_r51_repairs`, `test_r53_scale_in`, `test_scenario_reversal_safety`, `test_r7_release_runtime` |
| Execution and reconciliation | Event idempotency, pending unknown with no resend, incomplete history, partial close, unknown/rejected close, lost position read, emergency despite history failure; manual/foreign positions are not closed. Full/partial volume decreases refresh realized money immediately; additions wait for matching close-volume history. | `test_risk_engine`, `test_scenario_reversal_safety`, `test_r5_lot_history`, `test_r55_account_history`, `test_r73_trading_safety` |
| Risk accounting | Stop adjusted before lot sizing, tick/volume step and min/max constraints, slippage and fees, margin, whole-campaign budget, loss-making additions, missing stop and excess post-fill risk. | `test_risk_engine`, `test_r5_lot_history`, `test_r73_trading_safety` |
| Closed-candle/clock integrity | Every selected frame, future live/closed candle rejection, monthly calendar/offset correctness, stale context, overlapping live candle and clock migration isolation. | `test_r55_timeframes`, `test_r55_engine_frames`, `test_r73_trading_safety` |
| Read-only observers | Independent native frame histories/contexts; cached endpoint reads do not execute; observer confirmations cannot dispatch orders or overwrite the trading scenario archive; failure and identity isolation. | `test_r56_multiframe`, `test_r7_forecast_integration` |
| Frozen forecast and reversal semantics | Immutable campaign entry forecast; causal empirical forecast outcomes; no same-minute repaint across interruption; close-before-reverse, bounded deadline, fresh opposite confirmation and cancellation on pause/restart/feed failure. | `test_r7_price_forecast`, `test_scenario_reversal_safety`, `test_compute_reversal_integration` |

## Verification commands and results

Install the Python dependencies from `mt5_bridge/requirements_event.txt`, then run
from the repository root:

```sh
PYTHONPATH=mt5_bridge:tests/event_core python3 -m unittest discover -s tests/event_core -p 'test_*.py'
```

Final full discovery after the temporal reconciliation repair: **420 tests in
24.933 seconds, zero failures, one skip**. The skipped installer test requires
native Windows `cmd.exe` and a Windows virtual environment; this audit ran on
Linux. The result includes all 40 engine lifecycle combinations, the instrument
matrix, delayed full/partial close history regressions, and integrated runtime
and startup repairs. It supersedes the earlier intermediate failures during
parallel implementation. `git diff --check` passed for the audited files.

Independent review confirmed the temporal repair covers both the stale regular
history interval and delayed closing-deal visibility without altering entry
strategy thresholds.

## Practical limits

These are deterministic functional and safety checks, not profitability evidence.
The instrument fixtures are representative synthetic contract specifications;
they do not establish support for every symbol offered by every broker. Real
Windows MT5 connectivity, fills, broker-specific commissions/slippage and Android
device rendering require their separate runtime/device verification. The monthly
independent analog price forecast remains explicitly unavailable by design; this
does not suppress the monthly structural scenario engine.

Entry thresholds and NORMAL/SCALP strategy rules were not relaxed. Production R7
Portfolio/MT5 DEMO-only restrictions remain intact; legacy Engine REAL pilot
compatibility tests were left unchanged. No commits or pushes were made by this audit.
