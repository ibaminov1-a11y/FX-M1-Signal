"""Package original R7.4 plus a byte-identical local stdlib recovery copy."""
from pathlib import Path,PurePosixPath
import base64,hashlib,json,re,sys,zipfile

ORIGINAL='c6b11cbc98db06820ab9502cbada25c2256d16788e3ccceac5a214ed39181278'
APK='9cb2b370b8bc1a13c49b2c7b4da87aaf39a84e96da1231ff7b1f2cfcf8a0381d'

def sha(data):return hashlib.sha256(data).hexdigest()

def build(source,output):
    source=Path(source);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    assert sha(source.read_bytes())==ORIGINAL,'Unexpected original ZIP; do not blend versions'
    root=output/'FX-M1-Signal';assert not root.exists(),'Do not overwrite existing program'
    with zipfile.ZipFile(source) as z:
        assert z.testzip() is None
        for name in z.namelist():
            p=PurePosixPath(name)
            assert p.parts[0]=='FX-M1-Signal' and '..' not in p.parts and not p.is_absolute() and '\\' not in name
        z.extractall(output)
    manifest=json.loads((root/'PROGRAM_MANIFEST.json').read_text(encoding='utf-8'))
    for name,expected in manifest['files'].items():assert sha((root/name).read_bytes())==expected,name
    entries=[]
    for name in sorted(manifest['files']):
        if name.startswith('Runtime/Lib/') and name.endswith('.pyc') and '/site-packages/' not in name:
            assert re.fullmatch(r'Runtime/Lib/[A-Za-z0-9_./-]+\.pyc',name)
            data=(root/name).read_bytes()
            entries.append(dict(path=name,sha256=sha(data),size=len(data),data=base64.b64encode(data).decode('ascii')))
    assert len(entries)==533
    payload=json.dumps(dict(format='R74_STDLIB_RECOVERY_V1',files=entries),separators=(',',':'),ensure_ascii=True).encode('ascii')
    (root/'Runtime/stdlib_recovery.json').write_bytes(payload)
    template=(Path(__file__).parent/'runtime_repair.ps1').read_text(encoding='utf-8-sig')
    template=template.replace('__RESERVE_SHA256__',sha(payload)).replace('__FILE_COUNT__',str(len(entries)))
    assert '__RESERVE_' not in template
    (root/'Runtime/runtime_repair.ps1').write_bytes(template.replace('\n','\r\n').encode('utf-8-sig'))
    starts=[root/'START.cmd']+sorted((root/'mt5_bridge').glob('*.cmd'))+sorted((root/'mt5_bridge').glob('*.bat'))
    assert len(starts)==10
    for file in starts:
        text=file.read_text(encoding='utf-8-sig');prefix='' if file.parent==root else '..\\'
        before='pushd "%~dp0'+prefix+'"'
        assert text.count(before)==1
        preflight=('"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" '
                   '-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass '
                   '-File "%~dp0'+prefix+'Runtime\\runtime_repair.ps1"\n'
                   'if errorlevel 1 goto failed\n')
        text=text.replace(before,preflight+before)
        text=text.replace('FULL PROJECT / R7.4','FULL PROJECT / R7.4 - LIBRARY FIX')
        text=text.replace('FXM1_R74_COMPLETE_PROJECT.zip','FXM1_R74_COMPLETE_PROJECT_FIXED.zip')
        file.write_bytes(text.replace('\n','\r\n').encode('utf-8'))
    instruction=root/'INSTRUCTION_RU.txt'
    previous=instruction.read_text(encoding='utf-8-sig')
    note=('ИСПРАВЛЕНИЕ УПАКОВКИ БИБЛИОТЕК\n'
          'Это тот же R7.4 с прежним APK, не RC1 и не новая стратегия.\n'
          'START.cmd сначала проверяет стандартную библиотеку Python. Если файлы .pyc\n'
          'отсутствуют или отличаются, он восстанавливает точные исходные байты\n'
          'из проверенной копии внутри Runtime. Это выполняется до запуска Python,\n'
          'в том числе для модулей, нужных самому интерпретатору при старте.\n'
          'Это не загрузчик из Интернета. pip, старые папки и ручное копирование не нужны.\n'
          'Общая проверка целостности не отключена. Иные файлы автоматически не заменяются.\n'
          'Антивирус и защиту Windows отключать не нужно; права администратора не нужны.\n'
          'PowerShell вызывается только для этой локальной проверки; системная политика\n'
          'не меняется. База и ключ по прежнему пути LOCALAPPDATA сохраняются.\n\n')
    instruction.write_bytes((note+previous).replace('\n','\r\n').encode('utf-8-sig'))
    assert sha((root/'FXM1_R7_4.apk').read_bytes())==APK
    unchanged=[]
    for name,expected in manifest['files'].items():
        if (name.startswith('mt5_bridge/') and name.endswith('.py')) or name.startswith('app/'):
            assert sha((root/name).read_bytes())==expected,name
            unchanged.append(name)
    manifest['packaging_fix']='R74_STDLIB_RECOVERY_V1'
    manifest['files']={p.relative_to(root).as_posix():sha(p.read_bytes()) for p in sorted(root.rglob('*')) if p.is_file() and p.name!='PROGRAM_MANIFEST.json'}
    (root/'PROGRAM_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    target=output/'FXM1_R74_COMPLETE_PROJECT_FIXED.zip'
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(root.rglob('*')):
            if not p.is_file():continue
            assert p.suffix.lower() not in ('.zip','.xz','.whl','.7z','.rar','.ttf','.otf','.woff','.woff2'),p
            info=zipfile.ZipInfo(p.relative_to(output).as_posix(),date_time=(2026,10,13,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16
            z.writestr(info,p.read_bytes())
    with zipfile.ZipFile(target) as z:
        assert z.testzip() is None
        for name,expected in manifest['files'].items():assert sha(z.read('FX-M1-Signal/'+name))==expected,name
    print(json.dumps(dict(ok=True,archive=str(target),archive_sha256=sha(target.read_bytes()),bytes=target.stat().st_size,
        original_archive_sha256=ORIGINAL,stdlib_files=len(entries),reserve_sha256=sha(payload),start_aliases=len(starts),
        product_files_unchanged=len(unchanged),apk_sha256=APK,product_changed=False,state_changed=False,no_nested_archives=True),indent=2))

if __name__=='__main__':build(*sys.argv[1:])
