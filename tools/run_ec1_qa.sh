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
gradle --no-daemon --stacktrace :app:connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.class=com.openai.fxm1.EventCoreUiTest > evidence/android-runtime.log 2>&1
rc=$?
adb logcat -d > evidence/android-logcat.txt
adb pull /sdcard/Download/ec1-qa evidence/ui || true
cat evidence/android-runtime.log
exit "$rc"
