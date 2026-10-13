"""Merge the startup helpers into START.cmd; preserve original R7.4 trading bytes."""
from pathlib import Path, PurePosixPath
import hashlib, json, sys, zipfile

INPUT_SHA='5b998d9b72d7982ab83a81808939f4e4b2ae5189831fa2bde3c0873ba2eb5b6f'
PREFIX='FX-M1-Signal/'
PS_MARK='#R74_PS_BEGIN'
PY_MARK='#R74_PY_BEGIN'

HEADER=r'''@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
title FX-M1-Signal - R7.4
echo ============================================================
echo FX-M1-Signal / R7.4 / INTEGRATED START
echo Полный проект. Запуск встроен в START.cmd.
echo ============================================================
set "FXM1_START_FILE=%~f0"
set "FXM1_START_ARGS=%*"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$t=[IO.File]::ReadAllText($env:FXM1_START_FILE,[Text.Encoding]::UTF8).Replace([string][char]13,'');$m=[char]10+'#R74_PS_BEGIN'+[char]10;$e=[char]10+'#R74_PY_BEGIN'+[char]10;$s=$t.IndexOf($m)+$m.Length;$n=$t.IndexOf($e,$s);if($s -lt $m.Length -or $n -lt $s){Write-Output 'START_FILE_DAMAGED';exit 1};& ([scriptblock]::Create($t.Substring($s,$n-$s)))"
set "RESULT=%ERRORLEVEL%"
if "%RESULT%"=="0" goto done
echo.
echo Запуск остановлен. Причина и точный путь указаны выше. Данные не удаляйте.
:done
if not "%R7_NO_PAUSE%"=="1" pause
exit /b %RESULT%
'''

POWERSHELL=r'''$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$root=[IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($env:FXM1_START_FILE))
$process=$null
try {
    $nativeHashes=@{
__NATIVE_HASHES__
    }
    foreach ($relative in $nativeHashes.Keys) {
        $full=Join-Path $root $relative
        if (-not [IO.File]::Exists($full)) { throw ('MISSING_NATIVE: '+$full) }
        $entry=Get-Item -LiteralPath $full -Force
        if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw ('NATIVE_LINK_REFUSED: '+$full) }
        $actual=(Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $nativeHashes[$relative]) { throw ('NATIVE_HASH_MISMATCH: '+$full) }
    }
    # Embedded standard-library preflight, not a separately extracted PS1.
    & {
__REPAIR__
    }
    $text=[IO.File]::ReadAllText($env:FXM1_START_FILE,[Text.Encoding]::UTF8).Replace([string][char]13,'')
    $marker=[char]10+'#R74_PY_BEGIN'+[char]10
    $index=$text.IndexOf($marker)
    if ($index -lt 0) { throw 'EMBEDDED_LAUNCHER_MISSING' }
    $source=$text.Substring($index+$marker.Length)
    $bytes=[Text.Encoding]::UTF8.GetBytes($source)
    $hash=[Security.Cryptography.SHA256]::Create()
    try { $actual=([BitConverter]::ToString($hash.ComputeHash($bytes))).Replace('-','').ToLowerInvariant() }
    finally { $hash.Dispose() }
    if ($actual -ne '__SOURCE_HASH__') { throw 'EMBEDDED_LAUNCHER_HASH_MISMATCH' }
    $encoded=[Convert]::ToBase64String($bytes)
    # Only stdin is piped; stdout/stderr stay attached to the console.
    $driver=@"
import base64, ctypes, os, sys
__file__=os.path.abspath(os.environ['FXM1_START_FILE'])
shell=ctypes.WinDLL('shell32', use_last_error=True)
shell.CommandLineToArgvW.argtypes=[ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_int)]
shell.CommandLineToArgvW.restype=ctypes.POINTER(ctypes.c_wchar_p)
kernel=ctypes.WinDLL('kernel32', use_last_error=True)
kernel.LocalFree.argtypes=[ctypes.c_void_p]
kernel.LocalFree.restype=ctypes.c_void_p
count=ctypes.c_int()
args=shell.CommandLineToArgvW('fxm1 '+os.environ.get('FXM1_START_ARGS',''),ctypes.byref(count))
if not args: raise OSError(ctypes.get_last_error(), 'CommandLineToArgvW')
try: sys.argv=[__file__]+[args[i] for i in range(1,count.value)]
finally: kernel.LocalFree(ctypes.cast(args,ctypes.c_void_p))
exec(compile(base64.b64decode('$encoded'),'<R74 integrated launcher>','exec'),globals())
"@
    $info=[Diagnostics.ProcessStartInfo]::new()
    $info.FileName=Join-Path $root 'Runtime\python.exe'
    $info.Arguments='-I -B -u -X utf8 -'
    $info.WorkingDirectory=$root
    $info.UseShellExecute=$false
    $info.RedirectStandardInput=$true
    $process=[Diagnostics.Process]::new()
    $process.StartInfo=$info
    if (-not $process.Start()) { throw 'PYTHON_PROCESS_NOT_STARTED' }
    $process.StandardInput.Write($driver)
    $process.StandardInput.Close()
    $process.WaitForExit()
    exit $process.ExitCode
} catch {
    Write-Output ('START_ERROR: '+$_.Exception.Message)
    Write-Output ('Папка запуска: '+$root)
    Write-Output 'Состояние, ключ и торговые настройки не изменялись запускатором. Защиту Windows не отключайте.'
    exit 1
} finally {
    if ($null -ne $process) { $process.Dispose() }
}
'''

