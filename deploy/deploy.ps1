<#
.SYNOPSIS
    Выкат «Твёрдого знака» одной командой.

.DESCRIPTION
    Обычный путь — не этот: пуш в ветку запускает GitHub Actions, который
    прогоняет тесты и выкатывает сам (.github/workflows/deploy.yml).

    Скрипт — обёртка над той же серверной командой `tz-deploy`, ради
    единственного удобства: он ещё и пушит текущую ветку. Если пушить
    нечего, ровно то же делает

        ssh tz@85.198.66.41 tz-deploy

.EXAMPLE
    .\deploy\deploy.ps1
    .\deploy\deploy.ps1 -SkipPush          # выкатить то, что уже в origin
    .\deploy\deploy.ps1 -Branch main
#>
[CmdletBinding()]
param(
    [string]$Server = "tz@85.198.66.41",   # приложение работает не от root
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
# Вся серверная логика живёт в tz-deploy: одна команда и там, и здесь.
# Если короткая команда на сервере ещё не установлена, зовём скрипт
# по полному пути: выкат не должен зависеть от симлинка.
ssh $Server "command -v tz-deploy >/dev/null && tz-deploy '$Branch' || bash /srv/tverdyy-znak/deploy/scripts/pull-and-deploy.sh '$Branch'"
if ($LASTEXITCODE -ne 0) {
    throw "Выкат не прошёл. Логи: ssh $Server 'cd /srv/tverdyy-znak && docker compose logs --tail=50 web'"
}

Write-Host "`nГотово: https://tverdyy-znak.ru" -ForegroundColor Green
