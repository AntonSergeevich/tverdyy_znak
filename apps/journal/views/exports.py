"""Выгрузки. Каждая пишется в журнал доступа (ТЗ 8.4)."""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404

from apps.accounts.permissions import role_required
from apps.core.audit import AuditAction, log_audit
from apps.journal.access import get_student_or_403
from apps.journal.models import Module
from apps.journal.services import exports
from apps.journal.views.manage import MANAGER_ROLES, _payroll_rows, _period

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx_response(payload: bytes, filename: str) -> HttpResponse:
    response = HttpResponse(payload, content_type=XLSX)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
@role_required(*MANAGER_ROLES, "teacher")
def module_performance(request, module_id):
    module = get_object_or_404(Module.objects.select_related("academic_year"), pk=module_id)
    log_audit(action=AuditAction.EXPORT, request=request, obj=module, export="module_performance")
    return _xlsx_response(
        exports.module_performance_xlsx(module), f"module-{module.number}-performance.xlsx"
    )


@login_required
@role_required(*MANAGER_ROLES)
def students(request):
    log_audit(action=AuditAction.EXPORT, request=request, export="students")
    return _xlsx_response(exports.students_xlsx(), "students.xlsx")


@login_required
@role_required("owner", "platform_admin")
def payroll(request):
    start, end = _period(request)
    log_audit(action=AuditAction.EXPORT, request=request, export="payroll", start=str(start), end=str(end))
    return _xlsx_response(
        exports.payroll_xlsx(_payroll_rows(start, end), start, end),
        f"payroll-{start}-{end}.xlsx",
    )


@login_required
@role_required(*MANAGER_ROLES, "teacher", "parent")
def student_goals(request, student_id):
    student = get_student_or_403(request.user, request.organization, student_id)
    log_audit(action=AuditAction.EXPORT, request=request, obj=student, export="goals")
    return _xlsx_response(exports.goals_xlsx(student), f"goals-{student.pk}.xlsx")
