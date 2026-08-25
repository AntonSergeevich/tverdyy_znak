#!/bin/bash
# Первый выпуск сертификата Let's Encrypt.
#
# Важно: выпускаем в режиме --standalone, а не --webroot. Webroot требует
# работающего nginx, а nginx не поднимется без сертификата — тупик.
# Standalone сам поднимает временный сервер на 80 порту.
# Продление потом идёт через webroot: там nginx уже работает.
#
#   cd /srv/tverdyy-znak && bash deploy/scripts/issue-cert.sh
set -euo pipefail

DOMAIN="${DOMAIN:-tverdyy-znak.ru}"
EMAIL="${CERT_EMAIL:-admin@${DOMAIN}}"
PROJECT="$(basename "$(pwd)")"

echo "== Проверяю, что домен указывает на этот сервер"
SERVER_IP="$(curl -fsS --max-time 10 https://api.ipify.org || echo '')"
DOMAIN_IP="$(getent hosts "$DOMAIN" | awk '{print $1}' | head -1 || echo '')"
if [ -n "$SERVER_IP" ] && [ -n "$DOMAIN_IP" ] && [ "$SERVER_IP" != "$DOMAIN_IP" ]; then
    echo "   $DOMAIN → $DOMAIN_IP, а сервер $SERVER_IP."
    echo "   A-запись ещё не разошлась. Let's Encrypt выдаст ошибку — подождите DNS."
    exit 1
fi
echo "   $DOMAIN → ${DOMAIN_IP:-неизвестно}, сервер ${SERVER_IP:-неизвестно}"

echo "== Останавливаю nginx, чтобы освободить 80 порт"
docker compose stop nginx 2>/dev/null || true

echo "== Выпускаю сертификат"
docker run --rm -p 80:80 \
    -v "${PROJECT}_certbot-conf:/etc/letsencrypt" \
    -v "${PROJECT}_certbot-www:/var/www/certbot" \
    certbot/certbot certonly --standalone \
    -d "$DOMAIN" -d "www.$DOMAIN" \
    --email "$EMAIL" --agree-tos --no-eff-email --non-interactive

echo "== Поднимаю nginx"
docker compose up -d nginx
sleep 3
docker compose ps nginx

echo
echo "Готово. Проверить: curl -sI https://$DOMAIN/healthz | head -1"
