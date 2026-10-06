"""Ready EC1 launcher: new program, existing Windows Python and trading state.

Preflight never connects to MT5, reads the pairing token, repairs dependencies or
creates a replacement history. Ordinary server output stays in the user's console.
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class RuntimePaths:
    python: Path
    program_root: Path
    state_dir: Path


def resolve_runtime(root: Path) -> RuntimePaths:
    root=Path(root).resolve();old=root.parent/'mt5_bridge'
    if old.resolve()==root:raise RuntimeError('New program must be in its own folder beside mt5_bridge. Current folder: '+str(root))
    python=old/'.venv/Scripts/python.exe';state=old/'event_state'
    if not python.is_file():raise RuntimeError('Existing Bridge Python not found. Keep this folder next to mt5_bridge; do not delete .venv.')
    if not state.is_dir() or not (state/'campaign.sqlite3').is_file():
        raise RuntimeError('Existing trading state/history not found. No empty state was created. Keep the old mt5_bridge folder.')
    if not (state/'bridge-token.txt').is_file():raise RuntimeError('Existing pairing identity not found. No replacement token was created.')
    if not (root/'event_core/__init__.py').is_file():raise RuntimeError('Full program is missing. Extract the whole Bridge ZIP.')
    return RuntimePaths(python.resolve(),root,state.resolve())


def clean_environment():
    env={k:v for k,v in os.environ.items() if not k.upper().startswith('PYTHON')}
    env['PYTHONUTF8']='1';env['PYTHONDONTWRITEBYTECODE']='1'
    return env


def validate_python(report):
    if report.get('platform')!='win32' or report.get('bits')!=64 or report.get('version',[])<[3,10,0]:
        raise RuntimeError('Bridge requires Windows 64-bit Python 3.10+. Existing environment was not changed.')


def _probe(paths):
    # No user-controlled module names or shell interpolation. Imported code is
    # validated before the server can be launched with the old state path.
    code="""import sys,json,struct,importlib,contextlib,io
from pathlib import Path
root=Path(sys.argv[1]).resolve();sys.path.insert(0,str(root))
r={'platform':sys.platform,'bits':struct.calcsize('P')*8,'version':list(sys.version_info[:3]),'imports':{}}
for name,fields in [('flask',('Flask',)),('MetaTrader5',('initialize',)),('colorama',('AnsiToWin32',)),('event_core',('VERSION','BUILD','REVISION')),('event_core.server',('main',))]:
 try:
  with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):m=importlib.import_module(name)
  if not all(hasattr(m,key) for key in fields):raise ImportError('incomplete')
  if name.startswith('event_core') and not Path(m.__file__).resolve().is_relative_to(root/'event_core'):raise ImportError('foreign program')
  r['imports'][name]='OK'
  if name=='event_core':r['build']=m.BUILD
 except Exception as exc:r['imports'][name]=type(exc).__name__
print(json.dumps(r))
"""
    try:
        result=subprocess.run([str(paths.python),'-I','-B','-X','utf8','-c',code,str(paths.program_root)],
            cwd=paths.program_root,env=clean_environment(),capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=45)
        if result.returncode!=0:raise RuntimeError('Python preflight process failed. Existing state was preserved.')
        return json.loads(result.stdout)
    except (OSError,ValueError,subprocess.TimeoutExpired) as exc:
        raise RuntimeError('Python preflight could not run: '+type(exc).__name__+'. No files were repaired or removed.') from None


def check_runtime(paths) -> dict:
    report=_probe(paths);validate_python(report)
    if set(report.get('imports',{}))!={'flask','MetaTrader5','colorama','event_core','event_core.server'} or any(v!='OK' for v in report['imports'].values()):
        raise RuntimeError('Bridge imports failed: '+json.dumps(report.get('imports',{}),sort_keys=True))
    return dict(report,ok=True,read_only=True,live_mt5=False)


def require_stopped(paths):
    # Resolving only the supplied new helper never searches the old program.
    sys.path.insert(0,str(paths.program_root))
    from bridge_startup import _lock_status
    status=_lock_status(paths.state_dir/'runtime.lock')
    if status in ('held','unavailable'):raise RuntimeError('Bridge is already running or the runtime lock is unavailable. Close the old Bridge first.')


def server_command(paths,server_args):
    if any(arg=='--state-dir' or arg.startswith('--state-dir=') for arg in server_args):
        raise RuntimeError('The existing state directory cannot be overridden by server arguments.')
    code="import sys;sys.path.insert(0,sys.argv.pop(1));from event_core.server import main;main()"
    return ([str(paths.python),'-I','-B','-X','utf8','-c',code,str(paths.program_root),
             '--host','0.0.0.0','--state-dir',str(paths.state_dir),*server_args],clean_environment())


def launch(paths,server_args) -> int:
    require_stopped(paths);command,env=server_command(paths,server_args)
    try:return subprocess.run(command,cwd=paths.program_root,env=env).returncode
    except KeyboardInterrupt:return 130
    except OSError as exc:raise RuntimeError('Bridge process could not start: '+type(exc).__name__) from None


def main(argv=None):
    parser=argparse.ArgumentParser(description='EC1 ready Bridge: existing environment and state; new program only')
    parser.add_argument('--check',action='store_true',help='Read-only import check, no MT5 initialization')
    parser.add_argument('--diagnose',action='store_true',help='Read-only local connection diagnosis')
    parser.add_argument('--port',type=int,default=8000)
    args,extra=parser.parse_known_args(argv)
    if not 1<=args.port<=65535:parser.error('Port must be between 1 and 65535')
    paths=resolve_runtime(Path(__file__).parent)
    report=check_runtime(paths)
    if args.diagnose:
        sys.path.insert(0,str(paths.program_root));from bridge_startup import network_report
        print(json.dumps(dict(environment=report,network=network_report(paths.state_dir,args.port)),indent=2));return 0
    require_stopped(paths)
    print(str(report.get('build','EC1'))+' READY: '+json.dumps(report,sort_keys=True),flush=True)
    if args.check:return 0
    return launch(paths,['--port',str(args.port),*extra])

if __name__=='__main__':
    try:raise SystemExit(main())
    except RuntimeError as exc:print('BRIDGE NOT STARTED: '+str(exc),flush=True);raise SystemExit(1)
