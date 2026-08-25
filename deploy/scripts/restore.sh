#!/bin/sh
# Восстановление из бэкапа. Проверять на чистой машине не реже раза в квартал
# и записывать фактическое время восстановления в docs/DEPLOY.md.
#
#   sh restore.sh /backups/tz-20260901T030000Z.dump.age [имя_базы]
set -eu

ARCHIVE="${1:?укажите файл бэкапа}"
TARGET_DB="${2:-${POSTGRES_DB:-tverdyy_znak}_restore}"

export PGPASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD обязателен}"
PGHOST="${POSTGRES_HOST:-db}"
PGUSER="${POSTGRES_USER:-tz}"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

case "$ARCHIVE" in
    *.age)
        : "${BACKUP_AGE_IDENTITY:?нужен приватный ключ age в BACKUP_AGE_IDENTITY}"
        age --decrypt --identity "$BACKUP_AGE_IDENTITY" --output "$WORK/dump" "$ARCHIVE"
        ;;
    *.gpg)
        gpg --batch --yes --decrypt --output "$WORK/dump" "$ARCHIVE"
        ;;
    *)
        cp "$ARCHIVE" "$WORK/dump"
        ;;
esac

echo "[$(date -u)] создаю базу ${TARGET_DB}"
createdb --host="$PGHOST" --username="$PGUSER" "$TARGET_DB" 2>/dev/null || \
    echo "база уже существует, восстанавливаю поверх"

START="$(date +%s)"
pg_restore --host="$PGHOST" --username="$PGUSER" --dbname="$TARGET_DB" \
           --no-owner --no-privileges --clean --if-exists "$WORK/dump"
END="$(date +%s)"

echo "[$(date -u)] восстановлено за $((END - START)) с в базу ${TARGET_DB}"
echo
echo "Что проверить после восстановления:"
echo "  1. Число учеников и оценок совпадает с ожидаемым."
echo "  2. FIELD_ENCRYPTION_KEYS содержит ключ, которым шифровались поля,"
echo "     иначе даты рождения и документы не прочитаются."
echo "  3. python manage.py check --deploy проходит без ошибок."
