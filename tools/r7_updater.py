"""R7.3 updater: guarded program/dependency installation. No trading commands."""
from __future__ import annotations
import argparse,hashlib,json,os,shutil,sqlite3,subprocess,sys,tempfile,time
from pathlib import Path
from contextlib import closing

ALLOWED={'event_core','bridge_v10_0.py','bridge_startup.py','START_BRIDGE_V10_0.bat','requirements_event.txt',
         'CHECK_BROKER_CLOCK.py','CHECK_BROKER_CLOCK.cmd','export_ticks.py','research_config.json','BUILD.json'}
INCOMPLETE='R7.3 installation is incomplete. Run INSTALL_R7_3.cmd again for this folder.\n'

class Lock:
 def __init__(self,path):
  path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
  self.f=path.open('a+b')
  try:
   if os.name=='nt':
    import msvcrt
    self.f.seek(0,2)
    if self.f.tell()==0:self.f.write(b'0');self.f.flush()
    self.f.seek(0);msvcrt.locking(self.f.fileno(),msvcrt.LK_NBLCK,1)
   else:
    import fcntl
    fcntl.flock(self.f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
  except OSError as e:
   self.f.close();raise RuntimeError('Bridge is running. Close Bridge before updating.') from e
 def close(self):self.f.close()

def _flat(root):
 for path in (root/'event_state/campaign.sqlite3',root/'campaign.sqlite3'):
  if not path.exists():continue
  with tempfile.TemporaryDirectory(prefix='r72_db_probe_') as folder:
   dst=Path(folder)/'campaign.sqlite3'
   for suffix in ('','-wal','-shm'):
    src=Path(str(path)+suffix)
    if src.exists():shutil.copy2(src,str(dst)+suffix)
   with closing(sqlite3.connect(str(dst))) as db:
    if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise RuntimeError('Database integrity failed. Keep original state.')
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'intents' in tables and db.execute("SELECT 1 FROM intents WHERE status IN ('SENDING','UNKNOWN') LIMIT 1").fetchone():
     raise RuntimeError('Unresolved order: reconcile campaign in Bridge before updating.')
    if 'state' in tables:
     for key,text in db.execute('SELECT k,value FROM state'):
      if key=='engine' or key.endswith(':engine'):
       state=json.loads(text)
       if state.get('campaign') or state.get('exit_pending'):
        raise RuntimeError('Active campaign: wait for confirmed closure before updating.')

def _safe_manifest(source,manifest):
 if not isinstance(manifest,dict) or not manifest:raise RuntimeError('Missing package manifest')
 for name,digest in manifest.items():
  p=Path(name)
  if p.is_absolute() or '..' in p.parts or not p.parts or p.parts[0] not in ALLOWED:raise RuntimeError('Unsafe payload path')
  src=source/p
  if src.is_symlink() or not src.is_file() or hashlib.sha256(src.read_bytes()).hexdigest()!=digest:raise RuntimeError('Package checksum mismatch: '+name)
  if src.suffix=='.py':compile(src.read_bytes(),name,'exec')
 actual={p.relative_to(source).as_posix() for top in {Path(n).parts[0] for n in manifest}
         for p in ([source/top] if (source/top).is_file() else (source/top).rglob('*')) if p.is_file()}
 if actual!=set(manifest):raise RuntimeError('Program payload contains files outside its manifest')
 for required in ('event_core/__init__.py','event_core/server.py','bridge_v10_0.py','START_BRIDGE_V10_0.bat'):
  if required not in manifest:raise RuntimeError('Incomplete Bridge payload')

def _safe_dependencies(source,manifest):
 if not isinstance(manifest,dict) or not manifest:raise RuntimeError('Missing dependency manifest')
 for name,digest in manifest.items():
  p=Path(name)
  if p.is_absolute() or '..' in p.parts or not p.parts:raise RuntimeError('Unsafe dependency path')
  top=p.parts[0].lower()
  if top!='colorama' and not (top.startswith('colorama-') and top.endswith('.dist-info')):
   raise RuntimeError('Unexpected dependency payload: '+name)
  src=source/p
  if src.is_symlink() or not src.is_file() or hashlib.sha256(src.read_bytes()).hexdigest()!=digest:
   raise RuntimeError('Dependency checksum mismatch: '+name)
 actual={p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file()}
 if actual!=set(manifest):raise RuntimeError('Dependency payload contains files outside its manifest')
 init=source/'colorama/__init__.py'
 if not init.is_file() or 'AnsiToWin32' not in init.read_text(encoding='utf-8'):
  raise RuntimeError('Colorama payload is incomplete')

def _remove(path):
 path=Path(path)
 if not path.exists():return
 last=None
 for _ in range(12):
  try:
   if path.is_dir():shutil.rmtree(path)
   else:path.unlink()
   return
  except OSError as e:
   last=e;time.sleep(.25)
 raise last

def _copy_item(src,dst):
 src=Path(src);dst=Path(dst)
 if src.is_dir():
  dst.parent.mkdir(parents=True,exist_ok=True)
  shutil.copytree(src,dst,dirs_exist_ok=True)
 else:
  dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)

