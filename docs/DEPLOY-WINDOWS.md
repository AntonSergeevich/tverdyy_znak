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

Рабочая ветка — `claude/tverdyy-znak-django-sdrptm`, и весь код лежит
именно в ней, а не в `main`. Если проект уже склонирован, но файлов
не хватает — вы на старой ветке:

```powershell
git fetch origin
git checkout claude/tverdyy-znak-django-sdrptm
git pull
```

## 2. Настроить окружение

Подходит Python 3.12 или 3.13.

```powershell
py -3.13 -m venv .venv   # или py -3.12
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
`polskaya.jpg`, `margarita.jpg`, `anna.jpg`, `katnikov.jpg`) и выполнить:

Класть готовый файл прямо в `media\teachers\` бесполезно: на сервере это
docker-том, которого нет в образе. Обрабатывается всегда оригинал
из `assets\teachers\`.

```powershell
python scripts\prepare_teacher_photos.py
python manage.py setup_client_data
```

Скрипт кадрирует под портрет 4:5, поднимает резкость и контраст и
сохраняет WebP в `media\teachers\`. Команда привязывает файлы к карточкам.

**Оригиналы обязательно закоммитить** — иначе на сервере фотографий
не будет: `media/` в `.gitignore`, и WebP туда не попадает по замыслу,
он пересобирается из оригиналов на месте.

```powershell
git add assets/teachers
git commit -m "Фотографии педагогов"
git push
```

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

Дальше подготовка сервера. Скрипт копируется на сервер и запускается там,
а не передаётся через конвейер: PowerShell отдаёт файл с виндовыми
переводами строк, и bash спотыкается на `\r` («invalid option name»).
`sed` в первой строке снимает этот риск раз и навсегда.

```powershell
scp deploy\scripts\provision.sh root@85.198.66.41:/tmp/provision.sh
ssh root@85.198.66.41 "sed -i 's/\r$//' /tmp/provision.sh && bash /tmp/provision.sh"
```

Скрипт ставит Docker, заводит пользователя `tz`, включает фаервол и
fail2ban и отключает вход по паролю. Ваш ключ он копирует и пользователю
`tz` тоже.

**Дальше подключаемся от `tz`, а не от root.** Приложение работает
от непривилегированного пользователя, ему принадлежит `/srv/tverdyy-znak`,
и git из-под root на этом каталоге откажется работать
(«detected dubious ownership»). Проверка:

```powershell
ssh tz@85.198.66.41 "whoami; docker ps"
```

## 7. Первый деплой

```powershell
# Код на сервер
ssh tz@85.198.66.41 "cd /srv/tverdyy-znak && git clone https://github.com/AntonSergeevich/tverdyy_znak.git . && git checkout claude/tverdyy-znak-django-sdrptm"

# Секреты: заполнить .env на сервере
scp .env.example tz@85.198.66.41:/srv/tverdyy-znak/.env
ssh tz@85.198.66.41 -t "chmod 600 /srv/tverdyy-znak/.env && nano /srv/tverdyy-znak/.env"
```

Секреты генерируются одной командой — зависимостей у неё нет,
работает на голом Python:

```powershell
python scripts\gen_secrets.py
```

Вывод скопировать в `.env` на сервере, заменив пустые строки
`DJANGO_SECRET_KEY`, `FIELD_ENCRYPTION_KEYS`, `POSTGRES_PASSWORD`
и `DATABASE_URL`.

Отдельно заполнить `TG_BOT_TOKEN` и `TG_CHAT_ID`. Без них сайт поднимется
и заявки будут сохраняться, но уведомления в Telegram не придут:
задача пометит отправку неудачной и повторит её, когда токен появится.

`FIELD_ENCRYPTION_KEYS` нельзя терять — без него не прочитать
зашифрованные даты рождения и документы учеников.

Запуск, сертификат и первичные данные:

```powershell
# 1. Поднять базу, Redis и приложение
ssh tz@85.198.66.41 "cd /srv/tverdyy-znak && docker compose up -d --build db redis web worker beat"

# 2. Выпустить сертификат и поднять nginx.
#    Первый выпуск идёт в режиме standalone: webroot требует работающего
#    nginx, а nginx не стартует без сертификата.
ssh tz@85.198.66.41 "cd /srv/tverdyy-znak && bash deploy/scripts/issue-cert.sh"

# 3. Справочники, реквизиты и карточки педагогов
ssh tz@85.198.66.41 "cd /srv/tverdyy-znak && docker compose exec -T web python manage.py bootstrap_organization --domain tverdyy-znak.ru"
ssh tz@85.198.66.41 "cd /srv/tverdyy-znak && docker compose exec -T web python manage.py setup_client_data"

# 4. Учётная запись владельца
ssh tz@85.198.66.41 -t "cd /srv/tverdyy-znak && docker compose exec web python manage.py createsuperuser"

