<#
.SYNOPSIS
    Выкат «Твёрдого знака» одной командой.

.DESCRIPTION
    Обычный путь — не этот: пуш в ветку запускает GitHub Actions, который
    прогоняет тесты и выкатывает сам (.github/workflows/deploy.yml).
    Скрипт нужен, когда выкатить надо прямо сейчас: Actions недоступны,
    упали, или изменение на сервере, а не в коде.

    Что происходит на сервере, описано в deploy/scripts/remote-deploy.sh —
    один и тот же файл для CI и для ручного запуска. Тесты локально не
    гоняются: их место в CI, где база всегда есть.

.EXAMPLE
    .\deploy\deploy.ps1
    .\deploy\deploy.ps1 -SkipPush          # выкатить то, что уже в origin
    .\deploy\deploy.ps1 -Branch main
#>
[CmdletBinding()]
param(
    [string]$Server = "tz@85.198.66.41",   # приложение работает не от root
    [string]$Path   = "/srv/tverdyy-znak",
    [string]$Branch = "",
    [switch]$SkipPush
)

$ErrorActionPreference = "Stop"

function Write-Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Write-Ok($text)   { Write-Host "   $text" -ForegroundColor Green }

if (-not (Test-Path ".git")) {
    throw "Запускать из корня проекта: там, где лежит manage.py"
}
if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    throw "Не найден ssh. Установить: Параметры → Приложения → Дополнительные компоненты → OpenSSH Client."
}
if (-not $Branch) {
    $Branch = (git rev-parse --abbrev-ref HEAD).Trim()
}

Write-Step "Ветка: $Branch"

$dirty = git status --porcelain
if ($dirty) {
    Write-Host "   Есть незакоммиченные изменения — на сервер они не поедут:" -ForegroundColor Yellow
    git status --short
    $answer = Read-Host "   Продолжить? (y/N)"
    if ($answer -ne "y") { throw "Отменено. Сначала закоммитьте изменения." }
}

if (-not $SkipPush) {
    Write-Step "Отправляю в origin"
    git push origin $Branch
    # Код возврата проверяем обязательно: молча выкатить старый коммит,
    # потому что пуш отклонён, — худшее, что может сделать этот скрипт.
    if ($LASTEXITCODE -ne 0) {
        throw "git push не прошёл. Скорее всего в origin есть коммиты, которых нет у вас: git pull --rebase"
    }
    Write-Ok "Запушено"
}

Write-Step "Выкатываю на $Server"
# Рабочую копию на сервере обновляем до вызова скрипта, а не внутри него:
# сам скрипт приезжает вместе с кодом, и запустить ещё не доставленную
# версию нельзя. Внутри fetch повторяется — второй раз он ничего не меняет.
$remote = "cd '$Path' && git fetch origin '$Branch' && git reset --hard 'origin/$Branch'" +
          " && bash deploy/scripts/remote-deploy.sh '$Branch'"
ssh $Server $remote
if ($LASTEXITCODE -ne 0) {
    throw "Выкат не прошёл. Логи: ssh $Server 'cd $Path && docker compose logs --tail=50 web'"
}

Write-Host "`nГотово: https://tverdyy-znak.ru" -ForegroundColor Green