def _restore_items(backup,target,tops,old):
 for top in tops:
  _remove(target/top)
  if top in old and (backup/top).exists():_copy_item(backup/top,target/top)

def _validate_target(source,target):
 if source==target or target in source.parents or source in target.parents:
  raise RuntimeError('Package and working Bridge folders must be separate')
 target.mkdir(parents=True,exist_ok=True)
 marker=target/'INSTALL_INCOMPLETE.txt'
 resumable=marker.is_file() and marker.read_text(encoding='utf-8')==INCOMPLETE
 if any(target.iterdir()) and not (target/'bridge_v10_0.py').is_file() and not resumable:
  raise RuntimeError('Select the working Bridge folder, not an unrelated directory.')
 for name in ALLOWED:
  if (target/name).is_symlink():raise RuntimeError('Symbolic links in program paths are not supported')

def _copy_program(source,target,manifest):
 tops=sorted({Path(n).parts[0] for n in manifest})
 backup=target/('r73_program_backup_'+str(time.time_ns()));backup.mkdir()
 old=[]
 for top in tops:
  if (target/top).exists():_copy_item(target/top,backup/top);old.append(top)
 try:
  for top in tops:
   _remove(target/top)
   _copy_item(source/top,target/top)
  _safe_manifest(target,manifest)
  (backup/'ROLLBACK.json').write_text(json.dumps(dict(tops=tops,old=old,installed=manifest),indent=2),encoding='utf-8')
 except BaseException:
  _restore_items(backup,target,tops,old)
  raise
 return backup

def apply_update(source,target,manifest):
 source=Path(source).resolve();target=Path(target).resolve()
 _safe_manifest(source,manifest)
 _validate_target(source,target)
 lock=Lock(target/'event_state/runtime.lock')
 try:
  _flat(target)
  return _copy_program(source,target,manifest)
 finally:lock.close()

def rollback(target,backup=None):
 target=Path(target).resolve()
 choices=sorted(list(target.glob('r72_program_backup_*/ROLLBACK.json'))+list(target.glob('r73_program_backup_*/ROLLBACK.json')),key=lambda p:p.stat().st_mtime_ns)
 if backup is None:
  if not choices:raise RuntimeError('No program backup found')
  backup=choices[-1].parent
 backup=Path(backup).resolve()
 if backup.parent!=target:raise RuntimeError('Backup is outside this Bridge folder')
 record=json.loads((backup/'ROLLBACK.json').read_text(encoding='utf-8'))
 lock=Lock(target/'event_state/runtime.lock')
 try:
  _flat(target)
  saved=target/('r73_rollback_current_'+str(time.time_ns()));saved.mkdir()
  for top in record['tops']:
   if top not in ALLOWED:raise RuntimeError('Invalid backup metadata')
   if (target/top).exists():_copy_item(target/top,saved/top)
  _restore_items(backup,target,record['tops'],set(record['old']))
  (backup/'ROLLBACK.json').rename(backup/'ROLLED_BACK.json')
  return saved
 finally:lock.close()

