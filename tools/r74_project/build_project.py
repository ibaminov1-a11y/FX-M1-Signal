"""Restore the full GitHub project layout around the tested portable R7.4 runtime."""
from pathlib import Path, PurePosixPath
import hashlib, io, json, shutil, sys, zipfile, lzma
from check_project import inspect, SOURCE_SHA, APK_SHA

INSTRUCTION='''FX-M1-Signal — полный проект + готовый Bridge R7.4

ЗАПУСК
1. Извлеките всю папку FX-M1-Signal из ZIP в новое место, например в Загрузки.
   Не копируйте поверх другой установки и не переносите отдельные файлы.
2. Откройте установленный MetaTrader 5 на компьютере с нужным демосчётом.
3. Закройте другие окна Bridge. В этой папке дважды нажмите START.cmd.

Все исходники app, docs, tests, tools, .ci, .github и Gradle уже распакованы.
Runtime содержит Python x64 и необходимые библиотеки. Не устанавливайте Python,
не запускайте pip, старые INSTALL и BUILD для обычного запуска Bridge.
FXM1_R7_4.apk — готовое приложение для Android, не архив для извлечения.
Если R7.4 уже стоит на телефоне, переустанавливать его не надо.

КОД И ИСТОРИЯ
Торговое ядро — исходный R7.4, не R7.4.1 RC1. Правила торговли не изменены.
Поддержка исходного движка: только DEMO USD HEDGING. REAL остаётся заблокированным.
AUTO при запуске выключен. Ни сборщик, ни проверка комплекта не открывают сделки.
Новые локальные данные хранятся вне папки программы:
%LOCALAPPDATA%\\FXM1\\R74-Recovery\\event_state
Они сохраняются между версиями восстановления. Этот каталог не удаляйте.
Если база уже создана предыдущим RESTORE, её ключ сохраняется.
Если старая локальная база была удалена без копии, GitHub её не восстанавливает.
При новой базе нужны счёт без позиций и без отложенных ордеров. Если они есть,
запуск остановится, не закрывая их и не принимая под управление автоматически.
На телефоне укажите адрес Bridge и ключ, показанные в его окне. Пароль MT5 другой.
При запросе брандмауэра используйте только доверенную частную сеть; порт наружу не открывайте.

Для разработчика: BUILD_*.py и FIX_*.py сохранены как исходные файлы GitHub,
но для запуска они не нужны. Android Studio/SDK/Gradle в этот архив не входят:
готовый APK уже есть, самостоятельная пересборка Android — отдельная задача.
Старые BAT/CMD в mt5_bridge направлены на тот же встроенный запуск/диагностику;
их исходный текст без изменений сохранён в docs/original_launchers как TXT.
Старые транспортные части R5 из tools/r5delta распакованы в transport.json;
исходный apply_r5_delta.py сохранён как TXT, его рабочая копия читает JSON.
Никаких архивов исходников или библиотек внутри комплекта нет.
'''


def launcher(prefix='', default_args=''):
    text='''@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
title FX-M1-Signal - R7.4
echo ============================================================
echo FX-M1-Signal - FULL PROJECT / R7.4
echo Все компоненты в этой папке. Используется встроенный Python.
echo ============================================================
if not exist "%~dp0{p}Runtime\\python.exe" goto missing
if not exist "%~dp0{p}restore_launcher.py" goto missing
pushd "%~dp0{p}"
if errorlevel 1 goto failed
"%~dp0{p}Runtime\\python.exe" -I -B -u -X utf8 "%~dp0{p}restore_launcher.py" {args}%*
set "RESULT=%ERRORLEVEL%"
popd
if "%RESULT%"=="0" goto done
echo.
echo Запуск остановлен. Причина указана выше. Данные не удаляйте.
goto done
:missing
echo Извлечена не вся папка: нужны Runtime, mt5_bridge и restore_launcher.py.
echo Извлеките FXM1_R74_COMPLETE_PROJECT.zip целиком в новое место.
:failed
set "RESULT=1"
:done
if not "%R7_NO_PAUSE%"=="1" pause
exit /b %RESULT%
'''.format(p=prefix,args=(default_args+' ') if default_args else '')
    return text.replace('\n','\r\n').encode('utf-8')


