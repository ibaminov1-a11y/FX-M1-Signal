#!/usr/bin/env bash
# Reproduce the reported upgrade failure, then test and package an exact source commit.
set -euo pipefail
mkdir -p evidence/baseline-ui
expected=e434f7cbdbce98d926ff2e692ee99684dae3fa9b584ac43a10049baacf79c83c
base=1274d114a98bce7bace5185da84f4ab344f8b87b
test "$(git rev-parse HEAD^)" = "$base"
cat tools/r42patch.part[0-9][0-9] | gzip -dc > /tmp/r42.patch
echo "$expected  /tmp/r42.patch" | sha256sum -c -
git rev-parse HEAD > evidence/TRIGGER_COMMIT.txt
git apply --include='tests/**' --include='app/src/androidTest/**' /tmp/r42.patch
PYTHONPATH=mt5_bridge:tests/event_core python tests/event_core/ui_fixture.py > evidence/baseline-fixture.log 2>&1 &
fixture=$!
trap 'kill "$fixture" 2>/dev/null || true' EXIT
ready=0
for i in $(seq 1 30); do
  if curl -fsS -H 'Authorization: Bearer ci-fixture-token-not-for-real-trading' http://127.0.0.1:8765/health >/dev/null; then ready=1; break; fi
  sleep 1
done
test "$ready" = 1
adb reverse tcp:8765 tcp:8765
set +e
gradle --no-daemon --stacktrace :app:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=com.openai.fxm1.ScenarioUpgradeUiTest > evidence/baseline-android.log 2>&1
red=$?
set -e
cat evidence/baseline-android.log
kill "$fixture"; wait "$fixture" 2>/dev/null || true
trap - EXIT
adb pull /sdcard/Download/ec1-qa evidence/baseline-ui || true
test "$red" -ne 0
grep -q 'Legacy +5/+10/+15 forecast must never return' evidence/baseline-android.log
grep -q 'AUTO intent must be accepted' evidence/baseline-android.log
echo 'RED_VERIFIED: old forecast and actual AUTO upgrade regressions' | tee evidence/RED.txt
# The remaining patch contains only implementation/configuration/docs, not test changes.
git apply --exclude='tests/**' --exclude='app/src/androidTest/**' /tmp/r42.patch
git diff --check
git add app mt5_bridge/event_core tests/event_core docs/UPGRADE_R42.md tools/run_ec1_qa.sh
git -c user.name='FXM1 CI' -c user.email='fxm1-ci@users.noreply.github.com' commit -m 'fix: migrate legacy campaigns without blocking AUTO and render structural scenario map'
git rev-parse HEAD | tee evidence/COMMIT.txt
python -m compileall -q mt5_bridge/event_core tests/event_core
PYTHONPATH=mt5_bridge:tests/event_core python -m unittest discover -s tests/event_core -p 'test_*.py' -v 2>&1 | tee evidence/python-tests.log
# Existing test runner runs the actual app and Engine fixture, now with the upgrade tests.
bash tools/run_ec1_qa.sh
test -s evidence/ui/ec1-qa/r42-fullscreen-map.png
test -s evidence/ui/ec1-qa/r42-auto-wait.png
python tools/package_ec1.py
sha256sum evidence/FXM1_10_9_EVENT_CORE_DEMO.apk | tee evidence/APK_SHA256.txt
python - <<'PY'
import json, subprocess
from pathlib import Path
p=json.loads(Path('evidence/package/PROVENANCE.json').read_text())
assert p['commit']==subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
assert '10.9-EC1-R4.2' in Path('app/build.gradle').read_text()
print('PROVENANCE_OK',p['commit'])
PY
git diff --exit-code
git push origin HEAD:refs/heads/feature/r4-compute-rebuild
printf '%s\n' 'Source fast-forwarded only after successful full tests and packaging.' > evidence/PUBLISH.txt
