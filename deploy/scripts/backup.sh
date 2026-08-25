#!/bin/sh
# Бэкап PostgreSQL: дамп, шифрование, ротация 30 дней, выгрузка за пределы VPS.
#
# Бэкап, который не восстанавливали, бэкапом не является — сценарий
# восстановления лежит рядом: restore.sh. Проверять раз в квартал.
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-30}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DUMP="${BACKUP_DIR}/tz-${STAMP}.dump"

mkdir -p "$BACKUP_DIR"

# Параметры подключения берём из DATABASE_URL.
export PGPASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD обязателен}"
PGHOST="${POSTGRES_HOST:-db}"
PGUSER="${POSTGRES_USER:-tz}"
PGDATABASE="${POSTGRES_DB:-tverdyy_znak}"

echo "[$(date -u)] дамп ${PGDATABASE}"
pg_dump --host="$PGHOST" --username="$PGUSER" --dbname="$PGDATABASE" \
        --format=custom --no-owner --no-privileges --file="$DUMP"

# Шифрование. Ключ хранится НЕ на этом сервере (ТЗ 8.1).
if [ -n "${BACKUP_AGE_RECIPIENT:-}" ] && command -v age >/dev/null 2>&1; then
    age --recipient "$BACKUP_AGE_RECIPIENT" --output "${DUMP}.age" "$DUMP"
    rm -f "$DUMP"
    ARTIFACT="${DUMP}.age"
elif [ -n "${BACKUP_GPG_RECIPIENT:-}" ] && command -v gpg >/dev/null 2>&1; then
    gpg --batch --yes --encrypt --recipient "$BACKUP_GPG_RECIPIENT" --output "${DUMP}.gpg" "$DUMP"
    rm -f "$DUMP"
    ARTIFACT="${DUMP}.gpg"
else
    echo "ВНИМАНИЕ: шифрование не настроено (BACKUP_AGE_RECIPIENT / BACKUP_GPG_RECIPIENT)." >&2
    echo "Дамп с персональными данными детей лежит в открытом виде." >&2
    ARTIFACT="$DUMP"
fi

echo "[$(date -u)] готово: ${ARTIFACT} ($(du -h "$ARTIFACT" | cut -f1))"

# Копия за пределы VPS: rsync/scp/rclone — что настроено.
if [ -n "${BACKUP_REMOTE_TARGET:-}" ]; then
    if command -v rclone >/dev/null 2>&1; then
        rclone copy "$ARTIFACT" "$BACKUP_REMOTE_TARGET" && echo "выгружено в $BACKUP_REMOTE_TARGET"
    else
        scp -o StrictHostKeyChecking=accept-new "$ARTIFACT" "$BACKUP_REMOTE_TARGET" \
            && echo "выгружено в $BACKUP_REMOTE_TARGET"
    fi
else
    echo "ВНИМАНИЕ: BACKUP_REMOTE_TARGET не задан — копии за пределами VPS нет." >&2
fi

# Ротация.
find "$BACKUP_DIR" -name 'tz-*.dump*' -type f -mtime "+${KEEP_DAYS}" -delete
echo "[$(date -u)] хранится файлов: $(find "$BACKUP_DIR" -name 'tz-*.dump*' | wc -l)"
