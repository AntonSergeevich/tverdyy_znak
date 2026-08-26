#!/usr/bin/env bash
#
# Выкат на сервере. Единственное место, где описано, что именно
# происходит при деплое: и GitHub Actions, и deploy.ps1 вызывают этот
# скрипт, чтобы «через CI» и «руками» не разъезжались.
#
#   sudo -u tz bash /srv/tverdyy-znak/deploy/scripts/remote-deploy.sh <ветка>
#
set -euo pipefail

BRANCH="${1:-${DEPLOY_BRANCH:-main}}"
APP_DIR="${DEPLOY_PATH:-/srv/tverdyy-znak}"

step() { printf '\n\033[36m== %s\033[0m\n' "$1"; }

cd "$APP_DIR"

step "Забираю $BRANCH"
git fetch origin "$BRANCH"
git reset --hard "origin/$BRANCH"
git log -1 --pretty='  %h %s'

step "Собираю образы"
docker compose build web worker beat

# --wait: ждём, пока web станет healthy. Миграции и статику выполняет сам
# контейнер при старте (см. command в docker-compose.yml), и запускать их
# отсюда параллельно нельзя: две миграции одновременно дерутся за одну
# таблицу, и одна падает с «relation already exists».
step "Поднимаю контейнеры и жду готовности"
docker compose up -d --wait

step "Справочники"
# Модули, предметы и реквизиты объявлены в коде источником истины,
# поэтому база приводится к ним на каждом выкате. Тексты и цены,
# которые правятся в админке, команды не трогают.
docker compose exec -T web python manage.py bootstrap_organization
# Фотографии живут в томе, а не в образе: WebP пересобирается из
# оригиналов на месте, новые снимки подхватываются сами.
docker compose exec -T web python scripts/prepare_teacher_photos.py
docker compose exec -T web python manage.py setup_client_data

step "Перечитываю конфигурацию nginx"
# nginx запоминает адрес контейнера web при старте, а мы его только что
# пересоздали. Без перечитывания он отдаёт 502 на старый адрес.
docker compose exec -T nginx nginx -s reload

step "Проверяю, что приложение отвечает"
# Изнутри сети, а не снаружи: так проверка не зависит от DNS и TLS
# и говорит именно о приложении.
for attempt in $(seq 1 10); do
    if docker compose exec -T web curl -fsS http://127.0.0.1:8000/healthz >/dev/null; then
        echo "  healthz отвечает (попытка $attempt)"
        break
    fi
    if [ "$attempt" = "10" ]; then
        echo "  healthz молчит. Логи:" >&2
        docker compose logs --tail=50 web >&2
        exit 1
    fi
    sleep 3
done

step "Состояние контейнеров"
docker compose ps
