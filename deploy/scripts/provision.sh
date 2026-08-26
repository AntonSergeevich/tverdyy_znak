#!/bin/bash
# Первичная подготовка чистого сервера Ubuntu 24.04 под «Твёрдый знак».
# Запускать от root ОДИН раз. С Windows — копированием, а не конвейером:
# PowerShell отдаёт файл с CRLF, и bash падает на «invalid option name».
#   scp deploy/scripts/provision.sh root@СЕРВЕР:/tmp/provision.sh
#   ssh root@СЕРВЕР "sed -i 's/\r$//' /tmp/provision.sh && bash /tmp/provision.sh"
set -euo pipefail

APP_USER="${APP_USER:-tz}"
APP_DIR="${APP_DIR:-/srv/tverdyy-znak}"

echo "== Обновление пакетов"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl git ufw fail2ban age rsync

echo "== Docker"
if ! command -v docker >/dev/null 2>&1; then
    curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

echo "== Пользователь приложения"
if ! id "$APP_USER" >/dev/null 2>&1; then
    adduser --disabled-password --gecos "" "$APP_USER"
fi
usermod -aG docker "$APP_USER"
mkdir -p "$APP_DIR"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

echo "== Ключи SSH для пользователя приложения"
mkdir -p "/home/$APP_USER/.ssh"
if [ -f /root/.ssh/authorized_keys ]; then
    cp /root/.ssh/authorized_keys "/home/$APP_USER/.ssh/authorized_keys"
fi
chmod 700 "/home/$APP_USER/.ssh"
chmod 600 "/home/$APP_USER/.ssh/authorized_keys" 2>/dev/null || true
chown -R "$APP_USER:$APP_USER" "/home/$APP_USER/.ssh"

echo "== Каталог приложения как доверенный для git"
# Каталог принадлежит $APP_USER, и git из-под root отказывается с ним
# работать: «detected dubious ownership». Помечаем доверенным для обоих —
# иначе любая команда, случайно запущенная не тем пользователем, падает.
git config --global --add safe.directory "$APP_DIR" 2>/dev/null || true
sudo -u "$APP_USER" git config --global --add safe.directory "$APP_DIR" 2>/dev/null || true

echo "== Команда выката"
# Одна короткая команда вместо длинной строки с путями: «tz-deploy»
# работает и на сервере, и снаружи через ssh tz@<host> tz-deploy.
# Симлинк, а не копия: обновляется вместе с репозиторием.
ln -sf "$APP_DIR/deploy/scripts/pull-and-deploy.sh" /usr/local/bin/tz-deploy

echo "== Файрвол"
ufw --force default deny incoming
ufw --force default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "== fail2ban"
systemctl enable --now fail2ban

echo "== Вход по паролю отключаем (только ключи)"
# Делается последним: если ключ не работает, останется шанс успеть починить.
if grep -q "^PasswordAuthentication" /etc/ssh/sshd_config; then
    sed -i 's/^PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
else
    echo "PasswordAuthentication no" >> /etc/ssh/sshd_config
fi
systemctl reload ssh

echo
echo "Готово."
echo
echo "Дальше подключаемся НЕ от root, а от $APP_USER — тем же ключом:"
echo "  ssh $APP_USER@<адрес сервера>"
echo
echo "Приложение работает от непривилегированного пользователя, и все"
echo "команды деплоя выполняются от него же:"
echo "  1. cd $APP_DIR"
echo "  2. git clone <репозиторий> ."
echo "  3. cp .env.example .env && chmod 600 .env   # заполнить секреты"
echo "  4. docker compose up -d --build"
