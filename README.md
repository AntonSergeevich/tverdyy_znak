# Твёрдый знак — платформа центра семейного обучения

Публичный сайт, электронный журнал и личные кабинеты для центра семейного
обучения и профориентации. Django 5 + PostgreSQL 16 + Redis + Celery,
мультиарендная архитектура с первого коммита.

> **Важно про терминологию.** У организации нет лицензии на образовательную
> деятельность, поэтому слово «школа» о себе не используется нигде — ни в
> текстах, ни в названиях моделей и полей. Допустимо только про
> аккредитованную школу-партнёра, где проходит аттестация. На это есть
> автотест: `tests/test_content_rules.py`.

## Что уже работает

| Этап | Состояние |
|---|---|
| 1. Ядро: организации, роли, мультиарендность, аудит, безопасность | готово |
| 2. Публичный сайт: лендинг, заявки, правовые страницы, SEO | готово |
| 3. Журнал: справочники, модули, занятия, оценивание, кабинеты | готово |
| 4. Профиль ученика: цели, индикатор состояния | базовый объём готов |
| 5. Интеграции: Telegram, оплаты, экспорт xlsx | Telegram и экспорт готовы, эквайринг — интерфейс |

Подробности и открытые вопросы к заказчику — в [docs/STATUS.md](docs/STATUS.md).

## Быстрый старт

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env
python manage.py generate_secret          # → DJANGO_SECRET_KEY
python manage.py generate_fernet_key      # → FIELD_ENCRYPTION_KEYS

createdb tverdyy_znak
python manage.py migrate
python manage.py bootstrap_organization --domain localhost
python manage.py seed_demo                # демо-данные, только при DEBUG=True
python manage.py runserver
```

Демо-доступы после `seed_demo` (пароль `demo-parol-12345`):
`owner@example.org`, `teacher@example.org`, `parent@example.org`, `student1@example.org`.

## Тесты

```bash
pytest                     # 112 тестов
pytest tests/test_tenancy.py    # изоляция организаций
pytest tests/test_grading.py    # баллы, уровни, лимит 100
```

Обязательное покрытие по ТЗ: расчёт баллов и уровней, валидация 100-балльного
лимита, права по ролям, изоляция организаций, скрытые цели вне выгрузок,
отсутствие N+1 на списках.

## Структура

```
config/            настройки (base/dev/test/prod), celery, urls
apps/core/         организации, мультиарендность, шифрование полей, аудит, согласия
apps/accounts/     пользователи, роли, вход по email/телефону, второй фактор
apps/journal/      предметная область: модули, занятия, оценивание, кабинеты
  services/        бизнес-логика (во вью её нет)
  access.py        объектные права: чей ученик, чьё занятие
apps/site_public/  лендинг, заявки, правовые страницы
apps/notifications/ Telegram и журнал отправок
deploy/            nginx, скрипты бэкапа и восстановления
docs/              архитектура, деплой, статус, исходные спецификации
```

## Документация

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — решения и почему они такие
- [docs/DEPLOY.md](docs/DEPLOY.md) — развёртывание на Beget VPS, бэкапы, восстановление
- [docs/STATUS.md](docs/STATUS.md) — что сделано, что осталось, вопросы к заказчику
- [docs/spec/design-handoff.md](docs/spec/design-handoff.md) — исходная передача дизайна
- [docs/spec/tasks-frontend.md](docs/spec/tasks-frontend.md) — исходный список задач по фронту
