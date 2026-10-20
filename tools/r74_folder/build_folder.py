"""Package the already verified HF1 delta as ONE complete mt5_bridge folder.
Trading modules, portable interpreter, clock policy and APK are not changed here.
"""
from pathlib import Path
import argparse, hashlib, json, zipfile

def digest(data):return hashlib.sha256(data).hexdigest()
def crlf(s):return s.replace('\r\n','\n').replace('\n','\r\n').encode('utf-8')

TEMPLATE=r'''@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
set "FXM1_FOLDER_START=%~f0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -Command "$t=[IO.File]::ReadAllText($env:FXM1_FOLDER_START,[Text.Encoding]::UTF8);$m='#'+'HF1_FOLDER_BODY';$i=$t.LastIndexOf($m);if($i -lt 0){exit 1};& ([scriptblock]::Create($t.Substring($i+$m.Length)))"
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" goto failed
call "%~dp0..\START.cmd" %*
exit /b %ERRORLEVEL%
:failed
echo.
echo Bridge не запущен. База и ключ не заменялись. Причина указана выше.
if not "%R7_NO_PAUSE%"=="1" pause
exit /b %RESULT%
#HF1_FOLDER_BODY
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$folder=[IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($env:FXM1_FOLDER_START))
$root=[IO.Path]::GetDirectoryName($folder)
$payload=Join-Path $folder '_entry_hf1'
$locks=[Collections.Generic.List[IO.FileStream]]::new()
$changes=[Collections.Generic.List[object]]::new()
$done=[Collections.Generic.List[object]]::new()
$backup=$null
function Hash-Bytes([byte[]]$bytes){
    $h=[Security.Cryptography.SHA256]::Create()
    try{return ([BitConverter]::ToString($h.ComputeHash($bytes))).Replace('-','').ToLowerInvariant()}finally{$h.Dispose()}
}
function No-Links([string]$p){
    $q=$p
    while($q -and $q.Length -ge $root.Length){
        if(Test-Path -LiteralPath $q){
            $v=Get-Item -LiteralPath $q -Force
            $property=$v.PSObject.Properties['LinkType']
            if($property -and $property.Value -in @('SymbolicLink','Junction')){throw ('LINK_REFUSED: '+$q)}
        }
        $q=[IO.Path]::GetDirectoryName($q)
    }
}
function Write-Atomic([string]$target,[byte[]]$bytes){
    No-Links $target
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target))|Out-Null
    $tmp=$target+'.hf1-'+[Guid]::NewGuid().ToString('N')
    $old=$tmp+'.old'
    try{
        [IO.File]::WriteAllBytes($tmp,$bytes)
        if((Hash-Bytes ([IO.File]::ReadAllBytes($tmp))) -ne (Hash-Bytes $bytes)){throw 'WRITE_CHECK_FAILED'}
        if([IO.File]::Exists($target)){[IO.File]::Replace($tmp,$target,$old)}else{[IO.File]::Move($tmp,$target)}
    }finally{
        if([IO.File]::Exists($tmp)){[IO.File]::Delete($tmp)}
        if([IO.File]::Exists($old)){[IO.File]::Delete($old)}
    }
}
try{
    if([IO.Path]::GetFileName($folder) -ne 'mt5_bridge' -or -not [IO.File]::Exists((Join-Path $root 'Runtime/python.exe'))){
        throw 'WRONG_PARENT: скопируйте папку mt5_bridge в рабочую FX-M1-Signal рядом с существующей Runtime.'
    }
    No-Links $folder;No-Links $payload
    $support=@{
__SUPPORT_HASHES__
    }
    $data=@{}
    foreach($name in $support.Keys){
        $path=Join-Path $payload $name;No-Links $path
        if(-not [IO.File]::Exists($path)){throw ('SUPPORT_MISSING: '+$name)}
        $bytes=[IO.File]::ReadAllBytes($path)
        if((Hash-Bytes $bytes) -ne $support[$name]){throw ('SUPPORT_HASH_MISMATCH: '+$name)}
        $data[$name]=$bytes
    }
    $knownStart=@(__KNOWN_START__)
    $knownReserve=@(__KNOWN_RESERVE__)
    $currentStart=Join-Path $root 'START.cmd';No-Links $currentStart
    $currentReserve=Join-Path $root 'Runtime/program_recovery.json';No-Links $currentReserve
    if(-not [IO.File]::Exists($currentStart) -or (Hash-Bytes ([IO.File]::ReadAllBytes($currentStart))) -notin $knownStart){throw 'UNKNOWN_PARENT_VERSION: START.cmd не от комплекта 20.10 или ENTRY-HF1. Другой выпуск не перезаписан.'}
    if(-not [IO.File]::Exists($currentReserve) -or (Hash-Bytes ([IO.File]::ReadAllBytes($currentReserve))) -notin $knownReserve){throw 'UNKNOWN_PARENT_VERSION: другая восстановительная копия; автоматически не заменена.'}
    # Project and Bridge locks are held only while updating support files. Never write database/key/policy.
    $local=$env:LOCALAPPDATA
    if(-not $local){throw 'LOCALAPPDATA_MISSING'}
    $lockPaths=@((Join-Path $local 'FXM1/R74-Recovery/recovery-launch.lock'),(Join-Path $local 'FXM1/R74-Recovery/event_state/runtime.lock'))
    foreach($path in $lockPaths){
        if([IO.File]::Exists($path)){
            try{$locks.Add([IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None))}
            catch{throw 'CLOSE_BRIDGE: сначала выключите AUTO и закройте старое окно Bridge; файлы не заменены.'}
        }
    }
    $updateLock=Join-Path $root '.entry-hf1-update.lock';No-Links $updateLock
    try{$locks.Add([IO.File]::Open($updateLock,[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None))}
    catch{throw 'UPDATE_IN_PROGRESS: уже запущено другое обновление.'}
    # Recheck after taking locks; refuse upgrades from an unknown newer version.
    if((Hash-Bytes ([IO.File]::ReadAllBytes($currentStart))) -notin $knownStart -or
       (Hash-Bytes ([IO.File]::ReadAllBytes($currentReserve))) -notin $knownReserve){throw 'PARENT_CHANGED_DURING_CHECK'}
    $m=[Text.Encoding]::UTF8.GetString($data['PROGRAM_MANIFEST.json'])|ConvertFrom-Json
    $wrappers=@{
__WRAPPER_HASHES__
    }
    $wrappers['mt5_bridge/START_BRIDGE_V10_0.bat']=Hash-Bytes ([IO.File]::ReadAllBytes($env:FXM1_FOLDER_START))
    foreach($name in $wrappers.Keys){
        $p=Join-Path $root $name;No-Links $p
        if(-not [IO.File]::Exists($p) -or (Hash-Bytes ([IO.File]::ReadAllBytes($p))) -ne $wrappers[$name]){throw ('FOLDER_INCOMPLETE: '+$name)}
        $prop=$m.files.PSObject.Properties[$name]
        if($null -eq $prop){throw ('MANIFEST_PATH_MISSING: '+$name)}
        $prop.Value=$wrappers[$name]
    }
    $data['PROGRAM_MANIFEST.json']=[Text.Encoding]::UTF8.GetBytes(($m|ConvertTo-Json -Depth 10 -Compress))
    # Prepare and read all destinations before changing any; manifest is committed last.
    $names=@('Runtime/program_recovery.json','tests/event_core/test_r55_history_clock.py','tests/event_core/test_r743_entry_hf1.py','START.cmd','PROGRAM_MANIFEST.json')
    foreach($name in $names){
        $p=Join-Path $root $name;No-Links $p
        $before=$null
        if([IO.File]::Exists($p)){$before=[IO.File]::ReadAllBytes($p);if((Hash-Bytes $before) -eq (Hash-Bytes $data[$name])){continue}}
        elseif([IO.Directory]::Exists($p)){throw ('TARGET_IS_DIRECTORY: '+$name)}
        $changes.Add([pscustomobject]@{name=$name;target=$p;before=$before;after=$data[$name]})
    }
    if($changes.Count -gt 0){
        $backup=Join-Path $payload ('backups/'+[DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss')+'-'+[Guid]::NewGuid().ToString('N'))
        foreach($change in $changes){
            if($null -ne $change.before){Write-Atomic (Join-Path $backup ($change.name+'.before')) $change.before}
        }
        try{
            foreach($change in $changes){Write-Atomic $change.target $change.after;$done.Add($change)}
            foreach($change in $changes){if((Hash-Bytes ([IO.File]::ReadAllBytes($change.target))) -ne (Hash-Bytes $change.after)){throw 'READBACK_FAILED'}}
        }catch{
            $cause=$_.Exception.Message;$rollback=$true
            for($i=$done.Count-1;$i -ge 0;$i--){$change=$done[$i];try{
                if($null -eq $change.before){[IO.File]::Delete($change.target)}else{Write-Atomic $change.target $change.before}
            }catch{$rollback=$false}}
            throw ('SUPPORT_UPDATE_FAILED; rollback='+$rollback+'; backup='+$backup+'; '+$cause)
        }
        Write-Output 'ENTRY-HF1: служебные файлы согласованы автоматически. База, ключ и время сохранены.'
    }else{Write-Output 'ENTRY-HF1: папка Bridge уже подготовлена.'}
}catch{
    Write-Output ('BRIDGE НЕ ЗАПУЩЕН: '+$_.Exception.Message)
    exit 1
}finally{for($i=$locks.Count-1;$i -ge 0;$i--){$locks[$i].Dispose()}}
exit 0
'''

