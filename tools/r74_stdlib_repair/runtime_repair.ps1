# Local repair of packaged CPython bytecode only. No network, pip, account or trading calls.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$root = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$reserve = Join-Path $PSScriptRoot 'stdlib_recovery.json'
$expectedReserve = '__RESERVE_SHA256__'
$hasher = [Security.Cryptography.SHA256]::Create()
function Hash-Bytes([byte[]]$bytes) {
    return ([BitConverter]::ToString($hasher.ComputeHash($bytes))).Replace('-','').ToLowerInvariant()
}
function Hash-File([string]$name) {
    $stream = [IO.File]::OpenRead($name)
    try { return ([BitConverter]::ToString($hasher.ComputeHash($stream))).Replace('-','').ToLowerInvariant() }
    finally { $stream.Dispose() }
}
function Check-Links([string]$name) {
    $cursor = $name
    while ($cursor -and $cursor.Length -gt $root.Length) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            $property = $item.PSObject.Properties['LinkType']
            if ($property -and $property.Value -in @('SymbolicLink','Junction')) {
                throw ('RUNTIME_LINK_NOT_ALLOWED: ' + $cursor)
            }
        }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
}
try {
    if (-not [IO.File]::Exists($reserve)) { throw 'RESERVE_MISSING: Runtime/stdlib_recovery.json' }
    Check-Links $reserve
    if ((Hash-File $reserve) -ne $expectedReserve) { throw 'RESERVE_CHECKSUM_MISMATCH: Runtime/stdlib_recovery.json' }
    $payload = [IO.File]::ReadAllText($reserve, [Text.Encoding]::UTF8) | ConvertFrom-Json
    if ($payload.format -ne 'R74_STDLIB_RECOVERY_V1' -or @($payload.files).Count -ne __FILE_COUNT__) {
        throw 'RESERVE_FORMAT_INVALID'
    }
    $restored = 0
    $seen = @{}
    foreach ($entry in $payload.files) {
        $relative = [string]$entry.path
        if ($relative -cnotmatch '^Runtime/Lib/[A-Za-z0-9_./-]+\.pyc$' -or
            $relative.Contains('..') -or $relative.Contains('/site-packages/') -or $seen.ContainsKey($relative) -or
            [string]$entry.sha256 -cnotmatch '^[0-9a-f]{64}$') { throw 'RESERVE_PATH_INVALID' }
        $seen[$relative] = $true
        $target = [IO.Path]::GetFullPath((Join-Path $root $relative.Replace('/','\')))
        if (-not $target.StartsWith($root + '\',[StringComparison]::OrdinalIgnoreCase)) { throw 'RESERVE_PATH_OUTSIDE_ROOT' }
        Check-Links $target
        if ([IO.Directory]::Exists($target)) { throw ('RUNTIME_FILE_IS_DIRECTORY: ' + $relative) }
        if ([IO.File]::Exists($target) -and (Hash-File $target) -eq $entry.sha256) { continue }
        $bytes = [Convert]::FromBase64String([string]$entry.data)
        if ($bytes.Length -ne $entry.size -or (Hash-Bytes $bytes) -ne $entry.sha256) { throw ('RESERVE_FILE_CHECKSUM_MISMATCH: ' + $relative) }
        [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target)) | Out-Null
        $temporary = $target + '.r74-repair-' + [Guid]::NewGuid().ToString('N')
        try {
            [IO.File]::WriteAllBytes($temporary,$bytes)
            if ((Hash-File $temporary) -ne $entry.sha256) { throw ('RUNTIME_WRITE_CHECK_FAILED: ' + $relative) }
            try {
                if ([IO.File]::Exists($target)) { [IO.File]::Replace($temporary,$target,$null) }
                else { [IO.File]::Move($temporary,$target) }
            } catch {
                # A concurrent starter may have just restored the identical bytes.
                if (-not [IO.File]::Exists($target) -or (Hash-File $target) -ne $entry.sha256) { throw }
            }
            if ((Hash-File $target) -ne $entry.sha256) { throw ('RUNTIME_REPAIR_VERIFY_FAILED: ' + $relative) }
            $restored++
            if ($restored -le 3) { Write-Output ('Восстановлена библиотека: ' + $relative) }
        } finally {
            if ([IO.File]::Exists($temporary)) { [IO.File]::Delete($temporary) }
        }
    }
    Write-Output ('RUNTIME_LIBRARY_RESTORED ' + $restored + ' | LIBRARY CHECK OK')
    exit 0
} catch {
    Write-Output ('Подготовка Python остановлена: ' + $_.Exception.Message)
    Write-Output 'База, ключ и торговые настройки не изменялись. Пришлите текст этой ошибки; защиту Windows не отключайте.'
    exit 1
} finally {
    $hasher.Dispose()
}