def repair_colorama(package,target):
 package=Path(package).resolve();target=Path(target).resolve()
 manifest_path=package/'DEPENDENCY_MANIFEST.json'
 source=package/'Dependencies'
 if not manifest_path.is_file() or not source.is_dir():raise RuntimeError('R7.3 dependency payload is missing')
 manifest=json.loads(manifest_path.read_text(encoding='utf-8'));_safe_dependencies(source,manifest)
 python=target/'.venv/Scripts/python.exe'
 site=target/'.venv/Lib/site-packages'
 if not python.is_file() or not site.is_dir():
  print('Existing .venv not found; dependency repair skipped. Install requirements_event.txt before first start.')
  return None
 tops=sorted({Path(n).parts[0] for n in manifest})
 backup=target/('r73_dependency_backup_'+str(time.time_ns()));backup.mkdir()
 old=[]
 for top in tops:
  if (site/top).exists():_copy_item(site/top,backup/top);old.append(top)
 try:
  for top in tops:
   _remove(site/top);_copy_item(source/top,site/top)
  code='''import contextlib,io
try:
 with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
  import colorama
  assert hasattr(colorama,'AnsiToWin32')
except Exception as exc:
 print('COLORAMA ERROR '+type(exc).__name__)
 raise SystemExit(1)
print('COLORAMA OK')
'''
  result=subprocess.run([str(python),'-I','-X','utf8','-c',code],cwd=target,text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30)
  if result.returncode!=0 or 'COLORAMA OK' not in result.stdout:
   cause=next((line[len('COLORAMA ERROR '):] for line in result.stdout.splitlines() if line.startswith('COLORAMA ERROR ')),'')
   if not cause.isascii() or not cause.isidentifier():cause='process exit '+str(result.returncode)
   raise RuntimeError('Colorama verification failed ('+cause+'). Prior dependency files restored; keep .venv and check Python environment.')
  print('COLORAMA OK')
 except BaseException:
  for top in tops:_remove(site/top)
  for top in old:
   if (backup/top).exists():_copy_item(backup/top,site/top)
  raise
 return backup

def prepare_environment(target):
 target=Path(target).resolve();python=target/'.venv/Scripts/python.exe'
 if (target/'.venv').exists():
  if not python.is_file():
   raise RuntimeError('Existing .venv is incomplete. It was preserved. Use a separate fresh working folder; do not delete the original environment or trading state.')
 else:
  check_python(sys.executable,target)
  print('Creating a local 64-bit Python environment...',flush=True)
  try:
   result=subprocess.run([sys.executable,'-X','utf8','-m','venv',str(target/'.venv')],cwd=target,text=True,encoding='utf-8',errors='replace',
                         stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120)
  except (OSError,subprocess.TimeoutExpired) as exc:
   raise RuntimeError('Could not create Python environment ('+type(exc).__name__+'). Check Python venv support and folder permissions.') from None
  if result.returncode!=0 or not python.is_file():raise RuntimeError('Could not create Python environment. Check Python venv support and folder permissions.')
 check_python(python,target)
 return python

def _dependency_report(python,target):
 code='''import contextlib,importlib,io,json
report={}
for name,field in [('flask','Flask'),('MetaTrader5','initialize'),('colorama','AnsiToWin32')]:
 try:
  with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
   module=importlib.import_module(name)
  if not hasattr(module,field):raise AttributeError('incomplete module')
  report[name]='OK'
 except Exception as exc:report[name]=type(exc).__name__
print(json.dumps(report))
'''
 try:
  result=subprocess.run([str(python),'-I','-X','utf8','-c',code],cwd=target,text=True,encoding='utf-8',errors='replace',
                        stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=45)
  report=json.loads(result.stdout) if result.returncode==0 else None
 except (OSError,ValueError,subprocess.TimeoutExpired) as exc:
  raise RuntimeError('Dependency check could not run ('+type(exc).__name__+')') from None
 if not isinstance(report,dict) or set(report)!={'flask','MetaTrader5','colorama'}:
  raise RuntimeError('Dependency check returned an invalid result')
 return report

