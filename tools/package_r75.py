"""Exact-source, non-destructive Bridge package. No user state or private keys."""
from __future__ import annotations
import argparse,hashlib,json,re,zipfile
from pathlib import Path,PurePosixPath
PREFIX='mt5_bridge_R75/'
def digest(data):return hashlib.sha256(data).hexdigest()
def program_files(root:Path):
 source=Path(root)/'mt5_bridge';files={}
 for p in (source/'event_core').rglob('*.py'):
  if '__pycache__' not in p.parts:files[p.relative_to(source).as_posix()]=p.read_bytes()
 for name in ('bridge_v10_0.py','bridge_startup.py','ready_launcher.py','requirements_event.txt','CHECK_BROKER_CLOCK.py','CHECK_BROKER_CLOCK.cmd','export_ticks.py','research_config.json'):
  p=source/name
  if p.is_file():files[name]=p.read_bytes()
 files['START_BRIDGE_V10_0.bat']=(source/'READY_BRIDGE_R75.cmd').read_bytes().replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
 required={'event_core/__init__.py','event_core/server.py','event_core/scenarios/commitment.py','event_core/scenarios/pattern_view.py','ready_launcher.py','bridge_startup.py','requirements_event.txt'}
 if not required<=files.keys():raise ValueError('Incomplete runtime')
 for n,b in files.items():
  if n.endswith('.py'):compile(b,n,'exec')
 return files

def package_bridge(root:Path,out:Path,source_sha:str):
 if not re.fullmatch('[0-9a-f]{40}',source_sha):raise ValueError('Pinned source SHA required')
 files=program_files(root)
 files['START_HERE_RU.txt']=('R7.5 — DEMO-исполнение, полный Bridge\n\n'
 '1. Выключите AUTO. Не считайте остановку Bridge закрытием позиций.\n'
 '2. Закройте старый Bridge.\n'
 '3. Папку mt5_bridge_R75 распакуйте рядом с существующей mt5_bridge.\n'
 '4. Запустите mt5_bridge_R75\\START_BRIDGE_V10_0.bat.\n\n'
 'Новая программа использует существующие .venv и event_state из соседней mt5_bridge.\n'
 'Старые файлы программы не удаляются, среда не переустанавливается.\n'
 'При отсутствии прежней базы или ключа запуск остановится без создания пустой истории.\n'
 'На телефоне установите APK R7.5 поверх прежнего EC1, без удаления приложения.\n'
 'Перед AUTO проверьте DEMO, инструмент, период, риск и актуальность данных.\n'
 'Диагностика без торговли: START_BRIDGE_V10_0.bat --check или --diagnose.\n'
 'Режим PINNED_V1: один закреплённый план, новые события добавления, до 10 позиций или меньше по риску.\n'
 'Приём команды и её применение различаются; дождитесь подтверждения Bridge.\n'
 'REAL заблокирован. Требуется DEMO USD HEDGING; NETTING не поддерживается этим выпуском.\n'
 'Правила экспериментальные: доходность и точная будущая цена не гарантируются.\n').encode('utf-8')
 build=dict(source_sha=source_sha,version='10.9-EC1-R7.5',program_sha256={n:digest(b) for n,b in files.items()},state_included=False)
 files['BUILD.json']=json.dumps(build,indent=2,sort_keys=True).encode()
 out=Path(out);out.parent.mkdir(parents=True,exist_ok=True)
 with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
  for name,data in sorted(files.items()):z.writestr(PREFIX+name,data)
 return verify_bridge(out,source_sha)

def verify_bridge(path:Path,source_sha:str):
 with zipfile.ZipFile(path) as z:
  if z.testzip() is not None:raise ValueError('Broken ZIP')
  names=z.namelist()
  if len(names)!=len(set(names)):raise ValueError('Duplicate file')
  if any(not n.startswith(PREFIX) or '..' in PurePosixPath(n).parts or any(p in ('event_state','.venv','__pycache__') for p in PurePosixPath(n).parts) for n in names):raise ValueError('Unsafe payload')
  build=json.loads(z.read(PREFIX+'BUILD.json'))
  if build['source_sha']!=source_sha:raise ValueError('Source mismatch')
  manifest=build['program_sha256']
  if set(names)!={PREFIX+n for n in manifest}|{PREFIX+'BUILD.json'}:raise ValueError('Unexpected payload')
  for name,expected in manifest.items():
   if digest(z.read(PREFIX+name))!=expected:raise ValueError('Runtime checksum mismatch: '+name)
 return dict(source_sha=source_sha,sha256=digest(Path(path).read_bytes()),runtime_files=len(manifest),files=manifest)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--out',required=True);a=p.parse_args()
 print(json.dumps(package_bridge(Path(__file__).resolve().parents[1],Path(a.out),a.source),indent=2))
