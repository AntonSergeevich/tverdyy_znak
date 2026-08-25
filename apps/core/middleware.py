"""Определение текущей организации по домену запроса (ТЗ 3.1)."""
from __future__ import annotations

from django.conf import settings
from django.http import HttpResponseNotFound
from django.utils import timezone

from apps.core.models import Organization, OrganizationDomain
from apps.core.tenancy import reset_current_organization, set_current_organization


def resolve_organization(host: str) -> Organization | None:
    """
    Порядок разрешения:
    1. точное совпадение хоста с OrganizationDomain;
    2. организация по DEFAULT_ORGANIZATION_SLUG — режим одного арендатора.
    """
    host = (host or "").split(":")[0].strip().lower()
    if host:
        domain = (
            OrganizationDomain.objects.select_related("organization")
            .filter(host=host, organization__is_active=True)
            .first()
        )
        if domain:
            return domain.organization
    slug = getattr(settings, "DEFAULT_ORGANIZATION_SLUG", "")
    if slug:
        return Organization.objects.filter(slug=slug, is_active=True).first()
    return None


class OrganizationMiddleware:
    """
    Кладёт организацию в contextvar на время запроса и обязательно снимает её
    после. Без этого тенант-менеджеры вернут пустую выборку — это защита
    от утечки данных между организациями, а не баг.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        organization = resolve_organization(request.get_host())
        request.organization = organization
        token = set_current_organization(organization)
        try:
            if organization is None and not self._is_exempt(request):
                return HttpResponseNotFound("Организация для этого домена не найдена")
            if organization is not None:
                timezone.activate(organization.tzinfo)
            response = self.get_response(request)
        finally:
            timezone.deactivate()
            reset_current_organization(token)
        return response

    @staticmethod
    def _is_exempt(request) -> bool:
        # Админка платформы и health-check должны работать до создания организаций.
        return request.path.startswith(("/admin/", "/healthz", "/static/"))
