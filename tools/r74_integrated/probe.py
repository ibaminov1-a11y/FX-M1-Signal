"""Read-only-to-MT5 native distribution probe; no broker call is requested."""
from pathlib import Path
import argparse, hashlib, json, os, shutil, subprocess, tempfile, zipfile

def extract(archive, destination):
    script = "$ErrorActionPreference='Stop'; Expand-Archive -LiteralPath $env:R74_ZIP -DestinationPath $env:R74_DEST"
    env=dict(os.environ,R74_ZIP=str(Path(archive).resolve()),R74_DEST=str(destination))
    subprocess.run(['powershell.exe','-NoLogo','-NoProfile','-NonInteractive','-Command',script],env=env,check=True,timeout=90)
    return destination/'FX-M1-Signal'

def call(root, args='--check', cwd=None):
    env=dict(os.environ,LOCALAPPDATA=str(root.parent/'isolated-state'),R7_NO_PAUSE='1',PYTHONPATH='not-the-bundled-runtime',PYTHONHOME='not-the-bundled-runtime')
    # No system Python or py launcher can be selected through PATH.
    env['PATH']=os.path.join(os.environ['SystemRoot'],'System32')
    cmd='"'+str(root/'START.cmd')+'" '+args
    run=subprocess.run(['cmd.exe','/d','/c',cmd],cwd=cwd or root.parent,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=100)
    return dict(exit=run.returncode,stdout=run.stdout.decode('utf-8',errors='replace'),stderr=run.stderr.decode('utf-8',errors='replace'))

def main():
    p=argparse.ArgumentParser();p.add_argument('archive');p.add_argument('--red',action='store_true');p.add_argument('--out',default='evidence');a=p.parse_args()
    out=Path(a.out);out.mkdir(exist_ok=True,parents=True)
    report=dict(red=a.red,checks={},calls=[],broker_calls=0)
    def check(name, condition):
        report['checks'][name]=bool(condition)
        if not condition:raise AssertionError(name)
    with tempfile.TemporaryDirectory(prefix='R74 integrated ') as td:
        work=Path(td);root=extract(a.archive,work/'извлечено с пробелами')
        before=call(root);report['calls'].append(before)
        check('baseline_native_check',before['exit']==0 and '"ok": true' in before['stdout'])
        launcher=root/'restore_launcher.py'
        if a.red:
            check('old_launcher_was_present',launcher.is_file())
            launcher.unlink()
            after=call(root);report['calls'].append(after)
            check('reported_missing_bootstrap_reproduced',after['exit']!=0 and 'restore_launcher.py' in after['stdout'])
        else:
            check('no_external_launcher_needed',not launcher.exists())
            # A stray prior launcher is not executed or modified.
            sentinel=b"raise RuntimeError('DO_NOT_EXECUTE_STRAY_ROOT_SCRIPT')\n"
            launcher.write_bytes(sentinel)
            after=call(root);report['calls'].append(after)
            check('stray_prior_launcher_ignored',after['exit']==0 and '"ok": true' in after['stdout'] and launcher.read_bytes()==sentinel)
            launcher.unlink()
            (root/'Runtime/Lib/abc.pyc').unlink()
            (root/'mt5_bridge/event_core/__init__.py').unlink()
            restored=call(root);report['calls'].append(restored)
            check('prior_source_and_stdlib_repairs_retained',restored['exit']==0 and (root/'Runtime/Lib/abc.pyc').is_file() and (root/'mt5_bridge/event_core/__init__.py').is_file())
            moved=root.parent/'перемещённая папка & путь'
            root.rename(moved);root=moved
            again=call(root);report['calls'].append(again)
            check('move_and_special_path_without_install',again['exit']==0)
            native=root/'Runtime/python.exe';native.rename(root/'Runtime/python.saved')
            missing=call(root);report['calls'].append(missing)
            check('missing_native_reports_exact_path',missing['exit']!=0 and 'MISSING_NATIVE' in missing['stdout'] and 'Runtime' in missing['stdout'] and 'python.exe' in missing['stdout'])
            (root/'Runtime/python.saved').rename(native)
            # A corrupt native binary is never launched or silently replaced.
            payload=native.read_bytes();native.write_bytes(b'NOT_AN_EXECUTABLE')
            corrupt=call(root);report['calls'].append(corrupt)
            check('corrupt_native_refused_not_repaired',corrupt['exit']!=0 and 'NATIVE_HASH_MISMATCH' in corrupt['stdout'] and native.read_bytes()==b'NOT_AN_EXECUTABLE')
            native.write_bytes(payload)
            state=root.parent/'isolated-state'/'FXM1'/'R74-Recovery'/'event_state'
            check('check_did_not_create_personal_state',not state.exists())
            state.mkdir(parents=True);(state/'bridge-token.txt').write_text('do-not-replace-incomplete-state')
            refused=call(root);report['calls'].append(refused)
            check('incomplete_state_preserved',refused['exit']!=0 and (state/'bridge-token.txt').read_text()=='do-not-replace-incomplete-state' and not (state/'campaign.sqlite3').exists())
            manifest=json.loads((root/'PROGRAM_MANIFEST.json').read_text('utf-8'))['files']
            check('all_package_hashes_still_exact',all(hashlib.sha256((root/n).read_bytes()).hexdigest()==h for n,h in manifest.items()))
        report['ok']=all(report['checks'].values())
        (out/('RED.json' if a.red else 'WINDOWS.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
        print(json.dumps(dict(ok=report['ok'],red=a.red,checks=len(report['checks'])),ensure_ascii=False))

if __name__=='__main__':main()
