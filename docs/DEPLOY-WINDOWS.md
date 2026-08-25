# Работа из PyCharm на Windows: от клона до деплоя

Всё выполняется в терминале PyCharm (**Alt+F12**), профиль **PowerShell**.
Если PyCharm открывает cmd: *Settings → Tools → Terminal → Shell path* →
`powershell.exe`.

---

## 1. Забрать проект в PyCharm

*File → Project from Version Control* и вставить адрес репозитория:

```
https://github.com/AntonSergeevich/tverdyy_znak.git
```

Рабочая ветка — `claude/tverdyy-znak-django-sdrptm`. Переключиться на неё
можно внизу справа в PyCharm или командой:

```powershell
git checkout claude/tverdyy-znak-django-sdrptm
```

## 2. Настроить окружение

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
```

Если PowerShell ругается на запуск скриптов:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

В PyCharm: *Settings → Project → Python Interpreter → Add → Existing* →
`.venv\Scripts\python.exe`.

## 3. Локальный запуск

Нужен PostgreSQL 16 (Docker Desktop или установленный локально) и,
по желанию, Redis.

```powershell
Copy-Item .env.example .env
python manage.py generate_secret        # значение → DJANGO_SECRET_KEY в .env
python manage.py generate_fernet_key    # значение → FIELD_ENCRYPTION_KEYS в .env
```

Для локальной работы в `.env` поставить:

```
DJANGO_SETTINGS_MODULE=config.settings.dev
DJANGO_DEBUG=True
DATABASE_URL=postgres://tz:tz@127.0.0.1:5432/tverdyy_znak
```

Дальше:

```powershell
python manage.py migrate
python manage.py bootstrap_organization --domain localhost
python manage.py setup_client_data
python manage.py createsuperuser
python manage.py runserver
```

Открыть http://localhost:8000 — организация определяется по домену,
поэтому именно `localhost`, а не `127.0.0.1`.

## 4. Фотографии педагогов

Положить оригиналы в `assets\teachers\` под именами из
`assets\teachers\README.md` (`babadzhanova.jpg`, `manasyan.jpg`,
`polskaya.jpg`, `margarita.jpg`, `anna.jpg`) и выполнить:

```powershell
python scripts\prepare_teacher_photos.py
python manage.py setup_client_data
```

Скрипт кадрирует под портрет 4:5, поднимает резкость и контраст и
сохраняет WebP в `media\teachers\`. Команда привязывает файлы к карточкам.

## 5. Ключ SSH вместо пароля

Один раз на своей машине:

```powershell
ssh-keygen -t ed25519 -C "pycharm-deploy"
# Enter, Enter, Enter — путь по умолчанию C:\Users\<вы>\.ssh\id_ed25519

# Скопировать открытый ключ на сервер (ssh-copy-id в Windows нет):
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh root@85.198.66.41 "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

Проверка — вход должен пройти без пароля:

```powershell
ssh root@85.198.66.41 "hostname; docker --version"
```

## 6. Подготовка сервера (один раз)

DNS: A-запись `tverdyy-znak.ru` и `www.tverdyy-znak.ru` → `85.198.66.41`.
Проверить, что записи разошлись:

```powershell
Resolve-DnsName tverdyy-znak.ru -Type A
```

Дальше подготовка сервера одной командой из корня проекта:

```powershell
Get-Content deploy\scripts\provision.sh | ssh root@85.198.66.41 "bash -s"
```

Скрипт ставит Docker, заводит пользователя `tz`, включает фаервол и
fail2ban и отключает вход по паролю.

## 7. Первый деплой

```powershell
# Код на сервер
ssh root@85.198.66.41 "cd /srv/tverdyy-znak && git clone https://github.com/AntonSergeevich/tverdyy_znak.git . && git checkout claude/tverdyy-znak-django-sdrptm"

# Секреты: заполнить .env на сервере
scp .env.example root@85.198.66.41:/srv/tverdyy-znak/.env
ssh root@85.198.66.41 "chmod 600 /srv/tverdyy-znak/.env && nano /srv/tverdyy-znak/.env"
```

Обязательно заполнить: `DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`,
`DATABASE_URL` (с тем же паролем), `FIELD_ENCRYPTION_KEYS`,
`TG_BOT_TOKEN`, `TG_CHAT_ID`.

Сертификат Let's Encrypt и запуск:

```powershell
ssh root@85.198.66.41 @"
cd /srv/tverdyy-znak
docker compose up -d db redis web
docker run --rm -v tverdyy-znak_certbot-www:/var/www/certbot -v tverdyy-znak_certbot-conf:/etc/letsencrypt certbot/certbot certonly --webroot -w /var/www/certbot -d tverdyy-znak.ru -d www.tverdyy-znak.ru --email info@tverdyy-znak.ru --agree-tos --no-eff-email
docker compose up -d --build
docker compose exec -T web python manage.py bootstrap_organization --domain tverdyy-znak.ru
docker compose exec -T web python manage.py setup_client_data
docker compose exec -T web python manage.py createsuperuser --noinput --email admin@tverdyy-znak.ru || true
docker compose exec -T web python manage.py check --deploy
"@
```

Фотографии педагогов попадут на сервер вместе с репозиторием
(`assets/teachers/` коммитится), останется собрать из них WebP:

```powershell
ssh root@85.198.66.41 "cd /srv/tverdyy-znak && docker compose exec -T web python scripts/prepare_teacher_photos.py && docker compose exec -T web python manage.py setup_client_data"
```

## 8. Обычный деплой

Дальше каждое обновление — одна команда из корня проекта:

```powershell
.\deploy\deploy.ps1
```

Скрипт по шагам: проверяет рабочую копию, прогоняет тесты (красные —
деплой останавливается), пушит ветку, забирает её на сервере,
пересобирает контейнеры, применяет миграции, собирает статику
и дёргает `/healthz`.

Полезные ключи:

```powershell
.\deploy\deploy.ps1 -SkipPush          # выкатить то, что уже в origin
.\deploy\deploy.ps1 -Rebuild           # пересобрать образы с нуля
.\deploy\deploy.ps1 -Branch main       # выкатить другую ветку
```

## 9. Что смотреть, когда что-то не так

```powershell
ssh root@85.198.66.41 "cd /srv/tverdyy-znak && docker compose ps"
ssh root@85.198.66.41 "cd /srv/tverdyy-znak && docker compose logs --tail=100 web"
ssh root@85.198.66.41 "cd /srv/tverdyy-znak && docker compose logs --tail=50 worker"

# Django-консоль на сервере
ssh root@85.198.66.41 "cd /srv/tverdyy-znak && docker compose exec web python manage.py shell"

# Ручной бэкап
ssh root@85.198.66.41 "cd /srv/tverdyy-znak && docker compose exec backup sh /scripts/backup.sh"
```

Восстановление из бэкапа и проверка миграций на копии боевой базы —
в [DEPLOY.md](DEPLOY.md), разделы 5 и 6.
