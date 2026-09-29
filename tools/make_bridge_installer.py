"""Build a self-contained program-only Windows installer from packaged Bridge bytes."""
from pathlib import Path
import base64,hashlib,io,sys,zipfile,zlib

def build_installer(bridge,out,build):
    bridge=Path(bridge)
    paths=sorted((bridge/'event_core').rglob('*.py'))+[bridge/'bridge_v10_0.py',bridge/'START_BRIDGE_V10_0.bat']
    files={p.relative_to(bridge).as_posix():p.read_bytes() for p in paths}
    assert 'event_core/__init__.py' in files and 'event_core/scenarios/__init__.py' in files
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,data in files.items():archive.writestr(name,data)
    program='''from pathlib import Path
import base64,hashlib,io,os,shutil,sys,tempfile,zipfile
from datetime import datetime
root=Path.cwd()
if not (root/'bridge_v10_0.py').is_file() or not (root/'event_core/server.py').is_file():
    print('ERROR: put INSTALL_BRIDGE_R56.cmd in your working mt5_bridge folder, next to START_BRIDGE_V10_0.bat.')
    raise SystemExit(2)
archive=zipfile.ZipFile(io.BytesIO(base64.b64decode(PAYLOAD)))
expected=MANIFEST
if set(archive.namelist())!=set(expected) or archive.testzip() is not None:
    raise RuntimeError('Installer package damaged')
for name,digest in expected.items():
    if hashlib.sha256(archive.read(name)).hexdigest()!=digest:raise RuntimeError('Package checksum mismatch')
    if name.endswith('.py'):compile(archive.read(name),name,'exec')
backup=root/('bridge_program_backup_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
backup.mkdir()
core=root/'event_core'
with tempfile.TemporaryDirectory(prefix='bridge_program_staging_',dir=str(root)) as tmp:
    staged=Path(tmp);archive.extractall(staged)
    for name in ('bridge_v10_0.py','START_BRIDGE_V10_0.bat'):
        if (root/name).exists():shutil.copy2(root/name,backup/name)
    os.replace(core,backup/'event_core')
    try:
        os.replace(staged/'event_core',core)
        for name in ('bridge_v10_0.py','START_BRIDGE_V10_0.bat'):os.replace(staged/name,root/name)
    except BaseException:
        if core.exists():shutil.rmtree(core)
        os.replace(backup/'event_core',core)
        for name in ('bridge_v10_0.py','START_BRIDGE_V10_0.bat'):
            if (backup/name).exists():shutil.copy2(backup/name,root/name)
        raise
for name,digest in expected.items():
    if hashlib.sha256((root/name).read_bytes()).hexdigest()!=digest:raise RuntimeError('Installed checksum mismatch: '+name)
sys.path.insert(0,str(root))
from event_core import BUILD
assert BUILD==EXPECTED_BUILD
print('OK:',BUILD,'installed.',len(expected),'program files verified.')
print('Backup:',backup)
print('event_state, broker-clock.json and .venv were preserved.')
print('No trading commands were sent. Run START_BRIDGE_V10_0.bat next.')
'''.replace('PAYLOAD',repr(base64.b64encode(buffer.getvalue()).decode()))
    program=program.replace('MANIFEST',repr({n:hashlib.sha256(data).hexdigest() for n,data in files.items()})).replace('EXPECTED_BUILD',repr(build))
    encoded=base64.b64encode(zlib.compress(program.encode(),9)).decode()
    header='''@echo off
setlocal
cd /d "%~dp0"
set "PY=python"
if exist ".venv\\Scripts\\python.exe" set "PY=.venv\\Scripts\\python.exe"
set "PYTHONUTF8=1"
echo FXM1 R5.6 program update. Close Bridge before continuing.
echo Backup is automatic. Your settings, clock correction and history are preserved.
pause
"%PY%" -c "import sys,pathlib,base64,zlib; text=pathlib.Path(sys.argv[1]).read_text(encoding='ascii'); data=text.split('::FXM1_PAYLOAD_BEGIN::',2)[-1]; exec(compile(zlib.decompress(base64.b64decode(data)), '<FXM1_R56_INSTALL>', 'exec'))" "%~f0"
if errorlevel 1 (
  echo INSTALL FAILED. Send a screenshot of this window.
  pause
  exit /b 1
)
pause
exit /b 0
::FXM1_PAYLOAD_BEGIN::
'''
    cmd=(header+'\n'.join(encoded[i:i+100] for i in range(0,len(encoded),100))+'\n').replace('\n','\r\n').encode('ascii')
    assert max(map(len,cmd.splitlines()))<8191
    Path(out).write_bytes(cmd)

if __name__=='__main__':build_installer(*sys.argv[1:])
