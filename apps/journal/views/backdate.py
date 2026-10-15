"""
Открыть педагогу выставление баллов задним числом — на несколько дней.

Педагог ставит баллы не позже чем через `grade_backdate_days` после
работы. Когда он не успел (историк не выставил баллы за прошлый модуль),
руководителю раньше оставалось два пути: переносить его оценки руками или
просить программиста раздвинуть срок — для всех педагогов сразу. Теперь
доступ открывается одному человеку, за один модуль и на один–семь дней,
а потом закрывается сам.
"""
from __future__ import annotations

import datetime as dt

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.core.audit import AuditAction, log_audit
from apps.journal.models import BackdateGrant, Module, ModuleKind
from apps.journal.services.grading import can_open_backdating

DAY_CHOICES = (1, 3, 7)


def _modules(organization):
    """Модули текущего года, которые уже начались, — последние сверху."""
    today = timezone.localdate()
    return list(
        Module.objects.filter(
            academic_year__is_current=True, kind=ModuleKind.MODULE, starts_on__lte=today,
        ).order_by("-starts_on")
    )


def staff_card_context(request, person, teacher) -> dict | None:
    """Блок «Баллы задним числом» в карточке педагога — только тому, кто вправе открыть."""
    organization = request.organization
    if teacher is None or not can_open_backdating(request.user, organization):
        return None
    modules = _modules(organization)
    today = timezone.localdate()
    finished = next((module for module in modules if module.ends_on < today), None)
    grants = list(
        BackdateGrant.objects.filter(user=person).select_related("module", "granted_by")[:5]
    )
    return {
        "limit": organization.grade_backdate_days,
        "modules": modules,
        "default_module": finished or (modules[0] if modules else None),
        "days": DAY_CHOICES,
        "active": [grant for grant in grants if grant.is_active],
        "past": [grant for grant in grants if not grant.is_active],
    }


@login_required
@require_http_methods(["POST"])
def backdate_open(request, user_id):
    organization = request.organization
    if not can_open_backdating(request.user, organization):
        raise PermissionDenied("Открыть выставление задним числом может владелец.")
    person = get_object_or_404(
        get_user_model().objects.filter(memberships__organization=organization).distinct(),
        pk=user_id,
    )
    if getattr(person, "teacher_profile", None) is None:
        raise PermissionDenied("Это не педагог.")

    try:
        days = int(request.POST.get("days") or 3)
    except ValueError:
        days = 3
    days = days if days in DAY_CHOICES else 3
    module_id = request.POST.get("module") or ""
    module = get_object_or_404(Module.objects.all(), pk=module_id) if module_id else None

    grant = BackdateGrant.objects.create(
        organization=organization, user=person, module=module,
        until=timezone.now() + dt.timedelta(days=days), granted_by=request.user,
    )
    log_audit(
        action=AuditAction.BACKDATE_OPENED, request=request, obj=grant,
        teacher=str(person.pk), module=str(module) if module else "все",
        until=grant.until.isoformat(),
    )
    messages.success(
        request,
        f"{person.short_name} может выставлять баллы задним числом "
        f"{'за ' + str(module) if module else 'за любые модули'} "
        f"до {timezone.localtime(grant.until):%d.%m %H:%M}. Потом доступ закроется сам.",
    )
    return redirect("cabinet:staff_card", user_id=person.pk)


@login_required
@require_http_methods(["POST"])
def backdate_close(request, grant_id):
    organization = request.organization
    if not can_open_backdating(request.user, organization):
        raise PermissionDenied("Закрыть выставление задним числом может владелец.")
    grant = get_object_or_404(BackdateGrant.objects.select_related("user"), pk=grant_id)
    if grant.is_active:
        grant.revoked_at = timezone.now()
        grant.save(update_fields=["revoked_at", "updated_at"])
        log_audit(action=AuditAction.BACKDATE_CLOSED, request=request, obj=grant,
                  teacher=str(grant.user_id))
        messages.success(request, "Выставление задним числом закрыто.")
    return redirect("cabinet:staff_card", user_id=grant.user_id)
