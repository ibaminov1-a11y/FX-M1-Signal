#!/usr/bin/env bash
set -euo pipefail
mkdir -p evidence/ui
export PYTHONPATH=mt5_bridge:tests/event_core
python tests/event_core/export_r732_chart_fixtures.py
python tests/event_core/ui_fixture.py > evidence/fixture.log 2>&1 &
fixture=$!
trap 'kill "$fixture" 2>/dev/null || true' EXIT
for i in $(seq 1 30); do
 if curl -fsS -H 'Authorization: Bearer ci-fixture-token-not-for-real-trading' http://127.0.0.1:8765/health >/dev/null; then break; fi
 sleep 1
done
curl -fsS -H 'Authorization: Bearer ci-fixture-token-not-for-real-trading' http://127.0.0.1:8765/health >/dev/null
adb reverse tcp:8765 tcp:8765
gradle --no-daemon :app:assembleDebug :app:assembleDebugAndroidTest > evidence/build.log 2>&1
APK=app/build/outputs/apk/debug/app-debug.apk
TESTAPK=app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
signer=$(find "$ANDROID_HOME/build-tools" -name apksigner | sort -V | tail -1)
"$signer" verify --print-certs "$APK" > evidence/apk-signature.txt
grep -q '3d55a491046e661664f99c2a3e4a51338a794b313beb3e32d7ed88181a7a1885' evidence/apk-signature.txt
sha256sum "$APK" > evidence/apk-before.sha
adb install -r "$F1_OLD_APK"
adb install -r "$TESTAPK"
adb shell am instrument -w -r -e class com.openai.fxm1.R74ForecastUpgradeProbe#seedOldSettings com.openai.fxm1.ec1.test/androidx.test.runner.AndroidJUnitRunner > evidence/upgrade-seed.log 2>&1
grep -q 'OK (1 test)' evidence/upgrade-seed.log
adb install -r "$APK"
adb shell am instrument -w -r -e class com.openai.fxm1.R74ForecastUpgradeProbe#verifyPreservedSettings com.openai.fxm1.ec1.test/androidx.test.runner.AndroidJUnitRunner > evidence/upgrade-check.log 2>&1
grep -q 'OK (1 test)' evidence/upgrade-check.log
classes=$(python - <<'PY'
from pathlib import Path
import re,json
files=sorted(p for p in Path('app/src/androidTest/java/com/openai/fxm1').glob('*Test.java') if p.stem!='V108RepairTest')
tests=[]
for p in files:
 tests.extend('com.openai.fxm1.'+p.stem+'.'+n for n in re.findall(r'@Test\s+(?:public\s+)?void\s+(\w+)\s*\(',p.read_text()))
Path('evidence/EXPECTED.json').write_text(json.dumps(tests,indent=2))
print(','.join('com.openai.fxm1.'+p.stem for p in files))
PY
)
set +e
gradle --no-daemon :app:connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.class="$classes" > evidence/android.log 2>&1
rc=$?
set -e
timeout 15s adb logcat -d > evidence/logcat.txt 2>&1 || true
adb pull /sdcard/Download/ec1-qa evidence/ui > evidence/png-export.log 2>&1 || true
cp -r app/build/outputs/androidTest-results evidence/ 2>/dev/null || true
cp "$APK" evidence/FXM1_R7_4_F1.apk
sha256sum -c evidence/apk-before.sha
python - <<'PY'
import json,hashlib,subprocess,xml.etree.ElementTree as E
from pathlib import Path
cases=[]
for p in Path('evidence/androidTest-results').rglob('*.xml'):cases.extend(E.parse(p).getroot().iter('testcase'))
actual=[t.get('classname')+'.'+t.get('name') for t in cases]
expected=json.loads(Path('evidence/EXPECTED.json').read_text())
failed=[t.get('classname')+'.'+t.get('name') for t in cases if any(t.find(k) is not None for k in ('failure','error','skipped'))]
meta=json.loads(Path('app/build/outputs/apk/debug/output-metadata.json').read_text());item=meta['elements'][0]
report=dict(source_sha=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),count=len(cases),expected_count=len(expected),failed=failed,missing=sorted(set(expected)-set(actual)),unexpected=sorted(set(actual)-set(expected)),version_code=item['versionCode'],version_name=item['versionName'],apk_sha256=hashlib.sha256(Path('evidence/FXM1_R7_4_F1.apk').read_bytes()).hexdigest(),upgrade_from=934,upgrade_to=935,uninstalled=False,bridge_code_changed=False,live_mt5=False)
Path('evidence/RESULT.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
assert item['versionCode']==935 and item['versionName']=='10.9-EC1-R7.4-F1'
assert meta['applicationId']=='com.openai.fxm1.ec1'
assert len(actual)==len(expected)==len(set(actual)) and not failed and set(actual)==set(expected)
PY
exit "$rc"
