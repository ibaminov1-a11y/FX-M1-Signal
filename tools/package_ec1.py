"""Package exact tested APK/source. No user state, credentials, or signing keys are exported."""
from pathlib import Path
import shutil,json,hashlib,zipfile,subprocess,importlib.metadata as md
root=Path(__file__).resolve().parents[1];dest=root/'evidence';dest.mkdir(exist_ok=True)
package=dest/'package';package.mkdir(exist_ok=True);bridge=package/'Bridge';bridge.mkdir(exist_ok=True)
shutil.copy2(root/'app/build/outputs/apk/debug/app-debug.apk',package/'FXM1_10_9_EVENT_CORE_DEMO.apk')
for name in ('bridge_v10_0.py','START_BRIDGE_V10_0.bat','requirements_event.txt','export_ticks.py','research_config.json'):
    shutil.copy2(root/'mt5_bridge'/name,bridge/name)
shutil.copytree(root/'mt5_bridge/event_core',bridge/'event_core',ignore=shutil.ignore_patterns('__pycache__','*.pyc'),dirs_exist_ok=True)
# Pure-Python fallbacks, with licences. Exclude platform extensions, never ship environment credentials.
vendor=bridge/'_vendor';vendor.mkdir(exist_ok=True)
for distribution in ('Flask','Werkzeug','Jinja2','MarkupSafe','itsdangerous','click','blinker','colorama'):
    dist=md.distribution(distribution)
    for file in dist.files or []:
        p=Path(str(file))
        if '..' in p.parts or p.suffix in ('.pyc','.so','.pyd','.dll') or '__pycache__' in p.parts:continue
        source=Path(dist.locate_file(file))
        if not source.is_file():continue
        target=vendor/p;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
shutil.copy2(root/'docs/EVENT_CORE_RU.md',package/'READ_ME_RU.md')
commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
metadata={'commit':commit,'apk_sha256':hashlib.sha256((package/'FXM1_10_9_EVENT_CORE_DEMO.apk').read_bytes()).hexdigest(),
          'status':'DEMO_RESEARCH_CANDIDATE','market_backtest':'not_run','physical_phone':'not_tested','real_trading':'blocked'}
(package/'PROVENANCE.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
with zipfile.ZipFile(dest/'FXM1_10_9_EVENT_CORE_PACKAGE.zip','w',zipfile.ZIP_DEFLATED) as z:
    for p in package.rglob('*'):
        if p.is_file():z.write(p,p.relative_to(package))
shutil.copy2(package/'FXM1_10_9_EVENT_CORE_DEMO.apk',dest/'FXM1_10_9_EVENT_CORE_DEMO.apk')
subprocess.run(['git','archive','--format=zip','--output='+str(dest/'FXM1_EVENT_CORE_SOURCE.zip'),'HEAD'],cwd=root,check=True)
