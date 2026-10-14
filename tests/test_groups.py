"""
Группы: семейный класс, курсы подготовки к ОГЭ, клубы.

Алина: «можно добавить группы помимо семейного класса — ОГЭ математика,
ОГЭ русский, ОГЭ обществознание, 6 класс русский язык? Я могу сама?»

Сама не могла: раздела не было, группы заводились через техническую
админку. И даже заведённая группа упиралась в два ограничения: у ученика
была ровно одна группа (сохранение карточки стирало остальные), а класс
ученика был зашит как 8–11 — шестиклассника система не пускала.
"""
from __future__ import annotations

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.core.tenancy import organization_context
from apps.journal.models import Group, GroupKind, GroupMembership, Lesson
from tests.conftest import PASSWORD


@pytest.fixture
def owner(client, tenant_a):
    with override_settings(TWO_FACTOR_ENABLED=False):
        client.defaults["HTTP_HOST"] = tenant_a.host
        client.post(
            reverse("accounts:login"),
            {"username": tenant_a.owner_user.email, "password": PASSWORD},
        )
    return client


@pytest.fixture
def oge(tenant_a):
    with organization_context(tenant_a.organization):
        return Group.objects.create(
            organization=tenant_a.organization, academic_year=tenant_a.year,
            name="ОГЭ: математика", kind=GroupKind.COURSE,
        )


def test_the_owner_creates_a_course_group_herself(owner, tenant_a):
    response = owner.post(
        reverse("cabinet:groups"),
        {"name": "ОГЭ: русский язык", "kind": "course", "grade_level": ""},
    )

    with organization_context(tenant_a.organization):
        group = Group.objects.get(name="ОГЭ: русский язык")
    assert group.kind == GroupKind.COURSE
    assert group.academic_year == tenant_a.year
    assert response.status_code == 302
    assert response.headers["Location"] == reverse("cabinet:group_card", args=[group.pk])


def test_a_group_for_sixth_graders_and_a_sixth_grader_are_allowed(owner, tenant_a):
    """Рамка 8–11 не пускала шестиклассников вовсе — ни группу, ни ученика."""
    owner.post(
        reverse("cabinet:groups"),
        {"name": "6 класс: русский язык", "kind": "course", "grade_level": "6"},
    )
    owner.post(
        reverse("cabinet:student_create"),
        {"last_name": "Шестаков", "first_name": "Миша", "middle_name": "",
         "grade_level": "6", "status": "enrolled"},
    )

    from apps.journal.models import Student

    with organization_context(tenant_a.organization):
        assert Group.objects.get(name="6 класс: русский язык").grade_level == 6
        assert Student.objects.get(last_name="Шестаков").grade_level == 6


def test_a_duplicate_name_is_refused(owner, tenant_a, oge):
    body = owner.post(
        reverse("cabinet:groups"), {"name": "огэ: математика", "kind": "course"},
    ).content.decode()

    assert "уже есть" in body


def test_members_are_added_in_bulk_and_keep_their_family_class(owner, tenant_a, oge):
    """Ученик семейного класса идёт ещё и на курс — и остаётся в классе."""
    owner.post(
        reverse("cabinet:group_members_add", args=[oge.pk]),
        {"students": [str(tenant_a.student.pk)]},
    )

    with organization_context(tenant_a.organization):
        groups = set(
            GroupMembership.objects.filter(student=tenant_a.student).values_list("group_id", flat=True)
        )
    assert groups == {tenant_a.group.pk, oge.pk}


def test_saving_the_card_no_longer_drops_the_other_groups(owner, tenant_a, oge):
    """
    Раньше в карточке была одна группа, и сохранение стирало все прочие:
    ученик вылетал с курса от любой правки фамилии.
    """
    owner.post(
        reverse("cabinet:student_edit", args=[tenant_a.student.pk]),
        {
            "last_name": "Новофамильный", "first_name": tenant_a.student.first_name,
            "middle_name": "", "grade_level": "9", "birth_date": "",
            "status": "enrolled", "enrolled_on": "", "attestation_partner": "", "note": "",
            "groups": [str(tenant_a.group.pk), str(oge.pk)],
        },
    )

    with organization_context(tenant_a.organization):
        groups = set(
            GroupMembership.objects.filter(student=tenant_a.student).values_list("group_id", flat=True)
        )
    assert groups == {tenant_a.group.pk, oge.pk}


