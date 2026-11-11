<#
.SYNOPSIS
  Забрать новые резервные копии «Твёрдого знака» с Яндекс Диска на этот компьютер.

.DESCRIPTION
  Сервер несколько раз в сутки шифрует дамп базы и кладёт его на Яндекс Диск
  (deploy/scripts/backup.sh). Этот скрипт забирает оттуда то, чего на
  компьютере ещё нет. Запускается сам — при входе в Windows и каждый час
  (ставит backup-pull-setup.ps1), — а вручную так:

    powershell -ExecutionPolicy Bypass -File backup-pull.ps1

  Скрипт ТОЛЬКО ДОБАВЛЯЕТ файлы и никогда ничего не удаляет — ни здесь, ни
  на Диске. Если сервер взломают и сотрут копии на Диске, здесь они
  останутся. Если Яндекс недоступен, скрипт подождёт следующего часа.

  Файлы зашифрованы ключом age: без приватного ключа их не прочитать, так
  что держать их на обычном компьютере безопасно. Ключ хранится отдельно
  (см. docs/DEPLOY-WINDOWS.md, раздел про резервные копии).

  Если копии перестали приходить или Диск не отвечает дольше StaleHours,
  появится окно с предупреждением — не чаще раза в 12 часов.
#>
param(
    [string]$Target = (Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'TverdyyZnak-backups'),
    [string]$RemoteDir = '/tverdyy-znak-backups',
    [string]$WebDav = 'https://webdav.yandex.ru',
    [int]$StaleHours = 30
)

$ErrorActionPreference = 'Stop'
$AppDir = Join-Path $env:LOCALAPPDATA 'TverdyyZnak'
$CredFile = Join-Path $AppDir 'yadisk.xml'
$SuccessFile = Join-Path $AppDir 'last-success.txt'
$WarnedFile = Join-Path $AppDir 'last-warning.txt'
$NamePattern = '^tz-(\d{8}T\d{6}Z)\.dump(\.age|\.gpg)?$'

New-Item -ItemType Directory -Force -Path $AppDir, $Target | Out-Null
$Log = Join-Path $Target 'pull.log'

function Write-Log([string]$Text) {
    $line = '{0:yyyy-MM-dd HH:mm:ss}  {1}' -f (Get-Date), $Text
    Write-Host $line
    Add-Content -Path $Log -Value $line -Encoding UTF8
}

function Show-Warning([string]$Text) {
    # Не чаще раза в 12 часов: напоминание каждый час быстро начнут закрывать не читая.
    if (Test-Path $WarnedFile) {
        $last = [datetime]::Parse((Get-Content $WarnedFile -Raw).Trim(), [Globalization.CultureInfo]::InvariantCulture)
        if ((Get-Date) - $last -lt (New-TimeSpan -Hours 12)) { return }
    }
    Set-Content -Path $WarnedFile -Value ((Get-Date).ToString('o')) -Encoding UTF8
    Write-Log "ПРЕДУПРЕЖДЕНИЕ: $Text"
    # Окно само закроется через 40 минут — чтобы не задержать следующий запуск.
    $shell = New-Object -ComObject WScript.Shell
    $null = $shell.Popup($Text, 2400, 'Твёрдый знак — резервные копии', 0x30)
}

function Hours-Since([string]$File) {
    if (-not (Test-Path $File)) { return [double]::PositiveInfinity }
    $at = [datetime]::Parse((Get-Content $File -Raw).Trim(), [Globalization.CultureInfo]::InvariantCulture)
    return ((Get-Date) - $at).TotalHours
}

# Один запуск за раз: «при входе» и «каждый час» могут совпасть.
$mutex = New-Object System.Threading.Mutex($false, 'Local\TverdyyZnakBackupPull')
try {
    if (-not $mutex.WaitOne(0)) { exit 0 }
} catch [System.Threading.AbandonedMutexException] { }