# 5. Финальная проверка
ssh tz@85.198.66.41 "cd /srv/tverdyy-znak && docker compose exec -T web python manage.py check --deploy"
```

`check --deploy` должен пройти без предупреждений. Если ругается —
не запускаемся, а чиним.

Фотографии педагогов попадут на сервер вместе с репозиторием
(`assets/teachers/` коммитится), останется собрать из них WebP:

```powershell
ssh tz@85.198.66.41 "cd /srv/tverdyy-znak && docker compose exec -T web python scripts/prepare_teacher_photos.py && docker compose exec -T web python manage.py setup_client_data"
```

## 8. Обычный деплой: пуш в ветку

Выкатывать руками не нужно. Пуш в ветку разработки или в `main` запускает
GitHub Actions: он прогоняет тесты и, если они зелёные, выкатывает на
сервер. Локальная машина в этом не участвует, база для тестов не нужна.

```powershell
git add .
git commit -m "Chto izmenil"
git push
```

Ход выката виден на вкладке **Actions** в репозитории. Что именно
происходит на сервере, описано в `deploy/scripts/remote-deploy.sh` — этот
же файл вызывает и ручной выкат, чтобы «через CI» и «руками» не
разъезжались.

### Что нужно настроить один раз

Actions ходит на сервер по SSH, поэтому ему нужен свой ключ.

**1. Создать ключ (на своей машине):**

```powershell
ssh-keygen -t ed25519 -f $env:USERPROFILE\.ssh\tz_deploy -N '""' -C "github-actions"
type $env:USERPROFILE\.ssh\tz_deploy.pub | ssh tz@85.198.66.41 "cat >> ~/.ssh/authorized_keys"
```

**2. Положить его в секреты репозитория.** GitHub → репозиторий →
Settings → Secrets and variables → Actions → раздел **Repository secrets**
→ New repository secret.

Именно Repository secrets, не Environment secrets: секреты окружения
видит только та задача, которая объявила `environment:`, а наша этого
не делает. Если положить их не туда, выкат упадёт на первом же шаге
с сообщением, что секреты не заданы.

| Имя | Значение |
|---|---|
| `DEPLOY_SSH_KEY` | содержимое `tz_deploy` **без .pub**, целиком, включая строки `BEGIN`/`END` |
| `DEPLOY_HOST` | `85.198.66.41` |
| `DEPLOY_USER` | `tz` |

Приватный ключ в репозиторий не коммитится и в логах Actions не виден —
GitHub затирает значения секретов в выводе.

**3. Проверить:** вкладка Actions → «Тесты и выкат» → Run workflow.

### Выкат руками — одна команда

Нужен, когда Actions недоступны или менялось что-то на сервере:

```powershell
ssh tz@85.198.66.41 tz-deploy
```

Всё. Сервер сам забирает ветку из GitHub, пересобирает контейнеры,
применяет миграции, собирает статику, обновляет справочники и
фотографии, перечитывает конфигурацию nginx и дожидается `healthz`.
Локальная копия проекта для этого не нужна вовсе — команду можно
выполнить и с телефона.

Ту же команду можно набрать, зайдя на сервер:

```
ssh tz@85.198.66.41
tz-deploy
```

Ветка по умолчанию — та, что уже выкачена. Другую передают аргументом:
`tz-deploy main`.

Если нужно ещё и запушить текущую ветку перед выкатом:

```powershell
.\deploy\deploy.ps1
```

Это единственное, что скрипт добавляет к `tz-deploy` — вся серверная
логика живёт в одном месте.

### Установить короткую команду (один раз)

`provision.sh` ставит её на новом сервере сам. На уже работающем —
одной строкой от root:

```powershell
ssh root@85.198.66.41 "ln -sf /srv/tverdyy-znak/deploy/scripts/pull-and-deploy.sh /usr/local/bin/tz-deploy"
```

Пока симлинка нет, всё работает и так: и Actions, и `deploy.ps1`
вызывают скрипт по полному пути, если короткой команды не нашлось.

## 9. Второй фактор: кто и как заходит

Второй фактор (код из приложения) обязателен для владельца и
администратора. Он привязан **к человеку, а не к организации**: у каждого
свой аккаунт и свой QR. Если Алина заходит под своей учётной записью, ваше
подключённое устройство ей не мешает — она подключает своё при первом входе.

Заходить вдвоём под одним аккаунтом не нужно и не стоит: в журнале доступа
тогда не видно, кто что смотрел, а это как раз то, что требуется хранить по
персональным данным детей.

**Потерян телефон.** Не выключайте второй фактор целиком — сбросьте его
одному человеку, он подключит новое устройство при следующем входе:

```powershell
ssh tz@85.198.66.41 "cd /srv/tverdyy-znak && docker compose exec web python manage.py reset_two_factor pochta@example.ru"
```

**На время приёмки** второй фактор можно выключить совсем — но только пока
в базе нет настоящих данных учеников. В `.env` на сервере:

```
TWO_FACTOR_ENABLED=False
```

и перезапустить: `docker compose up -d web`. Обратно — `True` и снова
перезапуск. Пока выключено, `manage.py check --deploy` пишет об этом
предупреждение `accounts.W001`, чтобы это не забылось.

## 10. Расписание

Расписание видно в кабинете у всех ролей: раздел «Расписание», неделя с
переключением вперёд и назад. Педагогу показываются его занятия, родителю —
занятия его детей, ученику — свои. Блоки дня — обед, утренний круг,
рефлексия — стоят в сетке, но приглушены и баллов не приносят.

Ссылка на общий файл (Яндекс.Документы) лежит в админке, раздел
«Организация → Расписание». Она видна только в кабинете и нужна, пока
занятия не заведены в журнале.

### Загрузка таблицы

Команда читает таблицу заказчика как есть — переводить её в CSV не нужно.
Ожидается лист, где слева время (`9.30-10.10`), а в шапке дни с датами
(`ПН 31.08`). Образец — `docs/2.0.xlsx`.

**Проще всего — через репозиторий.** Всё содержимое проекта попадает
в образ, поэтому файл, положенный в `docs/`, после выката уже лежит внутри
контейнера по тому же пути:

```powershell
# 1. кладём файл в проект, коммитим, выкатываем
git add docs\raspisanie-2026-09.xlsx
git commit -m "Raspisanie na sentyabr"
.\deploy\deploy.ps1

