<#
.SYNOPSIS
    Деплой «Твёрдого знака» на сервер одной командой.

.DESCRIPTION
    Запускается из PowerShell внутри PyCharm, из корня проекта.
    Пушит текущую ветку, забирает её на сервере и перезапускает контейнеры.
    Миграции применяются внутри контейнера web при старте.

.EXAMPLE
    .\deploy\deploy.ps1
    .\deploy\deploy.ps1 -Branch main -SkipPush
#>
[CmdletBinding()]
param(
    [string]$Server  = "root@85.198.66.41",
    [string]$Path    = "/srv/tverdyy-znak",
    [string]$Branch  = "",
    [switch]$SkipPush,
    [switch]$Rebuild
)

$ErrorActionPreference = "Stop"

function Write-Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Write-Ok($text)   { Write-Host "   $text" -ForegroundColor Green }

# ── Проверки перед выкатом ──────────────────────────────────────────────────
Write-Step "Проверяю рабочую копию"

if (-not (Test-Path ".git")) {
    throw "Запускать из корня проекта: там, где лежит manage.py"
}

if (-not $Branch) {
    $Branch = (git rev-parse --abbrev-ref HEAD).Trim()
}
Write-Ok "Ветка: $Branch"

$dirty = git status --porcelain
if ($dirty) {
    Write-Host "   Есть незакоммиченные изменения:" -ForegroundColor Yellow
    git status --short
    $answer = Read-Host "   Продолжить деплой без них? (y/N)"
    if ($answer -ne "y") { throw "Отменено. Сначала закоммитьте изменения." }
}

# ── Тесты: красный прогон на прод не выкатываем ─────────────────────────────
Write-Step "Прогоняю тесты"
$env:DJANGO_SETTINGS_MODULE = "config.settings.test"
pytest -q
if ($LASTEXITCODE -ne 0) { throw "Тесты не прошли — деплой остановлен." }
Write-Ok "Тесты зелёные"

# ── Пуш ─────────────────────────────────────────────────────────────────────
if (-not $SkipPush) {
    Write-Step "Отправляю в origin"
    git push origin $Branch
    Write-Ok "Запушено"
}

# ── Выкат ───────────────────────────────────────────────────────────────────
Write-Step "Выкатываю на $Server"

$buildFlag = if ($Rebuild) { "--build" } else { "" }
$remote = @"
set -e
cd $Path
git fetch origin $Branch
git reset --hard origin/$Branch
docker compose build web worker beat
docker compose up -d $buildFlag
docker compose exec -T web python manage.py migrate --noinput
docker compose exec -T web python manage.py collectstatic --noinput
docker compose ps
"@

ssh $Server $remote
if ($LASTEXITCODE -ne 0) { throw "Удалённые команды завершились с ошибкой." }

# ── Проверка после выката ───────────────────────────────────────────────────
Write-Step "Проверяю, что сайт отвечает"
try {
    $response = Invoke-WebRequest -Uri "https://tverdyy-znak.ru/healthz" -TimeoutSec 20 -UseBasicParsing
    if ($response.StatusCode -eq 200) { Write-Ok "healthz отвечает 200" }
} catch {
    Write-Host "   Сайт не ответил: $($_.Exception.Message)" -ForegroundColor Yellow
    Write-Host "   Логи: ssh $Server 'cd $Path && docker compose logs --tail=50 web'" -ForegroundColor Yellow
    exit 1
}

Write-Host "`nГотово." -ForegroundColor Green