def test_a_past_year_group_survives_saving_the_card(owner, tenant_a):
    """
    Форма показывает только группы текущего года. Членство в прошлогодней —
    история, по ней считаны баллы тех модулей, и снимать его нельзя.
    """
    import datetime as dt

    from apps.journal.models import AcademicYear

    with organization_context(tenant_a.organization):
        old_year = AcademicYear.objects.create(
            organization=tenant_a.organization, title="Прошлый",
            starts_on=dt.date(2025, 9, 1), ends_on=dt.date(2026, 5, 21), is_current=False,
        )
        old_group = Group.objects.create(
            organization=tenant_a.organization, academic_year=old_year, name="Класс прошлого года",
        )
        GroupMembership.objects.create(
            organization=tenant_a.organization, group=old_group, student=tenant_a.student
        )

    owner.post(
        reverse("cabinet:student_edit", args=[tenant_a.student.pk]),
        {
            "last_name": tenant_a.student.last_name, "first_name": tenant_a.student.first_name,
            "middle_name": "", "grade_level": "9", "birth_date": "",
            "status": "enrolled", "enrolled_on": "", "attestation_partner": "", "note": "",
            "groups": [str(tenant_a.group.pk)],
        },
    )

    with organization_context(tenant_a.organization):
        assert GroupMembership.objects.filter(student=tenant_a.student, group=old_group).exists()


def test_a_course_student_sees_lessons_of_both_groups(owner, tenant_a, oge):
    """Расписание дня ученика собирается по всем его группам."""
    from apps.journal.models import Subject
    from apps.journal.views.parent import day_lessons

    with organization_context(tenant_a.organization):
        GroupMembership.objects.create(
            organization=tenant_a.organization, group=oge, student=tenant_a.student
        )
        subject = Subject.objects.create(
            organization=tenant_a.organization, academic_year=tenant_a.year,
            name="ОГЭ: математика", weekly_hours=2,
        )
        Lesson.objects.create(
            organization=tenant_a.organization, module=tenant_a.module, subject=subject,
            group=oge, teacher=tenant_a.teacher, starts_at=tenant_a.lesson.starts_at,
        )
        subjects = {lesson.subject.name for lesson in day_lessons(tenant_a.student)}

    assert subjects == {tenant_a.subject.name, "ОГЭ: математика"}


def test_removing_a_member_keeps_their_grades(owner, tenant_a, oge):
    from decimal import Decimal

    from apps.journal.models import Grade, GradeItem, GradeItemKind
    from apps.journal.services.grading import set_grade

    with organization_context(tenant_a.organization):
        GroupMembership.objects.create(
            organization=tenant_a.organization, group=oge, student=tenant_a.student
        )
        item = GradeItem.objects.create(
            organization=tenant_a.organization, module=tenant_a.module,
            subject=tenant_a.subject, group=oge, kind=GradeItemKind.QUIZ,
            title="Пробник", max_points=10,
        )
        set_grade(student=tenant_a.student, grade_item=item, points=Decimal("7"))

    owner.post(reverse("cabinet:group_member_remove", args=[oge.pk, tenant_a.student.pk]))

    with organization_context(tenant_a.organization):
        assert not GroupMembership.objects.filter(group=oge, student=tenant_a.student).exists()
        assert Grade.objects.filter(grade_item=item, student=tenant_a.student).exists()


def test_an_empty_group_is_deleted(owner, tenant_a, oge):
    owner.post(reverse("cabinet:group_delete", args=[oge.pk]))

    with organization_context(tenant_a.organization):
        assert not Group.objects.filter(pk=oge.pk).exists()


def test_a_group_with_lessons_is_not_deleted(owner, tenant_a):
    """Удаление унесло бы каскадом журнал и баллы — оценки терять нельзя (ТЗ 9.5)."""
    response = owner.post(reverse("cabinet:group_delete", args=[tenant_a.group.pk]), follow=True)

    with organization_context(tenant_a.organization):
        assert Group.objects.filter(pk=tenant_a.group.pk).exists()
    assert "удалить нельзя" in response.content.decode()


def test_teachers_cannot_manage_groups(client, tenant_a, oge):
    with override_settings(TWO_FACTOR_ENABLED=False):
        client.defaults["HTTP_HOST"] = tenant_a.host
        client.post(
            reverse("accounts:login"),
            {"username": tenant_a.teacher_user.email, "password": PASSWORD},
        )
    response = client.post(reverse("cabinet:group_delete", args=[oge.pk]))

    assert response.status_code in (302, 403)
    with organization_context(tenant_a.organization):
        assert Group.objects.filter(pk=oge.pk).exists()


def test_another_centre_cannot_touch_the_group(tenant_b, oge, client):
    with override_settings(TWO_FACTOR_ENABLED=False):
        client.defaults["HTTP_HOST"] = tenant_b.host
        client.post(
            reverse("accounts:login"),
            {"username": tenant_b.owner_user.email, "password": PASSWORD},
        )
    response = client.post(reverse("cabinet:group_delete", args=[oge.pk]))

    assert response.status_code == 404


def test_the_menu_has_groups(owner, tenant_a):
    body = owner.get(reverse("cabinet:dashboard")).content.decode()

    assert reverse("cabinet:groups") in body