try {
    # Короткий лог: последние 3000 строк хватит на несколько месяцев.
    if ((Test-Path $Log) -and (Get-Item $Log).Length -gt 1MB) {
        $tail = Get-Content $Log -Tail 3000
        Set-Content -Path $Log -Value $tail -Encoding UTF8
    }

    if (-not (Test-Path $CredFile)) {
        Write-Log 'Нет пароля Яндекс Диска — запустите backup-pull-setup.ps1.'
        exit 1
    }
    # Пароль приложения зашифрован Windows (DPAPI): прочитать его может только
    # эта учётная запись на этом компьютере.
    $cred = Import-Clixml -Path $CredFile
    $pair = '{0}:{1}' -f $cred.UserName, $cred.GetNetworkCredential().Password
    $basic = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pair))

    Add-Type -AssemblyName System.Net.Http
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $client = New-Object System.Net.Http.HttpClient
    $client.Timeout = [TimeSpan]::FromMinutes(20)
    $client.DefaultRequestHeaders.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue('Basic', $basic)

    $base = $WebDav.TrimEnd('/') + '/' + $RemoteDir.Trim('/') + '/'

    # Список файлов на Диске. Сразу после включения сети может ещё не быть —
    # несколько попыток с паузой, потом до следующего часа.
    $listing = $null
    for ($attempt = 1; $attempt -le 6 -and -not $listing; $attempt++) {
        try {
            $request = New-Object System.Net.Http.HttpRequestMessage((New-Object System.Net.Http.HttpMethod('PROPFIND')), $base)
            $request.Headers.Add('Depth', '1')
            $request.Content = New-Object System.Net.Http.StringContent(
                '<?xml version="1.0" encoding="utf-8"?><d:propfind xmlns:d="DAV:"><d:prop><d:getcontentlength/></d:prop></d:propfind>',
                [Text.Encoding]::UTF8, 'application/xml')
            $response = $client.SendAsync($request).GetAwaiter().GetResult()
            $code = [int]$response.StatusCode
            if ($code -eq 401) {
                Show-Warning 'Яндекс Диск не принимает пароль приложения. Возможно, его отозвали. Запустите backup-pull-setup.ps1 и введите новый.'
                exit 1
            }
            if ($code -eq 404) {
                Write-Log "На Диске нет папки $RemoteDir — сервер ещё ничего не выгружал."
                $listing = '<d:multistatus xmlns:d="DAV:"/>'
                break
            }
            if (-not $response.IsSuccessStatusCode) { throw "Яндекс Диск ответил $code" }
            $listing = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        } catch {
            Write-Log ("Попытка {0}: Яндекс Диск недоступен — {1}" -f $attempt, $_.Exception.Message)
            if ($attempt -lt 6) { Start-Sleep -Seconds 30 }
        }
    }

    if (-not $listing) {
        if ((Hours-Since $SuccessFile) -gt $StaleHours) {
            Show-Warning "Больше $StaleHours часов не удаётся связаться с Яндекс Диском. Копии за это время не скачаны. Проверьте интернет; если Диск недоступен долго — сообщите, нужен второй адрес для копий."
        }
        exit 1
    }

    # Разбираем ответ: имя файла и размер.
    [xml]$xml = $listing
    $ns = New-Object System.Xml.XmlNamespaceManager($xml.NameTable)
    $ns.AddNamespace('d', 'DAV:')
    $remote = @()
    foreach ($node in $xml.SelectNodes('//d:response', $ns)) {
        $href = [Uri]::UnescapeDataString($node.SelectSingleNode('d:href', $ns).InnerText)
        $name = $href.TrimEnd('/').Split('/')[-1]
        if (-not ($name -match $NamePattern)) { continue }
        $sizeNode = $node.SelectSingleNode('.//d:getcontentlength', $ns)
        $size = if ($sizeNode) { [long]$sizeNode.InnerText } else { -1 }
        $stamp = [datetime]::ParseExact($Matches[1], "yyyyMMdd'T'HHmmss'Z'",
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::AssumeUniversal -bor [Globalization.DateTimeStyles]::AdjustToUniversal)
        $remote += [pscustomobject]@{ Name = $name; Size = $size; Stamp = $stamp }
    }

    # Скачиваем то, чего здесь нет. Сначала во временный файл: оборванная
    # загрузка не должна выглядеть как готовая копия.
    $fetched = 0
    foreach ($file in ($remote | Sort-Object Stamp)) {
        $local = Join-Path $Target $file.Name
        if ((Test-Path $local) -and ($file.Size -lt 0 -or (Get-Item $local).Length -eq $file.Size)) { continue }
        $part = "$local.part"
        $response = $client.GetAsync($base + [Uri]::EscapeDataString($file.Name),
            [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) {
            Write-Log ("Не скачать {0}: Яндекс Диск ответил {1}" -f $file.Name, [int]$response.StatusCode)
            continue
        }
        $in = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
        $out = [IO.File]::Create($part)
        try { $in.CopyTo($out) } finally { $out.Dispose(); $in.Dispose() }
        if ($file.Size -ge 0 -and (Get-Item $part).Length -ne $file.Size) {
            Remove-Item $part -Force
            Write-Log ("{0}: скачалось не целиком, повторю в следующий раз" -f $file.Name)
            continue
        }
        Move-Item -Path $part -Destination $local -Force
        $fetched++
        Write-Log ("скачано: {0} ({1:N0} КБ)" -f $file.Name, ($file.Size / 1KB))
    }

    Set-Content -Path $SuccessFile -Value ((Get-Date).ToString('o')) -Encoding UTF8
    $total = (Get-ChildItem -Path $Target -Filter 'tz-*.dump*' | Where-Object { $_.Name -notlike '*.part' }).Count
    Write-Log ("готово: новых {0}, всего на компьютере {1}" -f $fetched, $total)

    # Свежая ли последняя копия. Если сервер перестал выгружать — это надо
    # узнать сразу, а не в день, когда копия понадобится.
    if ($remote.Count -eq 0) {
        Show-Warning 'На Яндекс Диске нет ни одной резервной копии. Сервер их не выгружает — проверьте backup на сервере.'
    } else {
        $newest = ($remote | Sort-Object Stamp | Select-Object -Last 1)
        $age = ((Get-Date).ToUniversalTime() - $newest.Stamp).TotalHours
        if ($age -gt $StaleHours) {
            Show-Warning ("Последняя копия на Яндекс Диске сделана {0:N0} ч назад ({1}). Сервер перестал выгружать копии — проверьте контейнер backup." -f $age, $newest.Name)
        }
    }
} finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
