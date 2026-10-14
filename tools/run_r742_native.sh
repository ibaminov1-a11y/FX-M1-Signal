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
sha256sum "$APK" > evidence/tested-apk-before.sha
printf '9cb2b370b8bc1a13c49b2c7b4da87aaf39a84e96da1231ff7b1f2cfcf8a0381d  %s\n' "$R742_OLD_APK" | sha256sum -c -
adb install -r "$R742_OLD_APK" > evidence/install-old.log
adb install -r "$TESTAPK" > evidence/install-test.log
adb shell am instrument -w -r -e class com.openai.fxm1.R742ForecastContractTest com.openai.fxm1.ec1.test/androidx.test.runner.AndroidJUnitRunner > evidence/original-red.log 2>&1
grep -q 'FORECAST_BUTTON_IS_PATTERNS' evidence/original-red.log
grep -q 'ORIGINAL_FORECAST_OVERWRITTEN' evidence/original-red.log
grep -q 'FAILURES!!!' evidence/original-red.log
adb shell am instrument -w -r -e class com.openai.fxm1.R742UpgradeProbe#seedOld com.openai.fxm1.ec1.test/androidx.test.runner.AndroidJUnitRunner > evidence/upgrade-seed.log 2>&1
grep -q 'OK (1 test)' evidence/upgrade-seed.log
adb install -r "$APK" > evidence/install-new.log
adb shell am instrument -w -r -e class com.openai.fxm1.R742UpgradeProbe#checkNew com.openai.fxm1.ec1.test/androidx.test.runner.AndroidJUnitRunner > evidence/upgrade-check.log 2>&1
grep -q 'OK (1 test)' evidence/upgrade-check.log
classes=$(python - <<'PY'
from pathlib import Path
import re,json
files=sorted(p for p in Path('app/src/androidTest/java/com/openai/fxm1').glob('*Test.java') if p.stem!='V108RepairTest')
expected=[]
for p in files:expected.extend('com.openai.fxm1.'+p.stem+'.'+n for n in re.findall(r'@Test\s+(?:public\s+)?void\s+(\w+)\s*\(',p.read_text()))
assert len(expected)>=223
Path('evidence/EXPECTED_NATIVE_TESTS.json').write_text(json.dumps(dict(tests=expected,excluded_legacy='V108RepairTest — retired V10.8/TwelveData protocol'),indent=2))
print(','.join('com.openai.fxm1.'+p.stem for p in files))
PY
)
set +e
gradle --no-daemon :app:connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.class="$classes" > evidence/android.log 2>&1
rc=$?
set -e
timeout 15s adb logcat -d > evidence/logcat.txt 2>&1 || true
adb pull /sdcard/Download/ec1-qa evidence/ui > evidence/png-export.log 2>&1 || true
for file in r742-forecast-line r742-forecast-comparison r742-forecast-offline r742-activity-forecast r742-activity-fullscreen; do
 adb pull "/sdcard/Android/data/com.openai.fxm1.ec1/files/$file.png" "evidence/ui/$file.png" >> evidence/png-export.log 2>&1 || true
done
if test -d app/build/outputs/androidTest-results; then cp -r app/build/outputs/androidTest-results evidence/; fi
cp "$APK" evidence/FXM1_R7_4_2_FORECAST.apk
sha256sum -c evidence/tested-apk-before.sha
git rev-parse HEAD > evidence/SOURCE_COMMIT.txt
git archive --format=zip --output=evidence/SOURCE.zip HEAD
python - <<'PY'
import json,hashlib,xml.etree.ElementTree as E
from pathlib import Path
cases=[]
for p in Path('evidence/androidTest-results').rglob('*.xml'):cases.extend(E.parse(p).getroot().iter('testcase'))
actual=[t.get('classname')+'.'+t.get('name') for t in cases]
expected=json.loads(Path('evidence/EXPECTED_NATIVE_TESTS.json').read_text())['tests']
failures=[t.get('classname')+'.'+t.get('name') for t in cases if any(t.find(k) is not None for k in ('failure','error','skipped'))]
meta=json.loads(Path('app/build/outputs/apk/debug/output-metadata.json').read_text());v=meta['elements'][0]
result=dict(count=len(cases),failures=failures,missing=sorted(set(expected)-set(actual)),extra=sorted(set(actual)-set(expected)),version_code=v['versionCode'],version_name=v['versionName'],application_id=meta['applicationId'],apk_sha256=hashlib.sha256(Path('evidence/FXM1_R7_4_2_FORECAST.apk').read_bytes()).hexdigest(),source_sha=Path('evidence/SOURCE_COMMIT.txt').read_text().strip(),certificate_sha256='3d55a491046e661664f99c2a3e4a51338a794b313beb3e32d7ed88181a7a1885',upgrade_from=934,uninstall_for_upgrade=False,bridge_changed=False)
Path('evidence/NATIVE_RESULT.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
assert not failures and not result['missing'] and not result['extra']
assert len(actual)==len(set(actual)) and len(cases)>=223
assert v['versionCode']==935 and meta['applicationId']=='com.openai.fxm1.ec1'
PY
exit "$rc"
