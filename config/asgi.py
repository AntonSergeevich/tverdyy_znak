"""
ASGI оставлен для совместимости, но прод работает на WSGI + Gunicorn sync.

Причина — в docs/ARCHITECTURE.md, раздел «Про асинхронность»: Django ORM
в async-вью даёт SynchronousOnlyOperation и утечки соединений, а нужная
«асинхронность» интерфейса достигается HTMX и Celery.
"""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

application = get_asgi_application()
