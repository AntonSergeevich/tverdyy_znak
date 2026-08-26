#!/usr/bin/env bash
#
# Выкат одной командой. Ничего, кроме этой строки, помнить не нужно:
#
#   на сервере:        tz-deploy
#   с любой машины:    ssh tz@85.198.66.41 tz-deploy
#
# Ветка по умолчанию — та, что уже выкачена на сервере. Другую можно
# передать аргументом: tz-deploy main
#
# Скрипт существует отдельно от remote-deploy.sh потому, что доставляет
# его: сам remote-deploy.sh приезжает вместе с кодом, и запустить ещё
# не доставленную версию нельзя.
set -euo pipefail

APP_DIR="${DEPLOY_PATH:-/srv/tverdyy-znak}"
cd "$APP_DIR"

BRANCH="${1:-$(git rev-parse --abbrev-ref HEAD)}"
if [ "$BRANCH" = "HEAD" ]; then
    # Рабочая копия в состоянии detached HEAD — обычное дело после
    # git reset --hard origin/<ветка>. Имя ветки берём у отслеживаемой.
    BRANCH="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null | sed 's|^origin/||')"
fi
BRANCH="${BRANCH:-main}"

printf '\033[36m== Обновляю рабочую копию: %s\033[0m\n' "$BRANCH"
git fetch origin "$BRANCH"
git reset --hard "origin/$BRANCH"

exec bash "$APP_DIR/deploy/scripts/remote-deploy.sh" "$BRANCH"
