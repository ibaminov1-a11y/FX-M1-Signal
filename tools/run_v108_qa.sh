#!/usr/bin/env bash
set -uo pipefail
mkdir -p evidence/ui
adb logcat -c
set +e
gradle --no-daemon --stacktrace :app:connectedDebugAndroidTest > evidence/android-tests.log 2>&1
code=$?
set -e
adb logcat -d > evidence/logcat.txt || true
adb pull /sdcard/Download/v108-qa evidence/ui/ || true
cat evidence/android-tests.log
exit "$code"
