@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
set "FXM1_CLOCK_SELF=%~f0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -Command "$t=[IO.File]::ReadAllText($env:FXM1_CLOCK_SELF,[Text.Encoding]::UTF8);$m='#'+' CLOCK_POLICY_BODY'; & ([scriptblock]::Create($t.Substring($t.LastIndexOf($m)+$m.Length)))"
set "result=%ERRORLEVEL%"
if not "%FXM1_CLOCK_NO_PAUSE%"=="1" pause
exit /b %result%
# CLOCK_POLICY_BODY
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$expectedAccount = '__PINNED_ACCOUNT__'
# Explicit configuration established from the user's report and independent UTC checks.
# This tool never estimates an offset. A different observed offset is refused.
$offsetMinutes = 180
$tempFile = $null
$token = $null
function Epoch { return [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()/1000.0 }
function Fail([string]$message) { throw $message }
function Number($value,[string]$name) {
    if ($null -eq $value) { Fail ('MISSING_FIELD: '+$name) }
    $n=[double]$value
    if ([double]::IsNaN($n) -or [double]::IsInfinity($n)) { Fail ('INVALID_FIELD: '+$name) }
    return $n
}
function ReadBridge {
    $request = [Net.HttpWebRequest]::Create('http://127.0.0.1:8000/ec/state')
    $request.Method = 'GET'
    $request.Timeout = 4000
    $request.ReadWriteTimeout = 4000
    $request.AllowAutoRedirect = $false
    $request.Proxy = $null
    $request.Headers['Authorization'] = 'Bearer ' + $token
    $request.Headers['X-FXM1-Client'] = 'R51'
    $response=$null;$reader=$null
    try {
        $response=$request.GetResponse()
        if ([int]$response.StatusCode -ne 200) { Fail 'BRIDGE_READ_FAILED' }
        $reader=New-Object IO.StreamReader($response.GetResponseStream())
        $body=$reader.ReadToEnd()
        if ($body.Length -gt 8000000) { Fail 'BRIDGE_RESPONSE_TOO_LARGE' }
        return $body | ConvertFrom-Json
    } finally {
        if ($null -ne $reader) { $reader.Close() }
        if ($null -ne $response) { $response.Close() }
    }
}
try {
    Write-Host 'FXM1 R7.4: настройка времени котировок для проверенного счёта.'
    Write-Host 'Windows, APK, ключ, базу и торговую логику программа не меняет.'
    Write-Host 'AUTO должен быть ВЫКЛЮЧЕН во всех профилях. Bridge оставьте запущенным.'
    if ($expectedAccount -notmatch '^\d+@[^\r\n]+$') { Fail 'ACCOUNT_NOT_PINNED' }
    if (-not $env:LOCALAPPDATA) { Fail 'LOCALAPPDATA_NOT_FOUND' }
    $state=[IO.Path]::Combine($env:LOCALAPPDATA,'FXM1','R74-Recovery','event_state')
    $target=[IO.Path]::Combine($state,'broker-clock.json')
    $key=[IO.Path]::Combine($state,'bridge-token.txt')
    if (-not [IO.Directory]::Exists($state) -or -not [IO.File]::Exists($key) -or -not [IO.File]::Exists([IO.Path]::Combine($state,'campaign.sqlite3'))) {
        Fail 'STATE_NOT_FOUND: запустите действующий Bridge R7.4 через START.cmd.'
    }
    if ([IO.File]::GetAttributes($state) -band [IO.FileAttributes]::ReparsePoint) { Fail 'STATE_LINK_REFUSED' }
    $token=[IO.File]::ReadAllText($key).Trim()
    if ($token.Length -lt 32 -or $token.Contains("`r") -or $token.Contains("`n")) { Fail 'INVALID_LOCAL_KEY' }
    $saved=[IO.File]::Exists($target)
    if ($saved) {
        $p=[IO.File]::ReadAllText($target) | ConvertFrom-Json
        if ($p.account -cne $expectedAccount -or $p.offset_minutes -isnot [int] -or $p.offset_minutes -ne $offsetMinutes -or $p.confirmed -isnot [bool] -or $p.confirmed -ne $true) {
            Fail 'OTHER_CLOCK_POLICY: уже есть другая настройка. Ничего не заменено.'
        }
    }
    $previousRaw=0.0;$activeOffset=$null
    for ($i=0;$i -lt 3;$i++) {
        $s=ReadBridge;$now=Epoch
        if ($s.account.key -cne $expectedAccount -or $s.account.type -cne 'DEMO') { Fail 'WRONG_ACCOUNT: подключён другой счёт. Ничего не изменено.' }
        if ($s.auto -isnot [bool] -or $s.auto -ne $false) { Fail 'AUTO_ON: выключите AUTO, затем повторите запуск этого файла.' }
        if ($null -eq $s.profiles -or @($s.profiles).Count -eq 0) { Fail 'PROFILE_STATUS_UNKNOWN' }
        foreach ($profile in $s.profiles) {
            if ($profile.auto -isnot [bool] -or $profile.auto -ne $false) { Fail 'PROFILE_AUTO_ON: выключите AUTO во всех профилях.' }
            if ($null -ne $profile.campaign) { Fail 'CAMPAIGN_ACTIVE: нельзя менять часы во время серии.' }
        }
        if ($s.positions_ok -ne $true -or $null -eq $s.all_positions) { Fail 'POSITIONS_NOT_CONFIRMED: дождитесь обновления состояния Bridge.' }
        if (@($s.all_positions).Count -ne 0 -or $null -ne $s.campaign -or $null -ne $s.pending_reversal -or $s.exit_pending -eq $true) {
            Fail 'EXPOSURE_ACTIVE: сначала завершите открытые позиции и серию; автоматического закрытия здесь нет.'
        }
        $age=Number $s.snapshot_age 'snapshot_age';$accountAge=Number $s.account_age 'account_age'
        if ($age -lt 0 -or $age -ge 3 -or $accountAge -lt 0 -or $accountAge -ge 10) { Fail 'STATE_STALE: дождитесь свежего статуса и повторите.' }
        $q=$s.quote_diagnostics
        $raw=Number $q.raw_tick_time_msc 'raw_tick_time_msc'
        $effective=Number $q.tick_time_msc 'tick_time_msc'
        $offset=Number $q.offset_minutes 'offset_minutes'
        if ($offset -ne 0 -and $offset -ne $offsetMinutes) { Fail 'OTHER_ACTIVE_OFFSET' }
        if ($i -gt 0 -and $offset -ne $activeOffset) { Fail 'CLOCK_CHANGED_DURING_CHECK' }
        $activeOffset=$offset
        if ($effective -ne ($raw-$offset*60000)) { Fail 'INCONSISTENT_CLOCK_DIAGNOSTICS' }
        if ($offset -eq 0 -and $q.clock_identity -cne 'UTC_NATIVE_R51') { Fail 'UNEXPECTED_CLOCK_IDENTITY' }
        if ($offset -eq $offsetMinutes -and $q.clock_identity -cne ('UTC_EXPLICIT_R55:'+$expectedAccount+':180')) { Fail 'WRONG_CLOCK_BINDING' }
        $correctedAge=$now-($raw/1000.0-$offsetMinutes*60)
        $receiveAge=$now-(Number $q.received_at 'received_at')
        if ($correctedAge -lt -2 -or $correctedAge -gt 10 -or $receiveAge -lt -2 -or $receiveAge -ge 10) {
            Fail 'OFFSET_NOT_CONFIRMED_NOW: текущие котировки не соответствуют подтверждённым +180 минутам. Ничего не изменено.'
        }
        if ($i -gt 0 -and $raw -le $previousRaw) { Fail 'NO_NEW_TICK: дождитесь обновления котировок и повторите запуск.' }
        $previousRaw=$raw
        if ($i -lt 2) { Start-Sleep -Seconds 1 }
    }
    if ($saved) {
        if ($activeOffset -eq $offsetMinutes) { Write-Host 'CLOCK_POLICY_ACTIVE: настройка уже применяется; повторной коррекции нет.' }
        else { Write-Host 'CLOCK_POLICY_ALREADY_SAVED: файл уже сохранён, нужен перезапуск Bridge.' }
    } else {
        # New file only. Never overwrite another policy, the database, or the token.
        $json='{ "account": "'+$expectedAccount+'", "offset_minutes": 180, "confirmed": true }'
        $bytes=([Text.UTF8Encoding]::new($false)).GetBytes($json)
        $tempFile=[IO.Path]::Combine($state,'.clock-'+[Guid]::NewGuid().ToString('N')+'.tmp')
        $stream=[IO.File]::Open($tempFile,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
        try { $stream.Write($bytes,0,$bytes.Length);$stream.Flush($true) } finally { $stream.Dispose() }
        [IO.File]::Move($tempFile,$target)
        $tempFile=$null
        Write-Host 'CLOCK_POLICY_SAVED_RESTART_REQUIRED'
        Write-Host ('Сохранено для счёта: '+$expectedAccount+'; смещение меток MT5: +180 минут.')
    }
    Write-Host ('Файл: '+$target)
    Write-Host ''
    Write-Host 'Теперь закройте только окно Bridge и запустите прежний START.cmd.'
    Write-Host 'MT5 не закрывайте. AUTO оставьте выключенным; мониторинг можно включить.'
    Write-Host 'После новых котировок проверьте ПРОГНОЗ / ПОСЛЕДНИЙ.'
    Write-Host 'При сохранении ошибки запустите CHECK_TIME.cmd повторно. Ничего не удаляйте.'
    $token=$null
    exit 0
} catch {
    $token=$null
    if ($null -ne $tempFile -and [IO.File]::Exists($tempFile)) { [IO.File]::Delete($tempFile) }
    Write-Host ('НАСТРОЙКА НЕ СОХРАНЕНА: '+$_.Exception.Message)
    Write-Host 'База и ключ не изменены. Пришлите текст этой ошибки без ключа.'
    exit 1
}
