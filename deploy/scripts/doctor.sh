#!/bin/bash
# Диагностика: почему сайт не отвечает.
# Запускать на сервере из каталога проекта:
#   cd /srv/tverdyy-znak && bash deploy/scripts/doctor.sh
#
# Ничего не меняет, только собирает факты. Секреты не печатает —
# только то, какие переменные пустые.
set -uo pipefail

DOMAIN="${DOMAIN:-tverdyy-znak.ru}"
line() { printf '\n== %s\n' "$1"; }

line "Контейнеры"
docker compose ps --format 'table {{.Service}}\t{{.Status}}\t{{.Ports}}' 2>&1

line "Проверка конфигурации nginx"
docker compose exec -T nginx nginx -t 2>&1 || echo "nginx не запущен — смотрите его логи ниже"

line "Сертификат"
docker compose exec -T nginx ls -la "/etc/letsencrypt/live/$DOMAIN/" 2>&1 | tail -6

line "Кто слушает 80 и 443 на хосте"
ss -tlnp 2>/dev/null | grep -E ':80 |:443 ' || echo "НИКТО не слушает 80/443 — nginx не поднялся"

line "Ответ изнутри сервера"
echo "--- http://127.0.0.1 (ожидается 301 на https)"
curl -sS -o /dev/null -w 'код %{http_code}\n' --max-time 10 -H "Host: $DOMAIN" http://127.0.0.1/ 2>&1
echo "--- https://127.0.0.1 (ожидается 200)"
curl -sSk -o /dev/null -w 'код %{http_code}\n' --max-time 10 -H "Host: $DOMAIN" https://127.0.0.1/ 2>&1
echo "--- приложение напрямую, мимо nginx (ожидается 200)"
docker compose exec -T web curl -sS -o /dev/null -w 'код %{http_code}\n' --max-time 10 \
    http://127.0.0.1:8000/healthz 2>&1

line "Файрвол"
ufw status 2>/dev/null | head -12 || echo "ufw недоступен"

line "Заполненность .env (значения не печатаются)"
for key in DJANGO_SECRET_KEY DJANGO_ALLOWED_HOSTS POSTGRES_PASSWORD DATABASE_URL \
           FIELD_ENCRYPTION_KEYS TG_BOT_TOKEN TG_CHAT_ID; do
    value="$(grep -E "^${key}=" .env 2>/dev/null | head -1 | cut -d= -f2-)"
    if [ -z "$value" ]; then
        printf '  %-24s ПУСТО\n' "$key"
    else
        printf '  %-24s задано (%s символов)\n' "$key" "${#value}"
    fi
done

line "Логи nginx (последние 30 строк)"
docker compose logs --tail=30 --no-log-prefix nginx 2>&1

line "Логи приложения (последние 40 строк)"
docker compose logs --tail=40 --no-log-prefix web 2>&1

line "Фотографии педагогов"
docker compose exec -T web sh -c 'ls assets/teachers/ 2>/dev/null | head; echo "---"; ls media/teachers/ 2>/dev/null | head' 2>&1

printf '\n== Готово. Пришлите этот вывод целиком.\n'
