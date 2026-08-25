"""Настройки разработки. На проде не использовать."""
from decouple import config

from .base import *  # noqa: F403

DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS += ["debug_toolbar"]  # noqa: F405
MIDDLEWARE.insert(1, "debug_toolbar.middleware.DebugToolbarMiddleware")  # noqa: F405
INTERNAL_IPS = ["127.0.0.1"]

# Проверка N+1 в dev: панель показывает число запросов на каждой странице (ТЗ 9.1).
# DEBUG_TOOLBAR=False отключает её, когда нужен чистый скриншот вёрстки.
_TOOLBAR_ON = config("DEBUG_TOOLBAR", default=True, cast=bool)
DEBUG_TOOLBAR_CONFIG = {"SHOW_TOOLBAR_CALLBACK": lambda request: DEBUG and _TOOLBAR_ON}

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Локально Redis может быть не поднят — не мешаем работать.
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    "sessions": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
}
SESSION_ENGINE = "django.contrib.sessions.backends.db"

AXES_ENABLED = False
