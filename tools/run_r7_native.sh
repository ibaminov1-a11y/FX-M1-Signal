#!/usr/bin/env bash
set -euo pipefail
mkdir -p evidence/ui
PYTHONPATH=mt5_bridge:tests/event_core python tests/event_core/ui_fixture.py > evidence/ui-fixture.log 2>&1 &
fixture=$!
trap 'kill "$fixture" 2>/dev/null || true' EXIT
for i in $(seq 1 30); do
  if curl -fsS -H 'Authorization: Bearer ci-fixture-token-not-for-real-trading' http://127.0.0.1:8765/health >/dev/null; then break; fi
  sleep 1
done
curl -fsS -H 'Authorization: Bearer ci-fixture-token-not-for-real-trading' http://127.0.0.1:8765/health >/dev/null
adb reverse tcp:8765 tcp:8765
set +e
gradle --no-daemon --stacktrace :app:connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.class=com.openai.fxm1.R7ReleaseUiTest > evidence/r7-native.log 2>&1
r7=$?
set -e
cp -r app/build/outputs/androidTest-results evidence/r7-focused-results
adb pull /sdcard/Android/data/com.openai.fxm1.ec1/files/r7-wait-price-forecast.png evidence/ui/ || true
if [ "$r7" -ne 0 ]; then cat evidence/r7-native.log; adb logcat -d > evidence/android-logcat.txt; exit "$r7"; fi
rm -rf app/build/outputs/androidTest-results
set +e
gradle --no-daemon --stacktrace :app:connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.class=com.openai.fxm1.R7ReleaseUiTest,com.openai.fxm1.R57ScalpUiTest,com.openai.fxm1.R56ConcurrencyUiTest,com.openai.fxm1.R56TimeframesUiTest,com.openai.fxm1.R56ChartSemanticsTest,com.openai.fxm1.R55ControlsUiTest,com.openai.fxm1.EventCoreUiTest,com.openai.fxm1.CampaignSignalUiTest,com.openai.fxm1.ScenarioMapUiTest,com.openai.fxm1.ScenarioUpgradeUiTest,com.openai.fxm1.R5SettingsHistoryTest,com.openai.fxm1.R5RedContractUiTest,com.openai.fxm1.R51RepairUiTest,com.openai.fxm1.LiveLayoutUiTest,com.openai.fxm1.R53ControlsUiTest,com.openai.fxm1.R53ScenarioDisplayUiTest,com.openai.fxm1.R54RefreshUiTest,com.openai.fxm1.R54ChartUiTest > evidence/android-runtime.log 2>&1
rc=$?
set -e
adb logcat -d > evidence/android-logcat.txt
adb pull /sdcard/Download/ec1-qa evidence/ui || true
cat evidence/android-runtime.log
if [ "$rc" -ne 0 ]; then exit "$rc"; fi
python - <<'PY'
import json
from pathlib import Path
import xml.etree.ElementTree as E
cases=[]
for p in Path('app/build/outputs/androidTest-results').rglob('*.xml'):
    cases.extend(E.parse(p).getroot().iter('testcase'))
assert cases, 'No executed Android tests'
assert all(t.find('failure') is None and t.find('error') is None and t.find('skipped') is None for t in cases)
r7=[t for t in cases if t.attrib.get('classname','').endswith('R7ReleaseUiTest')]
assert len(r7)==4, len(r7)
Path('evidence/ANDROID_RESULT.json').write_text(json.dumps({'tests':len(cases),'r7_tests':len(r7),'failures':0},indent=2))
print('R7_NATIVE_GREEN',len(cases),len(r7))
PY
test -s evidence/ui/r7-wait-price-forecast.png
signer=$(find "$ANDROID_HOME/build-tools" -name apksigner | sort -V | tail -1)
"$signer" verify --print-certs app/build/outputs/apk/debug/app-debug.apk > evidence/apk-signature.txt
grep -q '3d55a491046e661664f99c2a3e4a51338a794b313beb3e32d7ed88181a7a1885' evidence/apk-signature.txt
# Milestone evidence only. No installation package is published here.
