<#
.SYNOPSIS
    Деплой «Твёрдого знака» на сервер одной командой.

.DESCRIPTION
    Запускается из PowerShell внутри PyCharm, из корня проекта.
    Пушит текущую ветку, забирает её на сервере и перезапускает контейнеры.
    Миграции применяются внутри контейнера web при старте.

.EXAMPLE
    .\deploy\deploy.ps1
    .\deploy\deploy.ps1 -SkipTests          # если локальной базы нет
    .\deploy\deploy.ps1 -Branch main -SkipPush
#>
[CmdletBinding()]
param(
    [string]$Server  = "tz@85.198.66.41",   # приложение работает не от root
    [string]$Path    = "/srv/tverdyy-znak",
    [string]$Branch  = "",
    [switch]$SkipPush,
    [switch]$SkipTests,
    [switch]$Rebuild
)

$ErrorActionPreference = "Stop"

# В PowerShell 7.4+ ненулевой код возврата внешней команды сам бросает
# исключение — и наши разборчивые сообщения до пользователя не доходят,
# он видит только стектрейс. Коды возврата проверяем сами.
if (Get-Variable PSNativeCommandUseErrorActionPreference -Scope Global -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}

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

if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    throw "Не найден ssh. Установить: Settings → Приложения → Дополнительные компоненты → OpenSSH Client."
}

# ── Тесты: красный прогон на прод не выкатываем ─────────────────────────────
# Тестам нужен локальный PostgreSQL. Если его нет — -SkipTests, но тогда
# прогоните тесты хотя бы на сервере после выката.
if ($SkipTests) {
    Write-Host "`n== Тесты пропущены (-SkipTests)" -ForegroundColor Yellow
} else {
    Write-Step "Прогоняю тесты"

    # Python берём из окружения проекта, а не с PATH. Иначе тесты уедут
    # в системный Python, где нет зависимостей, и разбираться придётся
    # в простыне ImportError вместо одной понятной строчки.
    $python = @(".venv\Scripts\python.exe", "venv\Scripts\python.exe",
                ".venv/bin/python", "venv/bin/python") |
              Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $python) {
        throw @"
Не нашёл виртуальное окружение проекта (.venv). Создать и наполнить:
    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    pip install -r requirements.txt -r requirements-dev.txt
Либо выкатить без тестов: .\deploy\deploy.ps1 -SkipTests
"@
    }
    Write-Ok "Python: $python"

    & $python -c "import pytest, decouple" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw @"
В окружении $python не хватает зависимостей. Поставить:
    & '$python' -m pip install -r requirements.txt -r requirements-dev.txt
Либо выкатить без тестов: .\deploy\deploy.ps1 -SkipTests
"@
    }

    $env:DJANGO_SETTINGS_MODULE = "config.settings.test"
    & $python -m pytest -q
    if ($LASTEXITCODE -ne 0) {
        throw "Тесты не прошли — деплой остановлен. Если дело в отсутствии локальной базы: .\deploy\deploy.ps1 -SkipTests"
    }
    Write-Ok "Тесты зелёные"
}

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
# Справочники — часть кода: список предметов и данные организации объявлены
# источником истины, поэтому приводятся к нему на каждом выкате.
# Обе команды идемпотентны и ничего не удаляют.
docker compose exec -T web python manage.py bootstrap_organization
docker compose exec -T web python manage.py setup_client_data
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
