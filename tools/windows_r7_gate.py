"""Native Windows R7.3 gate: real CMD, upgrades, fresh venv and safe diagnostics."""
import hashlib,importlib.metadata as md,json,os,re,shutil,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def copy_colorama(pkg):
 deps=pkg/'Dependencies';deps.mkdir()
 dist=md.distribution('colorama')
 for f in dist.files or []:
  p=Path(str(f));top=p.parts[0].lower() if p.parts else ''
  if top!='colorama' and not (top.startswith('colorama-') and top.endswith('.dist-info')):continue
  if '__pycache__' in p.parts or p.suffix=='.pyc':continue
  src=Path(dist.locate_file(f))
  if src.is_file():
   dst=deps/p;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
 manifest={p.relative_to(deps).as_posix():digest(p) for p in deps.rglob('*') if p.is_file()}
 assert manifest and 'AnsiToWin32' in (deps/'colorama/__init__.py').read_text(encoding='utf-8')
 (pkg/'DEPENDENCY_MANIFEST.json').write_text(json.dumps(manifest),encoding='utf-8')

def main():
 assert sys.platform=='win32','This release gate must run on native Windows'
 evidence=ROOT/'evidence';evidence.mkdir(exist_ok=True)
 env=dict(os.environ,R7_NO_PAUSE='1',PYTHONPATH=str(ROOT/'mt5_bridge')+os.pathsep+str(ROOT/'tests/event_core'),PYTHONUTF8='1')
 r=subprocess.run([sys.executable,'-m','unittest','test_r7_installer','test_r73_installer','test_r7_profiles','test_r7_release_runtime','test_r72_simple_runtime_contract','-v'],
                  cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',timeout=240)
 (evidence/'windows-tests.log').write_text(r.stdout,encoding='utf-8');print(r.stdout);assert r.returncode==0
 tests_run=int(re.search(r'Ran (\d+) tests',r.stdout).group(1))
 with tempfile.TemporaryDirectory(prefix='R73 OneDrive путь space ! ') as folder:
  folder=Path(folder);pkg=folder/'package';bridge=pkg/'Bridge';target=folder/'target';bridge.mkdir(parents=True);target.mkdir()
  shutil.copytree(ROOT/'mt5_bridge/event_core',bridge/'event_core',ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.orig'))
  for n in ('bridge_v10_0.py','bridge_startup.py','START_BRIDGE_V10_0.bat','requirements_event.txt'):shutil.copy2(ROOT/'mt5_bridge'/n,bridge/n)
  manifest={p.relative_to(bridge).as_posix():digest(p) for p in bridge.rglob('*') if p.is_file()}
  (pkg/'BRIDGE_MANIFEST.json').write_text(json.dumps(manifest),encoding='utf-8')
  copy_colorama(pkg)
  shutil.copy2(ROOT/'tools/r7_updater.py',pkg/'update_bridge.py')
  from r7_updater import windows_wrapper
  (pkg/'INSTALL_R7_3.cmd').write_bytes(windows_wrapper())

  # Reproduce the user's actual failure class: existing venv, broken local Colorama,
  # stale/mixed event_core without VERSION, and an old launcher.
  subprocess.run([sys.executable,'-m','venv','--system-site-packages',str(target/'.venv')],check=True,timeout=120)
  site=target/'.venv/Lib/site-packages';(site/'colorama').mkdir(parents=True,exist_ok=True)
  (site/'colorama/__init__.py').write_text("BROKEN=True\n",encoding='utf-8')
  (target/'event_core').mkdir()
  (target/'event_core/__init__.py').write_text("BUILD='MIXED_OLD_STATE'\n",encoding='utf-8')
  (target/'event_core/server.py').write_text("# stale server\n",encoding='utf-8')
  (target/'bridge_v10_0.py').write_text("# old launcher\n",encoding='utf-8')
  (target/'event_state').mkdir();(target/'event_state/bridge-token.txt').write_text('test-secret-not-real')

  result=subprocess.run(['cmd.exe','/d','/c','call',str(pkg/'INSTALL_R7_3.cmd'),str(target),'--yes'],
                        env=env,capture_output=True,text=True,encoding='utf-8',timeout=120)
  with (evidence/'windows-tests.log').open('a',encoding='utf-8') as log:log.write('\n--- R7.3 mixed-state recovery ---\n'+result.stdout+result.stderr)
  assert result.returncode==0,result.stdout+result.stderr
  assert 'OK: R7.3 installed' in result.stdout
  assert 'COLORAMA OK' in result.stdout and 'EVENT_CORE OK' in result.stdout and 'BRIDGE IMPORT OK' in result.stdout
  assert not (target/'_vendor').exists(),'R7.3 must not install runtime _vendor'
  for name,h in manifest.items():assert digest(target/name)==h
  py=target/'.venv/Scripts/python.exe'
  check=subprocess.run([str(py),'-c',"import MetaTrader5,colorama,event_core,bridge_v10_0; assert hasattr(colorama,'AnsiToWin32'); assert hasattr(event_core,'VERSION'); print(event_core.BUILD,event_core.REVISION)"],
                       cwd=target,capture_output=True,text=True,encoding='utf-8',timeout=30)
  assert check.returncode==0,check.stdout+check.stderr
  assert '10.9-EC1-R7.3' in check.stdout and 'R7.3-DEMO' in check.stdout
  assert (target/'event_state/bridge-token.txt').read_text()=='test-secret-not-real'
  result=subprocess.run([str(py),str(target/'bridge_v10_0.py'),'--help'],cwd=target,env=env,capture_output=True,text=True,encoding='utf-8',timeout=30)
  assert result.returncode==0,result.stderr
  assert not (target/'event_state/campaign.sqlite3').exists(),'--help must not create trading state'
  state_before={p.name:p.read_bytes() for p in (target/'event_state').iterdir() if p.is_file()}
  result=subprocess.run(['cmd.exe','/d','/c','call',str(target/'START_BRIDGE_V10_0.bat'),'--diagnose'],
                        cwd=target,env=env,capture_output=True,text=True,encoding='utf-8',timeout=45)
  assert result.returncode==0,result.stdout+result.stderr
  assert 'localhost_reachable' in result.stdout and 'runtime_lock' in result.stdout
  assert 'test-secret-not-real' not in result.stdout+result.stderr
  assert state_before=={p.name:p.read_bytes() for p in (target/'event_state').iterdir() if p.is_file()}
  result=subprocess.run(['cmd.exe','/d','/c','call',str(target/'START_BRIDGE_V10_0.bat'),'--check'],
                        cwd=target,env=env,capture_output=True,text=True,encoding='utf-8',timeout=45)
  assert result.returncode==0,result.stdout+result.stderr
  assert (target/'event_state/bridge-startup.log').exists()
  assert 'test-secret-not-real' not in (target/'event_state/bridge-startup.log').read_text(encoding='utf-8')

  # A genuinely empty target must create a private venv and install Flask/MT5,
  # rather than accidentally inheriting the runner's preinstalled packages.
  fresh=folder/'fresh target путь !'
  result=subprocess.run(['cmd.exe','/d','/c','call',str(pkg/'INSTALL_R7_3.cmd'),str(fresh),'--yes'],
                        env=env,capture_output=True,text=True,encoding='utf-8',timeout=720)
  with (evidence/'windows-tests.log').open('a',encoding='utf-8') as log:
   log.write('\n--- R7.3 fresh environment ---\n'+result.stdout+result.stderr)
  assert result.returncode==0,result.stdout+result.stderr
  assert 'OK: R7.3 installed' in result.stdout
  assert (fresh/'.venv/Scripts/python.exe').is_file()
  assert 'include-system-site-packages = false' in (fresh/'.venv/pyvenv.cfg').read_text(encoding='utf-8')
  assert not (fresh/'event_state/campaign.sqlite3').exists()
  assert not (fresh/'event_state/bridge-token.txt').exists()
  result=subprocess.run(['cmd.exe','/d','/c','call',str(fresh/'START_BRIDGE_V10_0.bat'),'--check'],
                        cwd=fresh,env=env,capture_output=True,text=True,encoding='utf-8',timeout=45)
  assert result.returncode==0,result.stdout+result.stderr
  with (evidence/'windows-tests.log').open('a',encoding='utf-8') as log:
   log.write('\nCMD_INSTALL_OK; BROKEN_COLORAMA_REPAIRED; MIXED_EVENT_CORE_REPLACED; FRESH_VENV_OK; INSTALLED_LAUNCHER_CHECK_OK; READ_ONLY_DIAGNOSTICS_OK; no orders\n')
 commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
 (evidence/'WINDOWS_RESULT.json').write_text(json.dumps(dict(ok=True,platform=sys.platform,commit=commit,tests=tests_run,
   cmd_install=True,broken_colorama_repaired=True,mixed_event_core_replaced=True,installed_help=True,
   fresh_environment=True,installed_launcher_check=True,read_only_diagnostics=True,live_mt5=False)),encoding='utf-8')
 out=ROOT/'artifacts/windows/evidence';out.mkdir(parents=True,exist_ok=True)
 for n in ('WINDOWS_RESULT.json','windows-tests.log'):shutil.copy2(evidence/n,out/n)
if __name__=='__main__':main()
