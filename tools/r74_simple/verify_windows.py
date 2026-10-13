"""Verify the exact user ZIP on native Windows; never connect to a real MT5."""
from pathlib import Path
import hashlib, json, os, shutil, socket, subprocess, sys, tempfile, zipfile
from check_layout import inspect

ROOT=Path.cwd();ARCHIVE=ROOT/'dist/FXM1_R74_ONE_FOLDER.zip';E=ROOT/'evidence'
checks={};calls=[]
assert sys.platform=='win32'
layout=inspect(ARCHIVE);assert layout['ok'],layout
checks['one_folder_one_start_no_nested_archives']=True


def run(command,cwd,env,success=True):
    p=subprocess.run(command,cwd=cwd,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=90)
    calls.append(dict(command=command,exit=p.returncode,stdout=p.stdout[-5000:],stderr=p.stderr[-4000:]))
    assert (p.returncode==0)==success,(command,p.returncode,p.stdout,p.stderr)
    return p


def start(cmd,args,cwd,env,success=True):
    # Actual CMD entrypoint, not a direct call bypassing START.cmd.
    line='"'+os.environ['COMSPEC']+'" /d /s /c ""'+str(cmd)+'" '+args+'"'
    return run(line,cwd,env,success)


with tempfile.TemporaryDirectory(prefix='R74 simple ') as tmp:
    base=Path(tmp);extract=base/'Новая папка ! & пробелы';extract.mkdir()
    with zipfile.ZipFile(ARCHIVE) as z:z.extractall(extract)
    package=extract/'FXM1_R74_READY';system=package/'system';cmd=package/'START.cmd'
    python=system/'Runtime/python.exe'
    env=dict(os.environ,LOCALAPPDATA=str(base/'Local App Data'),R7_NO_PAUSE='1',
             PYTHONHOME='missing-system-python',PYTHONPATH='missing-global-packages',PATH=str(Path(os.environ['SystemRoot'])/'System32'))
    state=base/'Local App Data/FXM1/R74-Recovery/event_state'
    p=start(cmd,'--check',base,env)
    assert 'ONE FOLDER' in p.stdout and 'AUTO OFF' in p.stdout
    assert '"ok": true' in p.stdout and '"state": "NEW"' in p.stdout
    assert '"old_venv_required": false' in p.stdout and 'INSTALL_R7_3' not in p.stdout
    assert not (base/'Local App Data').exists()
    checks['start_cmd_native_windows']=True
    checks['spaces_cyrillic_bang_ampersand']=True
    checks['isolated_python_without_path_or_old_venv']=True
    checks['check_creates_no_state_or_credentials']=True
    probe=base/'probe.py'
    probe.write_text('import json,sys,ssl,sqlite3,ctypes,multiprocessing,numpy,MetaTrader5,flask,colorama\nfrom pathlib import Path\nroot=Path(sys.argv[1]).resolve()\nassert Path(sys.executable).resolve().is_relative_to(root)\nassert Path(json.__file__).resolve().is_relative_to(root/"Lib")\nfor m in (numpy,MetaTrader5,flask,colorama):assert Path(m.__file__).resolve().is_relative_to(root)\nassert not any(p.endswith(".zip") and Path(p).exists() for p in sys.path)\nprint("UNPACKED_STDLIB_NATIVE_MODULES_OK")\n',encoding='utf-8')
    p=run([str(python),'-I','-B','-X','utf8',str(probe),str(system/'Runtime')],base,env)
    assert 'UNPACKED_STDLIB_NATIVE_MODULES_OK' in p.stdout
    checks['unpacked_stdlib_and_real_native_libraries']=True
    start(cmd,'--port 0',base,env,False)
    checks['invalid_port_rejected']=True
    with socket.socket() as sock:
        sock.bind(('0.0.0.0',0));sock.listen();port=sock.getsockname()[1]
        p=start(cmd,'--port '+str(port),base,env,False)
        assert 'Порт уже занят' in p.stdout and not state.exists()
    checks['occupied_port_stops_before_mt5_or_initialization']=True
    runner=base/'unit_runner.py'
    runner.write_text('''import sys,unittest,gc,importlib.util
from pathlib import Path
system=Path(sys.argv[1]);source=Path(sys.argv[2])
sys.path[:0]=[str(system/'mt5_bridge'),str(source/'tools/r74_restore')]
import test_restore_launcher as t
spec=importlib.util.spec_from_file_location('actual_restore',system/'restore_launcher.py')
actual=importlib.util.module_from_spec(spec);sys.modules[spec.name]=actual;spec.loader.exec_module(actual);t.L=actual
old=t.RestoreTests.tearDown
def cleanup(self):
 gc.collect();old(self)
t.RestoreTests.tearDown=cleanup
r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(t.RestoreTests))
assert r.testsRun==8
sys.exit(0 if r.wasSuccessful() else 1)
''',encoding='utf-8')
    run([str(python),'-I','-B','-X','utf8',str(runner),str(system),str(ROOT)],base,env)
    checks['eight_state_and_account_safety_tests']=True
    state.mkdir(parents=True)
    token=state/'bridge-token.txt';token.write_text('test-partial-identity-must-not-be-replaced',encoding='utf-8');before=token.read_bytes()
    p=start(cmd,'--check',base,env,False)
    assert 'состояние неполное' in p.stdout and token.read_bytes()==before
    assert not (state/'campaign.sqlite3').exists()
    checks['partial_identity_is_not_replaced']=True
    damaged=system/'Runtime/Lib/site-packages/colorama/__init__.py'
    before=damaged.read_bytes();damaged.write_bytes(before+b'\n# corruption-test\n')
    p=start(cmd,'--check',base,env,False)
    assert 'повреждён' in p.stdout
    damaged.write_bytes(before)
    checks['corrupt_dependency_caught_before_launch']=True
    py_temp=python.with_suffix('.saved');python.rename(py_temp)
    p=start(cmd,'--check',base,env,False)
    assert 'Извлечена не вся папка' in p.stdout and 'ModuleNotFoundError' not in p.stdout
    py_temp.rename(python)
    checks['missing_runtime_never_falls_back_to_system_python']=True
    manifest=json.loads((system/'PROGRAM_MANIFEST.json').read_text(encoding='utf-8'))
    for name,h in manifest['files'].items():
        assert hashlib.sha256((system/name).read_bytes()).hexdigest()==h,name
    checks['installed_program_bytes_unchanged_after_tests']=True
assert not any(p.name in ('bridge-token.txt','campaign.sqlite3','recovery-install.json') for p in (ROOT/'dist/FXM1_R74_READY').rglob('*'))
checks['no_test_identity_in_distributed_package']=True
result=dict(ok=True,platform=sys.platform,checks=checks,check_count=len(checks),state_unit_tests=8,
    calls=calls,layout=layout,live_mt5=False,orders_sent=0,
    archive_sha256=hashlib.sha256(ARCHIVE.read_bytes()).hexdigest(),archive_bytes=ARCHIVE.stat().st_size)
(E/'WINDOWS_ONE_FOLDER.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print('WINDOWS_ONE_FOLDER_OK',len(checks))