def checked_members(z):
    for info in z.infolist():
        if info.is_dir():continue
        p=PurePosixPath(info.filename)
        if p.is_absolute() or '..' in p.parts or '\\' in info.filename:
            raise ValueError('Unsafe archive member: '+info.filename)
        yield info.filename,z.read(info.filename)


def build(one_folder, restore, output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    root=output/'FX-M1-Signal'
    if root.exists():raise FileExistsError('Do not overlay an existing project: '+str(root))
    root.mkdir()
    with zipfile.ZipFile(restore) as z:
        prefix='FXM1_R74_RESTORE/'
        source=z.read(prefix+'SOURCE_GITHUB_R74.zip');apk=z.read(prefix+'FXM1_R7_4.apk')
    assert hashlib.sha256(apk).hexdigest()==APK_SHA
    reference=output/'reference';reference.mkdir();(reference/'source.zip').write_bytes(source)
    forwarded=[]
    with zipfile.ZipFile(io.BytesIO(source)) as z:
        assert z.comment.decode()==SOURCE_SHA
        raw=lzma.decompress(b''.join(z.read(f'tools/r5delta/part{i:02d}.xz') for i in range(9)))
        assert len(raw)==185491
        for name,data in checked_members(z):
            if name.startswith('tools/r5delta/part') and name.endswith('.xz'):continue
            if name=='tools/apply_r5_delta.py':
                archived=root/'docs/original_launchers'/ (name+'.txt');archived.parent.mkdir(parents=True,exist_ok=True);archived.write_bytes(data)
                text=data.decode('utf-8');start=text.index("blob=b''.join");end=text.index('assert len(raw)==')
                text=text[:start]+"raw=(root/'tools/r5delta/transport.json').read_bytes()\nassert hashlib.sha256(raw).hexdigest()=="+repr(hashlib.sha256(raw).hexdigest())+"\n"+text[end:]
                data=text.encode('utf-8')
            target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
            if name.endswith(('.cmd','.bat')):
                archived=root/'docs/original_launchers'/ (name+'.txt')
                archived.parent.mkdir(parents=True,exist_ok=True);archived.write_bytes(data)
                depth=len(PurePosixPath(name).parts)-1
                option='--check' if PurePosixPath(name).name.startswith('INSTALL') else '--diagnose' if PurePosixPath(name).name.startswith('CHECK') else ''
                target.write_bytes(launcher('..\\'*depth,option));forwarded.append(name)
            else:target.write_bytes(data)
    target=root/'tools/r5delta/transport.json';target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    with zipfile.ZipFile(one_folder) as z:
        prefix='FXM1_R74_READY/system/'
        for name,data in checked_members(z):
            if not name.startswith(prefix):continue
            name=name[len(prefix):]
            if name=='PROGRAM_MANIFEST.json':continue
            target=root/name
            if name.startswith('mt5_bridge/'):
                assert target.is_file() and target.read_bytes()==data,'Product source mismatch: '+name
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    (root/'START.cmd').write_bytes(launcher())
    (root/'FXM1_R7_4.apk').write_bytes(apk)
    (root/'INSTRUCTION_RU.txt').write_bytes(INSTRUCTION.replace('\n','\r\n').encode('utf-8-sig'))
    manifest=dict(product_sha='5f6f47f303c337bfd57acec9958cb5ed910d375f',repository_sha=SOURCE_SHA,files={})
    for f in sorted(root.rglob('*')):
        if f.is_file():manifest['files'][f.relative_to(root).as_posix()]=hashlib.sha256(f.read_bytes()).hexdigest()
    (root/'PROGRAM_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    archive=output/'FXM1_R74_COMPLETE_PROJECT.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for f in sorted(root.rglob('*')):
            if f.is_file():
                info=zipfile.ZipInfo(f.relative_to(output).as_posix(),date_time=(2026,10,13,0,0,0))
                info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16
                z.writestr(info,f.read_bytes())
    result=inspect(archive,reference/'source.zip');assert result['ok'],result
    result.update(bytes=archive.stat().st_size,uncompressed_bytes=sum(f.stat().st_size for f in root.rglob('*') if f.is_file()),product_code_changed=False,apk_changed=False,account_state_replaced=False)
    return result

if __name__=='__main__':
    print(json.dumps(build(*sys.argv[1:]),ensure_ascii=False,indent=2))
