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
adb reverse tcp:8765 tcp:8765
set +e
bash tools/audit53_red_ui.sh
red_rc=$?
gradle --no-daemon --stacktrace :app:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=com.openai.fxm1.EventCoreUiTest,com.openai.fxm1.CampaignSignalUiTest,com.openai.fxm1.ScenarioMapUiTest,com.openai.fxm1.ScenarioUpgradeUiTest,com.openai.fxm1.R5SettingsHistoryTest,com.openai.fxm1.R5RedContractUiTest,com.openai.fxm1.R51RepairUiTest,com.openai.fxm1.LiveLayoutUiTest,com.openai.fxm1.R53ControlsUiTest,com.openai.fxm1.R53ScenarioDisplayUiTest \
  > evidence/android-runtime.log 2>&1
rc=$?
adb logcat -d > evidence/android-logcat.txt
adb pull /sdcard/Download/ec1-qa evidence/ui || true
cat evidence/android-runtime.log
if [ "$red_rc" -ne 0 ]; then exit "$red_rc"; fi
if [ "$rc" -eq 0 ]; then
  python tools/audit53_report.py
  signer=$(find "$ANDROID_HOME/build-tools" -name apksigner | sort -V | tail -1)
  "$signer" verify --print-certs app/build/outputs/apk/debug/app-debug.apk > evidence/apk-signature.txt
  grep -q '3d55a491046e661664f99c2a3e4a51338a794b313beb3e32d7ed88181a7a1885' evidence/apk-signature.txt
  python - <<'CHECK'
from pathlib import Path
assert 'versionCode 922' in Path('app/build.gradle').read_text()
Path('evidence/package-check.txt').write_text('versionCode 922; original EC1 signing identity verified; exact commit recorded in COMMIT.txt\n')
CHECK
  test -s evidence/ui/ec1-qa/r52-layout-short.png || exit 1
  test -s evidence/ui/ec1-qa/r52-layout-long.png || exit 1
  test -s evidence/ui/ec1-qa/r52-full-details.png || exit 1
  test -s evidence/ui/ec1-qa/r52-live-history-stable.png || exit 1
  test -s evidence/ui/ec1-qa/r51-instruments.png || exit 1
  test -s evidence/ui/ec1-qa/r51-fullscreen-map.png || exit 1
  test -s evidence/ui/ec1-qa/scenario-wait.png || exit 1
  test -s evidence/ui/ec1-qa/scenario-active-reversal.png || exit 1
  test -s evidence/ui/ec1-qa/r5-fullscreen-scenarios.png || exit 1
  test -s evidence/ui/ec1-qa/r5-history-viewport.png || exit 1
  test -s evidence/ui/ec1-qa/r53-sell-preparation.png || exit 1
  test -s evidence/ui/ec1-qa/r53-buy-preparation.png || exit 1
  test -s evidence/ui/ec1-qa/r53-live-versus-entry.png || exit 1
  test -s evidence/ui/ec1-qa/r53-offline-cache.png || exit 1
fi
exit "$rc"
