"""Merge verified portable R7.4, unchanged R7.4.2 APK and embedded clock startup.
The account is a local personalization argument; never committed to public sources.
"""
from pathlib import Path, PurePosixPath
import hashlib, io, json, re, sys, zipfile

PREFIX='FX-M1-Signal/'
MARKER='\n#R74_PY_BEGIN\n'
def sha(data):return hashlib.sha256(data).hexdigest()

def make(base, android, output, account='123@DEMO'):
    base=Path(base);android=Path(android);output=Path(output)
    with zipfile.ZipFile(base) as z:
        assert z.testzip() is None
        rows={n[len(PREFIX):]:z.read(n) for n in z.namelist() if n.startswith(PREFIX) and not n.endswith('/')}
    old_manifest=json.loads(rows['PROGRAM_MANIFEST.json'])
    assert all(sha(rows[n])==digest for n,digest in old_manifest['files'].items()),'BASE_CHECKSUM'
    with zipfile.ZipFile(android) as z:
        identity=json.loads(z.read('IDENTITY.json'));apk=z.read('app.apk');appsource=z.read('SOURCE.zip')
    assert identity['version_code']==935 and not identity['bridge_changed']
    assert sha(apk)==identity['apk_sha256']
    with zipfile.ZipFile(io.BytesIO(appsource)) as z:
        new_app={n:z.read(n) for n in z.namelist() if n.startswith('app/') and not n.endswith('/')}
        for name,data in rows.items():
            if name.startswith('mt5_bridge/') and name.endswith('.py'):
                assert data==z.read(name),'APP_SOURCE_BRIDGE_MISMATCH: '+name
    for name in list(rows):
        if name.startswith('app/') or name=='FXM1_R7_4.apk':del rows[name]
    rows.update(new_app);rows['FXM1_R7_4_2_FORECAST.apk']=apk
    source_dir=Path(__file__).parent
    for name in ('startup_clock.py','test_startup_clock.py','build_bundle.py'):
        rows['tools/r74_bulk/'+name]=(source_dir/name).read_bytes()
    if not re.fullmatch(r'\d+@[^\r\n\x00]+',account):raise ValueError('Invalid confirmed account')
    old=rows['START.cmd'].decode('utf-8-sig').replace('\r\n','\n')
    pre,py=old.split(MARKER,1)
    helper=(source_dir/'startup_clock.py').read_text(encoding='utf-8').replace('from __future__ import annotations\n','')
    py=py.replace('def main(argv=None):',helper+'\n\nCONFIRMED_CLOCK_ACCOUNT = '+repr(account)+'\n\ndef main(argv=None):',1)
    needle="        print('На телефоне укажите адрес и НОВЫЙ ключ из следующих строк. AUTO включается только вами в приложении.',flush=True)"
    assert py.count(needle)==1
    block='''        if details['key']==CONFIRMED_CLOCK_ACCOUNT:
            clock_guard=ProcessLock(paths.state_dir/'runtime.lock')
            try:
                clock_result=prepare_startup_clock(paths.state_dir,details['terminal'],CONFIRMED_CLOCK_ACCOUNT,180)
                _atomic_package_write(root/'STARTUP_CLOCK.json',json.dumps(clock_result,ensure_ascii=False,indent=2).encode('utf-8'))
            finally:clock_guard.close()
        else:
            print('Для этого счёта подтверждённая преднастройка +180 минут не применяется. Используется существующая настройка либо исходные метки UTC.',flush=True)
        if mode=='NEW':
            print('Создан новый ключ; укажите его и адрес сервера в приложении.',flush=True)
        else:
            print('Существующая база и ключ сохранены. Менять ключ в приложении не нужно.',flush=True)
'''
    py=py.replace(needle,block.rstrip())
    oldhash=sha(old.split(MARKER,1)[1].encode('utf-8'))
    assert oldhash in pre,'EMBEDDED_HASH_NOT_FOUND'
    pre=pre.replace(oldhash,sha(py.encode('utf-8')))
    pre=pre.replace('FX-M1-Signal / R7.4 / INTEGRATED START','FX-M1-Signal / COMPLETE 20.10 / BRIDGE R7.4 + APK R7.4.2')
    pre=pre.replace('Полный проект. Запуск встроен в START.cmd.','Полный комплект. Проверка времени встроена в START.cmd.')
    rows['START.cmd']=(pre+MARKER+py).replace('\n','\r\n').encode('utf-8')
    instruction='''ПОЛНЫЙ КОМПЛЕКТ 20.10: Bridge R7.4 + APK R7.4.2 Forecast

1. Отключите AUTO. Обновляйте без открытых позиций, отложенных ордеров и активной серии.
   Закройте старое окно Bridge. Сам MT5 оставьте открытым.
2. Извлеките весь ZIP в отдельную папку, не поверх прежних версий.
3. В папке FX-M1-Signal запустите START.cmd. Других установщиков запускать не надо.
   Для проверенного счёта настройка +180 минут применяется внутри этого запуска.
   До 45 секунд ожидаются 3 разные свежие котировки; повтор одной котировки не ошибка.
   После сохранения настройки Bridge продолжает запуск сам, повторный запуск не нужен.
4. APK на телефоне уже R7.4.2 — повторно ставить его не надо. Он включён в папку для
   восстановления. Это прежний подписанный APK (935), не новый торговый алгоритм.
   В приложении включите мониторинг и нажмите ПРОГНОЗ, затем ПОСЛЕДНИЙ.
   AUTO для проверки прогноза не требуется. После проверки настройте AUTO самостоятельно.

База и ключ сохранены по адресу:
%LOCALAPPDATA%\\FXM1\\R74-Recovery\\event_state
Не удаляйте эту папку. Запуск не меняет часы Windows, ключ, торговый лот или лимиты риска.
Существующая другая настройка часов не заменяется автоматически. Для другого счёта
подтверждённая преднастройка не применяется. При реальном отсутствии свежих котировок
защита не обходится; создание новой настройки останавливается с конкретной причиной.
Время MT5 нормализуется существующим адаптером одинаково для тиков, свечей и истории.
Исходные метки остаются в диагностике. Брокерский переход на другое смещение потребует
подтверждения новой настройки — автоматического угадывания часового пояса нет.

Runtime, Python, библиотеки, Bridge, app, docs, tests и tools включены.
Нет загрузки зависимостей и установки Python при запуске. Вложенные архивы не требуются.
CHECK_TIME и FIX_MT5_TIME из предыдущих сообщений для этой установки не нужны.

Ограничения Bridge: DEMO USD HEDGING. REAL не разблокирован.
Торговые правила, качество прогнозной модели и количество входов этим комплектом не
изменены. Он объединяет исправленный запуск и отображение прогноза, а не гарантирует
прибыли. Открытие позиции требует отдельного подтверждённого сигнала и доступного риска.
При неполной локальной базе нельзя создавать новую взамен неё: состояние сохраняется.
Файл PACKAGE_CHECK.json содержит проверку полноты. STARTUP_CLOCK.json — итог настройки.
'''
    rows['INSTRUCTION_RU.txt']=instruction.replace('\n','\r\n').encode('utf-8-sig')
    manifest=dict(old_manifest)
    manifest.update(bundle='R74_COMPLETE_CLOCK_20261020',android_source=identity['source'],apk_sha256=identity['apk_sha256'],
                    embedded_launcher_sha256=sha(py.encode('utf-8')),clock_policy='EXPLICIT_ACCOUNT_ONLY_180',trading_changed=False)
    manifest['files']={n:sha(data) for n,data in sorted(rows.items()) if n!='PROGRAM_MANIFEST.json'}
    rows['PROGRAM_MANIFEST.json']=json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf-8')
    for name,digest in old_manifest['files'].items():
        if name.startswith('mt5_bridge/') and name.endswith('.py'):assert sha(rows[name])==digest,name
        if name.startswith('Runtime/'):assert sha(rows[name])==digest,name
    assert not any(n.lower().endswith(('.zip','.rar','.7z','.tar','.gz')) for n in rows)
    output.parent.mkdir(exist_ok=True,parents=True)
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        dirs=set()
        for name in rows:
            for parent in PurePosixPath(PREFIX+name).parents:
                if str(parent)!='.':dirs.add(parent.as_posix()+'/')
        for name in sorted(dirs):
            i=zipfile.ZipInfo(name,date_time=(2026,10,20,6,0,0));i.create_system=0;i.external_attr=0x10;z.writestr(i,b'')
        for name,data in sorted(rows.items()):
            i=zipfile.ZipInfo(PREFIX+name,date_time=(2026,10,20,6,0,0));i.create_system=0;i.external_attr=0x20;i.compress_type=zipfile.ZIP_DEFLATED;z.writestr(i,data)
    return dict(bundle_sha256=sha(output.read_bytes()),size=output.stat().st_size,apk_sha256=sha(apk),android_source=identity['source'],
                files=len(rows),bridge_changed=False,embedded_launcher_sha256=sha(py.encode('utf-8')))
if __name__=='__main__':
    result=make(*sys.argv[1:]);print(json.dumps(result,indent=2));Path(str(sys.argv[3])+'.json').write_text(json.dumps(result,indent=2))
