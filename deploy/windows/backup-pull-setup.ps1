<#
.SYNOPSIS
  Установить на этот компьютер забор резервных копий «Твёрдого знака» с Яндекс Диска.

.DESCRIPTION
  Один раз:
    1. спрашивает логин Яндекса и ПАРОЛЬ ПРИЛОЖЕНИЯ (доступ «Файлы (WebDAV)»,
       не основной пароль) и сохраняет их зашифрованными средствами Windows —
       прочитать их сможет только эта учётная запись на этом компьютере;
    2. кладёт backup-pull.ps1 в %LOCALAPPDATA%\TverdyyZnak;
    3. заводит задание в Планировщике: при входе в Windows и каждый час.
       Пропущенный запуск (компьютер был выключен или спал) выполняется
       сразу, как только компьютер снова работает;
    4. сразу делает первый запуск, чтобы было видно, что всё работает.

  Запуск из папки репозитория:
    powershell -ExecutionPolicy Bypass -File deploy\windows\backup-pull-setup.ps1

  Другая папка для копий:
    ... -File deploy\windows\backup-pull-setup.ps1 -Target D:\Бэкапы\ТвёрдыйЗнак

  Убрать задание:
    ... -File deploy\windows\backup-pull-setup.ps1 -Uninstall
#>
param(
    [string]$Target = (Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'TverdyyZnak-backups'),
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$TaskName = 'TverdyyZnak backup pull'
$AppDir = Join-Path $env:LOCALAPPDATA 'TverdyyZnak'

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Задание «$TaskName» убрано. Скачанные копии остались в папке, их скрипт не трогает."
    exit 0
}

New-Item -ItemType Directory -Force -Path $AppDir, $Target | Out-Null

Write-Host ''
Write-Host 'Сейчас откроется окно входа.'
Write-Host '  Имя пользователя — логин Яндекса, на котором лежат копии (например, tz-backup@yandex.ru).'
Write-Host '  Пароль — ПАРОЛЬ ПРИЛОЖЕНИЯ с доступом «Файлы (WebDAV)», а не основной пароль.'
Write-Host '  Завести его: id.yandex.ru → Безопасность → Пароли приложений.'
Write-Host ''
$cred = Get-Credential -Message 'Логин Яндекса и пароль приложения «Файлы (WebDAV)»'
if (-not $cred) { throw 'Отменено.' }
$cred | Export-Clixml -Path (Join-Path $AppDir 'yadisk.xml')

$script = Join-Path $AppDir 'backup-pull.ps1'
Copy-Item -Path (Join-Path $PSScriptRoot 'backup-pull.ps1') -Destination $script -Force

$arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`" -Target `"$Target`""
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments
$user = "$env:USERDOMAIN\$env:USERNAME"
$atLogon = New-ScheduledTaskTrigger -AtLogOn -User $user
$hourly = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Hours 1)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $atLogon, $hourly `
    -Settings $settings -Principal $principal -Force `
    -Description 'Твёрдый знак: забирает новые резервные копии с Яндекс Диска в папку на компьютере. Ничего не удаляет.' | Out-Null

Write-Host ''
Write-Host "Задание «$TaskName» заведено: при входе в Windows и каждый час."
Write-Host "Копии будут лежать в: $Target"
Write-Host ''
Write-Host 'Первый запуск — проверка:'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $script -Target $Target
if ($LASTEXITCODE -eq 0) {
    Write-Host ''
    Write-Host 'Работает. Дальше всё идёт само.'
} else {
    Write-Host ''
    Write-Host "Первый запуск не удался — см. строки выше и $Target\pull.log."
}
