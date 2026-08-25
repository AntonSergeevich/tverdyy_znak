"""
Базовые настройки платформы «Твёрдый знак».

Разделение: base → dev / prod / test. Секретов здесь нет — только чтение
окружения (см. .env.example).
"""
from pathlib import Path
from urllib.parse import urlparse

from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ─── Безопасность ───────────────────────────────────────────────────────────
SECRET_KEY = config("DJANGO_SECRET_KEY", default="insecure-dev-key-do-not-use-in-prod")
DEBUG = config("DJANGO_DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("DJANGO_ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())
CSRF_TRUSTED_ORIGINS = config("DJANGO_CSRF_TRUSTED_ORIGINS", default="", cast=Csv())

# Ключи шифрования полей с ПДн. Первый — активный.
FIELD_ENCRYPTION_KEYS = config("FIELD_ENCRYPTION_KEYS", default="", cast=Csv())

# ─── Приложения ─────────────────────────────────────────────────────────────
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.sitemaps",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "django_htmx",
    "axes",
]

LOCAL_APPS = [
    "apps.core",
    "apps.accounts",
    "apps.journal",
    "apps.site_public",
    "apps.notifications",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    # Определяет текущую организацию и кладёт её в contextvar (ТЗ 3.1).
    "apps.core.middleware.OrganizationMiddleware",
    # Ограничение сессии по неактивности (ТЗ 8.2).
    "apps.accounts.middleware.SessionIdleTimeoutMiddleware",
    # django-axes должен быть последним из аутентификационных.
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.organization",
                "apps.core.context_processors.site_settings",
            ],
        },
    },
]

# ─── База данных ────────────────────────────────────────────────────────────
def _database_from_url(url: str) -> dict:
    parsed = urlparse(url)
    if parsed.scheme.startswith("sqlite"):
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": parsed.path or ":memory:"}
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.lstrip("/"),
        "USER": parsed.username or "",
        "PASSWORD": parsed.password or "",
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or ""),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {"connect_timeout": 10},
    }


DATABASES = {
    "default": _database_from_url(
        config("DATABASE_URL", default="postgres://tz:tz@127.0.0.1:5432/tverdyy_znak")
    )
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ─── Пользователи и аутентификация ──────────────────────────────────────────
AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = [
    # Порядок важен: axes перехватывает попытки до основного бэкенда.
    "axes.backends.AxesStandaloneBackend",
    "apps.accounts.backends.EmailOrPhoneBackend",
]

# Argon2 первым (ТЗ 8.1).
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# email — USERNAME_FIELD, но допускает пустое значение (вход возможен и по телефону),
# поэтому уникальность задана условным ограничением, а не unique=True.
# Бэкенд EmailOrPhoneBackend это учитывает.
SILENCED_SYSTEM_CHECKS = ["auth.W004"]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "cabinet:home"
LOGOUT_REDIRECT_URL = "public:landing"

# Сессия истекает по неактивности; для админских ролей — короче (ТЗ 8.2).
SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "sessions"
SESSION_COOKIE_AGE = 60 * 60 * 12
SESSION_IDLE_TIMEOUT = 60 * 60 * 4          # обычные роли
SESSION_IDLE_TIMEOUT_STAFF = 60 * 30        # owner / admin / platform_admin
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_SAVE_EVERY_REQUEST = True

# django-axes (ТЗ 8.2)
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1  # час
AXES_LOCKOUT_PARAMETERS = ["ip_address", "username"]
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = "accounts/lockout.html"

# ─── Локализация ────────────────────────────────────────────────────────────
LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "UTC"                 # в БД всё в UTC (ТЗ 9.1)
USE_I18N = True
USE_TZ = True
DISPLAY_TIME_ZONE = "Asia/Krasnoyarsk"   # дефолт отображения, перекрывается организацией

# ─── Статика и медиа ────────────────────────────────────────────────────────
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Файлы с ПДн лежат ВНЕ MEDIA_ROOT и отдаются вью с проверкой прав (ТЗ 8.1).
PRIVATE_MEDIA_ROOT = Path(config("PRIVATE_MEDIA_ROOT", default=str(BASE_DIR / "private-media")))

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# ─── Кэш и очереди ──────────────────────────────────────────────────────────
REDIS_URL = config("REDIS_URL", default="redis://127.0.0.1:6379/0")
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL},
    "sessions": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL},
}

CELERY_BROKER_URL = config("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = config("CELERY_RESULT_BACKEND", default=REDIS_URL)
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_TASK_TIME_LIMIT = 300
CELERY_TASK_SOFT_TIME_LIMIT = 240
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TIMEZONE = "UTC"
CELERY_TASK_ALWAYS_EAGER = False
# Недоступный брокер не должен подвешивать веб-запрос: заявка уже в БД,
# уведомление подберёт периодическая задача.
CELERY_BROKER_CONNECTION_TIMEOUT = 3
CELERY_BROKER_CONNECTION_MAX_RETRIES = 1
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# ─── Внешние сервисы ────────────────────────────────────────────────────────
TG_BOT_TOKEN = config("TG_BOT_TOKEN", default="")
TG_CHAT_ID = config("TG_CHAT_ID", default="")
YANDEX_METRIKA_ID = config("YANDEX_METRIKA_ID", default="")

DEFAULT_ORGANIZATION_SLUG = config("DEFAULT_ORGANIZATION_SLUG", default="tverdyy-znak")

# Версия текстов согласий — пишется в Lead и Consent (ТЗ 8.3).
LEGAL_DOC_VERSION = "2026-08-01"

# Антиспам публичных форм (ТЗ 4).
LEAD_RATE_LIMIT_PER_HOUR = 5
LEAD_MIN_FILL_SECONDS = 3

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = config("EMAIL_HOST", default="")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="noreply@localhost")

DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

# ─── Логирование ────────────────────────────────────────────────────────────
LOG_DIR = Path(config("LOG_DIR", default=str(BASE_DIR / "logs")))
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "{asctime} {levelname} {name} {message}", "style": "{"},
        "audit": {"format": "{asctime} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
        "audit_file": {
            # Отдельный журнал доступа к персональным данным (ТЗ 8.4).
            "class": "logging.handlers.TimedRotatingFileHandler",
            "filename": str(LOG_DIR / "pdn-access.log"),
            "when": "midnight",
            "backupCount": 90,
            "formatter": "audit",
            "encoding": "utf-8",
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.db.backends": {"level": "WARNING", "handlers": ["console"], "propagate": False},
        "apps.core.audit": {"level": "INFO", "handlers": ["audit_file", "console"], "propagate": False},
    },
}
