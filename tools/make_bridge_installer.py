"""Build a self-contained program-only Windows installer from packaged Bridge bytes."""
from pathlib import Path
import ast,base64,hashlib,io,re,sys,zipfile,zlib

def build_installer(bridge,out,build):
    bridge=Path(bridge)
    match=re.fullmatch(r'10\.9-EC1-(R\d+\.\d+)',build)
    if match is None:raise ValueError('Invalid release build: '+build)
    declared={}
    for node in ast.parse((bridge/'event_core/__init__.py').read_text(encoding='utf-8')).body:
        if isinstance(node,ast.Assign):
            for target in node.targets:
                if isinstance(target,ast.Name) and target.id in ('VERSION','BUILD','PROTOCOL','REVISION'):
                    declared[target.id]=ast.literal_eval(node.value)
    if declared.get('BUILD')!=build:raise ValueError('Bridge build does not match requested build')
    for name,value in (('VERSION','10.9-EC1'),('PROTOCOL','fxm1.event.v1')):
        if declared.get(name)!=value:raise ValueError('Bridge '+name+' compatibility contract is missing or invalid')
    if not isinstance(declared.get('REVISION'),str) or not declared['REVISION'].strip():
        raise ValueError('Bridge REVISION is missing')
    release=match.group(1)
    installer_name=Path(out).name
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',installer_name):raise ValueError('Invalid installer filename')
    paths=sorted((bridge/'event_core').rglob('*.py'))+[bridge/'bridge_v10_0.py',bridge/'START_BRIDGE_V10_0.bat']
    files={p.relative_to(bridge).as_posix():p.read_bytes() for p in paths}
    assert 'event_core/__init__.py' in files and 'event_core/scenarios/__init__.py' in files
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,data in files.items():archive.writestr(name,data)
    program='''from pathlib import Path
import base64,hashlib,io,os,shutil,subprocess,sys,tempfile,zipfile
from datetime import datetime
root=Path.cwd()
if not (root/'bridge_v10_0.py').is_file() or not (root/'event_core/server.py').is_file():
    print('ERROR: put INSTALLER_FILENAME in your working mt5_bridge folder, next to START_BRIDGE_V10_0.bat.')
    raise SystemExit(2)
archive=zipfile.ZipFile(io.BytesIO(base64.b64decode(PAYLOAD)))
expected=MANIFEST
if set(archive.namelist())!=set(expected) or archive.testzip() is not None:
    raise RuntimeError('Installer package damaged')
for name,digest in expected.items():
    if hashlib.sha256(archive.read(name)).hexdigest()!=digest:raise RuntimeError('Package checksum mismatch')
    if name.endswith('.py'):compile(archive.read(name),name,'exec')
def verify_imports(folder):
    probe="import sys; sys.path.insert(0,sys.argv[1]); from event_core import VERSION,BUILD,PROTOCOL,REVISION; assert (VERSION,BUILD,PROTOCOL)==('10.9-EC1',sys.argv[2],'fxm1.event.v1'); assert REVISION; from event_core.server import main; assert callable(main); import bridge_v10_0; assert bridge_v10_0.main is main"
    subprocess.run([sys.executable,'-B','-c',probe,str(folder),EXPECTED_BUILD],cwd=folder,check=True)
core=root/'event_core'
with tempfile.TemporaryDirectory(prefix='bridge_program_staging_',dir=str(root)) as tmp:
    staged=Path(tmp);archive.extractall(staged)
    verify_imports(staged)
    backup=root/('bridge_program_backup_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    backup.mkdir()
    for name in ('bridge_v10_0.py','START_BRIDGE_V10_0.bat'):
        if (root/name).exists():shutil.copy2(root/name,backup/name)
    os.replace(core,backup/'event_core')
    try:
        os.replace(staged/'event_core',core)
        for name in ('bridge_v10_0.py','START_BRIDGE_V10_0.bat'):os.replace(staged/name,root/name)
        for name,digest in expected.items():
            if hashlib.sha256((root/name).read_bytes()).hexdigest()!=digest:raise RuntimeError('Installed checksum mismatch: '+name)
        verify_imports(root)
    except BaseException:
        if core.exists():shutil.rmtree(core)
        os.replace(backup/'event_core',core)
        for name in ('bridge_v10_0.py','START_BRIDGE_V10_0.bat'):
            if (backup/name).exists():shutil.copy2(backup/name,root/name)
        raise
print('OK:',EXPECTED_BUILD,'installed.',len(expected),'program files verified.')
print('SERVER_IMPORT_OK: server and launcher loaded successfully.')
print('Backup:',backup)
print('event_state, broker-clock.json and .venv were preserved.')
print('No trading commands were sent. Run START_BRIDGE_V10_0.bat next.')
'''.replace('PAYLOAD',repr(base64.b64encode(buffer.getvalue()).decode()))
    program=program.replace('MANIFEST',repr({n:hashlib.sha256(data).hexdigest() for n,data in files.items()})).replace('EXPECTED_BUILD',repr(build))
    program=program.replace('INSTALLER_FILENAME',installer_name)
    encoded=base64.b64encode(zlib.compress(program.encode(),9)).decode()
    header='''@echo off
setlocal
cd /d "%~dp0"
set "PY=python"
if exist ".venv\\Scripts\\python.exe" set "PY=.venv\\Scripts\\python.exe"
set "PYTHONUTF8=1"
echo FXM1 RELEASE_NAME program update. Close Bridge before continuing.
echo Backup is automatic. Your settings, clock correction and history are preserved.
pause
"%PY%" -c "import sys,pathlib,base64,zlib; text=pathlib.Path(sys.argv[1]).read_text(encoding='ascii'); data=text.split('::FXM1_PAYLOAD_BEGIN::',2)[-1]; exec(compile(zlib.decompress(base64.b64decode(data)), '<FXM1_RELEASE_TAG_INSTALL>', 'exec'))" "%~f0"
if errorlevel 1 (
  echo INSTALL FAILED. Send a screenshot of this window.
  pause
  exit /b 1
)
pause
exit /b 0
::FXM1_PAYLOAD_BEGIN::
'''
    header=header.replace('RELEASE_NAME',release).replace('RELEASE_TAG',release.replace('.',''))
    cmd=(header+'\n'.join(encoded[i:i+100] for i in range(0,len(encoded),100))+'\n').replace('\n','\r\n').encode('ascii')
    assert max(map(len,cmd.splitlines()))<8191
    Path(out).write_bytes(cmd)

if __name__=='__main__':build_installer(*sys.argv[1:])
