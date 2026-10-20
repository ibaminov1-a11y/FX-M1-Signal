@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
set "FXM1_TIME_SELF=%~f0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -Command "$t=[IO.File]::ReadAllText($env:FXM1_TIME_SELF); $m='#'+' POWERSHELL_BODY'; & ([scriptblock]::Create($t.Substring($t.LastIndexOf($m)+$m.Length)))"
set "result=%ERRORLEVEL%"
if not "%FXM1_REPORT_NO_PAUSE%"=="1" pause
exit /b %result%
# POWERSHELL_BODY
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Write-Host 'FXM1: проверка времени. Никакие настройки и позиции не изменяются.'
Write-Host 'Bridge оставьте запущенным. Результат откроется в Блокноте.'
function Epoch { return [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()/1000.0 }
function UtcText($value) {
    if ($null -eq $value) { return $null }
    return [DateTimeOffset]::FromUnixTimeMilliseconds([long]($value*1000)).ToString('o')
}
# External requests carry NO Bridge headers, account details or report contents.
# HTTPS Date is approximate diagnostic evidence, NEVER an automatic clock policy.
function RemoteDate([string]$hostName) {
    $response = $null
    try {
        $uri = 'https://' + $hostName + '/?fxm1_time_probe=' + [Guid]::NewGuid().ToString('N')
        $request = [Net.HttpWebRequest]::Create($uri)
        $request.Method = 'HEAD'
        $request.Timeout = 4000
        $request.ReadWriteTimeout = 4000
        $request.AllowAutoRedirect = $false
        $request.UserAgent = 'Time-Diagnostic/1.0'
        $request.CachePolicy = New-Object Net.Cache.RequestCachePolicy([Net.Cache.RequestCacheLevel]::NoCacheNoStore)
        $start = Epoch
        $watch = [Diagnostics.Stopwatch]::StartNew()
        $response = $request.GetResponse()
        $end = Epoch
        $watch.Stop()
        $date = [DateTimeOffset]::Parse($response.Headers['Date'],[Globalization.CultureInfo]::InvariantCulture)
        $age = $response.Headers['Age']
        $usable = [Math]::Abs(($end-$start)-$watch.Elapsed.TotalSeconds) -le 2
        if ($age -and [double]$age -gt 5) { $usable = $false }
        return [ordered]@{host=$hostName;http_date_utc=$date.ToUniversalTime().ToString('o');
            approximate_remote_minus_windows_seconds=[Math]::Round(($date.ToUnixTimeMilliseconds()/1000)-(($start+$end)/2),2);
            roundtrip_seconds=[Math]::Round($watch.Elapsed.TotalSeconds,2);age_header=$age;usable=$usable;
            note='Approximate HTTP header time; no NTP synchronization performed.'}
    } catch {
        return [ordered]@{host=$hostName;usable=$false;error=$_.Exception.GetType().Name}
    } finally { if ($null -ne $response) { $response.Close() } }
}
function BridgeSnapshot([string]$token) {
    $response = $null
    $reader = $null
    try {
        $request = [Net.HttpWebRequest]::Create('http://127.0.0.1:8000/ec/state')
        $request.Method = 'GET'
        $request.Timeout = 4000
        $request.ReadWriteTimeout = 4000
        $request.AllowAutoRedirect = $false
        $request.Proxy = $null
        $request.Headers['Authorization'] = 'Bearer ' + $token
        $response = $request.GetResponse()
        if ([int]$response.StatusCode -ne 200) { throw 'LOCAL_BRIDGE_HTTP_ERROR' }
        $reader = New-Object IO.StreamReader($response.GetResponseStream())
        $body = $reader.ReadToEnd()
        if ($body.Length -gt 8000000) { throw 'LOCAL_BRIDGE_RESPONSE_TOO_LARGE' }
        return $body | ConvertFrom-Json
    } finally {
        if ($null -ne $reader) { $reader.Close() }
        if ($null -ne $response) { $response.Close() }
    }
}
$stateDir = [IO.Path]::Combine($env:LOCALAPPDATA,'FXM1','R74-Recovery','event_state')
$clockFile = [IO.Path]::Combine($stateDir,'broker-clock.json')
$keyFile = [IO.Path]::Combine($stateDir,'bridge-token.txt')
$policy = [ordered]@{present=[IO.File]::Exists($clockFile)}
if ($policy.present) {
    try {
        $p = [IO.File]::ReadAllText($clockFile) | ConvertFrom-Json
        $policy.account = $p.account
        $policy.offset_minutes = $p.offset_minutes
        $policy.confirmed = $p.confirmed
    } catch { $policy.error = 'CLOCK_POLICY_UNREADABLE' }
}
$report = [ordered]@{
    format='FXM1_TIME_DIAGNOSTIC_V1';settings_changed=$false;orders_sent=$false;
    result='EVIDENCE_ONLY_NO_CLOCK_CHANGE';
    windows=[ordered]@{local_time=[DateTimeOffset]::Now.ToString('o');utc_time=[DateTimeOffset]::UtcNow.ToString('o');
        timezone_id=[TimeZoneInfo]::Local.Id;utc_epoch=Epoch};
    saved_policy=$policy;bridge_samples=@();bridge_error=$null;public_utc_checks=@();
    note='Only local cached GET /ec/state and public HTTPS Date headers. Key, balances and positions are not exported.'
}
if ([IO.File]::Exists($keyFile)) {
    try {
        $token = [IO.File]::ReadAllText($keyFile).Trim()
        if ($token.Length -lt 32 -or $token.Contains("`r") -or $token.Contains("`n")) { throw 'INVALID_LOCAL_KEY' }
        for ($i=0; $i -lt 3; $i++) {
            $s = BridgeSnapshot $token
            $now = Epoch
            $q = $s.quote_diagnostics
            $row = [ordered]@{observed_pc_utc=UtcText $now;bridge_version=$s.bridge_version;
                account=$s.account.key;symbol=$s.config.symbol;timeframe=$s.config.timeframe;
                auto=$s.auto;quote_fresh=$s.quote_fresh;entry_allowed=$s.entry_allowed;
                server_time=$s.server_time;clock=$q.clock;clock_identity=$q.clock_identity;
                effective_offset_minutes=$q.offset_minutes;feed_confirmed=$q.feed_confirmed;
                raw_tick_time_msc=$q.raw_tick_time_msc;effective_tick_time_msc=$q.tick_time_msc;
                bridge_received_at=$q.received_at;snapshot_age=$s.snapshot_age}
            if ($null -ne $q.raw_tick_time_msc) {
                $row.raw_tick_as_utc = UtcText ($q.raw_tick_time_msc/1000.0)
                $row.raw_tick_minus_windows_seconds = [Math]::Round(($q.raw_tick_time_msc/1000.0)-$now,3)
            }
            if ($null -ne $q.tick_time_msc) {
                $row.effective_tick_minus_windows_seconds = [Math]::Round(($q.tick_time_msc/1000.0)-$now,3)
            }
            if ($policy.present -and $policy.Contains('account')) { $policy.account_matches_connected = ($policy.account -eq $s.account.key) }
            $report.bridge_samples += $row
            if ($i -lt 2) { Start-Sleep -Seconds 1 }
        }
    } catch { $report.bridge_error = 'LOCAL_BRIDGE_READ_FAILED: ' + $_.Exception.GetType().Name }
    finally { $token = $null }
} else { $report.bridge_error = 'LOCAL_KEY_NOT_FOUND' }
foreach ($hostName in @('www.microsoft.com','www.cloudflare.com')) {
    $report.public_utc_checks += RemoteDate $hostName
}
$report.windows.utc_at_end = [DateTimeOffset]::UtcNow.ToString('o')
$name = 'FXM1_TIME_REPORT_' + [DateTime]::Now.ToString('yyyyMMdd_HHmmss') + '.txt'
$folder = [IO.Path]::GetDirectoryName($env:FXM1_TIME_SELF)
$path = [IO.Path]::Combine($folder,$name)
$json = $report | ConvertTo-Json -Depth 8
try { [IO.File]::WriteAllText($path,$json,(New-Object Text.UTF8Encoding($true))) }
catch { $path=[IO.Path]::Combine([IO.Path]::GetTempPath(),$name); [IO.File]::WriteAllText($path,$json,(New-Object Text.UTF8Encoding($true))) }
Write-Host ''
Write-Host 'Готов диагностический отчёт. Автоторговля, время и настройки НЕ изменены.'
Write-Host ('Файл: ' + $path)
Write-Host 'Пришлите этот файл в чат. Ключ подключения в него не включён.'
if ($env:FXM1_REPORT_NO_OPEN -ne '1') { Start-Process -FilePath "$env:SystemRoot\System32\notepad.exe" -ArgumentList ('"'+$path+'"') }
exit 0
