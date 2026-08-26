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
if ($SkipTests) {
    Write-Host "`n== Тесты пропущены (-SkipTests)" -ForegroundColor Yellow
} else {
    Write-Step "Прогоняю тесты"

    # PowerShell 5.1 при $ErrorActionPreference = "Stop" считает любую строку
    # в stderr внешней команды терминальной ошибкой. Здесь мы коды возврата
    # проверяем сами, поэтому на время прогона это поведение выключаем —
    # иначе вместо разбираемого сообщения пользователь видит NativeCommandError.
    $savedEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
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

        $env:DJANGO_SETTINGS_MODULE = "config.settings.test"

        # Проверяем, есть ли условия для прогона: зависимости и живой
        # PostgreSQL. Отсутствие базы на ноутбуке — не красный прогон,
        # и валить из-за него выкат нельзя.
        #
        # Скрипт молчит в stderr намеренно: причину он печатает в stdout
        # одной строкой и возвращает код. Так PowerShell не превращает
        # traceback в собственную ошибку поверх нашей.
        $probe = @'
import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")


def fail(reason):
    print(reason)
    raise SystemExit(1)


try:
    import django
    import psycopg  # noqa: F401
    import pytest  # noqa: F401
except ImportError as exc:
    fail(f"нет зависимости: {exc}. Поставьте requirements.txt и requirements-dev.txt")

try:
    django.setup()
    from django.conf import settings
except Exception as exc:
    fail(f"настройки не загрузились: {type(exc).__name__}: {exc}")

# Подключаемся к серверу, а не к конкретной базе: базу для тестов
# pytest-django создаёт сам, и её отсутствие проблемой не является.
# Пустой HOST не подменяем на localhost — для Django это означает
# «через unix-сокет», и подмена сломала бы проверку там, где всё работает.
db = settings.DATABASES["default"]
try:
    psycopg.connect(
        host=db.get("HOST") or None,
        port=db.get("PORT") or None,
        user=db.get("USER") or None,
        password=db.get("PASSWORD") or None,
        dbname="postgres",
        connect_timeout=5,
    ).close()
except Exception as exc:
    fail(f"база недоступна: {str(exc).strip().splitlines()[0]}")

print("ok")
sys.exit(0)
'@
        $probeOutput = ($probe | & $python -) -join " "
        if ($LASTEXITCODE -ne 0) {
            Write-Host "   Тесты пропускаю: $probeOutput" -ForegroundColor Yellow
            Write-Host "   Это не падение тестов. Прогоните их там, где база есть." -ForegroundColor Yellow
        } else {
            & $python -m pytest -q
            if ($LASTEXITCODE -ne 0) {
                throw "Тесты не прошли — деплой остановлен. Условия для прогона были: смотрите вывод выше."
            }
            Write-Ok "Тесты зелёные"
        }
    } finally {
        $ErrorActionPreference = $savedEap
    }
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
# Фотографии педагогов живут в томе, а не в образе: WebP пересобирается
# из оригиналов на месте. Идемпотентно, новые снимки подхватываются сами.
docker compose exec -T web python scripts/prepare_teacher_photos.py
docker compose exec -T web python manage.py setup_client_data
# nginx запоминает адрес контейнера web при старте, а мы его только что
# пересоздали — без перечитывания конфигурации он отдаёт 502 на новый адрес.
docker compose exec -T nginx nginx -s reload
docker compose ps
"@

# .ps1 хранится в CRLF (так его любит PowerShell 5.1), поэтому в строке
# выше переводы строк — тоже CRLF. Для bash на сервере \r — часть команды:
# он спотыкается на «cd: /srv/tverdyy-znak\r: No such file or directory».
$remote = $remote -replace "`r", ""

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
