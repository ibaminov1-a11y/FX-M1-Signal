#!/usr/bin/env bash
set -euo pipefail
mkdir -p evidence
base=052a6bd19aaad40bbb7352551bbd62386cf1dc54
git merge-base --is-ancestor "$base" HEAD
git diff --exit-code "$base" HEAD -- app/src/main app/build.gradle mt5_bridge tests
export PYTHONPATH=mt5_bridge:tests/event_core
python tools/apply_r5_bundle.py red
set +e
python -m unittest test_r5_lot_history -v > evidence/r5-python-red.log 2>&1
red=$?
set -e
cat evidence/r5-python-red.log
test "$red" -ne 0
grep -q 'FAILED' evidence/r5-python-red.log
python tests/event_core/ui_fixture.py > evidence/r5-red-fixture.log 2>&1 &
fixture=$!
trap 'kill "$fixture" 2>/dev/null || true' EXIT
ready=0
for i in $(seq 1 30); do
 if curl -fsS -H 'Authorization: Bearer ci-fixture-token-not-for-real-trading' http://127.0.0.1:8765/health >/dev/null; then ready=1;break;fi
 sleep 1
done
test "$ready" -eq 1
adb reverse tcp:8765 tcp:8765
set +e
gradle --no-daemon --stacktrace :app:connectedDebugAndroidTest \
 -Pandroid.testInstrumentationRunnerArguments.class=com.openai.fxm1.R5SettingsHistoryTest\#configTransmitsChosenLotNotHardcoded001,com.openai.fxm1.R5SettingsHistoryTest\#lotSelectorHasPresetsAndCustomChoice,com.openai.fxm1.R5SettingsHistoryTest\#historyViewportStaysAnchoredWhileNewBarsArrive \
 > evidence/r5-android-red.log 2>&1
red=$?
set -e
cat evidence/r5-android-red.log
test "$red" -ne 0
grep -q 'Chosen lot must reach Bridge' evidence/r5-android-red.log
grep -q 'Lot selector needs preset sizes and manual input' evidence/r5-android-red.log
grep -q 'Historical viewport methods are missing' evidence/r5-android-red.log
kill "$fixture";wait "$fixture" || true
trap - EXIT
printf 'RED observed: fixed-volume/clock/history Python regressions; actual Android lot config, selector and anchored viewport regressions.\n' > evidence/RED.txt
python tools/apply_r5_bundle.py green
if test -f tools/r5_postfix.py; then python tools/r5_postfix.py; fi
python -m compileall -q mt5_bridge/event_core tests/event_core
python -m unittest discover -s tests/event_core -p 'test_*.py' -v 2>&1 | tee evidence/python-tests.log
git diff --check
git config user.name 'FXM1 CI'
git config user.email 'fxm1-ci@users.noreply.github.com'
git add app mt5_bridge tests docs .github/workflows/ec1-r3-rebuild-check.yml tools/package_ec1.py tools/run_ec1_qa.sh
git commit -m 'feat: R5 fixed lots, structural event scenarios, immutable archive and anchored LIVE/history chart'
git rev-parse HEAD | tee evidence/COMMIT.txt
bash tools/run_ec1_qa.sh
apksigner=$(find "${ANDROID_SDK_ROOT:-$ANDROID_HOME}/build-tools" -name apksigner | sort -V | tail -1)
"$apksigner" verify --print-certs app/build/outputs/apk/debug/app-debug.apk | tee evidence/APK_CERTIFICATE.txt
grep -q '3d55a491046e661664f99c2a3e4a51338a794b313beb3e32d7ed88181a7a1885' evidence/APK_CERTIFICATE.txt
sha256sum app/build/outputs/apk/debug/app-debug.apk | tee evidence/APK_SHA256.txt
python tools/package_ec1.py
python - <<'PY'
import json,subprocess
from pathlib import Path
p=json.loads(Path('evidence/package/PROVENANCE.json').read_text())
assert p['commit']==subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
assert p['real_trading']=='disabled_in_adapter'
assert p['revision']=='R5-scenario-v2-fixed-lot-history'
print('EXACT_SOURCE_PACKAGE_VERIFIED',p['commit'])
PY
git diff --exit-code
git push origin HEAD:refs/heads/feature/r4-compute-rebuild
printf 'Functional tests passed. No live MT5 terminal orders; no market profitability backtest or physical-phone test.\n' > evidence/RESULT.txt