INSTRUCTION='''R7.4 — ПОЛНЫЙ ПРОЕКТ / INTEGRATED START

Извлеките всю папку FX-M1-Signal из этого ZIP. Ничего внутри дополнительно
распаковывать или устанавливать не требуется. Откройте установленный MT5,
закройте другие копии Bridge и запустите START.cmd в корне проекта.

Отдельный restore_launcher.py больше не нужен: его код находится внутри START.cmd.
Полный проект, встроенный Python и библиотеки находятся в этой же папке.
Торговый алгоритм R7.4 и APK не изменены. Приложение на телефоне переустанавливать
не нужно. После удаления прежнего ключа может потребоваться повторное сопряжение.

База и ключ: %LOCALAPPDATA%\\FXM1\\R74-Recovery\\event_state. Не удаляйте их.
Запуск не восстанавливает удалённую историю решений и не принимает неизвестные
открытые позиции под управление. При новой базе счёт должен быть без открытых
позиций и отложенных ордеров. AUTO включается явно в приложении.
Ограничения исходного R7.4: DEMO, USD, HEDGING. REAL не включён.

При отсутствующем или изменённом EXE/DLL выводится точный путь; такие файлы
не восстанавливаются в обход защиты Windows. Никаких загрузок из сети и pip
при запуске нет. Проверка файлов не отключена. Запуск на компьютере пользователя
и связь с его терминалом не подтверждаются тестами на отдельной Windows-машине.
'''

