"""Продакшн: DEBUG выключен, HTTPS обязателен, Sentry включён (ТЗ 8.1, 9.1)."""
import sentry_sdk
from decouple import config
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration

from .base import *  # noqa: F403

DEBUG = False

# Второй фактор на проде не выключается. Переменная окружения здесь не
# действует намеренно: выключатель задумывался как временный, «на приёмку,
# пока данных нет», — и ровно так его и забыли включить обратно, когда дети
# появились. Нужно снять — снимается кодом и осознанно, а не строкой в .env,
# про которую через месяц никто не вспомнит.
TWO_FACTOR_ENABLED = True

if not ALLOWED_HOSTS or ALLOWED_HOSTS == ["localhost", "127.0.0.1"]:  # noqa: F405
    raise RuntimeError("DJANGO_ALLOWED_HOSTS обязателен в проде")
if SECRET_KEY.startswith("insecure-"):  # noqa: F405
    raise RuntimeError("DJANGO_SECRET_KEY обязателен в проде")
if not FIELD_ENCRYPTION_KEYS:  # noqa: F405
    raise RuntimeError("FIELD_ENCRYPTION_KEYS обязателен в проде: поля с ПДн шифруются")

# Локальные адреса нужны healthcheck-у контейнера: он ходит на
# http://127.0.0.1:8000/healthz изнутри, и со строгим ALLOWED_HOSTS Django
# отвечал бы 400, а контейнер навсегда оставался бы unhealthy.
# Снаружи это ничего не открывает: запрос с чужим Host обрывает nginx
# (default_server → 444), до Django он не доходит.
ALLOWED_HOSTS = ALLOWED_HOSTS + ["127.0.0.1", "localhost"]  # noqa: F405

# ─── Транспорт (ТЗ 8.1) ─────────────────────────────────────────────────────
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

SENTRY_DSN = config("SENTRY_DSN", default="")
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=config("SENTRY_ENVIRONMENT", default="production"),
        integrations=[DjangoIntegration(), CeleryIntegration()],
        traces_sample_rate=0.1,
        # Персональные данные детей в Sentry не отправляем.
        send_default_pii=False,
    )
