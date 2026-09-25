# Scenario Map and Safe Reversal Implementation Plan

**Goal:** Complete the approved scenario map and position lifecycle on existing R4.
**Base:** `6af6acfe1e3e48586dbce57e801b7b216655246c`, branch `feature/r4-compute-rebuild`.
**Spec:** `docs/superpowers/specs/2026-09-25-scenario-safe-reversal-design.md`.
**Execution:** Inline implementation; no separate reviewer or live MT5 orders.

## Constraints
Preserve existing controls, informational notification, journal, own-position isolation, protective SL and DEMO-only adapter. No martingale or promise of loss-free reversal. Weights and path times must not imply calibrated probability or known future prices.

## Completed before the integrated build
- Reproduced fixed-deadline, pause, unknown/partial close and prospective-crossing regressions before production fixes.
- Centralized ephemeral reversal queue/update/cancel. Close independently on invalidation; require flat exposure and full closing history before a still-current opposite entry.
- Added shared structural levels, labelled target sources and conditional paths; preserved entry snapshot and first exit cause.
- Added a real ComputeCore + Engine integration test with simulated broker transport only.
- Ran all 162 Python tests successfully; compile and diff checks passed.
- Pushed Android regression tests first. At `d6913834e597406bd1a023985c7f6544a35b0779`, the existing 16 tests passed and all 3 new map/summary tests failed on the expected missing behavior.
- Implemented map rendering, actual LIVE anchor, shared levels, active invalidation, uncertainty band, uncalibrated-weight wording and actual reversal status.

## Release gate — must be completed on the integrated commit
1. Fast-forward R4 only after verifying upstream has not changed.
2. Run existing Python/build/API35 instrumentation/package workflow on that exact SHA.
3. Inspect Android screenshots and results, verify source and APK hashes, and correct any regression before delivery.
4. Deliver only the tested APK + Bridge package. State that physical-phone behavior and real-market performance were not tested.
