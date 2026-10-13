"""Repackage original release; never change trading modules or APK."""
from pathlib import Path
import base64,hashlib,json,zipfile,sys

def sha(b):return hashlib.sha256(b).hexdigest()
def build(original,out):
 original=Path(original);out=Path(out);out.mkdir(parents=True,exist_ok=True)
 assert sha(original.read_bytes())=='91ed294cf92fb2a58326cf838eda3a2d1e293ea22abecaca903c55ecb376ba16'
 with zipfile.ZipFile(original) as z:
  assert z.testzip() is None
  data={n[len('FX-M1-Signal/'):]:z.read(n) for n in z.namelist() if not n.endswith('/')}
 manifest=json.loads(data['PROGRAM_MANIFEST.json'])
 assert all(sha(data[n])==h for n,h in manifest['files'].items())
 product={n:sha(b) for n,b in data.items() if n.startswith('mt5_bridge/') and n.endswith('.py')}
 apk=sha(data['FXM1_R7_4.apk'])
 originals={n:dict(size=len(b),data=base64.b64encode(b).decode('ascii')) for n,b in data.items()
            if n.endswith('.py') and (n.startswith('mt5_bridge/') or n.startswith('Runtime/Lib/site-packages/'))}
 payload=json.dumps(dict(format='R74_ORIGINAL_PYTHON_SOURCES_V1',files=originals),ensure_ascii=True,separators=(',',':')).encode('utf-8')
 data['Runtime/program_recovery.json']=payload
 block=(Path(__file__).parent/'verifier_block.txt').read_text(encoding='utf-8').replace('@RESERVE_SHA@',sha(payload))
 launcher=data['restore_launcher.py'].decode('utf-8').replace('\r\n','\n')
 start=launcher.index('def verify_package(root):');end=launcher.index('\ndef state_mode(state):',start)
 launcher=launcher[:start]+block+'\n\n'+launcher[end:]
 old="root=Path(__file__).resolve().parent;paths=resolve_runtime(root)\n    verify_package(root)"
 assert old in launcher
 launcher=launcher.replace(old,"root=Path(__file__).resolve().parent\n    verify_package(root)\n    paths=resolve_runtime(root)")
 data['restore_launcher.py']=launcher.replace('\r\n','\n').encode('utf-8')
 for n in list(data):
  if n=='START.cmd' or (n.startswith('mt5_bridge/') and n.endswith(('.bat','.cmd'))):
   text=data[n].decode('utf-8').replace(' - LIBRARY FIX',' - PACKAGE RECOVERY')
   text=text.replace('FXM1_R74_COMPLETE_PROJECT_FIXED.zip','FXM1_R74_FULL_PROJECT_RECOVER.zip')
   data[n]=text.replace('\r\n','\n').replace('\n','\r\n').encode('utf-8')
 info='''R7.4 — ПОЛНЫЙ ПРОЕКТ / PACKAGE RECOVERY

Извлеките папку FX-M1-Signal целиком в отдельное место. Откройте установленный
MetaTrader 5, закройте другие Bridge, запустите START.cmd. APK R7.4 прежний.
Python и библиотеки уже включены. Внутренних ZIP для ручной распаковки нет.
Не переносите отдельные файлы между разными версиями проекта.

Перед запуском проверяются стандартная библиотека Python и Python-код Bridge
и зависимостей. Отсутствующие/изменённые исходники возвращаются к исходному R7.4
из закреплённой контрольной суммой копии. Прежние изменённые исходники сохраняются
как Runtime/repair_backups/.../*.before; они не импортируются.
Файл PACKAGE_CHECK.json записывает сразу все найденные отличия, хэши и результат.
DLL/EXE/PYD, проверяющий код и недоступные файлы не восстанавливаются автоматически.
Защиту Windows не отключайте. Если проверка снова остановится, пришлите PACKAGE_CHECK.json
(это перечень файлов и хэшей; он не содержит ключ подключения).

Данные и ключ находятся отдельно: %LOCALAPPDATA%\\FXM1\\R74-Recovery\\event_state.
Они не удаляются и не заменяются восстановлением программных файлов.
При первом запуске новой базы требуется счёт без позиций/отложенных ордеров.
Существующие сделки программа сама не закрывает. AUTO OFF при запуске.
Ограничения R7.4 неизменны: DEMO USD HEDGING. REAL не разблокирован.
Торговый код и APK не менялись; прибыльность данным восстановлением не доказана.
'''
 data['INSTRUCTION_RU.txt']=b'\xef\xbb\xbf'+info.replace('\n','\r\n').encode('utf-8')
 manifest['packaging_fix']='ORIGINAL_R74_PYTHON_SOURCE_RECOVERY_V1'
 manifest['files']={n:sha(b) for n,b in sorted(data.items()) if n!='PROGRAM_MANIFEST.json'}
 data['PROGRAM_MANIFEST.json']=json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf-8')
 assert all(sha(data[n])==h for n,h in product.items())
 assert sha(data['FXM1_R7_4.apk'])==apk
 root=out/'FX-M1-Signal'
 for n,b in data.items():
  p=root/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
 archive=out/'FXM1_R74_FULL_PROJECT_RECOVER.zip'
 with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
  for n,b in sorted(data.items()):
   i=zipfile.ZipInfo('FX-M1-Signal/'+n,date_time=(2026,10,13,0,0,0));i.compress_type=zipfile.ZIP_DEFLATED;i.external_attr=0o100644<<16;z.writestr(i,b)
 with zipfile.ZipFile(archive) as z:
  assert z.testzip() is None
  for n,h in manifest['files'].items():assert sha(z.read('FX-M1-Signal/'+n))==h,n
  assert not any(n.lower().endswith(('.zip','.whl','.rar','.7z','.xz')) for n in z.namelist())
 result=dict(archive=str(archive),sha256=sha(archive.read_bytes()),bytes=archive.stat().st_size,
             recoverable_sources=len(originals),trading_modules_unchanged=len(product),apk_sha256=apk,
             file_count=len(data),state_touched=False)
 (out/'BUILD_RESULT.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
if __name__=='__main__':build(*sys.argv[1:])
