#!/usr/bin/env bash
set -euo pipefail
mkdir -p evidence
PYTHONPATH=mt5_bridge:tests/event_core python tests/event_core/ui_fixture.py > evidence/r54-fixture.log 2>&1 &
fixture=$!
trap 'kill "$fixture" 2>/dev/null || true' EXIT
for i in $(seq 1 30); do
  if curl -fsS -H 'Authorization: Bearer ci-fixture-token-not-for-real-trading' http://127.0.0.1:8765/health >/dev/null; then break; fi
  sleep 1
done
adb reverse tcp:8765 tcp:8765
set +e
gradle --no-daemon :app:connectedDebugAndroidTest '-Pandroid.testInstrumentationRunnerArguments.class=com.openai.fxm1.R54ChartUiTest#blockedClockRendersRealCandlesWithoutTradingPaths,com.openai.fxm1.R54RefreshUiTest#downwardSwipeRefreshesWholeScreenWhileMonitoringIsStoppedWithoutCommands' > evidence/r54-red.log 2>&1
rc=$?
set -e
cat evidence/r54-red.log
test "$rc" -ne 0
python - <<'PY'
from pathlib import Path
import xml.etree.ElementTree as ET
failures=[]
for p in Path('app/build/outputs/androidTest-results').rglob('TEST-*.xml'):
    for test in ET.parse(p).iter('testcase'):
        failed=test.find('failure')
        if failed is not None:failures.append((test.attrib['name'],failed.attrib.get('message','')))
expected={'blockedClockRendersRealCandlesWithoutTradingPaths':'Raw chart must disclose',
          'downwardSwipeRefreshesWholeScreenWhileMonitoringIsStoppedWithoutCommands':'Downward swipe from top'}
assert len(failures)==2,failures
for name,message in failures:
    assert name in expected and expected[name] in message,(name,message)
Path('evidence/R54_RED_CONFIRMED.txt').write_text(str(failures)+'\n')
print('R54_RED_CONFIRMED',failures)
PY
