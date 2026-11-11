#!/bin/sh
# Ежедневный бэкап без внешнего cron: контейнер сам держит расписание.
set -eu

# Часы запуска по UTC через запятую. Одного раза в сутки мало: потерять
# можно целый учебный день баллов. По умолчанию — 03:00 по Красноярску;
# рекомендуемое — каждые 6 часов: BACKUP_HOURS_UTC=20,2,8,14
# (03:00, 09:00, 15:00, 21:00 по Красноярску).
HOURS="${BACKUP_HOURS_UTC:-${BACKUP_HOUR_UTC:-20}}"
# «08» и «8» — одно и то же время; date +%-H даёт без нуля.
HOURS="$(echo "$HOURS" | tr -d ' ' | sed -E 's/(^|,)0+([0-9])/\1\2/g')"
echo "backup-loop запущен, по UTC в часы: ${HOURS}"

while :; do
    NOW_H="$(date -u +%-H)"
    NOW_M="$(date -u +%M)"
    case ",$HOURS," in *",$NOW_H,"*) DUE=1 ;; *) DUE=0 ;; esac
    if [ "$DUE" = 1 ] && [ "$NOW_M" = "00" ]; then
        sh /scripts/backup.sh || echo "БЭКАП НЕ УДАЛСЯ — разобраться немедленно" >&2
        sleep 3600
    else
        sleep 60
    fi
done
