"""Настройки тестов: быстрые хэши, без внешних сервисов."""
from .base import *  # noqa: F403

DEBUG = False
ALLOWED_HOSTS = ["*", "testserver"]

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    "sessions": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
}
SESSION_ENGINE = "django.contrib.sessions.backends.db"

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

AXES_ENABLED = False

# В тестах организация определяется строго по домену: подстраховка
# «организация по умолчанию» замаскировала бы утечку между арендаторами.
DEFAULT_ORGANIZATION_SLUG = ""

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Фиксированный ключ шифрования полей — тесты должны быть детерминированными.
FIELD_ENCRYPTION_KEYS = ["YDAsdHtFGHDeFqoAwZma3QbaLjU1W9Q2IZ_NjOti_eY="]

# В тестах журнал доступа пишется в БД, но не засоряет вывод.
LOGGING["loggers"]["apps.core.audit"]["handlers"] = []  # noqa: F405
LOGGING["root"]["level"] = "WARNING"  # noqa: F405
