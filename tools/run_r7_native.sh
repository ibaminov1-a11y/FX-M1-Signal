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
# V108RepairTest covers the retired pre-EventCore protocol/version10.8.
# All current EventCore test classes run, including the own-risk UI.
classes=$(python - <<'PY'
from pathlib import Path
print(','.join('com.openai.fxm1.'+p.stem for p in sorted(Path('app/src/androidTest/java/com/openai/fxm1').glob('*Test.java')) if p.stem!='V108RepairTest'))
PY
)
set +e
gradle --no-daemon --stacktrace :app:connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.class="$classes" > evidence/android-runtime.log 2>&1
rc=$?
set -e
adb logcat -d > evidence/android-logcat.txt
adb pull /sdcard/Download/ec1-qa evidence/ui || true
adb pull /sdcard/Android/data/com.openai.fxm1.ec1/files evidence/ui/app-files || true
cat evidence/android-runtime.log
if [ "$rc" -ne 0 ]; then exit "$rc"; fi
python - <<'PY'
import json,subprocess
from pathlib import Path
import xml.etree.ElementTree as E
cases=[]
for p in Path('app/build/outputs/androidTest-results').rglob('*.xml'):
    cases.extend(E.parse(p).getroot().iter('testcase'))
assert cases, 'No executed Android tests'
assert all(t.find('failure') is None and t.find('error') is None and t.find('skipped') is None for t in cases)
def count(name):return sum(t.attrib.get('classname','').endswith(name) for t in cases)
assert count('R7ReleaseUiTest')==6
assert count('R73ChartUiTest')>=19
assert count('R73ControlsUiTest')>=19
result={'commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'tests':len(cases),'r7_tests':count('R7ReleaseUiTest'),'failures':0,
        'r73_chart_tests':count('R73ChartUiTest'),'r73_controls_tests':count('R73ControlsUiTest'),
        'excluded_legacy_suite':'V108RepairTest: retired V10.8/TwelveData protocol'}
Path('evidence/ANDROID_RESULT.json').write_text(json.dumps(result,indent=2))
print('R73_NATIVE_GREEN',json.dumps(result))
PY
signer=$(find "$ANDROID_HOME/build-tools" -name apksigner | sort -V | tail -1)
"$signer" verify --print-certs app/build/outputs/apk/debug/app-debug.apk > evidence/apk-signature.txt
grep -q '3d55a491046e661664f99c2a3e4a51338a794b313beb3e32d7ed88181a7a1885' evidence/apk-signature.txt