def build(base,patch,out):
    with zipfile.ZipFile(base) as z:
        original={n[len('FX-M1-Signal/'):]:z.read(n) for n in z.namelist() if n.startswith('FX-M1-Signal/') and not n.endswith('/')}
    with zipfile.ZipFile(patch) as z:delta={n:z.read(n) for n in z.namelist() if not n.endswith('/')}
    assert len(delta)==9
    files={n:v for n,v in original.items() if n.startswith('mt5_bridge/')}
    for n,v in delta.items():
        if n.startswith('mt5_bridge/'):files[n]=v
    support={n:v for n,v in delta.items() if not n.startswith('mt5_bridge/')}
    assert len(support)==5
    alias=crlf('@echo off\nsetlocal DisableDelayedExpansion\ncall "%~dp0START_BRIDGE_V10_0.bat" %*\nexit /b %ERRORLEVEL%\n')
    changes={}
    for n in files:
        if n.lower().endswith(('.bat','.cmd')) and not n.endswith('/START_BRIDGE_V10_0.bat'):files[n]=alias;changes[n]=digest(alias)
    readme=crlf('Bridge R7.4 ENTRY-HF1\n\nСкопируйте всю эту папку mt5_bridge в существующую рабочую FX-M1-Signal с заменой одноимённых файлов.\nНе удаляйте Runtime и данные. Первый запуск: START_BRIDGE_V10_0.bat внутри этой папки.\nСогласование служебных файлов выполняется автоматически, вручную раскладывать патч не нужно.\nПК использует уже установленную Runtime; APK на телефоне не меняется.\nПеред копированием: AUTO OFF, нет незавершённой серии/ордеров, старый Bridge закрыт; MT5 оставьте открытым.\nОграничения торговли R7.4 не изменены. Это упаковка проверенного ENTRY-HF1, не новая стратегия.\n')
    for n in ('mt5_bridge/README.txt','mt5_bridge/README_START.txt'):files[n]=readme;changes[n]=digest(readme)
    def psmap(m):return '\n'.join("        '%s'='%s'"%(n,h) for n,h in sorted(m.items()))
    main=TEMPLATE.replace('__SUPPORT_HASHES__',psmap({n:digest(v) for n,v in support.items()}))
    main=main.replace('__WRAPPER_HASHES__',psmap(changes))
    main=main.replace('__KNOWN_START__',','.join("'%s'"%digest(v) for v in (original['START.cmd'],delta['START.cmd'])))
    main=main.replace('__KNOWN_RESERVE__',','.join("'%s'"%digest(v) for v in (original['Runtime/program_recovery.json'],delta['Runtime/program_recovery.json'])))
    files['mt5_bridge/START_BRIDGE_V10_0.bat']=crlf(main)
    for n,v in support.items():files['mt5_bridge/_entry_hf1/'+n]=v
    manifest=json.loads(delta['PROGRAM_MANIFEST.json']);mnames=manifest['files']
    for n,v in files.items():
        if n.endswith('.py') and '/_entry_hf1/' not in n:assert digest(v)==mnames[n],n
    out=Path(out);out.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for n,v in sorted(files.items()):z.writestr(n,v)
    info=dict(files=len(files),top_level='mt5_bridge',size=out.stat().st_size,sha256=digest(out.read_bytes()),
        base_sha256=digest(Path(base).read_bytes()),patch_sha256=digest(Path(patch).read_bytes()),
        trade_code='byte-identical ENTRY-HF1',runtime_included=False,apk_included=False,
        automatic_parent_support=list(support),changed_python_hashes={n:digest(v) for n,v in delta.items() if n.startswith('mt5_bridge/')})
    out.with_suffix('.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(info,ensure_ascii=False,indent=2));return info

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('base');a.add_argument('patch');a.add_argument('out');v=a.parse_args();build(v.base,v.patch,v.out)
