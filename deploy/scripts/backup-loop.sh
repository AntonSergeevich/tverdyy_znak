#!/bin/sh
# Ежедневный бэкап без внешнего cron: контейнер сам держит расписание.
set -eu

HOUR="${BACKUP_HOUR_UTC:-20}"   # 03:00 по Красноярску
echo "backup-loop запущен, ежедневно в ${HOUR}:00 UTC"

while :; do
    NOW_H="$(date -u +%H)"
    NOW_M="$(date -u +%M)"
    if [ "$NOW_H" = "$HOUR" ] && [ "$NOW_M" = "00" ]; then
        sh /scripts/backup.sh || echo "БЭКАП НЕ УДАЛСЯ — разобраться немедленно" >&2
        sleep 3600
    else
        sleep 60
    fi
done