def ensure_dependencies(source,target):
 source=Path(source);target=Path(target);python=target/'.venv/Scripts/python.exe'
 report=_dependency_report(python,target)
 missing=[name for name,status in report.items() if status!='OK']
 if not missing:return
 requirements=source/'requirements_event.txt'
 if not requirements.is_file():raise RuntimeError('Package requirements_event.txt is missing')
 print('Installing missing or broken dependencies: '+', '.join(missing)+'. Internet access may be required.',flush=True)
 try:
  result=subprocess.run([str(python),'-X','utf8','-m','pip','install','--disable-pip-version-check','--no-input','-r',str(requirements)],
                        cwd=target,text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=600)
 except (OSError,subprocess.TimeoutExpired) as exc:
  raise RuntimeError('Dependency installation failed ('+type(exc).__name__+'). Check network access and rerun INSTALL_R7_3.cmd. Existing trading state was preserved.') from None
 # pip may print credential-bearing index URLs: never copy raw output into logs.
 if result.returncode!=0:
  raise RuntimeError('Dependency installation failed (exit '+str(result.returncode)+'). Check network access, Python 3.12 x64 and package availability; rerun INSTALL_R7_3.cmd. Existing trading state was preserved.')
 report=_dependency_report(python,target)
 if any(status!='OK' for status in report.values()):
  raise RuntimeError('Dependencies still fail to import: '+', '.join(name for name,status in report.items() if status!='OK'))

