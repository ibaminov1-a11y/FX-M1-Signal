#!/usr/bin/env bash
set -euo pipefail
mkdir -p evidence/red
PYTHONPATH=mt5_bridge:tests/event_core python tests/event_core/ui_fixture.py > evidence/red-fixture.log 2>&1 &
fixture=$!
trap 'kill "$fixture" 2>/dev/null || true' EXIT
for i in $(seq 1 30); do
  if curl -fsS -H 'Authorization: Bearer ci-fixture-token-not-for-real-trading' http://127.0.0.1:8765/health >/dev/null; then break; fi
  sleep 1
done
adb reverse tcp:8765 tcp:8765
set +e
gradle --no-daemon --stacktrace :app:connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.class=com.openai.fxm1.R51RepairUiTest > evidence/red/android.log 2>&1
rc=$?
set -e
cat evidence/red/android.log
cp -r app/build/outputs/androidTest-results evidence/red/results
python - <<'PY'
from pathlib import Path
import xml.etree.ElementTree as ET
expected={'legacyCatalogueIsRemovedWithoutChangingChosenSymbolOrLot','liveCatalogueSyncDoesNotReplaceTheWatchlist','tiedForecastIsNotLabelledMainAndMissingT2IsNotFabricated','compactChartShowsNoMoreThanTwoSelectedPaths','historyGenerationClearsTheOldViewportInsteadOfMergingShiftedCandles','denseAnnotationPlacementNeverOverlapsOrEscapesBounds'}
failed=set();seen=set()
for p in Path('evidence/red/results').rglob('*.xml'):
    try:r=ET.parse(p).getroot()
    except ET.ParseError:continue
    for t in r.iter('testcase'):
        if 'R51RepairUiTest' not in t.get('classname',''):continue
        name=t.get('name','').split('[')[0];seen.add(name)
        if t.find('failure') is not None:failed.add(name)
assert expected<=seen,(expected-seen,seen)
assert expected<=failed,(expected-failed,failed)
Path('evidence/RED_UI_CONFIRMED.txt').write_text('\n'.join(sorted(failed)))
print('RED_UI_CONFIRMED',sorted(failed))
PY
kill "$fixture" 2>/dev/null || true
wait "$fixture" 2>/dev/null || true
trap - EXIT
