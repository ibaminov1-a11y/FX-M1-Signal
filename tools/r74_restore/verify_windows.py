"""Native Windows checks for the actual portable package. No live MT5 connection."""
from pathlib import Path
import hashlib, json, os, shutil, socket, subprocess, sys, tempfile, zipfile
ROOT=Path.cwd();PACKAGE=ROOT/'dist/FXM1_R74_RESTORE';E=ROOT/'evidence'
checks={};calls=[]
def run(args,cwd,env,ok=True):
    p=subprocess.run(args,cwd=cwd,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=90)
    calls.append(dict(command=str(args[0]),arguments=[str(x) for x in args[1:]],exit=p.returncode,stdout=p.stdout[-5000:],stderr=p.stderr[-3000:]))
    assert (p.returncode==0)==ok,(args,p.returncode,p.stdout,p.stderr)
    return p
with tempfile.TemporaryDirectory(prefix='R74 recovery ') as tmp:
    base=Path(tmp);copy=base/'Копия ! папка с пробелами'/PACKAGE.name
    shutil.copytree(PACKAGE,copy)
    env=dict(os.environ,LOCALAPPDATA=str(base/'Local Data'),R7_NO_PAUSE='1',PYTHONHOME='invalid-old-python',PYTHONPATH='invalid-old-packages')
    cmd=copy/'START_BRIDGE_V10_0.bat'
    p=run(['cmd.exe','/d','/c','call',str(cmd),'--check'],base,env)
    assert '"ok": true' in p.stdout and '"state": "NEW"' in p.stdout
    assert '"old_venv_required": false' in p.stdout
    assert not (base/'Local Data').exists()
    checks['offline_portable_imports_without_old_python']=True
    checks['spaces_cyrillic_bang_path']=True
    checks['check_does_not_initialize_state']=True
    run(['cmd.exe','/d','/c','call',str(cmd),'--port','0'],base,env,False)
    checks['invalid_port_rejected']=True
    with socket.socket() as sock:
        sock.bind(('0.0.0.0',0));sock.listen();port=sock.getsockname()[1]
        p=run(['cmd.exe','/d','/c','call',str(cmd),'--port',str(port)],base,env,False)
        assert 'Порт уже занят' in p.stdout
        assert not (base/'Local Data/FXM1/R74-Recovery/event_state').exists()
    checks['existing_listener_blocks_start_before_mt5']=True
    # Run restoration tests using the embedded interpreter and installed real packages.
    script=base/'unit_runner.py'
    script.write_text("import sys, unittest, gc\nfrom pathlib import Path\nroot=Path(sys.argv[1]);source=Path(sys.argv[2])\nsys.path[:0]=[str(root/'mt5_bridge'),str(source/'tools/r74_restore')]\nimport test_restore_launcher as t\nold=t.RestoreTests.tearDown\ndef cleanup(self):\n gc.collect()\n old(self)\nt.RestoreTests.tearDown=cleanup\nr=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(t.RestoreTests))\nassert r.testsRun==8\nsys.exit(0 if r.wasSuccessful() else 1)\n",encoding='utf-8')
    run([str(copy/'Runtime/python.exe'),'-I','-B','-X','utf8',str(script),str(copy),str(ROOT)],base,env)
    checks['eight_restoration_tests_on_embedded_python']=True
    # Confirm partial local state refuses startup and does not replace an identity.
    state=base/'Local Data/FXM1/R74-Recovery/event_state';state.mkdir(parents=True)
    token=state/'bridge-token.txt';token.write_text('temporary-test-identity-that-must-not-be-reset',encoding='utf-8')
    before=token.read_bytes()
    p=run(['cmd.exe','/d','/c','call',str(cmd),'--check'],base,env,False)
    assert 'состояние неполное' in p.stdout and token.read_bytes()==before
    assert not (state/'campaign.sqlite3').exists()
    checks['partial_identity_not_overwritten']=True
# No test state or private keys from the native probes may be packaged.
manifest=json.loads((PACKAGE/'PROGRAM_MANIFEST.json').read_text(encoding='utf-8'))
for name,h in manifest['files'].items():assert hashlib.sha256((PACKAGE/name).read_bytes()).hexdigest()==h,name
assert not any(p.name in ('bridge-token.txt','campaign.sqlite3','runtime.lock') for p in PACKAGE.rglob('*'))
checks['package_bytes_unchanged_after_checks']=True
archive=ROOT/'dist/FXM1_R7_4_RESTORE_FULL.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for p in sorted(PACKAGE.rglob('*')):
        if p.is_file():z.write(p,PACKAGE.name+'/'+p.relative_to(PACKAGE).as_posix())
with zipfile.ZipFile(archive) as z:assert z.testzip() is None
checks['final_zip_crc']=True
report=dict(ok=True,platform=sys.platform,tests=checks,calls=calls,live_mt5=False,authenticated_broker=False,
            old_environment_present=False,archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),archive_bytes=archive.stat().st_size)
(E/'NATIVE_RESTORE_RESULT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('RESTORE_WINDOWS_OK',len(checks),archive.stat().st_size)
