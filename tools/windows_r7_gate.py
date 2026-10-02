"""Native Windows check of the real distributed Python installer plus CMD launch."""
import hashlib,json,os,shutil,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 assert sys.platform=='win32','This release gate must run on native Windows'
 evidence=ROOT/'evidence';evidence.mkdir(exist_ok=True)
 env=dict(os.environ,R7_NO_PAUSE='1',PYTHONPATH=str(ROOT/'mt5_bridge')+os.pathsep+str(ROOT/'tests/event_core'),PYTHONUTF8='1')
 r=subprocess.run([sys.executable,'-m','unittest','test_r7_installer','test_r7_profiles','test_r7_release_runtime','-v'],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',timeout=180)
 (evidence/'windows-tests.log').write_text(r.stdout,encoding='utf-8');print(r.stdout);assert r.returncode==0
 with tempfile.TemporaryDirectory(prefix='R7 путь space ') as folder:
  pkg=Path(folder)/'package';bridge=pkg/'Bridge';target=Path(folder)/'target';bridge.mkdir(parents=True)
  shutil.copytree(ROOT/'mt5_bridge/event_core',bridge/'event_core',ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.orig'))
  for n in ('bridge_v10_0.py','START_BRIDGE_V10_0.bat','requirements_event.txt'):shutil.copy2(ROOT/'mt5_bridge'/n,bridge/n)
  manifest={p.relative_to(bridge).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in bridge.rglob('*') if p.is_file()}
  (pkg/'BRIDGE_MANIFEST.json').write_text(json.dumps(manifest),encoding='utf-8')
  shutil.copy2(ROOT/'tools/r7_updater.py',pkg/'update_bridge.py')
  from r7_updater import windows_wrapper
  (pkg/'INSTALL_R7.cmd').write_bytes(windows_wrapper())
  # CALL avoids cmd.exe stripping the first quoted executable path with spaces.
  result=subprocess.run(['cmd.exe','/d','/c','call',str(pkg/'INSTALL_R7.cmd'),str(target),'--yes'],env=env,capture_output=True,text=True,encoding='utf-8',timeout=60)
  assert result.returncode==0,result.stdout+result.stderr
  assert 'OK: R7 installed' in result.stdout
  for name,h in manifest.items():assert hashlib.sha256((target/name).read_bytes()).hexdigest()==h
  result=subprocess.run([sys.executable,str(target/'bridge_v10_0.py'),'--help'],env=env,capture_output=True,text=True,encoding='utf-8',timeout=30)
  assert result.returncode==0,result.stderr
  assert not (target/'event_state/campaign.sqlite3').exists(),'--help must not create trading state'
  with (evidence/'windows-tests.log').open('a',encoding='utf-8') as log:
   log.write('\nCMD_INSTALL_OK; INSTALLED_LAUNCHER_HELP_OK; no MT5 process, no orders\n')
 commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
 (evidence/'WINDOWS_RESULT.json').write_text(json.dumps(dict(ok=True,platform=sys.platform,commit=commit,tests=17,cmd_install=True,installed_help=True,live_mt5=False)),encoding='utf-8')
 out=ROOT/'artifacts/windows/evidence';out.mkdir(parents=True,exist_ok=True)
 for n in ('WINDOWS_RESULT.json','windows-tests.log'):shutil.copy2(evidence/n,out/n)
if __name__=='__main__':main()
