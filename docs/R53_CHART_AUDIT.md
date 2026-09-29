# R5.3 scenario chart audit

## Confirmed causes

- `ScenarioMapRenderer.route()` selected `routeColor()` once per route and reused it for every segment. A SELL preparation move toward an upper zone therefore appeared red, even before the required confirmation. The rendering had no phase distinction.
- `ScenarioUi.levels()` showed current live scenario stages and a generic open campaign summary, without the campaign's recorded scenario ID, version, snapshot ID, or matching frozen scenario. A new WATCHING branch could be mistaken for the scenario that opened an existing position.
- `ScenarioUi.levels()` returned early when the live forecast was missing, also hiding any recorded entry information.

## Changes within assigned scope

- `ScenarioMapRenderer.java`: destination `phase=PREPARATION` uses a neutral dashed segment, including the segment into confirmation. `TRADE` uses the existing branch color regardless of local slope. Confirmation nodes have a small neutral ring. Terminal arrows are shown only for trade segments. A three-line footer explains preparation, the conditional post-confirmation route, and navigation; chart space reserves room for it.
- Old semantic v3 paths without `phase` use target labels/anchors to distinguish preparation. Old unlabelled v2 paths retain their original branch styling and receive an explicit legacy legend instead of an invented confirmation boundary.
- `ScenarioUi.java`: adds a current-hypothesis heading and a separate saved entry section from `campaign.scenario_id`, `scenario_version`, `snapshot_id`, and `forecast_at_entry`. The frozen branch is selected by ID and compatible recorded version, never by its array index or the current WATCHING branch. The saved stage, targets, and invalidation are explicitly labelled as values at entry. Missing identity or frozen data is stated. The entry section remains available when the current forecast is unavailable.
- `SparklineView.java`: accessibility describes preparation and conditional trade phases, exposes scenario stage, and describes the actual selected/live/archive/history view.

## Added Android instrumentation coverage

File: `app/src/androidTest/java/com/openai/fxm1/R53ScenarioDisplayUiTest.java`.

1. SELL first rises toward a zone in neutral dashed preparation, stays neutral into confirmation, and then falls in red toward a conditional target.
2. BUY first falls toward a zone in neutral dashed preparation and then rises in green.
3. Old semantic v3 anchors without phase metadata still separate preparation and targets.
4. Explicit trade phase retains SELL red even when a conditional segment rises; no BUY green is substituted from slope.
5. Current WATCHING hypothesis and saved campaign entry are distinct. The frozen matching entry is deliberately the second archived branch, so selecting the first item fails the test. ID, version, snapshot, frozen title, and target are asserted.
6. A missing frozen forecast keeps recorded identity and does not borrow the live WATCHING scenario.
7. Recorded entry identity survives a missing live forecast.

Tests render the real Android `SparklineView` to a Canvas. Pixel checks isolate path segments from headers, candles, grid colors, and annotations; neutral dash gaps are checked as separate connected strokes, rather than inferring color from text. Screenshots export to `/sdcard/Download/ec1-qa/`: `r53-sell-preparation.png`, `r53-buy-preparation.png`, `r53-live-versus-entry.png`.

## Verification status

- Tests were written before production edits and use only APIs that already exist in the baseline.
- `git diff --check` passed locally after the edits.
- This environment has no Java/Gradle/Android SDK or emulator, so no local compilation or Android pass is claimed.
- Parent agent is responsible for the remote baseline-red then fixed-green workflow and full Android suite, plus screenshot inspection. Record remote outcomes before claiming the UI fix is verified.

No backend, MainActivity, EventClient, or other agent-owned files were edited by this subtask. No commits were created.
