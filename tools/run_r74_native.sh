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
# Same certificate: verify the reported defect against the actual shipped 933.
adb install -r "$R74_OLD_APK"
adb install -r "$TESTAPK"
adb shell am instrument -w -r -e class com.openai.fxm1.R74ControlUiTest com.openai.fxm1.ec1.test/androidx.test.runner.AndroidJUnitRunner > evidence/original-red.log 2>&1
grep -q 'QUEUED_RECEIPT_IS_NOT_APPLIED' evidence/original-red.log
grep -q 'FAILURES!!!' evidence/original-red.log
adb shell am instrument -w -r -e class com.openai.fxm1.R74UpgradeProbe#seedOldSettings com.openai.fxm1.ec1.test/androidx.test.runner.AndroidJUnitRunner > evidence/upgrade-seed.log 2>&1
grep -q 'OK (1 test)' evidence/upgrade-seed.log
# Upgrade, never uninstall or clear data between these two observations.
adb install -r "$APK"
adb shell am instrument -w -r -e class com.openai.fxm1.R74UpgradeProbe#verifyPreservedSettingsAfterUpdate com.openai.fxm1.ec1.test/androidx.test.runner.AndroidJUnitRunner > evidence/upgrade-check.log 2>&1
grep -q 'OK (1 test)' evidence/upgrade-check.log
python - <<'PY'
import json,hashlib
from pathlib import Path
apk=Path('app/build/outputs/apk/debug/app-debug.apk').read_bytes()
Path('evidence/UPGRADE_RESULT.json').write_text(json.dumps(dict(ok=True,previous_version_code=933,new_version_code=934,apk_sha256=hashlib.sha256(apk).hexdigest(),uninstalled=False)))
PY
classes=$(python - <<'PY'
from pathlib import Path
import re,json
files=sorted(p for p in Path('app/src/androidTest/java/com/openai/fxm1').glob('*Test.java') if p.stem!='V108RepairTest')
tests=[]
for p in files:tests.extend(re.findall(r'@Test\s+(?:public\s+)?void\s+(\w+)\s*\(',p.read_text()))
Path('evidence/EXPECTED_NATIVE_TESTS.json').write_text(json.dumps(dict(tests=tests,classes=[p.stem for p in files],excluded_legacy='V108RepairTest — retired V10.8/TwelveData protocol'),indent=2))
print(','.join('com.openai.fxm1.'+p.stem for p in files))
PY
)
set +e
gradle --no-daemon :app:connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.class="$classes" > evidence/android.log 2>&1
rc=$?
set -e
timeout 15s adb logcat -d > evidence/logcat.txt 2>&1 || true
adb pull /sdcard/Download/ec1-qa evidence/ui > evidence/png-export.log 2>&1 || true
if test -d app/build/outputs/androidTest-results; then cp -r app/build/outputs/androidTest-results evidence/; fi
cp "$APK" evidence/FXM1_R7_4.apk
sha256sum -c evidence/tested-apk-before.sha
python - <<'PY'
import json,hashlib,subprocess,xml.etree.ElementTree as E
from pathlib import Path
source=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip();Path('evidence/SOURCE_COMMIT.txt').write_text(source)
cases=[]
for p in Path('evidence/androidTest-results').rglob('*.xml'):cases.extend(E.parse(p).getroot().iter('testcase'))
meta=json.loads(Path('app/build/outputs/apk/debug/output-metadata.json').read_text());el=meta['elements'][0]
assert el['versionCode']==934 and el['versionName']=='10.9-EC1-R7.4' and meta['applicationId']=='com.openai.fxm1.ec1'
identity=dict(source_sha=source,tested_apk_sha256=hashlib.sha256(Path('evidence/FXM1_R7_4.apk').read_bytes()).hexdigest(),certificate_sha256='3d55a491046e661664f99c2a3e4a51338a794b313beb3e32d7ed88181a7a1885',version_code=el['versionCode'],version_name=el['versionName'],application_id=meta['applicationId'],native_tests=len(cases))
Path('evidence/IDENTITY.json').write_text(json.dumps(identity,indent=2))
assert len(cases)>=200,'Missing native cases'
failed=[t.get('classname')+'.'+t.get('name') for t in cases if any(t.find(k) is not None for k in ('failure','error','skipped'))]
Path('evidence/NATIVE_RESULT.json').write_text(json.dumps(dict(source_sha=source,count=len(cases),failures=failed,production_signature_verified=True),indent=2))
print('NATIVE_RESULT',len(cases),'failed',failed)
assert not failed
PY
exit "$rc"
