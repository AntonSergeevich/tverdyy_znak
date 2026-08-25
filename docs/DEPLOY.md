# Развёртывание на Beget VPS

Минимальная конфигурация: 2 vCPU, 4 ГБ RAM, 40 ГБ SSD, Ubuntu 24.04 LTS.
Серверы Beget находятся в РФ — требование о размещении данных российских
граждан выполняется.

## 1. Подготовка сервера

```bash
# от root, один раз
adduser --disabled-password --gecos "" tz
usermod -aG docker tz            # docker ставится отдельно, см. ниже
mkdir -p /srv/tverdyy-znak && chown tz:tz /srv/tverdyy-znak
```

Docker и compose-плагин:

```bash
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker
```

SSH и файрвол:

```bash
# /etc/ssh/sshd_config
PasswordAuthentication no
PermitRootLogin no
systemctl restart ssh

apt install -y fail2ban
systemctl enable --now fail2ban

ufw default deny incoming
ufw allow OpenSSH
ufw allow 80,443/tcp
ufw enable
```

## 2. Код и секреты

```bash
su - tz
cd /srv/tverdyy-znak
git clone <репозиторий> .
cp .env.example .env
chmod 600 .env
```

Заполнить в `.env` обязательно:

| Переменная | Как получить |
|---|---|
| `DJANGO_SECRET_KEY` | `docker compose run --rm web python manage.py generate_secret` |
| `FIELD_ENCRYPTION_KEYS` | `docker compose run --rm web python manage.py generate_fernet_key` |
| `POSTGRES_PASSWORD` | сгенерировать, 32+ символа |
| `DJANGO_ALLOWED_HOSTS` | `tverdyy-znak.ru,www.tverdyy-znak.ru` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://tverdyy-znak.ru,https://www.tverdyy-znak.ru` |
| `TG_BOT_TOKEN`, `TG_CHAT_ID` | у @BotFather и из чата, куда падают заявки |
| `SENTRY_DSN` | из проекта Sentry |
| `BACKUP_AGE_RECIPIENT` | публичный ключ age; **приватный хранить не на этом сервере** |
| `BACKUP_REMOTE_TARGET` | rclone-remote или `user@host:/path` для копии вне VPS |

`FIELD_ENCRYPTION_KEYS` и бэкапы не должны лежать в одном месте: иначе
шифрование бэкапа бессмысленно.

## 3. Сертификат

Первый выпуск — до старта nginx с TLS-конфигом:

```bash
docker compose up -d db redis web
docker run --rm \
  -v tverdyy-znak_certbot-www:/var/www/certbot \
  -v tverdyy-znak_certbot-conf:/etc/letsencrypt \
  certbot/certbot certonly --webroot -w /var/www/certbot \
  -d tverdyy-znak.ru -d www.tverdyy-znak.ru \
  --email admin@tverdyy-znak.ru --agree-tos --no-eff-email
docker compose up -d
```

Дальше продление автоматическое: контейнер `certbot` проверяет дважды
в сутки и обновляет, когда до конца меньше 30 дней.

## 4. Первый запуск

```bash
docker compose up -d --build
docker compose exec web python manage.py bootstrap_organization \
    --slug tverdyy-znak --name "Твёрдый знак" --domain tverdyy-znak.ru
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py check --deploy
```

`check --deploy` должен пройти без предупреждений. Если он ругается —
не выкатываем.

Владелец и администратор при первом входе обязаны подключить второй
фактор: система сама уводит их на страницу подключения.

## 5. Обновление

```bash
cd /srv/tverdyy-znak
git pull
docker compose build web
docker compose run --rm web python manage.py migrate --plan   # что применится
docker compose up -d
```

Каждая миграция должна быть проверена **на копии боевой базы** до выката:

```bash
sh deploy/scripts/restore.sh /backups/<последний>.age tz_staging
DATABASE_URL=postgres://tz:...@db:5432/tz_staging \
    docker compose run --rm web python manage.py migrate
```

Применённые миграции не редактируются и не удаляются.

## 6. Бэкапы

Контейнер `backup` делает `pg_dump` ежедневно в 20:00 UTC (03:00 по
Красноярску), шифрует ключом `BACKUP_AGE_RECIPIENT`, хранит 30 дней
и выгружает копию за пределы VPS.

Ручной запуск:

```bash
docker compose exec backup sh /scripts/backup.sh
```

### Восстановление — проверять, а не надеяться

Бэкап, который не восстанавливали, бэкапом не является. Проверка не реже
раза в квартал, на чистой машине:

```bash
sh deploy/scripts/restore.sh /backups/tz-20260901T030000Z.dump.age tz_restore_check
```

Скрипт печатает фактическое время восстановления. Записывать сюда:

| Дата проверки | Размер дампа | Время восстановления | Кто проверял |
|---|---|---|---|
| _не проводилась_ | | | |

После восстановления проверить: число учеников и оценок, читаемость
зашифрованных полей (нужен тот же `FIELD_ENCRYPTION_KEYS`), `check --deploy`.

## 7. Логи и мониторинг

- логи приложения — `docker compose logs -f web worker`;
- журнал доступа к персональным данным — том `logs`, файл `pdn-access.log`,
  ротация ежедневная, хранение 90 дней;
- ошибки — Sentry, `send_default_pii=False`: данные детей туда не уходят;
- health-check — `GET /healthz`, используется и Docker, и внешним монитором.

## 8. Что проверить перед сдачей первого этапа

- [ ] сайт открывается по домену, TLS валиден, http редиректит на https;
- [ ] форма заявки создаёт лид и присылает уведомление в Telegram;
- [ ] правовые страницы на месте, чекбокс согласия обязателен;
- [ ] заведены организация, педагоги, ученики, предметы, модули;
- [ ] педагог с телефона выставляет баллы, родитель их видит;
- [ ] итог модуля и уровень посчитаны верно на трёх учениках;
- [ ] пользователь другой организации не видит чужого (`pytest tests/test_tenancy.py`);
- [ ] бэкап делается автоматически и восстановлен вручную хотя бы раз;
- [ ] `DEBUG=False`, секретов в репозитории нет, Sentry получает ошибки.