# 2. загружаем — файл уже внутри, копировать ничего не нужно
ssh tz@85.198.66.41 "cd /srv/tverdyy-znak && docker compose exec -T web python manage.py import_schedule docs/raspisanie-2026-09.xlsx --module 1 --dry-run"
```

Сообщение коммита лучше писать латиницей или переключить консоль на UTF-8
(`chcp 65001`): PowerShell 5.1 отдаёт git текст в кодировке консоли,
и кириллица приезжает кракозябрами.

В `docs/` лежат два файла: `2.0.xlsx` — как прислал заказчик, без правок,
и `raspisanie-2026-09.xlsx` — та же таблица с исправленными датами в шапке
(четыре ячейки). Грузить нужно второй: в первом среда, четверг и пятница
второй недели подписаны датами первой, и эти дни просто не существуют.

Разовый файл, которого в репозитории нет, кладётся в два шага — папка
проекта внутрь контейнера не смонтирована:

```powershell
scp raspisanie.xlsx tz@85.198.66.41:/srv/tverdyy-znak/raspisanie.xlsx
ssh tz@85.198.66.41 "cd /srv/tverdyy-znak && docker compose cp raspisanie.xlsx web:/tmp/raspisanie.xlsx"
ssh tz@85.198.66.41 "cd /srv/tverdyy-znak && docker compose exec -T web python manage.py import_schedule /tmp/raspisanie.xlsx --module 1 --dry-run"
```

`--dry-run` только показывает, что получится, и ничего не пишет. Если счёт
занятий выглядит правильно — повторить без этого ключа. Команду можно
запускать сколько угодно раз: уже созданные занятия не дублируются.

Ключи:

```
--module 2             в какой модуль грузить (по умолчанию текущий)
--group «Класс 9»      чьё это расписание, если групп больше одной
--sheet «Лист3»        если нужный лист называется не «Расписание …»
--repeat-last-week     продлить последнюю полную неделю до конца модуля
```

`--repeat-last-week` нужен, когда в файле расписаны первые недели, а дальше
«так же». По умолчанию выключен: додуманные занятия в кабинете ребёнка хуже,
чем их отсутствие.

Команда проверяет файл и говорит, что в нём не сходится: дата с чужим днём
недели, скопированная и не исправленная шапка второй недели, названия,
которых нет в журнале. Такие строки не загружаются молча — их видно
в выводе.

### Если названия не совпали

Названия предметов должны совпадать с журналом. Что заведено сейчас — видно
в админке, раздел «Предметы». Там же у предмета есть тип:

- **учебный предмет** — по нему раскладываются 100 баллов модуля;
- **блок дня без баллов** — обед, утренний круг, профориентация,
  проектная деятельность, рефлексия. В расписании стоят, в оценивание
  не попадают.

### Если расписание ведётся как «каждую неделю одно и то же»

Тогда удобнее CSV: шесть колонок, одна строка — занятие на все такие дни
модуля. Образец — `docs/schedule.example.csv`, команда та же.

## 11. Что смотреть, когда что-то не так

```powershell
ssh tz@85.198.66.41 "cd /srv/tverdyy-znak && docker compose ps"
ssh tz@85.198.66.41 "cd /srv/tverdyy-znak && docker compose logs --tail=100 web"
ssh tz@85.198.66.41 "cd /srv/tverdyy-znak && docker compose logs --tail=50 worker"

# Django-консоль на сервере
ssh tz@85.198.66.41 "cd /srv/tverdyy-znak && docker compose exec web python manage.py shell"

# Ручной бэкап
ssh tz@85.198.66.41 "cd /srv/tverdyy-znak && docker compose exec backup sh /scripts/backup.sh"
```

Восстановление из бэкапа и проверка миграций на копии боевой базы —
в [DEPLOY.md](DEPLOY.md), разделы 5 и 6.
