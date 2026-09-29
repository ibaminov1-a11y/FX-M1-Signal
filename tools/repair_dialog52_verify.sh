#!/usr/bin/env bash
set -euo pipefail
mkdir -p evidence/dialog-red
python - <<'PY'
from pathlib import Path
import hashlib,subprocess
p=Path('tools/repair_dialog52_test.patch').read_bytes()
assert hashlib.sha256(p).hexdigest()=='7d1594303e464b102a274f6833bb384f2d3085a0ad5c7bce590af6721cb28356'
subprocess.run(['git','apply','--unidiff-zero','--check','-'],input=p,check=True)
subprocess.run(['git','apply','--unidiff-zero','-'],input=p,check=True)
PY
PYTHONPATH=mt5_bridge:tests/event_core python tests/event_core/ui_fixture.py > evidence/dialog-red/fixture.log 2>&1 &
fixture=$!
trap 'kill "$fixture" 2>/dev/null || true' EXIT
for i in $(seq 1 30); do
  if curl -fsS -H 'Authorization: Bearer ci-fixture-token-not-for-real-trading' http://127.0.0.1:8765/health >/dev/null; then break; fi
  sleep 1
done
adb reverse tcp:8765 tcp:8765
set +e
gradle --no-daemon :app:connectedDebugAndroidTest '-Pandroid.testInstrumentationRunnerArguments.class=com.openai.fxm1.LiveLayoutUiTest#fullTextRemainsReadableInFrozenSnapshot' > evidence/dialog-red/android.log 2>&1
rc=$?
set -e
cat evidence/dialog-red/android.log
cp -r app/build/outputs/androidTest-results evidence/dialog-red/results
python - <<'PY'
from pathlib import Path
import xml.etree.ElementTree as ET
cases=[]
for p in Path('evidence/dialog-red/results').rglob('TEST-*.xml'):
    cases.extend(ET.parse(p).getroot().iter('testcase'))
assert len(cases)==1,len(cases)
t=cases[0];assert t.get('name','').startswith('fullTextRemainsReadableInFrozenSnapshot')
f=t.find('failure');assert f is not None
assert 'Snapshot close button' in (f.get('message','')+' '+(f.text or '')),ET.tostring(t)
assert t.find('error') is None
Path('evidence/DIALOG_RED_CONFIRMED.txt').write_text('Long snapshot pushes close button offscreen in build920; reproduced before fix.\n')
print('DIALOG_RED_CONFIRMED')
PY
kill "$fixture" 2>/dev/null || true
wait "$fixture" 2>/dev/null || true
trap - EXIT
python - <<'PY'
from pathlib import Path
import hashlib,subprocess
p=Path('tools/repair_dialog52.patch').read_bytes()
assert hashlib.sha256(p).hexdigest()=='74583f0115d31678aa323cba42178e1b4014800d0d9ae71eb554cb87780ebe9a'
subprocess.run(['git','apply','--unidiff-zero','--check','-'],input=p,check=True)
subprocess.run(['git','apply','--unidiff-zero','-'],input=p,check=True)
PY
python tools/repair_layout52_apply.py --verify
git add -- app/build.gradle app/src/main/java/com/openai/fxm1/StableLiveTextView.java app/src/androidTest/java/com/openai/fxm1/LiveLayoutUiTest.java docs/UPGRADE_R52.md tools/repair_layout52_manifest.json tools/repair_layout52_verify.py
git diff --cached --check
test -z "$(git diff --cached --name-only -- .github/)"
git config user.name 'FXM1 CI'
git config user.email 'fxm1-ci@users.noreply.github.com'
git commit -m 'fix: keep full live snapshot scrollable with visible close control in R5.2 build921'
git rev-parse HEAD > evidence/COMMIT.txt
git archive --format=zip HEAD -o evidence/R52_CANDIDATE_SOURCE.zip
set -o pipefail
python -m compileall -q mt5_bridge/event_core tests/event_core
PYTHONPATH=mt5_bridge:tests/event_core python -m unittest discover -s tests/event_core -p 'test_*.py' -v 2>&1 | tee evidence/python-tests.log
bash tools/run_ec1_qa.sh
python tools/repair_layout52_verify.py
python tools/repair_layout52_apply.py --verify
git diff --exit-code
signer=$(find "$ANDROID_HOME/build-tools" -name apksigner | sort -V | tail -1)
"$signer" verify --print-certs app/build/outputs/apk/debug/app-debug.apk | tee evidence/apk-signature.txt
grep -q '3d55a491046e661664f99c2a3e4a51338a794b313beb3e32d7ed88181a7a1885' evidence/apk-signature.txt
python tools/package_ec1.py
python tools/repair_layout52_verify.py --package
python tools/package_ec1.py
python tools/repair_layout52_verify.py --package
git push origin HEAD:feature/r4-compute-rebuild