def sha(b):return hashlib.sha256(b).hexdigest()
def build(source, destination):
    source=Path(source);destination=Path(destination);destination.mkdir(exist_ok=True,parents=True)
    assert sha(source.read_bytes())==INPUT_SHA,'INPUT_IDENTITY'
    with zipfile.ZipFile(source) as z:
        assert z.testzip() is None
        rows={n[len(PREFIX):]:z.read(n) for n in z.namelist() if n.startswith(PREFIX) and not n.endswith('/')}
    manifest=json.loads(rows['PROGRAM_MANIFEST.json'])
    assert all(sha(rows[n])==h for n,h in manifest['files'].items()),'INPUT_MANIFEST'
    py=rows.pop('restore_launcher.py').decode('utf-8-sig').replace('\r\n','\n').rstrip('\n')+'\n'
    repair=rows.pop('Runtime/runtime_repair.ps1').decode('utf-8-sig').replace('\r\n','\n')
    assert repair.count('    exit 0')==1 and repair.count('    exit 1')==1
    repair=repair.replace('$root = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))',
                          '$root = [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($env:FXM1_START_FILE))')
    repair=repair.replace("Join-Path $PSScriptRoot 'stdlib_recovery.json'", "Join-Path (Join-Path $root 'Runtime') 'stdlib_recovery.json'")
    repair=repair.replace('    exit 0','    return').replace('    exit 1',"    throw 'RUNTIME_LIBRARY_PREPARATION_FAILED'")
    natives={n:sha(b) for n,b in rows.items() if n.startswith('Runtime/') and n.count('/')==1 and n.endswith(('.exe','.dll'))}
    hashes='\n'.join("        '"+n+"'='"+h+"'" for n,h in sorted(natives.items()))
    ps=POWERSHELL.replace('__NATIVE_HASHES__',hashes).replace('__REPAIR__',repair).replace('__SOURCE_HASH__',sha(py.encode('utf-8')))
    cmd=HEADER+'\n'+PS_MARK+'\n'+ps+'\n'+PY_MARK+'\n'+py
    rows['START.cmd']=cmd.replace('\n','\r\n').encode('utf-8')
    aliases=[]
    for name in rows:
        if name.startswith('mt5_bridge/') and name.count('/')==1 and name.endswith(('.cmd','.bat')):
            rows[name]=('@echo off\r\nsetlocal DisableDelayedExpansion\r\ncall "%~dp0..\\START.cmd" %*\r\nexit /b %ERRORLEVEL%\r\n').encode('utf-8')
            aliases.append(name)
    rows['INSTRUCTION_RU.txt']=INSTRUCTION.replace('\n','\r\n').encode('utf-8-sig')
    for n in ('restore_launcher.py','Runtime/runtime_repair.ps1'):manifest['files'].pop(n)
    for n in ['START.cmd','INSTRUCTION_RU.txt']+aliases:manifest['files'][n]=sha(rows[n])
    manifest['packaging_fix']='R74_INTEGRATED_START_V1'
    manifest['embedded_launcher_sha256']=sha(py.encode('utf-8'))
    rows['PROGRAM_MANIFEST.json']=json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf-8')
    original_modules={n:h for n,h in manifest['files'].items() if n.startswith('mt5_bridge/') and n.endswith('.py')}
    assert all(sha(rows[n])==h for n,h in original_modules.items())
    assert not any(n.endswith(('.zip','.7z','.rar','.tar','.gz')) for n in rows),'NO_EXTRACTION_PAYLOAD'
    output=destination/'FXM1_R74_FULL_FOLDER_START.zip'
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        dirs=set()
        for name in rows:
            p=PurePosixPath(PREFIX+name)
            for parent in p.parents:
                if str(parent)!='.':dirs.add(parent.as_posix()+'/')
        for directory in sorted(dirs):
            i=zipfile.ZipInfo(directory,date_time=(2026,10,13,12,0,0));i.create_system=0;i.external_attr=0x10
            z.writestr(i,b'')
        for name,data in sorted(rows.items()):
            i=zipfile.ZipInfo(PREFIX+name,date_time=(2026,10,13,12,0,0));i.create_system=0;i.external_attr=0x20;i.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(i,data)
    result=dict(archive=str(output),sha256=sha(output.read_bytes()),size=output.stat().st_size,files=len(rows),no_external_launcher=True,no_nested_archives=True,unchanged_trading_sources=len(original_modules),apk_sha256=sha(rows['FXM1_R7_4.apk']),native_binaries_unchanged=len(natives))
    print(json.dumps(result,ensure_ascii=False,indent=2))
    (destination/'BUILD_RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    return output

if __name__=='__main__':build(*sys.argv[1:])
