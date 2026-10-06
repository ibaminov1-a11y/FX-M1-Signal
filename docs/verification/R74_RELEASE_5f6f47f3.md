# R7.4 DEMO — verified delivery record

Date: 2026-10-06. This document records an already tested source revision; it does not alter product code.

- Product source: `5f6f47f303c337bfd57acec9958cb5ed910d375f`.
- CI controller commit: `d77dde9577ed707b528005b22dec6481d007505e` on `ci/r74-acceptance-20261006`.
- Full signed acceptance run: `37433783603`, SUCCESS.
- Version: `10.9-EC1-R7.4`; Android versionCode 934; applicationId `com.openai.fxm1.ec1`.
- Original certificate SHA256: `3d55a491046e661664f99c2a3e4a51338a794b313beb3e32d7ed88181a7a1885`.

## Results

Python: 567 cases, 566 passed, 1 explicitly skipped Windows-only legacy launcher case, 0 failures. Separate native Windows launcher gate: 10/10. Android API35: 209/209, no failure or skip; XML names matched the complete current source test set. Only retired V108RepairTest/TwelveData protocol is excluded. Upgrade from the actual previously delivered version 933 to 934 succeeded without uninstalling and preserved the checked settings.

Supplemental replay used the actual Flask/CommandInbox/Portfolio/Engine stack with a fake broker: BUY and SELL each executed two distinct 0.01 entries and closed at the original plan target; duplicate quote did not resend, campaign risk and frozen entry forecast were checked. This is not live MT5 or profitability evidence; synthetic quotes and zero fees were used in that supplemental replay.

Actual localhost HTTP test held the owner lock: eight configuration receipts and a deduplicated safety pause were accepted without HTTP503; the pause inhibited entries, cancelled old pending configurations and became APPLIED after the owner was available. No orders were sent. These timings are not performance guarantees for a user's Windows, MT5 or phone.

## Defects resolved during continuation

1. Test-session isolation: Android fixture resets reused the client sequence but retained the durable CommandInbox order_seen/inhibits/inbox state. Three RED tests reproduced the old rejection/stop contamination. Only the test-session reset was corrected; production restart persistence remains intact. Intermediate source c1676d95 passed the full native gate.
2. Actual production bug: explicit `/ec/state?refresh=1` omitted queued-controls capability metadata. The phone could revert to legacy control admission after refresh. Two RED tests reproduced missing negotiation and the exact Busy HTTP503. Shared metadata is now applied to both normal and explicit-refresh state responses; the entire latest source gate was repeated.

## Delivery files, SHA256

- FXM1_R7_4_FULL.zip: `63b6061cdc318a2a8aec7c6de63eb89e79ae1c4222fc993cebe7ce4d95a402ac`
- FXM1_R7_4.apk: `9cb2b370b8bc1a13c49b2c7b4da87aaf39a84e96da1231ff7b1f2cfcf8a0381d`
- FXM1_R7_4_Bridge.zip: `214e6364b8bf52c6333b643339f7109c0d31bb2526575ea898d1daad534b246b`
- FXM1_R7_4_VERIFICATION.zip: `17e92343203b7d5e330df3d47205c69c6d6d75d66e5f0a5aef72b653da6dcd1c`

The full package contains the exact tested APK and the complete `mt5_bridge_R74` program folder. Its files match the separate Bridge archive byte-for-byte. Put that folder beside the existing `mt5_bridge`; preserve the old .venv, event_state, pairing identity and history. Run the new folder's START_BRIDGE_V10_0.bat, not the old shortcut. APK installs over existing EC1. No dependency repair, cache deletion or manual JSON edits are required.

## Scope and limits

DEMO USD HEDGING only; REAL and NETTING remain blocked. STABLE_V1 adds prospective fixed boundary-return plans and retains risk-checked favorable additions and original target/expiry exits. It complements existing scenario paths; it is not a calibrated learned probability model, an exact three-hour future price prediction, martingale, or an assurance of profitable trades. Slow in-flight terminal I/O may still delay command application; queue receipt is not broker fill confirmation. Optional observer analysis runs after primary execution, but this release is not a full independent-process/MQL5 rewrite.

Self-review only; no independent reviewer tool was available. Ten reviewed screenshot/contact-sheet files represent 19 pattern variants and forming/no-figure/stale/offline/position views plus full-screen and version/profile screens. An automatically exported archive-named PNG captured the preceding position screen and is not counted as visual proof of the archive dialog. Functional archive tests passed. Existing dense chart labels/ellipsized explanations were not comprehensively redesigned.

No authenticated user MT5, physical phone or real network/broker execution was accessed. New trading events still require actual observed confirmation and acceptable risk; no forced order schedule is introduced.
