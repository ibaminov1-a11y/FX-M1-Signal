"""R7.2 updater: copy-based program restore plus offline Colorama repair. No trading commands."""
from __future__ import annotations
import argparse,hashlib,json,os,shutil,sqlite3,subprocess,sys,tempfile,time
from pathlib import Path
from contextlib import closing

ALLOWED={'event_core','bridge_v10_0.py','START_BRIDGE_V10_0.bat','requirements_event.txt',
         'CHECK_BROKER_CLOCK.py','CHECK_BROKER_CLOCK.cmd','export_ticks.py','research_config.json','BUILD.json'}

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

def apply_update(source,target,manifest):
 source=Path(source).resolve();target=Path(target).resolve()
 _safe_manifest(source,manifest)
 target.mkdir(parents=True,exist_ok=True)
 if any(target.iterdir()) and not (target/'bridge_v10_0.py').is_file():raise RuntimeError('Select the working Bridge folder, not an unrelated directory.')
 for name in ALLOWED:
  if (target/name).is_symlink():raise RuntimeError('Symbolic links in program paths are not supported')
 lock=Lock(target/'event_state/runtime.lock')
 try:
  _flat(target)
  tops=sorted({Path(n).parts[0] for n in manifest})
  backup=target/('r72_program_backup_'+str(time.time_ns()));backup.mkdir()
  old=[]
  for top in tops:
   if (target/top).exists():_copy_item(target/top,backup/top);old.append(top)
  try:
   for top in tops:
    _remove(target/top)
    _copy_item(source/top,target/top)
   _safe_manifest(target,manifest)
  except BaseException:
   _restore_items(backup,target,tops,old)
   raise
  (backup/'ROLLBACK.json').write_text(json.dumps(dict(tops=tops,old=old,installed=manifest),indent=2),encoding='utf-8')
  return backup
 finally:lock.close()

def rollback(target,backup=None):
 target=Path(target).resolve()
 choices=sorted(target.glob('r72_program_backup_*/ROLLBACK.json'),key=lambda p:p.parent.name)
 if backup is None:
  if not choices:raise RuntimeError('No R7.2 program backup found')
  backup=choices[-1].parent
 backup=Path(backup).resolve()
 if backup.parent!=target:raise RuntimeError('Backup is outside this Bridge folder')
 record=json.loads((backup/'ROLLBACK.json').read_text(encoding='utf-8'))
 lock=Lock(target/'event_state/runtime.lock')
 try:
  _flat(target)
  saved=target/('r72_rollback_current_'+str(time.time_ns()));saved.mkdir()
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
 if not manifest_path.is_file() or not source.is_dir():raise RuntimeError('R7.2 dependency payload is missing')
 manifest=json.loads(manifest_path.read_text(encoding='utf-8'));_safe_dependencies(source,manifest)
 python=target/'.venv/Scripts/python.exe'
 site=target/'.venv/Lib/site-packages'
 if not python.is_file() or not site.is_dir():
  print('Existing .venv not found; dependency repair skipped. Install requirements_event.txt before first start.')
  return None
 tops=sorted({Path(n).parts[0] for n in manifest})
 backup=target/('r72_dependency_backup_'+str(time.time_ns()));backup.mkdir()
 old=[]
 for top in tops:
  if (site/top).exists():_copy_item(site/top,backup/top);old.append(top)
 try:
  for top in tops:
   _remove(site/top);_copy_item(source/top,site/top)
  code="import colorama; assert hasattr(colorama,'AnsiToWin32'); print('COLORAMA OK',colorama.__version__,colorama.__file__)"
  result=subprocess.run([str(python),'-c',code],cwd=target,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30)
  print(result.stdout.strip())
  if result.returncode!=0:raise RuntimeError('Colorama verification failed')
 except BaseException:
  for top in tops:_remove(site/top)
  for top in old:
   if (backup/top).exists():_copy_item(backup/top,site/top)
  raise
 return backup

