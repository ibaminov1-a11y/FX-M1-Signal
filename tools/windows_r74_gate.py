"""Native Windows launcher acceptance in a disposable fixture. No live MT5 calls."""
from __future__ import annotations
import ctypes,hashlib,json,os,shutil,sqlite3,subprocess,sys,tempfile,venv
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'mt5_bridge'),str(ROOT/'tools')]
from package_r74 import program_files
from ready_launcher import RuntimePaths,check_runtime,validate_python

def locked(path):
 from ctypes import wintypes
 fn=ctypes.windll.kernel32.CreateFileW;fn.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE];fn.restype=wintypes.HANDLE
 handle=fn(str(path),0x80000000,0,None,3,0,None)
 if handle==ctypes.c_void_p(-1).value:raise ctypes.WinError()
 return handle

def main():
 if sys.platform!='win32':raise SystemExit('Windows-only native gate')
 result=dict(source_sha=os.environ['R74_SOURCE_SHA'],platform=sys.platform,live_mt5=False,tests={})
 with tempfile.TemporaryDirectory(prefix='R74 путь space ! ') as folder:
  base=Path(folder);old=base/'mt5_bridge';new=base/'mt5_bridge_R74';new.mkdir();old.mkdir()
  venv.EnvBuilder(with_pip=False,system_site_packages=True).create(old/'.venv')
  for n,b in program_files(ROOT).items():
   p=new/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
  state=old/'event_state';state.mkdir()
  with sqlite3.connect(state/'campaign.sqlite3') as db:db.execute('create table sentinel(value text)');db.execute("insert into sentinel values ('existing history')")
  db.close()  # sqlite transaction context does not close the native Windows handle.
  (state/'bridge-token.txt').write_text('ci-fixture-existing-pairing-key-not-for-real-trading')
  (state/'broker-clock.json').write_text('{"offset_minutes":180}')
  (state/'runtime.lock').write_bytes(b'0')
  oldcode=old/'event_core';oldcode.mkdir();(oldcode/'__init__.py').write_text("raise RuntimeError('OLD_CODE_IMPORTED')")
  (oldcode/'__pycache__').mkdir();cache=oldcode/'__pycache__/locked.pyc';cache.write_bytes(b'do not delete old cache')
  local_site=old/'.venv/Lib/site-packages';local_site.mkdir(parents=True,exist_ok=True)
  import colorama
  shutil.copytree(Path(colorama.__file__).parent,local_site/'colorama',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
  colour_cache=local_site/'colorama/__pycache__';colour_cache.mkdir();pyc=colour_cache/'__init__.cpython-312.pyc';pyc.write_bytes(b'locked colorama cache')
  marker=base/'FORBIDDEN_MT5_CALL'
  (local_site/'sitecustomize.py').write_text("import MetaTrader5\nfrom pathlib import Path\ndef forbidden(*a,**k):\n Path("+repr(str(marker))+").write_text('forbidden')\n raise RuntimeError('No MT5 calls in diagnostics')\nfor name in ('initialize','order_send','shutdown'):setattr(MetaTrader5,name,forbidden)\n")
  before={p:p.read_bytes() for p in state.rglob('*') if p.is_file()}
  env=dict(os.environ,R7_NO_PAUSE='1',PYTHONPATH=str(old),PYTHONHOME='nonexistent-poison-home')
  calls=[]
  def run(args,ok=True):
   cmd='""'+str(new/'START_BRIDGE_V10_0.bat')+'" '+args+'"'
   p=subprocess.run(['cmd.exe','/d','/c','call',str(new/'START_BRIDGE_V10_0.bat'),*args.split()],cwd=base,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=65)
   calls.append(dict(args=args,returncode=p.returncode,output=p.stdout[-2500:]))
   assert (p.returncode==0)==ok,(args,p.returncode,p.stdout,p.stderr)
   return p.stdout
  handles=[]
  try:
   handles=[locked(cache),locked(pyc)]
   out=run('--check');assert '"ok": true' in out and '"event_core": "OK"' in out
   result['tests']['spaced_cyrillic_bang_path_and_poisoned_environment']=True
   result['tests']['locked_old_and_colorama_bytecode_preserved']=True
   out=run('--diagnose');assert '"read_only": true' in out
   result['tests']['diagnostic_read_only']=True
   out=run('--help');assert 'usage:' in out
   result['tests']['cmd_help']=True
   run('--port 0',ok=False);result['tests']['bad_port_nonzero']=True
   token=(state/'bridge-token.txt').read_bytes();(state/'bridge-token.txt').rename(state/'saved-token')
   try:run('--check',ok=False);assert not (state/'bridge-token.txt').exists()
   finally:(state/'saved-token').rename(state/'bridge-token.txt')
   result['tests']['missing_identity_no_reset']=True
   (state/'campaign.sqlite3').rename(state/'saved-db')
   try:run('--check',ok=False);assert not (state/'campaign.sqlite3').exists()
   finally:(state/'saved-db').rename(state/'campaign.sqlite3')
   result['tests']['missing_history_no_reset']=True
   import msvcrt
   with (state/'runtime.lock').open('r+b') as f:
    msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
    try:run('--check',ok=False)
    finally:f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
   result['tests']['shared_process_lock']=True
  finally:
   for h in handles:ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(h))
  assert not marker.exists(),'Diagnostics initialized MT5 or sent order'
  assert before=={p:p.read_bytes() for p in state.rglob('*') if p.is_file()},'State changed'
  assert cache.read_bytes()==b'do not delete old cache' and pyc.read_bytes()==b'locked colorama cache'
  assert not (new/'event_state').exists() and not (new/'.venv').exists()
  result['tests']['state_unchanged_and_no_mt5_calls']=True
  for r in ({'platform':'win32','bits':32,'version':[3,12]},{'platform':'win32','bits':64,'version':[3,9]}):
   try:validate_python(r)
   except RuntimeError:pass
   else:raise AssertionError('Invalid Python accepted')
  result['tests']['invalid_python_rejected']=True
  result['invocations']=calls;result['ok']=True
 Path('evidence').mkdir(exist_ok=True);Path('evidence/WINDOWS_R74.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
 print('WINDOWS_R74_PASS',len(result['tests']))
if __name__=='__main__':main()
