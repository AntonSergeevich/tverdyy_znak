"""Кабинет администратора и владельца (ТЗ 5.4)."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.accounts.permissions import role_required
from apps.core.audit import AuditAction, log_audit
from apps.journal.models import (
    Lesson,
    Module,
    ModuleKind,
    ModuleResult,
    Payment,
    Student,
    StudentStatus,
    Teacher,
)
from apps.journal.views.parent import current_module
from apps.site_public.models import Lead

FUNNEL_ORDER = [
    Lead.Status.NEW,
    Lead.Status.DIAGNOSTIC_SCHEDULED,
    Lead.Status.DIAGNOSTIC_DONE,
    Lead.Status.CONTRACT,
    Lead.Status.ENROLLED,
    Lead.Status.DECLINED,
]

MANAGER_ROLES = ("admin", "owner", "platform_admin")


def _period(request) -> tuple[date, date]:
    today = timezone.localdate()
    start = request.GET.get("from")
    end = request.GET.get("to")
    try:
        start_date = date.fromisoformat(start) if start else today.replace(day=1)
    except ValueError:
        start_date = today.replace(day=1)
    try:
        end_date = date.fromisoformat(end) if end else today
    except ValueError:
        end_date = today
    return start_date, end_date


@login_required
@role_required(*MANAGER_ROLES)
def dashboard(request):
    organization = request.organization
    start, end = _period(request)

    students_now = Student.objects.filter(status=StudentStatus.ENROLLED).count()
    revenue = Payment.objects.filter(
        status=Payment.Status.PAID, paid_on__gte=start, paid_on__lte=end
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    payroll = _payroll_rows(start, end)
    payroll_total = sum((row["amount"] for row in payroll), Decimal("0.00"))

    leads = Lead.objects.filter(created_at__date__gte=start, created_at__date__lte=end)
    by_status = {row["status"]: row["n"] for row in leads.values("status").annotate(n=Count("id"))}
    total_leads = sum(by_status.values())
    funnel = [
        {
            "status": status,
            "label": Lead.Status(status).label,
            "count": by_status.get(status, 0),
            "share": round(by_status.get(status, 0) / total_leads * 100) if total_leads else 0,
        }
        for status in FUNNEL_ORDER
    ]
    enrolled = by_status.get(Lead.Status.ENROLLED, 0)

    module = current_module(organization)
    failing = (
        ModuleResult.objects.filter(module=module, is_passed=False)
        .select_related("student", "subject")
        .order_by("student__last_name")[:20]
        if module
        else []
    )

    return render(
        request,
        "cabinet/manage/dashboard.html",
        {
            "start": start,
            "end": end,
            "students_now": students_now,
            "revenue": revenue,
            "payroll_total": payroll_total,
            "result": revenue - payroll_total,
            "funnel": funnel,
            "total_leads": total_leads,
            "conversion": round(enrolled / total_leads * 100, 1) if total_leads else 0.0,
            "module": module,
            "failing": list(failing),
        },
    )


@login_required
@role_required(*MANAGER_ROLES)
def leads(request):
    status = request.GET.get("status") or ""
    queryset = Lead.objects.all().order_by("-created_at")
    if status in dict(Lead.Status.choices):
        queryset = queryset.filter(status=status)
    log_audit(action=AuditAction.VIEW_LEAD, request=request, scope="list", status=status or "all")
    return render(
        request,
        "cabinet/manage/leads.html",
        {
            "leads": list(queryset[:200]),
            "statuses": Lead.Status.choices,
            "active_status": status,
        },
    )


@login_required
@role_required(*MANAGER_ROLES)
@require_http_methods(["POST"])
def lead_status(request, lead_id):
    lead = get_object_or_404(Lead.objects.all(), pk=lead_id)
    lead.status = request.POST.get("status") or lead.status
    lead.decline_reason = (request.POST.get("decline_reason") or "").strip()[:250]
    lead.status_changed_at = timezone.now()
    error = ""
    try:
        lead.full_clean(exclude=["organization", "consent_at", "policy_version"])
        lead.save(
            update_fields=["status", "decline_reason", "status_changed_at", "updated_at"]
        )
    except ValidationError as exc:
        error = next((m for msgs in exc.message_dict.values() for m in msgs), "Ошибка сохранения.")
        lead.refresh_from_db()
    return render(
        request,
        "cabinet/manage/partials/lead_row.html",
        {"lead": lead, "statuses": Lead.Status.choices, "error": error},
        status=422 if error else 200,
    )


@login_required
@role_required(*MANAGER_ROLES)
def students(request):
    query = (request.GET.get("q") or "").strip()
    queryset = Student.objects.all().order_by("last_name", "first_name")
    if query:
        queryset = queryset.filter(
            Q(last_name__icontains=query) | Q(first_name__icontains=query)
        )
    show_deleted = request.GET.get("deleted") == "1"
    if show_deleted:
        queryset = Student.all_objects.filter(
            organization=request.organization, deleted_at__isnull=False
        ).order_by("last_name")
    return render(
        request,
        "cabinet/manage/students.html",
        {"students": list(queryset[:300]), "q": query, "show_deleted": show_deleted},
    )


@login_required
@role_required(*MANAGER_ROLES)
@require_http_methods(["POST"])
def student_restore(request, student_id):
    """Восстановление случайно удалённого ученика посреди года (ТЗ 9.5)."""
    student = get_object_or_404(
        Student.all_objects.filter(organization=request.organization), pk=student_id
    )
    student.restore()
    log_audit(action=AuditAction.PERMISSION_CHANGED, request=request, obj=student, change="restore")
    return render(request, "cabinet/manage/partials/student_row.html", {"student": student})


def _payroll_rows(start: date, end: date) -> list[dict]:
    rows = (
        Teacher.objects.annotate(
            minutes=Sum(
                "lessons__duration_minutes",
                filter=Q(
                    lessons__starts_at__date__gte=start,
                    lessons__starts_at__date__lte=end,
                ),
            )
        )
        .select_related("user")
        .order_by("user__last_name")
    )
    result = []
    for teacher in rows:
        hours = Decimal(teacher.minutes or 0) / Decimal(60)
        result.append(
            {
                "teacher": teacher,
                "hours": hours.quantize(Decimal("0.01")),
                "rate": teacher.hourly_rate,
                "amount": (hours * teacher.hourly_rate).quantize(Decimal("0.01")),
            }
        )
    return result


@login_required
@role_required("owner", "platform_admin")
def payroll(request):
    start, end = _period(request)
    rows = _payroll_rows(start, end)
    return render(
        request,
        "cabinet/manage/payroll.html",
        {
            "rows": rows,
            "start": start,
            "end": end,
            "total": sum((row["amount"] for row in rows), Decimal("0.00")),
        },
    )


@login_required
@role_required(*MANAGER_ROLES)
@require_http_methods(["POST"])
def payment_mark_paid(request, payment_id):
    from apps.journal.services.payments import get_provider

    payment = get_object_or_404(Payment.objects.select_related("student"), pk=payment_id)
    get_provider(payment.provider).mark_paid(payment, actor=request.user)
    log_audit(action=AuditAction.PERMISSION_CHANGED, request=request, obj=payment, change="paid")
    return render(request, "cabinet/manage/partials/payment_row.html", {"payment": payment})
