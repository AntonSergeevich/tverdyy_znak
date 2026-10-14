"""
«Отменить» вместо «Вы уверены?» — и поиск ученика по мере набора.

Мелкое удаление делается сразу, на следующей странице приезжает плашка
с кнопкой, и эта кнопка возвращает всё как было. Где вернуть всё нельзя —
работа вместе с баллами, — отмены нет и не должно быть.
"""
from __future__ import annotations

import pytest
from django.test import Client, override_settings
from django.urls import reverse

from apps.core.tenancy import organization_context
from apps.journal.models import Grade, GradeItem, GradeItemKind, Group, GroupKind, GroupMembership
from apps.journal.services.grading import set_grade
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db

TOAST = "data-undo-toast"


def sign_in(tenant, user):
    client = Client()
    client.defaults["HTTP_HOST"] = tenant.host
    with override_settings(TWO_FACTOR_ENABLED=False):
        client.post(reverse("accounts:login"), {"username": user.email, "password": PASSWORD})
    return client


@pytest.fixture
def quiz(tenant_a):
    with organization_context(tenant_a.organization):
        return GradeItem.objects.create(
            organization=tenant_a.organization, module=tenant_a.module,
            subject=tenant_a.subject, group=tenant_a.group,
            kind=GradeItemKind.QUIZ, title="Словарный диктант", max_points=5,
        )


def test_removed_from_a_group_and_back_with_one_button(tenant_a):
    with organization_context(tenant_a.organization):
        course = Group.objects.create(
            organization=tenant_a.organization, academic_year=tenant_a.year,
            name="ОГЭ: математика", kind=GroupKind.COURSE,
        )
        GroupMembership.objects.create(
            organization=tenant_a.organization, group=course, student=tenant_a.student
        )
    owner = sign_in(tenant_a, tenant_a.owner_user)

    response = owner.post(
        reverse("cabinet:group_member_remove", args=[course.pk, tenant_a.student.pk]),
        follow=True,
    )
    body = response.content.decode()
    assert TOAST in body
    assert reverse("cabinet:group_members_add", args=[course.pk]) in body
    with organization_context(tenant_a.organization):
        assert not GroupMembership.objects.filter(group=course).exists()

    # Плашка — один раз: на следующей странице её уже нет.
    assert TOAST not in owner.get(reverse("cabinet:group_card", args=[course.pk])).content.decode()

    owner.post(
        reverse("cabinet:group_members_add", args=[course.pk]),
        {"students": str(tenant_a.student.pk), "undo": "1"},
    )
    with organization_context(tenant_a.organization):
        assert GroupMembership.objects.filter(group=course, student=tenant_a.student).exists()


def test_an_empty_work_is_deleted_and_comes_back(tenant_a, quiz):
    teacher = sign_in(tenant_a, tenant_a.teacher_user)

    body = teacher.post(
        reverse("cabinet:item_delete", args=[quiz.pk]),
        {"from": str(tenant_a.lesson.pk)}, follow=True,
    ).content.decode()
    assert TOAST in body
    assert reverse("cabinet:item_restore", args=[quiz.pk]) in body

    response = teacher.post(
        reverse("cabinet:item_restore", args=[quiz.pk]), {"from": str(tenant_a.lesson.pk)}
    )
    assert response.status_code == 302
    assert "vkladka=raboty" in response.headers["Location"]
    with organization_context(tenant_a.organization):
        assert GradeItem.objects.filter(pk=quiz.pk).exists()


def test_a_work_deleted_with_grades_has_no_undo(tenant_a, quiz):
    with organization_context(tenant_a.organization):
        set_grade(student=tenant_a.student, grade_item=quiz, points=4)
    teacher = sign_in(tenant_a, tenant_a.teacher_user)

    body = teacher.post(
        reverse("cabinet:item_delete", args=[quiz.pk]), {"drop_grades": "1"}, follow=True,
    ).content.decode()
    assert TOAST not in body

    # И в обход плашки — тоже нет: баллы ушли вместе с работой.
    teacher.post(reverse("cabinet:item_restore", args=[quiz.pk]))
    with organization_context(tenant_a.organization):
        assert not GradeItem.objects.filter(pk=quiz.pk).exists()
        assert not Grade.objects.filter(grade_item_id=quiz.pk).exists()


def test_someone_else_cannot_restore_a_work(tenant_a, tenant_b, quiz):
    sign_in(tenant_a, tenant_a.teacher_user).post(reverse("cabinet:item_delete", args=[quiz.pk]))

    stranger = sign_in(tenant_b, tenant_b.teacher_user)
    response = stranger.post(reverse("cabinet:item_restore", args=[quiz.pk]))

    assert response.status_code in (403, 404)
    with organization_context(tenant_a.organization):
        assert not GradeItem.objects.filter(pk=quiz.pk).exists()


def test_student_search_narrows_the_list_as_you_type(tenant_a):
    owner = sign_in(tenant_a, tenant_a.owner_user)
    name = tenant_a.student.last_name

    found = owner.get(reverse("cabinet:students"), {"q": name[:3]}).content.decode()
    missing = owner.get(reverse("cabinet:students"), {"q": "Яяяяя"}).content.decode()

    assert 'id="students-list"' in found
    assert tenant_a.student.last_name in found
    assert "Никого не нашли" in missing
