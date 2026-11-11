#!/bin/sh
# Яндекс Диск по WebDAV: выгрузить файл бэкапа и убрать слишком старые.
#
#   sh yadisk.sh upload /backups/tz-20261111T200000Z.dump.age
#   sh yadisk.sh rotate
#
# Доступ — пароль приложения Яндекса с правом «Файлы (WebDAV)», не основной
# пароль аккаунта: YADISK_LOGIN, YADISK_APP_PASSWORD в .env. Пароль не
# попадает в командную строку (её видно в списке процессов) — он уходит
# в curl через временный netrc-файл, доступный только владельцу.
set -eu

ACTION="${1:?upload ФАЙЛ | rotate}"
BASE="${YADISK_WEBDAV_URL:-https://webdav.yandex.ru}"
DIR="${YADISK_DIR:-/tverdyy-znak-backups}"
KEEP_DAYS="${YADISK_KEEP_DAYS:-180}"

HOST="$(echo "$BASE" | sed -E 's#^[a-z]+://([^/:]+).*#\1#')"
NETRC="$(mktemp)"
trap 'rm -f "$NETRC"' EXIT
chmod 600 "$NETRC"
printf 'machine %s login %s password %s\n' \
    "$HOST" "${YADISK_LOGIN:?YADISK_LOGIN обязателен}" "${YADISK_APP_PASSWORD:?YADISK_APP_PASSWORD обязателен}" > "$NETRC"

dav() {
    curl --silent --show-error --netrc-file "$NETRC" --connect-timeout 20 "$@"
}

case "$ACTION" in
    upload)
        FILE="${2:?какой файл выгрузить}"
        NAME="$(basename "$FILE")"
        # Папка: 201 — создана, 405 — уже есть. Остальное — повод разбираться.
        CODE="$(dav -o /dev/null -w '%{http_code}' -X MKCOL "$BASE$DIR/")"
        case "$CODE" in
            201|405) ;;
            *) echo "Яндекс Диск: не создать папку $DIR (HTTP $CODE)" >&2; exit 1 ;;
        esac
        # Сначала под временным именем, потом переименование: компьютер,
        # забирающий копии, не должен увидеть недокачанный файл.
        dav --fail --retry 3 --retry-delay 15 --retry-all-errors \
            -T "$FILE" "$BASE$DIR/$NAME.part"
        dav --fail -X MOVE -H "Destination: $DIR/$NAME" -H "Overwrite: T" "$BASE$DIR/$NAME.part"
        echo "[$(date -u)] выгружено на Яндекс Диск: $DIR/$NAME"
        ;;
    rotate)
        # Копии старше KEEP_DAYS — долой: место на Диске не бесконечно.
        # Компьютер владельца сам ничего не удаляет, у него остаются все.
        CUTOFF="$(date -u -d "-${KEEP_DAYS} days" +%Y%m%d)"
        LISTING="$(dav --fail -X PROPFIND -H "Depth: 1" "$BASE$DIR/")"
        echo "$LISTING" | grep -o 'tz-[0-9]\{8\}T[0-9]\{6\}Z\.dump[A-Za-z.]*' | sort -u | while read -r NAME; do
            DAY="$(echo "$NAME" | cut -c4-11)"
            if [ "$DAY" -lt "$CUTOFF" ]; then
                dav --fail -X DELETE "$BASE$DIR/$NAME" -o /dev/null && echo "убрана старая копия: $NAME"
            fi
        done
        ;;
    *)
        echo "неизвестное действие: $ACTION" >&2
        exit 2
        ;;
esac
