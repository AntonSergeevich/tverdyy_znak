"""
Сквозной сценарий приёмки: педагог выставляет балл, родитель его видит
(ТЗ 10, пункты 5 и 6).
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.core.tenancy import organization_context
from apps.journal.models import Grade, GradeItem, GradeItemKind, ModuleResult
from apps.journal.services.grading import points_budget
from tests.conftest import login


@pytest.fixture
def graded_lesson(tenant_a):
    """Занятие, отмеченное педагогом как оцениваемое."""
    with organization_context(tenant_a.organization):
        item = GradeItem.objects.create(
            organization=tenant_a.organization, module=tenant_a.module,
            subject=tenant_a.subject, group=tenant_a.group, lesson=tenant_a.lesson,
            kind=GradeItemKind.LESSON, max_points=Decimal("5.00"),
            due_date=tenant_a.lesson.local_date,
        )
        tenant_a.lesson.is_graded = True
        tenant_a.lesson.save(update_fields=["is_graded"])
    return item


def test_teacher_marks_lesson_as_graded(client, tenant_a):
    login(client, tenant_a, tenant_a.teacher_user)
    response = client.post(
        reverse("cabinet:lesson_toggle_graded", args=[tenant_a.lesson.pk]), {"is_graded": "1"}
    )
    assert response.status_code == 200
    tenant_a.lesson.refresh_from_db()
    assert tenant_a.lesson.is_graded is True

    with organization_context(tenant_a.organization):
        item = GradeItem.objects.get(lesson=tenant_a.lesson)
    assert item.max_points == tenant_a.organization.lesson_max_points
    assert item.kind == GradeItemKind.LESSON


def test_teacher_saves_grade_via_htmx(client, tenant_a, graded_lesson):
    login(client, tenant_a, tenant_a.teacher_user)
    response = client.post(
        reverse("cabinet:grade_save", args=[tenant_a.lesson.pk]),
        {"student": str(tenant_a.student.pk), "points": "4,5", "comment": "Хорошая работа"},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    assert "сохранено" in response.content.decode()

    with organization_context(tenant_a.organization):
        grade = Grade.objects.get(student=tenant_a.student)
        assert grade.points == Decimal("4.50")
        assert grade.comment == "Хорошая работа"
        assert grade.given_by == tenant_a.teacher_user
        result = ModuleResult.objects.get(student=tenant_a.student, subject=tenant_a.subject)
        assert result.total_points == Decimal("4.50")


def test_grade_above_max_shows_error_next_to_field(client, tenant_a, graded_lesson):
    login(client, tenant_a, tenant_a.teacher_user)
    response = client.post(
        reverse("cabinet:grade_save", args=[tenant_a.lesson.pk]),
        {"student": str(tenant_a.student.pk), "points": "9"},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 422
    assert "Максимум за эту работу" in response.content.decode()
    with organization_context(tenant_a.organization):
        assert Grade.objects.count() == 0


def test_non_numeric_grade_is_rejected(client, tenant_a, graded_lesson):
    login(client, tenant_a, tenant_a.teacher_user)
    response = client.post(
        reverse("cabinet:grade_save", args=[tenant_a.lesson.pk]),
        {"student": str(tenant_a.student.pk), "points": "отлично"},
    )
    assert response.status_code == 422
    assert "числом" in response.content.decode()


def test_parent_sees_the_grade(client, tenant_a, graded_lesson):
    """Тот самый сценарий приёмки: педагог поставил — родитель увидел."""
    login(client, tenant_a, tenant_a.teacher_user)
    client.post(
        reverse("cabinet:grade_save", args=[tenant_a.lesson.pk]),
        {"student": str(tenant_a.student.pk), "points": "5", "comment": "Разобрал тему"},
    )
    client.logout()

    login(client, tenant_a, tenant_a.parent_user)
    body = client.get(reverse("cabinet:parent_home")).content.decode()
    assert tenant_a.subject.name in body
    assert "Разобрал тему" in body
    # Уровень выводится и цветом, и текстом — доступность (ТЗ 5.1, 9.3).
    assert "level level--failed" in body
    assert "требуется поддержка" in body


def test_module_plan_blocks_over_limit(client, tenant_a):
    login(client, tenant_a, tenant_a.teacher_user)
    url = reverse(
        "cabinet:module_plan_action",
        args=[tenant_a.module.pk, tenant_a.subject.pk, tenant_a.group.pk],
    )
    assert client.post(url, {"action": "default_structure"}).status_code == 200

    response = client.post(
        url, {"action": "add_item", "kind": GradeItemKind.QUIZ, "title": "Лишняя", "max_points": "5"}
    )
    body = response.content.decode()
    assert "осталось 0" in body
    with organization_context(tenant_a.organization):
        budget = points_budget(tenant_a.module, tenant_a.subject, tenant_a.group)
        assert budget.distributed == Decimal("100.00")


def test_teacher_saves_lesson_topic(client, tenant_a):
    login(client, tenant_a, tenant_a.teacher_user)
    response = client.post(
        reverse("cabinet:lesson_topic_save", args=[tenant_a.lesson.pk]),
        {"topic": "Квадратные уравнения"},
    )
    assert response.status_code == 200
    tenant_a.lesson.refresh_from_db()
    assert tenant_a.lesson.topic == "Квадратные уравнения"


def test_cannot_unmark_lesson_with_existing_grades(client, tenant_a, graded_lesson):
    login(client, tenant_a, tenant_a.teacher_user)
    client.post(
        reverse("cabinet:grade_save", args=[tenant_a.lesson.pk]),
        {"student": str(tenant_a.student.pk), "points": "5"},
    )
    response = client.post(
        reverse("cabinet:lesson_toggle_graded", args=[tenant_a.lesson.pk]), {"is_graded": "0"}
    )
    assert "Сначала удалите выставленные баллы" in response.content.decode()
    tenant_a.lesson.refresh_from_db()
    assert tenant_a.lesson.is_graded is True


def test_empty_points_removes_grade(client, tenant_a, graded_lesson):
    login(client, tenant_a, tenant_a.teacher_user)
    url = reverse("cabinet:grade_save", args=[tenant_a.lesson.pk])
    client.post(url, {"student": str(tenant_a.student.pk), "points": "5"})
    client.post(url, {"student": str(tenant_a.student.pk), "points": ""})

    with organization_context(tenant_a.organization):
        assert Grade.objects.filter(student=tenant_a.student).count() == 0
        # Мягкое удаление: запись остаётся в базе и её можно восстановить.
        assert Grade.all_objects.filter(student=tenant_a.student).count() == 1
        result = ModuleResult.objects.get(student=tenant_a.student, subject=tenant_a.subject)
        assert result.total_points == Decimal("0.00")


def test_lead_funnel_requires_decline_reason(client, tenant_a):
    from apps.site_public.models import Lead

    with organization_context(tenant_a.organization):
        lead = Lead.objects.create(
            organization=tenant_a.organization, name="Ольга", phone="79130001122",
            grade=9, call_window=Lead.CallWindow.DAY,
            consent_at="2026-08-01T10:00:00Z", policy_version="2026-08-01",
        )
    login(client, tenant_a, tenant_a.owner_user)
    response = client.post(
        reverse("cabinet:lead_status", args=[lead.pk]), {"status": Lead.Status.DECLINED}
    )
    assert response.status_code == 422
    assert "причину отказа" in response.content.decode().lower()

    ok = client.post(
        reverse("cabinet:lead_status", args=[lead.pk]),
        {"status": Lead.Status.DECLINED, "decline_reason": "Далеко ехать"},
    )
    assert ok.status_code == 200
    lead.refresh_from_db()
    assert lead.status == Lead.Status.DECLINED
