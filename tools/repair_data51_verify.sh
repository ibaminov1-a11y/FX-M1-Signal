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
python tools/repair_data51_apply.py
# Re-run new Python regressions against an isolated unchanged baseline.
python - <<'PY'
from pathlib import Path
import os,subprocess,tempfile,tarfile,io,shutil
root=Path.cwd()
with tempfile.TemporaryDirectory() as td:
    data=subprocess.check_output(['git','archive','HEAD','mt5_bridge','tests'])
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:tf.extractall(td,filter='data')
    shutil.copy2('tests/event_core/test_r51_repairs.py',Path(td)/'tests/event_core/test_r51_repairs.py')
    env=dict(os.environ,PYTHONPATH='mt5_bridge:tests/event_core')
    code="import unittest; s=unittest.defaultTestLoader.discover('tests/event_core',pattern='test_r51_repairs.py'); r=unittest.TextTestRunner(verbosity=2).run(s); assert r.testsRun==15; assert not r.errors; assert len(r.failures)>=10"
    p=subprocess.run(['python','-c',code],cwd=td,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    (root/'evidence/red/python.log').write_text(p.stdout)
    print(p.stdout);assert p.returncode==0,'Baseline regressions not reproduced as expected'
    (root/'evidence/RED.txt').write_text('R5.1 regressions reproduced on unchanged R5 baseline. See red/python.log and red/android.log. These failures are intentional baseline evidence, not release results.')
PY
python -m compileall -q mt5_bridge/event_core tests/event_core
set -o pipefail
PYTHONPATH=mt5_bridge:tests/event_core python -m unittest discover -s tests/event_core -p 'test_*.py' -v 2>&1 | tee evidence/python-tests.log
git diff --check --cached
# No workflow mutation in the product commit; the current build is explicitly approved.
test -z "$(git diff --cached --name-only -- .github/)"
git config user.name 'FXM1 CI'
git config user.email 'fxm1-ci@users.noreply.github.com'
git commit -m 'fix: R5.1 native UTC history, preserved watchlist and truthful scenario diagnostics'
git rev-parse HEAD | tee evidence/COMMIT.txt
bash tools/run_ec1_qa.sh
python tools/repair_data51_apply.py --verify
signer=$(find "$ANDROID_HOME/build-tools" -name apksigner | sort -V | tail -1)
"$signer" verify --print-certs app/build/outputs/apk/debug/app-debug.apk | tee evidence/apk-signature.txt
grep -q '3d55a491046e661664f99c2a3e4a51338a794b313beb3e32d7ed88181a7a1885' evidence/apk-signature.txt
python tools/package_ec1.py
python - <<'PY' | tee evidence/package-check.txt
import hashlib,json,subprocess,zipfile
from pathlib import Path
root=Path.cwd();head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
meta=json.loads(Path('evidence/package/PROVENANCE.json').read_text());assert meta['commit']==head
with zipfile.ZipFile('evidence/FXM1_EVENT_CORE_SOURCE.zip') as source:
    for file in Path('evidence/package/Bridge/event_core').rglob('*.py'):
        path='mt5_bridge/event_core/'+str(file.relative_to('evidence/package/Bridge/event_core'))
        assert file.read_bytes()==source.read(path),path
apk=Path('evidence/package/FXM1_10_9_EVENT_CORE_DEMO.apk')
assert hashlib.sha256(apk.read_bytes()).hexdigest()==meta['apk_sha256']
assert b'versionCode 919' in Path('app/build.gradle').read_bytes()
print('EXACT_SOURCE_APK_AND_BRIDGE_VERIFIED',head)
print('APK_SHA256',meta['apk_sha256'])
PY
# The final artifact records the source actually tested; never force a changed branch.
git push origin HEAD:feature/r4-compute-rebuild
