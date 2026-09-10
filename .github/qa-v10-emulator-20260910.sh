#!/usr/bin/env bash
set -eu

APK='app/build/outputs/apk/debug/app-debug.apk'
PKG='com.openai.fxm1'

# 1) Build the exact committed QA sources and install the produced APK.
gradle --no-daemon :app:assembleDebug
test -s "$APK"
adb install -r "$APK"
adb shell pm grant "$PKG" android.permission.POST_NOTIFICATIONS || true
adb shell am force-stop "$PKG"
adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null
sleep 4

# Helper: locate a view by resource-id, scrolling down until it is visible, then optionally tap it.
cat >/tmp/fxm1_ui.py <<'PY'
import re, subprocess, sys, time, xml.etree.ElementTree as ET
pkg='com.openai.fxm1'
def dump(path='/tmp/ui.xml'):
    subprocess.run(['adb','shell','uiautomator','dump','/sdcard/ui.xml'], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(['adb','pull','/sdcard/ui.xml',path], check=True, stdout=subprocess.DEVNULL)
    return ET.parse(path).getroot()
def find(root, rid):
    want=f'{pkg}:id/{rid}'
    for n in root.iter():
        if n.attrib.get('resource-id') == want: return n
    return None
def bounds(n):
    nums=list(map(int,re.findall(r'-?\d+',n.attrib.get('bounds',''))))
    return nums if len(nums)==4 else None
def visible(n):
    b=bounds(n); return bool(b and b[2]>b[0] and b[3]>b[1] and b[3]>0 and b[1]<2400)
def locate(rid, max_swipes=12):
    root=dump(); n=find(root,rid)
    if n is not None and visible(n): return root,n
    for _ in range(max_swipes):
        subprocess.run(['adb','shell','input','swipe','540','1900','540','500','250'], check=True)
        time.sleep(.35); root=dump(); n=find(root,rid)
        if n is not None and visible(n): return root,n
    raise SystemExit(f'view not visible: {rid}')
def tap(n):
    x1,y1,x2,y2=bounds(n)
    subprocess.run(['adb','shell','input','tap',str((x1+x2)//2),str((y1+y2)//2)], check=True)
cmd=sys.argv[1]; rid=sys.argv[2]
_,n=locate(rid)
if cmd=='tap': tap(n)
elif cmd!='assert': raise SystemExit('unknown command')
PY

# 2) Verify the actual rendered positions card and money/history action.
python /tmp/fxm1_ui.py assert positionsCard
python /tmp/fxm1_ui.py assert positionsText
python /tmp/fxm1_ui.py tap moneyHistoryButton
sleep 1
adb shell uiautomator dump /sdcard/fxm1-dialog.xml >/dev/null
adb pull /sdcard/fxm1-dialog.xml /tmp/fxm1-dialog.xml >/dev/null
python - <<'PY'
import xml.etree.ElementTree as ET
root=ET.parse('/tmp/fxm1-dialog.xml').getroot()
text='\n'.join(n.attrib.get('text','') for n in root.iter())
assert 'Деньги / история MT5' in text, text
assert 'ВСЯ ИСТОРИЯ ЗАКРЫТЫХ СДЕЛОК' in text, text
print('Money/history rendered dialog: PASS')
PY

# 3) Start MonitoringService using debug-app preferences. AUTO is explicitly OFF; no bridge URL exists.
adb shell am force-stop "$PKG"
PREF_XML='<?xml version="1.0" encoding="utf-8" standalone="yes" ?><map><boolean name="auto_user_enabled" value="false" /><boolean name="auto_trading" value="false" /><string name="apikey">QA_DUMMY_KEY</string><string name="target_trade_mode">DEMO</string></map>'
printf '%s' "$PREF_XML" | adb shell run-as "$PKG" sh -c 'mkdir -p shared_prefs; cat > shared_prefs/fxm1.xml'
adb shell am start-foreground-service -n "$PKG/.MonitoringService" -a com.openai.fxm1.action.START_MONITORING >/dev/null
sleep 4

# 4) Inspect the Android notification shade: all three requested actions must render.
adb shell cmd statusbar expand-notifications
sleep 2
adb shell uiautomator dump /sdcard/shade.xml >/dev/null
adb pull /sdcard/shade.xml /tmp/shade.xml >/dev/null
python - <<'PY'
import xml.etree.ElementTree as ET
root=ET.parse('/tmp/shade.xml').getroot()
text='\n'.join((n.attrib.get('text','')+' '+n.attrib.get('content-desc','')).strip() for n in root.iter())
assert 'FX M1 Bot' in text, text
missing=[x for x in ('PLAY','PAUSE','EMERGENCY STOP') if x not in text]
assert not missing, f'missing notification actions: {missing}\n{text}'
print('Notification PLAY/PAUSE/EMERGENCY STOP: PASS')
PY
adb shell cmd statusbar collapse

# 5) Exercise PAUSE then PLAY through the actual service actions.
adb shell am start-foreground-service -n "$PKG/.MonitoringService" -a com.openai.fxm1.action.PAUSE_BACKGROUND >/dev/null
sleep 1
adb shell am start-foreground-service -n "$PKG/.MonitoringService" -a com.openai.fxm1.action.RESUME_BACKGROUND >/dev/null
sleep 1
adb shell run-as "$PKG" cat shared_prefs/fxm1.xml >/tmp/fxm1-prefs-after-play.xml
python - <<'PY'
import xml.etree.ElementTree as ET
root=ET.parse('/tmp/fxm1-prefs-after-play.xml').getroot()
vals={n.attrib.get('name'):n.attrib.get('value') for n in root if n.tag=='boolean'}
assert vals.get('bg_paused')=='false', vals
assert vals.get('trading_paused')=='false', vals
print('PAUSE/PLAY persisted state: PASS')
PY

# 6) Runtime emergency persistence test: seed AUTO flags true, restart, invoke confirmed emergency,
# then verify neither AUTO flag survives. No server_url is provided, so no order endpoint can be contacted.
adb shell am force-stop "$PKG"
PREF_XML='<?xml version="1.0" encoding="utf-8" standalone="yes" ?><map><boolean name="auto_user_enabled" value="true" /><boolean name="auto_trading" value="true" /><string name="apikey">QA_DUMMY_KEY</string><string name="target_trade_mode">DEMO</string></map>'
printf '%s' "$PREF_XML" | adb shell run-as "$PKG" sh -c 'mkdir -p shared_prefs; cat > shared_prefs/fxm1.xml'
adb shell am start-foreground-service -n "$PKG/.MonitoringService" -a com.openai.fxm1.action.EMERGENCY_CONFIRMED >/dev/null || true
sleep 2
adb shell run-as "$PKG" cat shared_prefs/fxm1.xml >/tmp/fxm1-prefs-after-emergency.xml
python - <<'PY'
import xml.etree.ElementTree as ET
root=ET.parse('/tmp/fxm1-prefs-after-emergency.xml').getroot()
vals={n.attrib.get('name'):n.attrib.get('value') for n in root if n.tag=='boolean'}
assert vals.get('auto_user_enabled')=='false', vals
assert vals.get('auto_trading')=='false', vals
assert vals.get('stop_all_requested')=='true', vals
print('Emergency persisted AUTO lockout: PASS')
PY

echo 'ANDROID EMULATOR SMOKE: PASS'
