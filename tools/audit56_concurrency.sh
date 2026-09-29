#!/usr/bin/env bash
set -euo pipefail
mkdir -p evidence/concurrency
PYTHONPATH=mt5_bridge:tests/event_core python tests/event_core/ui_fixture.py > evidence/concurrency/fixture.log 2>&1 &
fixture=$!
restore() {
  git restore --source=HEAD -- app/src/main/java/com/openai/fxm1/EventClient.java app/src/main/java/com/openai/fxm1/MonitoringService.java
}
cleanup() { restore; kill "$fixture" 2>/dev/null || true; }
trap cleanup EXIT
for i in $(seq 1 30); do
  if curl -fsS -H 'Authorization: Bearer ci-fixture-token-not-for-real-trading' http://127.0.0.1:8765/health >/dev/null; then break; fi
  sleep 1
done
adb reverse tcp:8765 tcp:8765
for name in EventClient MonitoringService; do
  git show "0d95ed8260989b2c82cf67edd7bf44fae6fc701a:app/src/main/java/com/openai/fxm1/$name.java" > "app/src/main/java/com/openai/fxm1/$name.java"
done
set +e
gradle --no-daemon :app:connectedDebugAndroidTest '-Pandroid.testInstrumentationRunnerArguments.class=com.openai.fxm1.R56ConcurrencyUiTest#acceptedResetRejectsAnOlderEmergencySnapshotButFreshEmergencyStillLatches,com.openai.fxm1.R56ConcurrencyUiTest#runningFlagIsPublishedOnlyAfterNativeForegroundPromotion' > evidence/concurrency/red.log 2>&1
set -e
cp -r app/build/outputs/androidTest-results evidence/concurrency/red-results
restore
python - <<'PY'
from pathlib import Path
import xml.etree.ElementTree as ET
cases=[]
for p in Path('evidence/concurrency/red-results').rglob('TEST-*.xml'):
    cases.extend(ET.parse(p).getroot().iter('testcase'))
expected={'acceptedResetRejectsAnOlderEmergencySnapshotButFreshEmergencyStillLatches':'An older HTTP response cannot restore the cleared emergency latch',
          'runningFlagIsPublishedOnlyAfterNativeForegroundPromotion':'bg_running is an acknowledgement of completed foreground promotion'}
assert len(cases)==2,[(c.get('name'),c.find('failure') is not None) for c in cases]
for c in cases:
    failure=c.find('failure');assert failure is not None,c.get('name')
    assert expected[c.get('name')] in (failure.get('message','')+' '+(failure.text or '')),ET.tostring(c)
Path('evidence/concurrency/RED_CONFIRMED.txt').write_text('Both concurrency defects reproduced against 0d95ed8260989b2c82cf67edd7bf44fae6fc701a.\n')
PY
set +e
gradle --no-daemon :app:connectedDebugAndroidTest '-Pandroid.testInstrumentationRunnerArguments.class=com.openai.fxm1.R56ConcurrencyUiTest,com.openai.fxm1.R53ControlsUiTest#emergencyNeedsDoubleTapAndSuccessfulSettingsResetClearsBothLatches,com.openai.fxm1.R53ControlsUiTest#destroyedMonitoringServiceClearsItsRunningIndicator' > evidence/concurrency/green.log 2>&1
rc=$?
set -e
cp -r app/build/outputs/androidTest-results evidence/concurrency/green-results
adb logcat -d > evidence/concurrency/android-logcat.txt
cat evidence/concurrency/green.log
exit "$rc"
