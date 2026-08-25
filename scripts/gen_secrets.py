"""
Генерация секретов для .env. Зависимостей нет — только стандартная библиотека,
поэтому запускается на любой машине, где есть Python, до установки пакетов.

    python scripts/gen_secrets.py

Выводит готовый кусок .env. Скопировать в файл на сервере и не хранить
нигде больше: ни в репозитории, ни в переписке.
"""
from __future__ import annotations

import base64
import os
import secrets
import string

SECRET_KEY_ALPHABET = string.ascii_letters + string.digits + "!@#%^&*(-_=+)"


def django_secret_key(length: int = 50) -> str:
    return "".join(secrets.choice(SECRET_KEY_ALPHABET) for _ in range(length))


def fernet_key() -> str:
    """Тот же формат, что у cryptography.fernet.Fernet.generate_key()."""
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


def password(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def main() -> None:
    postgres_password = password()

    print("# ─── Сгенерировано scripts/gen_secrets.py ─────────────────────────")
    print(f"DJANGO_SECRET_KEY={django_secret_key()}")
    print(f"FIELD_ENCRYPTION_KEYS={fernet_key()}")
    print(f"POSTGRES_PASSWORD={postgres_password}")
    print(f"DATABASE_URL=postgres://tz:{postgres_password}@db:5432/tverdyy_znak")
    print()
    print("# Пароль базы подставлен в DATABASE_URL — значения должны совпадать.")
    print("# FIELD_ENCRYPTION_KEYS нельзя терять: без него не прочитать")
    print("# зашифрованные даты рождения и документы учеников.")
    print("# Храните его отдельно от бэкапов, иначе шифрование бэкапа бессмысленно.")


if __name__ == "__main__":
    main()
