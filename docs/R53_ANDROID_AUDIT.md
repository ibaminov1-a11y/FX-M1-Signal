# Android controls and indicators audit — R5.3 work

## Scope and verification

Reviewed the active EventCore paths in `MainActivity`, `EventClient`, and `MonitoringService`, including listeners installed in `onCreate`, settings dialogs, the one second UI refresh, service lifecycle, HTTP configuration, and cache updates. The older local-analysis methods are unreachable from the active EventCore monitor and were not treated as runtime bugs.

Added `R53ControlsUiTest` with 13 Android instrumentation cases. These use real Android views and the real authenticated Flask/Engine HTTP endpoints with the fake MT5 broker. At implementation time, test source preceded the corresponding production edits; Android execution was delegated to remote baseline-production red and corrected-production verification runs because this workspace has no Java compiler, Android SDK, emulator, or Gradle. `git diff --check` passed for the owned files. Final test counts, results and evidence are recorded in the generated `Verification/R53_REPORT_RU.md`.

## Findings addressed

| Defect | Root cause | Change / regression case |
|---|---|---|
| SCALP choice silently becomes NORMAL | `EventClient.config()` hardcoded NORMAL | Config uses saved selected mode; spinner → service → actual HTTP config is checked, including return to NORMAL and Activity recreation |
| Unsupported timeframe choices appear usable | Scenario V2 uses M5 while UI exposed every frame | Initial selection is normalized to M5; timeframe control remains disabled through refresh/recreation |
| Reconnecting phone can queue a stale profile | Bridge profile was shown without reliably synchronizing saved mode; startup configure preceded poll | Running/campaign profile synchronizes mode, symbol and risk before config comparison; same-value spinner callbacks do not issue refresh; remote SCALP AUTO survives stale local NORMAL |
| Successful Settings reset leaves emergency blocked | Settings called transport directly; cleanup existed only in the unused generic reset UI branch | Successful transport reset clears both local latch and pending retry; failed HTTP reset preserves latch |
| Emergency retry could be lost before service dispatch | Pending retry was first persisted by service, after Activity dispatched start | Activity durably sets retry and latch before service request; double-tap test verifies immediate pending flag |
| Disconnected UI can keep active controls | UI refresh skipped restoring controls when `server_verified` became false | Every refresh applies online/offline snapshot; disconnect and recovery checked |
| Disconnected cached forecast still appears LIVE | Cached forecast and signal were rendered without phone-connection provenance | `EventClient.state()` annotates a cloned root/forecast with `client_offline`; cache, neutral signal/headline, snapshot age and explanation are explicit; recovery restores current presentation without clearing independent Bridge AUTO |
| Recreation test can interact with a destroyed Activity | ActivityTestRule retains the instance launched before recreation | Tests resolve the resumed MainActivity through lifecycle monitoring, wait for a distinct resumed instance, and finish the actual current Activity during cleanup |
| Last check time stays empty | EventCore poll never updated the timestamp used by the label | Poll records attempt timestamp |
| Market session labels stay at launch values | Calendar/session refresh only ran in `onCreate` | UI ticker refreshes both labels; test replaces labels with stale sentinel then verifies refresh |
| Missing quote can preserve old price or display NaN | Price render skipped NaN entry; price formatter accepted nonfinite values | Price render always runs; nonfinite values use unavailable marker |
| Stopped service can remain displayed as running | `onDestroy` did not clear `bg_running` | Service destroy clears indicator; external service stop test checks main button recovery |
| Notification fails to identify SCALP | Summary omitted mode and hardcoded timeframe | Summary uses current Bridge timeframe/mode; still information only, no notification actions |
| Selected REAL shows DEMO authorization prompt | `targetTradeMode()` returned actual account type instead of selected profile | Uses selected profile; REAL remains blocked before authorization, even if MT5 is DEMO; command audit verifies no enable/arm_real |

