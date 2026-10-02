"""Transactional program-only update/rollback. No MT5 imports or trading commands."""
from __future__ import annotations
import argparse,hashlib,json,os,shutil,sqlite3,sys,tempfile,time
from pathlib import Path
from contextlib import closing

ALLOWED={'event_core','_vendor','bridge_v10_0.py','START_BRIDGE_V10_0.bat','requirements_event.txt',
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
 # Inspect a disposable, coherent main/WAL/SHM set with every connection explicitly
 # closed BEFORE temp cleanup (Windows holds SQLite file handles until close()).
 for path in (root/'event_state/campaign.sqlite3',root/'campaign.sqlite3'):
  if not path.exists():continue
  with tempfile.TemporaryDirectory(prefix='r7_db_probe_') as folder:
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
  f=source/p
  if f.is_symlink() or not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest()!=digest:raise RuntimeError('Package checksum mismatch: '+name)
  if f.suffix=='.py':compile(f.read_bytes(),name,'exec')
 for required in ('event_core/__init__.py','event_core/server.py','bridge_v10_0.py','START_BRIDGE_V10_0.bat'):
  if required not in manifest:raise RuntimeError('Incomplete Bridge payload')

def _remove(path):
 if path.is_dir():shutil.rmtree(path)
 elif path.exists():path.unlink()

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
  backup=target/('r7_program_backup_'+str(time.time_ns()));backup.mkdir()
  moved=[];installed=[]
  with tempfile.TemporaryDirectory(prefix='r7_staged_',dir=target) as folder:
   staged=Path(folder)
   for name in manifest:
    out=staged/name;out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/name,out)
   try:
    for top in tops:
     if (target/top).exists():os.replace(target/top,backup/top);moved.append(top)
     os.replace(staged/top,target/top);installed.append(top)
    _safe_manifest(target,manifest)
   except BaseException:
    for top in installed:_remove(target/top)
    for top in moved:
     if (backup/top).exists():os.replace(backup/top,target/top)
    raise
  (backup/'ROLLBACK.json').write_text(json.dumps(dict(tops=tops,old=moved,installed=manifest),indent=2),encoding='utf-8')
  return backup
 finally:lock.close()

def rollback(target,backup=None):
 target=Path(target).resolve()
 choices=sorted(target.glob('r7_program_backup_*/ROLLBACK.json'),key=lambda p:p.parent.name)
 if backup is None:
  if not choices:raise RuntimeError('No R7 program backup found')
  backup=choices[-1].parent
 backup=Path(backup).resolve()
 if backup.parent!=target:raise RuntimeError('Backup is outside this Bridge folder')
 record=json.loads((backup/'ROLLBACK.json').read_text(encoding='utf-8'))
 lock=Lock(target/'event_state/runtime.lock')
 try:
  _flat(target);_safe_manifest(target,record['installed'])
  # Keep current code as well; rollback never deletes trading history.
  saved=target/('r7_rollback_current_'+str(time.time_ns()));saved.mkdir();moved=[];restored=[]
  try:
   for top in record['tops']:
    if top not in ALLOWED:raise RuntimeError('Invalid backup metadata')
    if (target/top).exists():os.replace(target/top,saved/top);moved.append(top)
    if top in record['old']:os.replace(backup/top,target/top);restored.append(top)
  except BaseException:
   for top in restored:os.replace(target/top,backup/top)
   for top in moved:os.replace(saved/top,target/top)
   raise
  (backup/'ROLLBACK.json').rename(backup/'ROLLED_BACK.json')
  return saved
 finally:lock.close()

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
 if not args.yes and input('Update program files only? Type YES: ').strip().upper()!='YES':return
 if args.rollback:
  result=rollback(target);print('OK: previous Bridge restored. Current program backup:',result)
 else:
  manifest=json.loads((package/'BRIDGE_MANIFEST.json').read_text(encoding='utf-8'))
  result=apply_update(package/'Bridge',target,manifest)
  print('OK: R7 installed. Program backup:',result)
  print('Run:',target/'START_BRIDGE_V10_0.bat')
 print('History, token and Python environment were preserved. No trading commands sent.')
if __name__=='__main__':
 try:main()
 except Exception as exc:print('UPDATE FAILED:',exc);sys.exit(1)
