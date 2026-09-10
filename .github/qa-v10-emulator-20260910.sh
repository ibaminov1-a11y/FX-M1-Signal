#!/usr/bin/env bash
set -eu
APK='app/build/outputs/apk/debug/app-debug.apk'
PKG='com.openai.fxm1'

gradle --no-daemon :app:assembleDebug
test -s "$APK"
adb install -r "$APK"
adb shell pm grant "$PKG" android.permission.POST_NOTIFICATIONS || true

seed_prefs() {
  xml="$1"
  adb shell run-as "$PKG" mkdir -p shared_prefs
  printf '%s' "$xml" | adb shell run-as "$PKG" tee shared_prefs/fxm1.xml >/dev/null
}

# Start foreground monitoring safely: DEMO, AUTO off, no bridge URL.
adb shell am force-stop "$PKG"
PREF_XML='<?xml version="1.0" encoding="utf-8" standalone="yes" ?><map><boolean name="auto_user_enabled" value="false" /><boolean name="auto_trading" value="false" /><string name="apikey">QA_DUMMY_KEY</string><string name="target_trade_mode">DEMO</string></map>'
seed_prefs "$PREF_XML"
adb shell am start-foreground-service -n "$PKG/.MonitoringService" -a com.openai.fxm1.action.START_MONITORING >/dev/null
sleep 4

# Notification must render all three requested actions.
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

# Exercise PAUSE then PLAY through actual service intents and verify persisted state.
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

# Seed AUTO=true, invoke confirmed Emergency, verify AUTO cannot survive/re-arm from saved permission.
adb shell am force-stop "$PKG"
PREF_XML='<?xml version="1.0" encoding="utf-8" standalone="yes" ?><map><boolean name="auto_user_enabled" value="true" /><boolean name="auto_trading" value="true" /><string name="apikey">QA_DUMMY_KEY</string><string name="target_trade_mode">DEMO</string></map>'
seed_prefs "$PREF_XML"
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

echo 'ANDROID EMULATOR NOTIFICATION/EMERGENCY: PASS'