## Main controls coverage

| Control | Audit / behavior coverage |
|---|---|
| Instrument spinner | Real GBP/USD selection reaches config; custom instrument dialog path inspected |
| M5 timeframe | Fixed M5, explicitly disabled |
| NORMAL / SCALP | Actual popup selections, HTTP configuration, locked-profile restoration, recreation |
| Monitor start / stop | Starts foreground polling; stopping preserves independent Bridge AUTO; service destroy updates button |
| AUTO switch | Cancel sends no enable; DEMO confirmation enables; switch off disables/pauses; REAL block; offline unavailable |
| Emergency | First tap confirmation only; second persists retry and sends emergency; explicit successful/failed reset |
| Lot spinner | Preset 0.05 applies to fixed/probe lot; manual editor validation path inspected in existing TradeSettings |
| Risk spinner | 0.50% reaches HTTP config; locked profile uses Bridge risk |
| Legacy drift spinner | Remains explicitly disabled |
| Bridge key | Edit/save visibility and stored key checked |
| Server address | Dialog opens/cancels; normalization, required input, connect success/error path inspected |
| Settings | Opens/cancels; REAL selected profile persists and sends explicit pause; reset success checked; adopt-account confirmation path inspected |
| Manage positions | Real fixture manual position appears in list; position detail and whole-campaign close path inspected |
| Close campaign | Confirmation opens; cancel leaves manual position intact; existing backend tests own actual close semantics |
| Money history | Real history dialog opens/closes; refresh path inspected |
| Trading journal | Nav and card/listeners open full journal; clear-local/refresh paths inspected |
| Full signal details | Full snapshot dialog opens |
| Bottom navigation | Positions, signals, settings scroll; overview returns to top; journal opens dialog |
| Chart/route controls | Delegated to renderer/scenario audit; not edited here |
| Notification | Displays actual mode; no trading action buttons introduced |

## Nineteen dynamic TextViews

The instrumentation checks every listed field is populated; data-bearing fields also have the explicit source/assertion below. It deliberately does not require every field to change on each quote because session/status/journal values have distinct triggers.

| Field | Source / exercised assertion |
|---|---|
| statusText | Current state symbol/timeframe and monitor state |
| marketStatusText | Calendar recomputed by UI tick, stale sentinel replaced |
| marketSessionText | Calendar session recomputed by UI tick, stale sentinel replaced |
| confidenceText | Exactly `ScenarioUi.headline` of real server forecast; neutral cache label on disconnect |
| signalAgeText | Cached update and poll timestamps; explicit saved-signal timestamp on disconnect |
| levelsText | Real scenario/campaign/decision formatter, nonempty |
| contextText | Exact EventClient context derived from actual state |
| whyWaitText | Actual decision reason plus execution feedback |
| componentScoresText | Scenario explanation recomputed from current presentation snapshot, including offline provenance |
| autoStatusText | Actual AUTO, PAUSE, emergency, connection loss and recovery |
| accountText | Two changed balance fixtures reflected exactly |
| positionsText | Actual manual position count and current floating P/L path |
| priceCompareText | Two changed bid fixtures; missing quote clears previous price |
| smartStatusText | MT5 source, active mode/risk and operation status |
| statsText | Real trade ledger fetched after completed fake broker trade |
| signalHistoryText | Actual cached symbol/decision history |
| tradeHistoryText | Real closed EURUSD trade fetched through `/trade-ledger` |
| serverStatusText | Online MT5 state and offline/recovery transition |
| journalText | Existing event/ledger fallback is populated; full journal opens |

## Remaining verification constraints

This document describes implementation-time coverage. Consult generated `Verification/R53_REPORT_RU.md` for the final remote Android and Python verification counts/results and screenshot evidence. Navigation/dialog tests exercise representative branches; the audit does not claim every dialog confirmation has an independent automated case. DEMO-only execution and informational notifications remain intact.
