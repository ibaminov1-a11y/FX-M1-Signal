"""Repackage the previously verified runtime: one folder, one launcher, no ZIP inside.
Does not modify trading sources, credentials, or any user's state.
"""
from pathlib import Path, PurePosixPath
import hashlib, io, json, sys, zipfile

OLD_SHA='f6d5c361968dc093253e2b36760d49ca9e28c188553bcc18b733560df1da8a13'
ROOT_NAME='FXM1_R74_READY'
ARCHIVE='FXM1_R74_ONE_FOLDER.zip'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def safe_name(name):
    p=PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or '\\' in name:
        raise ValueError('Unsafe archive member')
    return p


def build(source, output):
    source=Path(source);output=Path(output)
    if sha(source.read_bytes())!=OLD_SHA:
        raise ValueError('Unexpected original recovery package')
    folder=output/ROOT_NAME
    folder.mkdir(parents=True,exist_ok=False)
    system=folder/'system';system.mkdir()
    with zipfile.ZipFile(source) as old:
        prefix='FXM1_R74_RESTORE/'
        metadata=json.loads(old.read(prefix+'PROGRAM_MANIFEST.json'))
        for name,digest in metadata['files'].items():
            if sha(old.read(prefix+name))!=digest:
                raise ValueError('Original package checksum mismatch: '+name)
        for name in old.namelist():
            if name.endswith('/'):
                continue
            if not name.startswith(prefix):
                raise ValueError('Unexpected package root')
            rel=name[len(prefix):];p=safe_name(rel)
            if not (rel.startswith(('Runtime/','mt5_bridge/')) or rel in ('restore_launcher.py','DEPENDENCIES.json')):
                continue
            if p.suffix.lower() in ('.zip','.whl','.gz','.tar','.7z','.rar','.bat','.cmd','.ps1'):
                continue
            target=system.joinpath(*p.parts);target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(old.read(name))
        # Expand the standard library, preserving compiled module names/bytes.
        lib=system/'Runtime/Lib';lib.mkdir(exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(old.read(prefix+'Runtime/python313.zip'))) as std:
            for name in std.namelist():
                if name.endswith('/'):
                    continue
                p=safe_name(name)
                if p.suffix.lower() in ('.bat','.cmd','.ps1','.zip','.whl','.gz','.7z','.rar','.tar'):
                    continue
                target=lib.joinpath(*p.parts)
                target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(std.read(name))
        (system/'Runtime/python313._pth').write_bytes(b'Lib\r\n.\r\nLib/site-packages\r\nimport site\r\n')
        unchanged={name:digest for name,digest in metadata['files'].items() if name.startswith('mt5_bridge/') or name=='restore_launcher.py'}
        for name,digest in unchanged.items():
            if sha((system/name).read_bytes())!=digest:
                raise ValueError('Trading source or recovery guard changed: '+name)
    start='\r\n'.join([
        '@echo off','setlocal DisableDelayedExpansion','chcp 65001 >nul',
        'title FXM1 R7.4 - START',
        'echo ============================================================',
        'echo FXM1 R7.4 - ONE FOLDER / ОДНА ПАПКА',
        'echo Папка: "%~dp0"',
        'echo Проверка встроенного Python и библиотек...',
        'echo ============================================================',
        'if not exist "%~dp0system\\Runtime\\python.exe" goto missing',
        'if not exist "%~dp0system\\restore_launcher.py" goto missing',
        'pushd "%~dp0system"','if errorlevel 1 goto failed',
        '"%~dp0system\\Runtime\\python.exe" -I -B -u -X utf8 "%~dp0system\\restore_launcher.py" %*',
        'set "RESULT=%ERRORLEVEL%"','popd',
        'if "%RESULT%"=="0" goto done',
        'echo.','echo Запуск остановлен. Причина указана выше. Файлы состояния не удаляйте.',
        'goto done',':missing',
        'echo Извлечена не вся папка: рядом со START.cmd должна быть папка system.',
        'echo Извлеките FXM1_R74_ONE_FOLDER.zip целиком. Ничего устанавливать не надо.',
        ':failed','set "RESULT=1"',':done',
        'if not "%R7_NO_PAUSE%"=="1" pause','exit /b %RESULT%',''])
    (folder/'START.cmd').write_bytes(start.encode('utf-8'))
    instructions='''FXM1 R7.4 — ОДНА ПАПКА, ОДИН ЗАПУСК

1. Извлеките папку FXM1_R74_READY целиком в любое обычное доступное место.
2. Откройте MT5 на компьютере и нужный счёт.
3. Нажмите START.cmd. Больше ничего распаковывать, устанавливать или переносить не нужно.

system — готовые программные файлы. Внутрь заходить не нужно.
Python и библиотеки уже включены. Старые .venv и папки Bridge не нужны.
Приложение R7.4 на телефоне оставьте как есть.
В нём укажите адрес сервера и ключ из окна Bridge. Ключ никому не отправляйте.
После удаления старых данных может потребоваться новый ключ; пароль MT5 не меняется.
Телефон и компьютер — в одной доверенной локальной сети. Порт в Интернет не открывайте.

Не запускайте сразу несколько Bridge. AUTO включается отдельно в приложении.
R7.4 поддерживает DEMO / USD / HEDGING; торговая логика и ограничения не изменены.
При совершенно новой базе запуск останавливается, если на счёте есть позиции/ордера:
программа сама ничего не закрывает и не принимает старые позиции без их истории.
Если локальная база уже создавалась автономным R7.4, она и ключ сохраняются.
Хранилище автоматически: %LOCALAPPDATA%\\FXM1\\R74-Recovery\\event_state
Старые удалённые ключи и внутренние планы не восстанавливаются из GitHub.
Эта папка не включает исходники в ZIP, другие установщики или вложенные архивы.
'''
    (folder/'INSTRUCTION_RU.txt').write_bytes(instructions.replace('\n','\r\n').encode('utf-8-sig'))
    files={p.relative_to(system).as_posix():sha(p.read_bytes()) for p in sorted(system.rglob('*')) if p.is_file()}
    metadata['files']=files
    (system/'PROGRAM_MANIFEST.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    archive=output/ARCHIVE
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(folder.rglob('*')):
            if p.is_file():
                z.write(p,ROOT_NAME+'/'+p.relative_to(folder).as_posix())
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
    return dict(package=str(archive),archive_sha256=sha(archive.read_bytes()),archive_bytes=archive.stat().st_size,
                product_sha=metadata['product_sha'],unchanged_program_files=unchanged,
                only_entrypoint='START.cmd',old_environment_required=False,nested_archives=0,
                standard_library_unpacked=True,state_migration=False,trading_changes=False)

if __name__=='__main__':
    print(json.dumps(build(sys.argv[1],sys.argv[2]),ensure_ascii=False,indent=2))
