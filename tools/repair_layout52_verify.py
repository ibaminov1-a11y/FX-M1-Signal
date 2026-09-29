"""Fail closed on incomplete instrumentation, then verify source/APK/Bridge identity."""
from pathlib import Path
import hashlib,json,re,subprocess,sys,xml.etree.ElementTree as ET,zipfile
root=Path(__file__).resolve().parents[1];e=root/'evidence'
classes='EventCoreUiTest CampaignSignalUiTest ScenarioMapUiTest ScenarioUpgradeUiTest R5SettingsHistoryTest R5RedContractUiTest R51RepairUiTest LiveLayoutUiTest'.split()
expected={}
for c in classes:
    text=(root/f'app/src/androidTest/java/com/openai/fxm1/{c}.java').read_text()
    expected[c]=set(re.findall(r'@Test(?:\([^)]*\))?\s+public\s+void\s+(\w+)',text))
seen={c:set() for c in classes};problems=[]
for p in (root/'app/build/outputs/androidTest-results/connected').rglob('TEST-*.xml'):
    tree=ET.parse(p).getroot()
    for t in tree.iter('testcase'):
        c=t.get('classname','').rsplit('.',1)[-1]
        if c not in seen:continue
        name=t.get('name','').split('[')[0]
        assert name not in seen[c],('duplicate',c,name)
        seen[c].add(name)
        if any(t.find(x) is not None for x in ('error','failure','skipped')):problems.append((c,name))
assert not problems,problems
assert seen==expected,{'missing':{c:sorted(expected[c]-seen[c]) for c in classes},'extra':{c:sorted(seen[c]-expected[c]) for c in classes}}
count=sum(map(len,seen.values()));assert count==45,count
summary={'tests':count,'failures':0,'errors':0,'skipped':0,'api':35,'broker':'synthetic fixture','cases':{c:sorted(v) for c,v in seen.items()}}
(e/'ANDROID_TESTS.json').write_text(json.dumps(summary,indent=2))
print('COMPLETE_ANDROID_SUITE_VERIFIED',count)
if '--package' not in sys.argv:raise SystemExit
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
meta=json.loads((e/'package/PROVENANCE.json').read_text());assert meta['commit']==head
apk=e/'package/FXM1_10_9_EVENT_CORE_DEMO.apk'
assert hashlib.sha256(apk.read_bytes()).hexdigest()==meta['apk_sha256']
assert meta['revision']=='R5.2-stable-live-ui-native-utc'
assert 'versionCode 920' in (root/'app/build.gradle').read_text()
with zipfile.ZipFile(e/'FXM1_EVENT_CORE_SOURCE.zip') as z:
    for f in (e/'package/Bridge/event_core').rglob('*.py'):
        source='mt5_bridge/event_core/'+str(f.relative_to(e/'package/Bridge/event_core'))
        assert z.read(source)==f.read_bytes(),source
    for name,hashes in json.loads((root/'tools/repair_layout52_manifest.json').read_text()).items():
        assert hashlib.sha256(z.read(name)).hexdigest()==hashes['after'],name
for bundle in ('FXM1_R5_2_FULL.zip','FXM1_R5_2_BRIDGE.zip'):
    with zipfile.ZipFile(e/bundle) as z:
        assert z.testzip() is None
        for n in z.namelist():assert not n.endswith(('.jks','.keystore','.db','.sqlite','.sqlite3')),n
(e/'package-check.txt').write_text('EXACT_SOURCE_APK_AND_BRIDGE_VERIFIED '+head+'\nAPK_SHA256 '+meta['apk_sha256']+'\nANDROID_COMPLETE 45/45; no skips\n')
(e/'R52_CHECKLIST.md').write_text('# R5.2 verification\n\nSource commit: '+head+'\n\n45 Android instrumentation tests passed on API35 with the Python broker fixture. See ANDROID_TESTS.json for every executed case. Python results are in python-tests.log. Layout geometry, bottom scroll, frozen full text, actual cache-to-UI updates, old Activity callbacks, watchlist, lot selection, map/history and journal controls are covered by these tests.\n\nPhysical phone, real MT5 order execution and profitability are NOT established by these tests. REAL sending remains disabled in the adapter.\n')
print((e/'package-check.txt').read_text())
