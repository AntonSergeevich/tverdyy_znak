import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("tverdyy_znak")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "purge-expired-personal-data": {
        # Автоудаление по истечении срока хранения (ТЗ 8.3).
        "task": "apps.core.tasks.purge_expired_personal_data",
        "schedule": 60 * 60 * 24,
    },
    "retry-failed-notifications": {
        "task": "apps.notifications.tasks.retry_failed_notifications",
        "schedule": 60 * 15,
    },
}
