"""Run on Windows CI; downloads official runtime/wheels once for offline distribution."""
from pathlib import Path
import hashlib, json, os, shutil, subprocess, sys, tempfile, urllib.request, zipfile

BASE='796c54d93f212aa9424670c72aac5d56bbae1081'
PRODUCT='5f6f47f303c337bfd57acec9958cb5ed910d375f'
PYTHON_URL='https://www.python.org/ftp/python/3.13.15/python-3.13.15-embed-amd64.zip'
PYTHON_SHA='d1f04d990aee1253d8569e8e5104e30fa9f5fa830899f14843448872d936a2cf'
APK_SHA='9cb2b370b8bc1a13c49b2c7b4da87aaf39a84e96da1231ff7b1f2cfcf8a0381d'
ROOT=Path.cwd();OUT=ROOT/'dist';PACKAGE=OUT/'FXM1_R74_RESTORE';EVIDENCE=ROOT/'evidence'
REQ=['Flask==3.1.2','MetaTrader5==5.0.6090','numpy==2.2.6','colorama==0.4.6']

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def run(args,**kw):return subprocess.run([str(x) for x in args],check=True,**kw)
def download(url,destination):
    with urllib.request.urlopen(url,timeout=120) as r:Path(destination).write_bytes(r.read())
def write(p,text):Path(p).write_text(text,encoding='utf-8')

OUT.mkdir(exist_ok=True);EVIDENCE.mkdir(exist_ok=True)
if PACKAGE.exists():raise RuntimeError('Fresh build directory required')
PACKAGE.mkdir()
# Official app-local Python, no dependency on py.exe, PATH or an old .venv.
runtime=PACKAGE/'Runtime';runtime.mkdir()
archive=OUT/'python-embed.zip';download(PYTHON_URL,archive)
assert sha(archive)==PYTHON_SHA,'Official Python checksum mismatch'
with zipfile.ZipFile(archive) as z:z.extractall(runtime)
write(runtime/'python313._pth','python313.zip\n.\nLib/site-packages\nimport site\n')
wheels=OUT/'wheels';wheels.mkdir()
run([sys.executable,'-m','pip','download','--only-binary=:all:','--dest',wheels,'--python-version','3.13','--platform','win_amd64','--implementation','cp','--abi','cp313',*REQ])
whls=sorted(wheels.glob('*.whl'))
wheel_meta=[]
for whl in whls:
    with zipfile.ZipFile(whl) as z:
        from email.parser import BytesParser
        meta=BytesParser().parsebytes(z.read(next(n for n in z.namelist() if n.endswith('.dist-info/METADATA'))))
    name,version=meta['Name'],meta['Version']
    with urllib.request.urlopen(f'https://pypi.org/pypi/{name}/{version}/json',timeout=60) as r:data=json.load(r)
    found=next(row for row in data['urls'] if row['filename']==whl.name)
    assert sha(whl)==found['digests']['sha256']
    wheel_meta.append(dict(name=name,version=version,file=whl.name,sha256=sha(whl),url=found['url']))
run([sys.executable,'-m','pip','install','--no-index','--no-deps','--no-compile','--target',runtime/'Lib/site-packages',*whls])
# Exact original program sources, not RC1 and not the legacy dependency-reusing launcher.
program=PACKAGE/'mt5_bridge';program.mkdir()
source_map={}
for p in sorted((ROOT/'mt5_bridge/event_core').rglob('*.py')):
    relative=p.relative_to(ROOT);old=subprocess.check_output(['git','show',f'{PRODUCT}:{relative.as_posix()}'])
    assert p.read_bytes()==old,'Trading code changed: '+str(relative)
    target=program/p.relative_to(ROOT/'mt5_bridge');target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(old)
    source_map[str(target.relative_to(PACKAGE).as_posix())]=hashlib.sha256(old).hexdigest()
for name in ['bridge_v10_0.py','bridge_startup.py','requirements_event.txt','export_ticks.py','research_config.json','CHECK_BROKER_CLOCK.py']:
    raw=subprocess.check_output(['git','show',f'{PRODUCT}:mt5_bridge/{name}'])
    (program/name).write_bytes(raw);source_map['mt5_bridge/'+name]=hashlib.sha256(raw).hexdigest()
shutil.copy2(ROOT/'tools/r74_restore/restore_launcher.py',PACKAGE/'restore_launcher.py')
# Same signed APK as R7.4; no signing key is read or included.
apk=ROOT/'previous-release/FXM1_R7_4.apk';assert sha(apk)==APK_SHA
shutil.copy2(apk,PACKAGE/apk.name)
# Full original repository snapshot, including Android sources and tests.
run(['git','archive','--format=zip','--output',PACKAGE/'SOURCE_GITHUB_R74.zip',BASE])
with zipfile.ZipFile(PACKAGE/'SOURCE_GITHUB_R74.zip') as z:
    assert not any(n.lower().endswith(('.ttf','.otf','.woff','.woff2','.jks','.p12','.sqlite3')) for n in z.namelist())