def check_python(python,target):
 code="import json,struct,sys;print(json.dumps(dict(version=list(sys.version_info[:3]),bits=struct.calcsize('P')*8,platform=sys.platform)))"
 try:
  result=subprocess.run([str(python),'-I','-X','utf8','-c',code],cwd=target,text=True,encoding='utf-8',errors='replace',
                        stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
  if result.returncode!=0:raise RuntimeError('Bridge Python environment could not run. Existing .venv was preserved; check its Python installation.')
  data=json.loads(result.stdout)
 except (OSError,ValueError,subprocess.TimeoutExpired) as exc:
  raise RuntimeError('Bridge Python environment cannot run ('+type(exc).__name__+'). Keep the existing .venv intact.') from None
 if data.get('bits')!=64:
  raise RuntimeError('Bridge requires 64-bit Python. Existing .venv was preserved; use Python 3.12 x64 in a separate working folder.')
 if data.get('platform')!='win32' or data.get('version',[])<[3,10,0]:
  raise RuntimeError('Bridge requires Windows Python 3.10 or newer (3.12 x64 recommended). Existing environment was preserved.')
 return data

def postflight(target):
 target=Path(target).resolve();python=target/'.venv/Scripts/python.exe'
 if not python.is_file():raise RuntimeError('Bridge Python environment is missing; installation is incomplete')
 check_python(python,target)
 code="import bridge_startup,json;print(json.dumps(bridge_startup.environment_report()))"
 try:
  result=subprocess.run([str(python),'-X','utf8','-B','-c',code],cwd=target,text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=45)
  report=json.loads(result.stdout) if result.returncode==0 else {}
 except (OSError,ValueError,subprocess.TimeoutExpired) as exc:
  raise RuntimeError('R7.3 post-install check could not run ('+type(exc).__name__+')') from None
 if not report.get('ok'):raise RuntimeError('R7.3 post-install import check failed. Prior program will be restored; see r73-install.log and rerun INSTALL_R7_3.cmd.')
 print('MT5 OK; FLASK OK; EVENT_CORE OK; BRIDGE IMPORT OK')

def _install_log(target,message):
 with (target/'r73-install.log').open('a',encoding='utf-8') as log:
  log.write(time.strftime('%Y-%m-%d %H:%M:%S ')+message+'\n')

def windows_wrapper(rollback=False):
 flag=' --rollback' if rollback else ''
 script=r'''@echo off
setlocal DisableDelayedExpansion
set "PYTHONUTF8=1"
pushd "%~dp0"
if errorlevel 1 exit /b 1
set "R7_PY="
set "R7_EXTRA="
if not "%~1"=="" if exist "%~1\.venv\Scripts\python.exe" set "R7_PY=%~1\.venv\Scripts\python.exe"
if not defined R7_PY if exist "%USERPROFILE%\OneDrive\Documents\GitHub\FX-M1-Signal\mt5_bridge\.venv\Scripts\python.exe" set "R7_PY=%USERPROFILE%\OneDrive\Documents\GitHub\FX-M1-Signal\mt5_bridge\.venv\Scripts\python.exe"
if defined R7_PY goto run
python -c "import sys; assert sys.version_info >= (3,10)" >nul 2>&1
if not errorlevel 1 (
 set "R7_PY=python"
 goto run
)
py -3 -c "import sys; assert sys.version_info >= (3,10)" >nul 2>&1
if not errorlevel 1 (
 set "R7_PY=py"
 set "R7_EXTRA=-3"
 goto run
)
echo Python 3.10 or newer was not found. Install Python 3.12 x64, then run this installer again.
if not "%R7_NO_PAUSE%"=="1" pause
popd
exit /b 1
:run
"%R7_PY%" %R7_EXTRA% "%~dp0update_bridge.py"@FLAG@ %*
set "R7_EXIT=%ERRORLEVEL%"
if not "%R7_EXIT%"=="0" echo Update failed. Keep your existing Bridge folder and state. See r73-install.log in the selected folder.
if not "%R7_NO_PAUSE%"=="1" pause
popd
exit /b %R7_EXIT%
'''
 return script.replace('@FLAG@',flag).replace('\n','\r\n').encode('ascii')

def main():
 parser=argparse.ArgumentParser();parser.add_argument('target',nargs='?');parser.add_argument('--yes',action='store_true');parser.add_argument('--rollback',action='store_true');args=parser.parse_args()
 package=Path(__file__).resolve().parent
 if args.target:target=Path(args.target)
 else:
  guess=Path.home()/'OneDrive/Documents/GitHub/FX-M1-Signal/mt5_bridge'
  if not (guess/'bridge_v10_0.py').exists():guess=Path.home()/'FXM1-Bridge'
  print('Working Bridge folder (Enter uses): '+str(guess))
  target=Path(input('Path: ').strip().strip('"') or str(guess))
 print('AUTO must be OFF; close Bridge; finish any bot campaign first.')
 if not args.yes and input('Install R7.3 program files? Type YES: ').strip().upper()!='YES':return
 if args.rollback:
  result=rollback(target);print('OK: previous Bridge program restored. Current program backup:',result)
 else:
  manifest=json.loads((package/'BRIDGE_MANIFEST.json').read_text(encoding='utf-8'))
  source=(package/'Bridge').resolve();target=target.resolve()
  _safe_manifest(source,manifest)
  if not {'bridge_startup.py','requirements_event.txt'}<=set(manifest):
   raise RuntimeError('Incomplete R7.3 payload: startup helper and requirements are required')
  dependencies=json.loads((package/'DEPENDENCY_MANIFEST.json').read_text(encoding='utf-8'))
  _safe_dependencies(package/'Dependencies',dependencies)
  _validate_target(source,target)
  lock=Lock(target/'event_state/runtime.lock')
  result=None
  try:
   _flat(target)
   if not (target/'bridge_v10_0.py').is_file():
    (target/'INSTALL_INCOMPLETE.txt').write_text(INCOMPLETE,encoding='utf-8')
   _install_log(target,'Installation started; runtime lock acquired; campaign checks passed')
   prepare_environment(target)
   dep=repair_colorama(package,target)
   _install_log(target,'Python architecture verified; bundled Colorama verified')
   ensure_dependencies(source,target)
   _install_log(target,'Dependency imports verified')
   result=_copy_program(source,target,manifest)
   postflight(target)
   (target/'INSTALL_INCOMPLETE.txt').unlink(missing_ok=True)
   _install_log(target,'Installation and postflight completed')
  except BaseException as exc:
   if result is not None:
    record=json.loads((result/'ROLLBACK.json').read_text(encoding='utf-8'))
    _restore_items(result,target,record['tops'],set(record['old']))
    (result/'ROLLBACK.json').rename(result/'AUTO_RESTORED.json')
   _install_log(target,'Installation failed: '+type(exc).__name__+'; prior program restored if replacement began; trading state preserved')
   raise
  finally:lock.close()
  print('OK: R7.3 installed. Program backup:',result)
  if dep:print('Dependency backup:',dep)
  print('Run:',target/'START_BRIDGE_V10_0.bat')
 print('History, token, database and broker clock were preserved. No trading commands sent.')
if __name__=='__main__':
 try:main()
 except Exception as exc:print('UPDATE FAILED:',exc);sys.exit(1)
