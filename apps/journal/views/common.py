"""Общий вход в кабинет: маршрутизация по роли."""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from apps.accounts.models import ORG_MANAGER_ROLES, Role


@login_required
def home(request):
    organization = request.organization
    user = request.user
    if user.is_superuser or user.has_role(organization, *ORG_MANAGER_ROLES, Role.PLATFORM_ADMIN):
        return redirect("cabinet:dashboard")
    if user.has_role(organization, Role.TEACHER):
        return redirect("cabinet:teacher_today")
    if user.has_role(organization, Role.PARENT):
        return redirect("cabinet:parent_home")
    if user.has_role(organization, Role.STUDENT):
        return redirect("cabinet:student_home")
    return render(request, "cabinet/no_role.html", status=403)