for name,option in [('START_BRIDGE_V10_0.bat',''),('CHECK_BRIDGE.cmd','--check'),('CHECK_MT5.cmd','--diagnose')]:
    text='\r\n'.join(['@echo off','setlocal DisableDelayedExpansion','chcp 65001 >nul','pushd "%~dp0"',
        'if errorlevel 1 goto failed','if not exist "%~dp0Runtime\\python.exe" goto missing',
        '"%~dp0Runtime\\python.exe" -I -B -X utf8 "%~dp0restore_launcher.py" '+option+' %*',
        'set "RESULT=%ERRORLEVEL%"','popd','if not "%R7_NO_PAUSE%"=="1" pause','exit /b %RESULT%',
        ':missing','echo Runtime/python.exe missing. Extract the entire ZIP folder.',':failed',
        'if not "%R7_NO_PAUSE%"=="1" pause','exit /b 1',''])
    (PACKAGE/name).write_bytes(text.encode('utf-8'))
readme='''R7.4 — ПОЛНЫЙ КОМПЛЕКТ ПОСЛЕ УДАЛЕНИЯ СТАРОЙ ПАПКИ
Это исходная торговая логика R7.4, НЕ R7.4.1 RC1. Изменён только способ запуска.

1. Распакуйте папку FXM1_R74_RESTORE целиком, например в C:\\FXM1_R74_RESTORE.
   Не запускайте прямо из архива. OneDrive и Program Files лучше не использовать.
2. Откройте на компьютере MT5 и нужный DEMO USD HEDGING счёт.
   На ПЕРВОМ запуске нового состояния позиции и ожидающие ордера должны отсутствовать.
   Иначе программа остановится без закрытия или изменения позиций — сначала проверьте их в MT5.
3. Запустите START_BRIDGE_V10_0.bat в корне папки. Старый Python, .venv и установщик НЕ нужны.
4. На телефоне оставьте существующее приложение R7.4. APK внутри нужен только если приложение удалено.
   Удалять приложение перед установкой APK не надо. В «ИЗМЕНИТЬ СЕРВЕР» укажите адрес из консоли.
   В «КЛЮЧ BRIDGE» замените старый ключ НОВЫМ ключом из консоли. Ключ никому не отправляйте.
5. Телефон и компьютер должны быть в доверенной локальной сети. При запросе брандмауэра
   разрешите Python только для частной сети. Не отключайте защиту и не открывайте порт 8000 в Интернет.
6. Проверьте номер счёта, инструмент, период, NORMAL/SCALP, риск и лот. AUTO после запуска выключен.
   Включение AUTO — отдельное ваше действие в телефоне; запускатор никогда сам его не включает.

ЧТО ВНУТРИ
Runtime — собственный 64-битный Python и все библиотеки. Не зависит от удалённой .venv.
mt5_bridge — полный рабочий код R7.4. Не переносите туда файлы RC1.
FXM1_R7_4.apk — тот же APK версии 934 с прежней подписью.
SOURCE_GITHUB_R74.zip — полный снимок исходников последнего commit ветки R7.4 на дату сборки.
CHECK_BRIDGE.cmd — проверка комплектности и импортов без подключения к MT5.
CHECK_MT5.cmd — чтение состояния терминала и диагностика времени, без отправки ордеров.

УДАЛЁННЫЕ ДАННЫЕ
Из GitHub восстановлен код, но НЕ удалённые личные файлы состояния, ключ и локальный журнал.
При первом разрешённом запуске создаются новая база и новый ключ с AUTO OFF.
Они сохраняются ВНЕ программной папки:
%LOCALAPPDATA%\\FXM1\\R74-Recovery\\event_state
Открыть её можно через Win+R, вставив эту строку.
Следующие запуски используют ту же базу/ключ и НЕ обнуляют историю.
Не удаляйте этот каталог. Резервную копию делайте только при закрытом Bridge, целиком с WAL/SHM.
История сделок, которую вернёт MT5 по тому же счёту, снова может загрузиться; архивные планы,
исходные причины сделок и локальные настройки отсутствуют без старой резервной копии.
Настройка broker-clock.json, если она была, тоже не восстановлена. Смещение времени НЕ угадывается.
Если появится ошибка времени, сохраните результат CHECK_MT5.cmd; не редактируйте часы наугад.

ОГРАНИЧЕНИЯ
DEMO USD HEDGING, как в исходном R7.4. REAL и NETTING не разблокированы.
Это восстановление установки, а не новая стратегия и не обещание прибыли.
Исправление прокрутки Android и изменения из RC1 сюда не включены.
Предыдущую копию Bridge одновременно не запускайте.
Фактическое соединение с вашим MT5 и вашей локальной сетью проверяются уже на вашем компьютере.
'''
write(PACKAGE/'START_HERE_RU.txt',readme)
write(PACKAGE/'DEPENDENCIES.json',json.dumps(dict(python_url=PYTHON_URL,python_sha256=PYTHON_SHA,wheels=wheel_meta),indent=2))
write(EVIDENCE/'PRODUCT_SOURCE_MATCH.json',json.dumps(dict(product_sha=PRODUCT,repository_sha=BASE,files=source_map,apk_sha256=APK_SHA,trading_changes=False),indent=2))
# All package bytes covered; user-created state is deliberately stored outside this tree.
files={p.relative_to(PACKAGE).as_posix():sha(p) for p in sorted(PACKAGE.rglob('*')) if p.is_file()}
write(PACKAGE/'PROGRAM_MANIFEST.json',json.dumps(dict(product_sha=PRODUCT,repository_sha=BASE,files=files),ensure_ascii=False,indent=2))
print('PREPARED',PACKAGE)
