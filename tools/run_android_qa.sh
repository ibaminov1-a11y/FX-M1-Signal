#!/usr/bin/env bash
set -euo pipefail
mkdir -p evidence/ui
python v11_bridge/tests/ui_fixture_server.py > evidence/fixture-server.log 2>&1 &
fixture_pid=$!
trap 'kill "$fixture_pid" 2>/dev/null || true' EXIT
sleep 2
result=0
gradle --no-daemon --stacktrace :app:connectedDebugAndroidTest > evidence/android-runtime.txt 2>&1 || result=$?
adb logcat -d > evidence/logcat.txt || true
adb shell dumpsys notification --noredact > evidence/notification.txt || true
adb pull /sdcard/Download/v11-qa evidence/ui || true
cat evidence/android-runtime.txt
if [ "$result" -ne 0 ]; then exit "$result"; fi
python - <<'PY'
from pathlib import Path
import xml.etree.ElementTree as ET
files=list(Path('app/build/outputs/androidTest-results').rglob('TEST-*.xml'))
assert files, 'Instrumentation JUnit XML is missing'
cases=[]
for f in files:
    root=ET.parse(f).getroot()
    assert int(root.attrib.get('failures',0))==0 and int(root.attrib.get('errors',0))==0, f
    cases.extend(root.findall('.//testcase'))
assert len(cases)==6, f'Expected 6 actual instrumentation cases, got {len(cases)}'
assert not any(c.find('skipped') is not None for c in cases), 'Skipped instrumentation case'
for name in ['01-trading','02-history','03-settings','04-notification','05-emergency']:
    matches=list(Path('evidence/ui').rglob(name+'.png'))
    assert len(matches)==1 and matches[0].stat().st_size>1000, 'Missing screenshot: '+name
assert (Path('evidence/ui/v11-qa')/'purple-candle-render.png').stat().st_size>1000, 'Missing actual candle rendering evidence'
print('Executed Android cases:',len(cases),'; required screenshots: 5; candle render: present')
PY