def postflight(target):
 target=Path(target).resolve();python=target/'.venv/Scripts/python.exe'
 if not python.is_file():return
 code=("import MetaTrader5 as mt5,flask,colorama,event_core,bridge_v10_0;"
       "assert hasattr(colorama,'AnsiToWin32');assert hasattr(event_core,'VERSION');"
       "print('MT5 OK',getattr(mt5,'__version__','?'));"
       "print('FLASK OK',flask.__version__ if hasattr(flask,'__version__') else flask.__file__);"
       "print('EVENT_CORE OK',event_core.BUILD,event_core.REVISION);print('BRIDGE IMPORT OK')")
 result=subprocess.run([str(python),'-c',code],cwd=target,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=45)
 print(result.stdout)
 if result.returncode!=0 or 'BRIDGE IMPORT OK' not in result.stdout:raise RuntimeError('R7.2 post-install import check failed')

def windows_wrapper(rollback=False):
 flag=' --rollback' if rollback else ''
 script=r'''@echo off
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0"
set "R7_PY="
set "R7_EXTRA="
if not "%~1"=="" if exist "%~1\.venv\Scripts\python.exe" set "R7_PY=%~1\.venv\Scripts\python.exe"
if not defined R7_PY if exist "%USERPROFILE%\OneDrive\Documents\GitHub\FX-M1-Signal\mt5_bridge\.venv\Scripts\python.exe" set "R7_PY=%USERPROFILE%\OneDrive\Documents\GitHub\FX-M1-Signal\mt5_bridge\.venv\Scripts\python.exe"
if defined R7_PY goto run
python -c "import sys; assert sys.version_info >= (3,10)"
if not errorlevel 1 (
 set "R7_PY=python"
 goto run
)
py -3 -c "import sys; assert sys.version_info >= (3,10)"
if not errorlevel 1 (
 set "R7_PY=py"
 set "R7_EXTRA=-3"
 goto run
)
echo Python 3.10 or newer was not found.
if not "%R7_NO_PAUSE%"=="1" pause
exit /b 1
:run
"%R7_PY%" %R7_EXTRA% "%~dp0update_bridge.py"@FLAG@ %*
set "R7_EXIT=%ERRORLEVEL%"
if not "%R7_EXIT%"=="0" echo Update failed. Original program backup was preserved.
if not "%R7_NO_PAUSE%"=="1" pause
exit /b %R7_EXIT%
'''
 return script.replace('@FLAG@',flag).replace('\n','\r\n').encode('ascii')

def main():
 parser=argparse.ArgumentParser();parser.add_argument('target',nargs='?');parser.add_argument('--yes',action='store_true');parser.add_argument('--rollback',action='store_true');args=parser.parse_args()
 package=Path(__file__).resolve().parent
 if args.target:target=Path(args.target)
 else:
  guess=Path.home()/'OneDrive/Documents/GitHub/FX-M1-Signal/mt5_bridge'
  if not (guess/'bridge_v10_0.py').exists():guess=package/'Bridge'
  print('Working Bridge folder (Enter uses): '+str(guess))
  target=Path(input('Path: ').strip().strip('"') or str(guess))
 print('AUTO must be OFF; close Bridge; finish any bot campaign first.')
 if not args.yes and input('Restore R7.2 program files? Type YES: ').strip().upper()!='YES':return
 if args.rollback:
  result=rollback(target);print('OK: previous Bridge program restored. Current program backup:',result)
 else:
  dep=repair_colorama(package,target)
  manifest=json.loads((package/'BRIDGE_MANIFEST.json').read_text(encoding='utf-8'))
  result=apply_update(package/'Bridge',target,manifest)
  postflight(target)
  print('OK: R7.2 installed. Program backup:',result)
  if dep:print('Dependency backup:',dep)
  print('Run:',target/'START_BRIDGE_V10_0.bat')
 print('History, token, database and broker clock were preserved. No trading commands sent.')
if __name__=='__main__':
 try:main()
 except Exception as exc:print('UPDATE FAILED:',exc);sys.exit(1)
