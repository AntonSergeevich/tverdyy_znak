"""
Загрузка календарно-тематического планирования.

КТП составляют не здесь — его присылают файлом. Задача экрана простая:
принять файл, показать, как мы его поняли, дать поправить и разложить темы
по занятиям расписания.

Разметка колонок правится руками намеренно. Угадать чужую таблицу с
первого раза нельзя: колонки называют как угодно, шапка бывает в пять
строк. Показать, что понял, и дать поправить — надёжнее любого угадывания.
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.accounts.permissions import role_required
from apps.core.audit import AuditAction, log_audit
from apps.journal.access import accessible_groups, is_manager
from apps.journal.models import AcademicYear, Group, Subject, ThematicPlan
from apps.journal.services import ktp as ktp_service


def _current_year(organization) -> AcademicYear | None:
    return (
        AcademicYear.objects.filter(is_current=True).first()
        or AcademicYear.objects.order_by("-starts_on").first()
    )


@login_required
@role_required("teacher", "admin", "owner", "platform_admin")
def plan_list(request):
    """Что уже загружено — по предметам."""
    organization = request.organization
    plans = (
        ThematicPlan.objects.select_related("subject", "group", "academic_year")
        .prefetch_related("entries")
        .order_by("subject__name", "-created_at")
    )
    return render(
        request,
        "cabinet/teacher/ktp_list.html",
        {
            "plans": list(plans),
            "subjects": Subject.objects.order_by("name"),
            "groups": accessible_groups(request.user, organization).order_by("name"),
            "year": _current_year(organization),
            "supported": sorted(ktp_service.SUPPORTED_SUFFIXES),
        },
    )


@login_required
@role_required("teacher", "admin", "owner", "platform_admin")
@require_http_methods(["POST"])
def plan_upload(request):
    """
    Принять файл.

    Файл сохраняем сразу и целиком, ещё до разбора: разбор можно повторить
    сколько угодно раз, а вот заново просить прислать файл — нельзя.
    """
    organization = request.organization
    year = _current_year(organization)
    if year is None:
        messages.error(request, "Сначала заведите учебный год.")
        return redirect("cabinet:ktp_list")

    subject = get_object_or_404(Subject, pk=request.POST.get("subject"))
    group = None
    if request.POST.get("group"):
        group = get_object_or_404(
            accessible_groups(request.user, organization), pk=request.POST["group"]
        )
    uploaded = request.FILES.get("source")
    if uploaded is None:
        messages.error(request, "Файл не выбран.")
        return redirect("cabinet:ktp_list")

    plan = ThematicPlan(
        organization=organization, academic_year=year, subject=subject, group=group,
        title=(request.POST.get("title") or "").strip()[:200],
        source_name=uploaded.name[:250], uploaded_by=request.user,
    )
    plan.save()
    plan.source = uploaded
    plan.save(update_fields=["source", "updated_at"])

    # Первый разбор — угадыванием. Дальше человек поправит, если не угадали.
    try:
        table = ktp_service.read_table(plan.source, filename=plan.source_name)
    except ValidationError as exc:
        plan.delete()
        messages.error(request, "; ".join(exc.messages))
        return redirect("cabinet:ktp_list")

    parsed = ktp_service.parse(table)
    if parsed.rows:
        ktp_service.save_entries(plan, parsed)
    else:
        plan.header_row = parsed.header_row
        plan.column_map = parsed.column_map
        plan.save(update_fields=["header_row", "column_map", "updated_at"])

    log_audit(action=AuditAction.PLAN_IMPORTED, request=request, obj=plan, scope="ktp_upload")
    return redirect("cabinet:ktp_detail", plan_id=plan.pk)


def _plan_or_404(plan_id) -> ThematicPlan:
    return get_object_or_404(
        ThematicPlan.objects.select_related("subject", "group", "academic_year"), pk=plan_id
    )


@login_required
@role_required("teacher", "admin", "owner", "platform_admin")
def plan_detail(request, plan_id):
    """Что вышло из файла: разметка колонок, разобранные строки, исходник."""
    plan = _plan_or_404(plan_id)

    table, warnings = [], []
    if plan.source:
        try:
            table = ktp_service.read_table(plan.source, filename=plan.source_name)
        except ValidationError as exc:
            warnings = list(exc.messages)

    header = []
    if table:
        header = [
            {"index": index, "title": str(cell or "") or f"колонка {index + 1}"}
            for index, cell in enumerate(table[min(plan.header_row, len(table) - 1)])
        ]

    entries = list(plan.entries.select_related("lesson", "lesson__group"))
    lessons = [entry for entry in entries if not entry.is_section]

    return render(
        request,
        "cabinet/teacher/ktp_detail.html",
        {
            "plan": plan,
            "entries": entries,
            # Итог виден сразу: по нему педагог узнаёт свой план — «102 часа»
            # для русского в седьмом классе значит, что файл прочитан верно.
            "lesson_count": len(lessons),
            "section_count": len(entries) - len(lessons),
            "hours_total": sum((entry.hours for entry in lessons), Decimal("0")),
            "attached_count": sum(1 for entry in lessons if entry.lesson_id),
            # Разметку готовим здесь, а не в шаблоне: доставать значение из
            # словаря по имени поля шаблонным языком — три строки тегов
            # вместо одной строки кода.
            "fields": [
                {
                    "name": name,
                    "label": label,
                    "selected": plan.column_map.get(name, ""),
                }
                for name, label in ktp_service.FIELDS
            ],
            "header": header,
            "preview": table[: plan.header_row + 6],
            "warnings": warnings,
            "can_delete": is_manager(request.user, request.organization),
        },
    )


@login_required
@role_required("teacher", "admin", "owner", "platform_admin")
@require_http_methods(["POST"])
def plan_remap(request, plan_id):
    """Перечитать файл по исправленной разметке колонок."""
    plan = _plan_or_404(plan_id)
    if not plan.source:
        raise Http404("Исходного файла нет.")

    try:
        header_row = max(0, int(request.POST.get("header_row") or 0))
    except (TypeError, ValueError):
        header_row = 0

    column_map = {}
    for name in ktp_service.FIELD_NAMES:
        raw = request.POST.get(f"column_{name}")
        if raw not in (None, ""):
            try:
                column_map[name] = int(raw)
            except (TypeError, ValueError):
                continue

    try:
        table = ktp_service.read_table(plan.source, filename=plan.source_name)
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
        return redirect("cabinet:ktp_detail", plan_id=plan.pk)

    parsed = ktp_service.parse(table, header_row=header_row, column_map=column_map or None)
    if parsed.rows:
        saved = ktp_service.save_entries(plan, parsed)
        messages.success(request, f"Разобрано строк: {saved}.")
    for warning in parsed.warnings:
        messages.error(request, warning)
    return redirect("cabinet:ktp_detail", plan_id=plan.pk)


@login_required
@role_required("teacher", "admin", "owner", "platform_admin")
@require_http_methods(["POST"])
def plan_attach(request, plan_id):
    """Разложить темы плана по занятиям расписания."""
    plan = _plan_or_404(plan_id)
    result = ktp_service.attach_to_lessons(
        plan, overwrite=request.POST.get("overwrite") == "1"
    )
    messages.success(
        request,
        "Привязано строк: {matched}. Тем вписано: {filled}. "
        "Оставлено как было: {skipped}. Без занятия: {unmatched}.".format(**result),
    )
    log_audit(action=AuditAction.PLAN_IMPORTED, request=request, obj=plan, scope="ktp_attach")
    return redirect("cabinet:ktp_detail", plan_id=plan.pk)


@login_required
@role_required("admin", "owner", "platform_admin")
@require_http_methods(["POST"])
def plan_delete(request, plan_id):
    plan = _plan_or_404(plan_id)
    if plan.source:
        plan.source.delete(save=False)
    plan.delete()
    messages.success(request, "Планирование удалено.")
    return redirect("cabinet:ktp_list")


@login_required
@role_required("teacher", "admin", "owner", "platform_admin")
def plan_source(request, plan_id):
    """Исходник, как прислали. Лежит вне MEDIA_ROOT — отдаём сами."""
    plan = _plan_or_404(plan_id)
    if not plan.source:
        raise Http404("Файла нет.")
    return FileResponse(
        plan.source.open("rb"), as_attachment=True, filename=plan.source_name or "ktp.xlsx"
    )
