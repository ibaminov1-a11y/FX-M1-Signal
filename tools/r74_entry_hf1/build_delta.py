"""Build only replaced files for the exact 20-Oct R7.4 portable package.
No state files, account policies, keys, runtime binaries or APKs are changed.
"""
import argparse, base64, hashlib, json, re, shutil, zipfile
from pathlib import Path

PRODUCT=('mt5_bridge/event_core/mt5_adapter.py','mt5_bridge/event_core/engine.py',
         'mt5_bridge/event_core/scenarios/stable_plans.py','mt5_bridge/event_core/scenarios/continuation.py')
TESTS=('tests/event_core/test_r55_history_clock.py','tests/event_core/test_r743_entry_hf1.py')
SERVICE=('Runtime/program_recovery.json','START.cmd','PROGRAM_MANIFEST.json')
FILES=PRODUCT+TESTS+SERVICE

def sha(data):return hashlib.sha256(data).hexdigest()
def build(root,source,out,commit='LOCAL_TESTED'):
    root,source,out=map(Path,(root,source,out));out.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((root/'PROGRAM_MANIFEST.json').read_text(encoding='utf-8'))
    assert manifest['bundle']=='R74_COMPLETE_CLOCK_20261020','Wrong source bundle'
    before={n:(root/n).read_bytes() for n in manifest['files']}
    assert all(sha(v)==manifest['files'][n] for n,v in before.items()),'Input package identity failed'
    reserve=json.loads(before['Runtime/program_recovery.json'])
    replacements={n:(source/n).read_bytes() for n in PRODUCT+TESTS}
    for n in PRODUCT:
        assert n in reserve['files']
        value=replacements[n]
        reserve['files'][n]={'size':len(value),'data':base64.b64encode(value).decode('ascii')}
    reserve_bytes=json.dumps(reserve,separators=(',',':'),ensure_ascii=False).encode('utf-8')
    replacements['Runtime/program_recovery.json']=reserve_bytes
    original_start=before['START.cmd'].decode('utf-8').replace('\r\n','\n')
    old_reserve_hash=sha(before['Runtime/program_recovery.json'])
    anchor="PROGRAM_RESERVE_SHA256 = '"+old_reserve_hash+"'"
    assert original_start.count(anchor)==1
    start=original_start.replace(anchor,"PROGRAM_RESERVE_SHA256 = '"+sha(reserve_bytes)+"'")
    banner='echo FX-M1-Signal / COMPLETE 20.10 / BRIDGE R7.4 + APK R7.4.2'
    assert start.count(banner)==1
    start=start.replace(banner,banner+' / ENTRY-HF1')
    marker='\n#R74_PY_BEGIN\n'
    old_py_hash=sha(original_start.split(marker,1)[1].encode('utf-8'))
    new_py_hash=sha(start.split(marker,1)[1].encode('utf-8'))
    check="if ($actual -ne '"+old_py_hash+"') { throw 'EMBEDDED_LAUNCHER_HASH_MISMATCH' }"
    assert start.count(check)==1,'Original embedded launcher verification mismatch'
    start=start.replace(check,check.replace(old_py_hash,new_py_hash))
    replacements['START.cmd']=start.replace('\n','\r\n').encode('utf-8')
    for n,value in replacements.items():manifest['files'][n]=sha(value)
    manifest.update(bundle='R74_ENTRY_HF1_20261020',entry_patch='ENTRY-HF1',patch_source=commit,
        embedded_launcher_sha256=new_py_hash,trading_changed=True,risk_rules_changed=False,
        forecast_model_changed=False,account_policy_changed=False)
    replacements['PROGRAM_MANIFEST.json']=json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf-8')
    for n,v in replacements.items():p=root/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(v)
    assert all(sha((root/n).read_bytes())==h for n,h in manifest['files'].items())
    expected_set={n for n in manifest['files'] if n.endswith('.py') and (n.startswith('mt5_bridge/') or n.startswith('Runtime/Lib/site-packages/'))}
    assert set(reserve['files'])==expected_set
    for n,record in reserve['files'].items():
        data=base64.b64decode(record['data'],validate=True)
        assert len(data)==record['size'] and sha(data)==manifest['files'][n],n
    changed=sorted(n for n,v in before.items() if (root/n).read_bytes()!=v)
    assert set(changed)==set(FILES)-{'tests/event_core/test_r743_entry_hf1.py','PROGRAM_MANIFEST.json'}
    for n in ('FXM1_R7_4_2_FORECAST.apk','Runtime/python.exe'):
        assert (root/n).read_bytes()==before[n]
    target=out/'FXM1_R74_ENTRY_HF1_PATCH.zip'
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,9) as z:
        for n in FILES:
            info=zipfile.ZipInfo(n,(2026,10,20,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o644<<16
            z.writestr(info,replacements[n])
    with zipfile.ZipFile(target) as z:assert z.testzip() is None and sorted(z.namelist())==sorted(FILES)
    identity=dict(patch='ENTRY-HF1',base_bundle='R74_COMPLETE_CLOCK_20261020',source=commit,
        files={n:sha(v) for n,v in replacements.items()},zip_sha256=sha(target.read_bytes()),bytes=target.stat().st_size,
        apk_sha256=sha(before['FXM1_R7_4_2_FORECAST.apk']),changed_program=list(PRODUCT),state_included=False,
        account_policy_changed=False,embedded_launcher_sha256=new_py_hash)
    (out/'PATCH_IDENTITY.json').write_text(json.dumps(identity,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in identity.items() if k!='files'},indent=2))
    return target

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--source',required=True);p.add_argument('--out',required=True);p.add_argument('--commit',default='LOCAL_TESTED');a=p.parse_args()
    build(a.root,a.source,a.out,a.commit)
