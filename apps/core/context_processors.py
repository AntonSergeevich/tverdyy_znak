"""Контекст, доступный во всех шаблонах."""
from django.conf import settings


def organization(request):
    return {"organization": getattr(request, "organization", None)}


def site_settings(request):
    return {
        "LEGAL_DOC_VERSION": settings.LEGAL_DOC_VERSION,
        "YANDEX_METRIKA_ID": settings.YANDEX_METRIKA_ID,
        "DEBUG": settings.DEBUG,
    }
