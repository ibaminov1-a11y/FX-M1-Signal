"""Package the exact tested R7.2 commit using the user's normal Python environment."""
from pathlib import Path
import hashlib,importlib.metadata as md,json,shutil,subprocess,sys,zipfile
ROOT=Path(__file__).resolve().parents[1];E=ROOT/'evidence'
CERT='3d55a491046e661664f99c2a3e4a51338a794b313beb3e32d7ed88181a7a1885'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def copy_colorama(package):
 deps=package/'Dependencies';deps.mkdir()
 dist=md.distribution('colorama')
 copied=0
 for f in dist.files or []:
  p=Path(str(f));top=p.parts[0].lower() if p.parts else ''
  if top!='colorama' and not (top.startswith('colorama-') and top.endswith('.dist-info')):continue
  if p.is_absolute() or '..' in p.parts or '__pycache__' in p.parts or p.suffix=='.pyc':continue
  src=Path(dist.locate_file(f))
  if src.is_file():
   dst=deps/p;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst);copied+=1
 assert copied>=8
 init=(deps/'colorama/__init__.py').read_text(encoding='utf-8')
 assert 'AnsiToWin32' in init
 manifest={p.relative_to(deps).as_posix():digest(p) for p in sorted(deps.rglob('*')) if p.is_file()}
 (package/'DEPENDENCY_MANIFEST.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')

def main():
 sys.path.insert(0,str(ROOT/'mt5_bridge'))
 from event_core import BUILD,REVISION,PROTOCOL
 assert BUILD=='10.9-EC1-R7.2'
 commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
 assert (E/'COMMIT.txt').read_text().strip()==commit
 subprocess.run(['git','diff','--exit-code','HEAD'],cwd=ROOT,check=True)
 assert CERT in (E/'apk-signature.txt').read_text()
 android=json.loads((E/'ANDROID_RESULT.json').read_text());assert android['failures']==0 and android['tests']>=126
 windows=json.loads((E/'WINDOWS_RESULT.json').read_text());assert windows['ok'] and windows['platform']=='win32' and windows['commit']==commit
 package=E/'package_r72'
 if package.exists():shutil.rmtree(package)
 bridge=package/'Bridge';bridge.mkdir(parents=True)
 for n in ('bridge_v10_0.py','START_BRIDGE_V10_0.bat','requirements_event.txt','export_ticks.py','research_config.json','CHECK_BROKER_CLOCK.py','CHECK_BROKER_CLOCK.cmd'):
  shutil.copy2(ROOT/'mt5_bridge'/n,bridge/n)
 shutil.copytree(ROOT/'mt5_bridge/event_core',bridge/'event_core',ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.orig'))
 assert not (bridge/'_vendor').exists()
 (bridge/'BUILD.json').write_text(json.dumps(dict(commit=commit,build=BUILD,revision=REVISION,protocol=PROTOCOL)),encoding='utf-8')
 manifest={p.relative_to(bridge).as_posix():digest(p) for p in sorted(bridge.rglob('*')) if p.is_file()}
 (package/'BRIDGE_MANIFEST.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
 copy_colorama(package)
 shutil.copy2(ROOT/'tools/r7_updater.py',package/'update_bridge.py')
 from r7_updater import windows_wrapper
 for name,back in (('INSTALL_R7_2.cmd',False),('ROLLBACK_R7_2.cmd',True)):
  (package/name).write_bytes(windows_wrapper(back))
 apk=package/'FXM1_R7_2_DEMO.apk';shutil.copy2(ROOT/'app/build/outputs/apk/debug/app-debug.apk',apk)
 shutil.copy2(ROOT/'docs/UPGRADE_R7.md',package/'START_HERE_RU.md')
 source=package/'Sources/FXM1_R7_2_SOURCE.zip';source.parent.mkdir()
 subprocess.run(['git','archive','--format=zip','--output='+str(source),'HEAD'],cwd=ROOT,check=True)
 with zipfile.ZipFile(source) as z:
  for p in bridge.rglob('*'):
   if p.is_file() and p.name!='BUILD.json':assert z.read('mt5_bridge/'+p.relative_to(bridge).as_posix())==p.read_bytes()
 provenance=dict(commit=commit,build=BUILD,version_code=930,protocol=PROTOCOL,apk_sha256=digest(apk),
  certificate_sha256=CERT,source_sha256=digest(source),android=android,windows=windows,
  runtime_dependencies='NORMAL_VENV_PLUS_OFFLINE_COLORAMA_REPAIR',runtime_vendor=False,
  real_trading='DISABLED_IN_ADAPTER',market_profitability='NOT_ESTABLISHED',physical_mt5='NOT_TESTED',
  forecast='RESEARCH_EMPIRICAL_ANALOG; NOT_CALIBRATED',supported_trade_frames=['M1','M5','M15','M30','H1','H4','D1','W1','MN1'])
 (package/'PROVENANCE.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
 verify=package/'Verification';verify.mkdir()
 for n in ('COMMIT.txt','python-tests.log','android-runtime.log','apk-signature.txt','WINDOWS_RESULT.json','windows-tests.log','ANDROID_RESULT.json'):
  shutil.copy2(E/n,verify/n)
 for p in (E/'ui').rglob('*.png'):
  if p.name.startswith('r7'):
   shutil.copy2(p,verify/p.name)
 sums={p.relative_to(package).as_posix():digest(p) for p in package.rglob('*') if p.is_file()}
 (package/'SHA256SUMS.txt').write_text(''.join(v+'  '+k+'\n' for k,v in sorted(sums.items())),encoding='utf-8')
 out=E/'FXM1_R7_2_FULL.zip'
 with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
  for p in sorted(package.rglob('*')):
   if p.is_file():z.write(p,p.relative_to(package).as_posix())
 with zipfile.ZipFile(out) as z:assert z.testzip() is None
 assert out.stat().st_size<32*1024*1024
 (E/'R7_PACKAGE_SHA256.txt').write_text(digest(out)+'  '+out.name+'\n')
 print('R7_2_DEMO_PACKAGE_VERIFIED',commit,digest(out),out.stat().st_size)
if __name__=='__main__':main()
