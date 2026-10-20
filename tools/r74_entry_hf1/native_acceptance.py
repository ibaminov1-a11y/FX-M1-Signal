"""Native Windows delivery verification. Never connect to a real MT5 terminal."""
import hashlib, json, os, shutil, sqlite3, subprocess, sys, tempfile, zipfile
from pathlib import Path
from build_delta import FILES, PRODUCT

def digest(data):return hashlib.sha256(data).hexdigest()
def cmd(path,env,log):
    command='"'+os.environ['COMSPEC']+'" /d /s /c ""'+str(path)+'" --check"'
    r=subprocess.run(command,env=env,cwd=path.parent,capture_output=True,timeout=90)
    text=(r.stdout+r.stderr).decode('utf-8','replace');log.write_text(text,encoding='utf-8')
    assert r.returncode==0 and 'PACKAGE CHECK OK' in text and 'ENTRY-HF1' in text,text
    return text

def main(original,delta,out):
    original,delta,out=map(Path,(original,delta,out));out=out.resolve();out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='FXM1 обновление ') as temp:
        temp=Path(temp);dest=temp/'Project (проверка)'
        zipfile.ZipFile(original).extractall(dest);root=dest/'FX-M1-Signal'
        old_manifest=json.loads((root/'PROGRAM_MANIFEST.json').read_text(encoding='utf-8'))
        before={n:(root/n).read_bytes() for n in old_manifest['files']}
        local=temp/'AppData';state=local/'FXM1/R74-Recovery/event_state';state.mkdir(parents=True)
        with sqlite3.connect(state/'campaign.sqlite3') as c:
            for table in ('state','intents','commands','campaigns'):c.execute('CREATE TABLE '+table+'(key text,value text)')
            c.execute("INSERT INTO state VALUES('sentinel','do not change')")
        (state/'bridge-token.txt').write_text('fake-local-token-preservation-01234567890123456789',encoding='utf-8')
        (state/'broker-clock.json').write_text('{"account":"123@DEMO","offset_minutes":180,"confirmed":true}',encoding='utf-8')
        state_before={p.name:p.read_bytes() for p in state.iterdir()}
        env={k:v for k,v in os.environ.items() if k not in ('PYTHONHOME','PYTHONPATH')}
        env.update(LOCALAPPDATA=str(local),R7_NO_PAUSE='1')
        with zipfile.ZipFile(delta) as z:
            assert set(z.namelist())==set(FILES) and z.testzip() is None
            z.extractall(root)
        changed={n for n,v in before.items() if (root/n).read_bytes()!=v}
        assert changed==set(FILES)-{'PROGRAM_MANIFEST.json','tests/event_core/test_r743_entry_hf1.py'}
        assert (root/'FXM1_R7_4_2_FORECAST.apk').read_bytes()==before['FXM1_R7_4_2_FORECAST.apk']
        cmd(root/'START.cmd',env,out/'START_AFTER_OVERLAY.log')
        report=json.loads((root/'PACKAGE_CHECK.json').read_text(encoding='utf-8'))
        assert report['ok'] and report['restored_files']==0,report
        # Test actual patched files using the exact distributed Windows runtime.
        driver='import sys,runpy;sys.path[:0]='+repr([str(root/'mt5_bridge'),str(root/'tests/event_core')])+';runpy.run_path('+repr(str(root/'tests/event_core/test_r743_entry_hf1.py'))+',run_name="__main__")'
        r=subprocess.run([str(root/'Runtime/python.exe'),'-I','-B','-X','utf8','-c',driver],env=env,cwd=root,capture_output=True,timeout=60)
        text=(r.stdout+r.stderr).decode('utf-8','replace');(out/'BUNDLED_ENTRY_TESTS.log').write_text(text,encoding='utf-8')
        assert r.returncode==0 and 'Ran 8 tests' in text,text
        # Recovery must restore NEW modules rather than silently roll the fix back.
        expected={n:digest((root/n).read_bytes()) for n in PRODUCT}
        (root/PRODUCT[1]).write_bytes(b'# damaged fixture\n')
        (root/PRODUCT[3]).unlink()
        cmd(root/'START.cmd',env,out/'RECOVERY_AFTER_CORRUPTION.log')
        report=json.loads((root/'PACKAGE_CHECK.json').read_text(encoding='utf-8'))
        assert report['ok'] and report['restored_files']==2,report
        assert all(digest((root/n).read_bytes())==h for n,h in expected.items())
        moved=temp/'Moved (другая папка)'/'FX-M1-Signal';moved.parent.mkdir()
        shutil.move(str(root),str(moved));root=moved
        cmd(root/'START.cmd',env,out/'REPEATED_MOVED_START.log')
        assert state_before=={p.name:p.read_bytes() for p in state.iterdir()},'Personal state modified'
        manifest=json.loads((root/'PROGRAM_MANIFEST.json').read_text(encoding='utf-8'))
        assert manifest['entry_patch']=='ENTRY-HF1'
        assert all(digest((root/n).read_bytes())==h for n,h in manifest['files'].items())
        (out/'WINDOWS_RESULT.json').write_text(json.dumps(dict(delta_sha256=digest(delta.read_bytes()),tests=8,
            actual_cmd=True,packaged_python=True,delta_overlay=True,package_check_passed=True,
            new_code_survives_repair=True,moved_folder_start=True,existing_state_key_clock_preserved=True,
            changed_modules=expected,apk_unchanged=True,real_mt5_connected=False,real_broker_orders_sent=0),indent=2),encoding='utf-8')

if __name__=='__main__':main(*sys.argv[1:])
