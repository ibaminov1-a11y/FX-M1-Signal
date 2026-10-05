"""Package the exact tested R7.3 commit, native evidence and safe Windows installer."""
from pathlib import Path
import hashlib,importlib.metadata as md,json,shutil,struct,subprocess,sys,zipfile
ROOT=Path(__file__).resolve().parents[1];E=ROOT/'evidence'
CERT='3d55a491046e661664f99c2a3e4a51338a794b313beb3e32d7ed88181a7a1885'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def validate_windows_evidence(windows,commit):
 if windows.get('commit')!=commit:raise RuntimeError('Windows evidence commit does not match source commit')
 if windows.get('platform')!='win32':raise RuntimeError('Native Windows evidence is required')
 for field in ('ok','cmd_install','broken_colorama_repaired','mixed_event_core_replaced','installed_help',
               'fresh_environment','installed_launcher_check','read_only_diagnostics'):
  if windows.get(field) is not True:raise RuntimeError('Windows release gate is missing or failed: '+field)

def collect_r73_screenshots(directory):
 files={}
 for path in sorted(Path(directory).rglob('r73*.png')):
  data=path.read_bytes()
  if (len(data)<=1000 or data[:8]!=b'\x89PNG\r\n\x1a\n' or data[12:16]!=b'IHDR'
      or min(struct.unpack('>II',data[16:24]))<200):
   raise RuntimeError('Invalid native PNG screenshot: '+path.name)
  if path.name in files and digest(path)!=digest(files[path.name]):
   raise RuntimeError('Conflicting native PNG screenshots: '+path.name)
  files[path.name]=path
 required={'r73-chart-broker-position.png','r73-chart-two-scenarios.png'}
 required.update('r73-chart-frame-'+tf+'.png' for tf in ('m1','m5','m15','m30','h1','h4','d1','w1','mn1'))
 required.update('r73-chart-'+symbol+'-'+width+'.png' for symbol in ('eurusd','usdjpy','xauusd','btcusd') for width in ('320','360'))
 required.update('r73-chart-'+state+'.png' for state in ('history_only','stale','archive','client_offline'))
 if not required<=set(files):raise RuntimeError('Missing native R7.3 PNG screenshots: '+', '.join(sorted(required-set(files))))
 return [files[name] for name in sorted(files)]

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
 assert BUILD=='10.9-EC1-R7.3' and REVISION=='R7.3-DEMO'
 commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
 assert (E/'COMMIT.txt').read_text().strip()==commit
 subprocess.run(['git','diff','--exit-code','HEAD'],cwd=ROOT,check=True)
 assert CERT in (E/'apk-signature.txt').read_text()
 android=json.loads((E/'ANDROID_RESULT.json').read_text());assert android['failures']==0 and android['tests']>=126
 assert android.get('commit')==commit and android.get('r73_chart_tests',0)>0 and android.get('r73_controls_tests',0)>0
 windows=json.loads((E/'WINDOWS_RESULT.json').read_text());validate_windows_evidence(windows,commit)
 screenshots=collect_r73_screenshots(E/'ui')
 package=E/'package_r73'
 if package.exists():shutil.rmtree(package)
 bridge=package/'Bridge';bridge.mkdir(parents=True)
 for n in ('bridge_v10_0.py','bridge_startup.py','START_BRIDGE_V10_0.bat','requirements_event.txt','export_ticks.py','research_config.json','CHECK_BROKER_CLOCK.py','CHECK_BROKER_CLOCK.cmd'):
  shutil.copy2(ROOT/'mt5_bridge'/n,bridge/n)
 shutil.copytree(ROOT/'mt5_bridge/event_core',bridge/'event_core',ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.orig'))
 assert not (bridge/'_vendor').exists()
 (bridge/'BUILD.json').write_text(json.dumps(dict(commit=commit,build=BUILD,revision=REVISION,protocol=PROTOCOL)),encoding='utf-8')
 manifest={p.relative_to(bridge).as_posix():digest(p) for p in sorted(bridge.rglob('*')) if p.is_file()}
 (package/'BRIDGE_MANIFEST.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
 copy_colorama(package)
 shutil.copy2(ROOT/'tools/r7_updater.py',package/'update_bridge.py')
 from r7_updater import windows_wrapper
 for name,back in (('INSTALL_R7_3.cmd',False),('ROLLBACK_R7_3.cmd',True)):
  (package/name).write_bytes(windows_wrapper(back))
 apk=package/'FXM1_R7_3_DEMO.apk';shutil.copy2(ROOT/'app/build/outputs/apk/debug/app-debug.apk',apk)
 shutil.copy2(ROOT/'docs/UPGRADE_R7.md',package/'START_HERE_RU.md')
 source=package/'Sources/FXM1_R7_3_SOURCE.zip';source.parent.mkdir()
 subprocess.run(['git','archive','--format=zip','--output='+str(source),'HEAD'],cwd=ROOT,check=True)
 with zipfile.ZipFile(source) as z:
  for p in bridge.rglob('*'):
   if p.is_file() and p.name!='BUILD.json':assert z.read('mt5_bridge/'+p.relative_to(bridge).as_posix())==p.read_bytes()
 provenance=dict(commit=commit,build=BUILD,version_code=931,protocol=PROTOCOL,apk_sha256=digest(apk),
  certificate_sha256=CERT,source_sha256=digest(source),android=android,windows=windows,
  runtime_dependencies='PRESERVED_OR_NEW_VENV; OFFLINE_COLORAMA; PIP_FOR_MISSING_DEPENDENCIES',runtime_vendor=False,
  real_trading='DISABLED_IN_ADAPTER',market_profitability='NOT_ESTABLISHED',physical_mt5='NOT_TESTED',
  forecast='RESEARCH_EMPIRICAL_ANALOG; NOT_CALIBRATED',supported_trade_frames=['M1','M5','M10','M15','M30','H1','H4','D1','W1','MN1'],
  selectable_trade_frames=['M1','M5','M15','M30','H1','H4','D1','W1','MN1'],legacy_trade_frames=['M10'],
  native_chart_screenshots=[p.name for p in screenshots])
 (package/'PROVENANCE.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
 verify=package/'Verification';verify.mkdir()
 for n in ('COMMIT.txt','python-tests.log','android-runtime.log','apk-signature.txt','WINDOWS_RESULT.json','windows-tests.log','ANDROID_RESULT.json'):
  shutil.copy2(E/n,verify/n)
 for p in (E/'ui').rglob('*.png'):
  if p.name.startswith('r7') and not p.name.startswith('r73'):
   shutil.copy2(p,verify/p.name)
 for p in screenshots:shutil.copy2(p,verify/p.name)
 for required in ('R73_INSTALLER_AUDIT.md','R73_TRADING_AUDIT.md'):
  assert (ROOT/'docs/verification'/required).is_file(),required
 for p in sorted((ROOT/'docs/verification').glob('R73*.md')):shutil.copy2(p,verify/p.name)
 sums={p.relative_to(package).as_posix():digest(p) for p in package.rglob('*') if p.is_file()}
 (package/'SHA256SUMS.txt').write_text(''.join(v+'  '+k+'\n' for k,v in sorted(sums.items())),encoding='utf-8')
 out=E/'FXM1_R7_3_FULL.zip'
 with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
  for p in sorted(package.rglob('*')):
   if p.is_file():z.write(p,p.relative_to(package).as_posix())
 with zipfile.ZipFile(out) as z:assert z.testzip() is None
 assert out.stat().st_size<32*1024*1024
 (E/'R7_PACKAGE_SHA256.txt').write_text(digest(out)+'  '+out.name+'\n')
 print('R7_3_DEMO_PACKAGE_VERIFIED',commit,digest(out),out.stat().st_size)
if __name__=='__main__':main()
