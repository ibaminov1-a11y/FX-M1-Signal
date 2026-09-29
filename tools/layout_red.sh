#!/usr/bin/env bash
set -euo pipefail
mkdir -p evidence
PYTHONPATH=mt5_bridge:tests/event_core python tests/event_core/ui_fixture.py > evidence/fixture.log 2>&1 &
pid=$!
trap 'kill "$pid" 2>/dev/null || true' EXIT
for i in $(seq 1 30); do
  if curl -fsS -H 'Authorization: Bearer ci-fixture-token-not-for-real-trading' http://127.0.0.1:8765/health >/dev/null; then break; fi
  sleep 1
done
adb reverse tcp:8765 tcp:8765
set +e
gradle --no-daemon :app:connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.class=com.openai.fxm1.LiveLayoutUiTest > evidence/layout-red.log 2>&1
set -e
cat evidence/layout-red.log
python - <<'PY'
from pathlib import Path
import xml.etree.ElementTree as ET
required={'changingLiveTextKeepsGeometryAndScroll','shrinkingStatusesAtPageBottomDoesNotSnap','fullTextRemainsReadableInFrozenSnapshot'}
seen=set();failed=set()
for p in Path('app/build/outputs/androidTest-results').rglob('*.xml'):
    for case in ET.parse(p).getroot().iter('testcase'):
        if 'LiveLayoutUiTest' not in case.get('classname',''):continue
        name=case.get('name','').split('[')[0];seen.add(name)
        if case.find('failure') is not None:failed.add(name)
assert required <= seen,(required-seen)
assert required <= failed,(required-failed)
Path('evidence/LAYOUT_RED_CONFIRMED.txt').write_text('\n'.join(sorted(failed)))
print('LAYOUT_RED_CONFIRMED',sorted(failed))
PY
