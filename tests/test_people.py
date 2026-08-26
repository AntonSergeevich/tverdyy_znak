"""Выдача доступов и управление людьми в кабинете (ТЗ 5.4)."""
from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.accounts.models import Membership, Role
from apps.journal.models import Parent, Student, Teacher
from apps.journal.services import onboarding
from tests.conftest import PASSWORD


def _login(client, tenant, user):
    client.defaults["HTTP_HOST"] = tenant.host
    client.post(reverse("accounts:login"), {"username": user.email, "password": PASSWORD})


@pytest.fixture
def admin_client(client, tenant_a):
    """Владелец без второго фактора: проверяем управление, а не вход."""
    from django.test import override_settings

    with override_settings(TWO_FACTOR_ENABLED=False):
        _login(client, tenant_a, tenant_a.owner_user)
        yield client


# ─── Логины и пароли ────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "text, expected",
    [
        ("Бабаджанова", "babadzhanova"),
        ("Щербакова", "scherbakova"),
        ("Ёлкин", "elkin"),
        ("Объедков", "obedkov"),
        ("O'Brien", "obrien"),
    ],
)
def test_transliteration(text, expected):
    assert onboarding.transliterate(text) == expected


def test_login_is_built_from_name_and_stays_unique(db, tenant_a):
    first = onboarding.build_login("Петрова", "Мария", "example.org")
    assert first == "petrova.m@example.org"

    get_user_model().objects.create_user(email=first, password="x")
    second = onboarding.build_login("Петрова", "Мария", "example.org")

    assert second == "petrova.m2@example.org"


def test_password_is_readable_over_the_phone():
    """
    Пароль диктуют голосом, поэтому в нём нет 0, 1 и заглавных букв.

    Это сознательный размен: длина и алфавит слогов дают достаточную
    стойкость, а неразличимые символы стоили бы звонка «а это ноль или о».
    """
    for _ in range(50):
        password = onboarding.generate_password()
        assert "0" not in password and "1" not in password
        assert password == password.lower()
        assert len(password) >= 8


def test_issue_account_creates_user_with_role(db, tenant_a):
    user, credentials = onboarding.issue_account(
        organization=tenant_a.organization, role=Role.STUDENT,
        last_name="Смирнов", first_name="Пётр",
    )

    assert user.check_password(credentials.password)
    assert Membership.objects.filter(
        user=user, organization=tenant_a.organization, role=Role.STUDENT
    ).exists()


def test_reset_password_replaces_the_old_one(db, tenant_a):
    user, first = onboarding.issue_account(
        organization=tenant_a.organization, role=Role.TEACHER,
        last_name="Иванов", first_name="Иван",
    )
    second = onboarding.reset_password(user)
    user.refresh_from_db()

    assert first.password != second.password
    assert user.check_password(second.password)
    assert not user.check_password(first.password)


# ─── Ученики ────────────────────────────────────────────────────────────────

def test_admin_creates_student_and_sees_credentials_once(admin_client, tenant_a):
    response = admin_client.post(
        reverse("cabinet:student_create"),
        {
            "last_name": "Соколова", "first_name": "Вера", "middle_name": "",
            "phone": "", "email": "", "grade_level": "9",
            "birth_date": "", "enrolled_on": "2026-09-01", "status": "enrolled", "note": "",
            "parent_last_name": "", "parent_first_name": "",
            "parent_phone": "", "parent_email": "",
        },
    )
    body = response.content.decode()

    assert response.status_code == 200
    student = Student.all_objects.filter(
        organization=tenant_a.organization, last_name="Соколова"
    ).first()
    assert student is not None
    assert student.user is not None
    assert "sokolova.v@" in body
    assert "Пароль" in body
    assert "Скопировать для отправки" in body


def test_creating_student_with_parent_gives_two_accesses(admin_client, tenant_a):
    admin_client.post(
        reverse("cabinet:student_create"),
        {
            "last_name": "Орлов", "first_name": "Илья", "middle_name": "",
            "phone": "", "email": "", "grade_level": "10",
            "birth_date": "", "enrolled_on": "", "status": "enrolled", "note": "",
            "parent_last_name": "Орлова", "parent_first_name": "Анна",
            "parent_phone": "+7 913 111 22 33", "parent_email": "",
        },
    )

    from apps.core.tenancy import organization_context

    student = Student.all_objects.get(organization=tenant_a.organization, last_name="Орлов")
    parent = Parent.all_objects.get(organization=tenant_a.organization, last_name="Орлова")
    assert parent.user is not None
    # Связи читаем в контексте организации: без него менеджеры арендатора
    # честно отдают пустоту, и тест проверял бы не то, что нужно.
    with organization_context(tenant_a.organization):
        assert student.parent_links.filter(parent=parent).exists()


def test_half_filled_parent_is_rejected(admin_client, tenant_a):
    """Телефон без имени — контакт, про который потом не вспомнить, чей он."""
    response = admin_client.post(
        reverse("cabinet:student_create"),
        {
            "last_name": "Титов", "first_name": "Егор", "middle_name": "",
            "phone": "", "email": "", "grade_level": "8",
            "birth_date": "", "enrolled_on": "", "status": "enrolled", "note": "",
            "parent_last_name": "", "parent_first_name": "",
            "parent_phone": "+7 913 000 00 00", "parent_email": "",
        },
    )

    assert response.status_code == 200
    assert not Student.all_objects.filter(last_name="Титов").exists()
    assert "фамилия и имя" in response.content.decode()


def test_student_card_opens_from_the_list(admin_client, tenant_a):
    body = admin_client.get(reverse("cabinet:students")).content.decode()
    assert reverse("cabinet:student_card", args=[tenant_a.student.pk]) in body

    card = admin_client.get(reverse("cabinet:student_card", args=[tenant_a.student.pk]))
    assert card.status_code == 200
    assert tenant_a.student.full_name in card.content.decode()


def test_student_card_hides_private_goals(admin_client, tenant_a):
    """
    Скрытая цель ученика — скрытая и для администратора.

    Механика личных целей держится ровно на этом: если её видит начальство,
    подросток перестанет ими пользоваться.
    """
    from apps.journal.models import Goal, GoalKind, GoalVisibility

    Goal.all_objects.create(
        organization=tenant_a.organization, student=tenant_a.student,
        kind=GoalKind.PERSONAL, visibility=GoalVisibility.HIDDEN,
        title="Тайная цель", created_by=tenant_a.student_user,
    )
    body = admin_client.get(
        reverse("cabinet:student_card", args=[tenant_a.student.pk])
    ).content.decode()

    assert "Тайная цель" not in body


def test_student_delete_requires_typing_the_surname(admin_client, tenant_a):
    url = reverse("cabinet:student_delete", args=[tenant_a.student.pk])

    wrong = admin_client.post(url, {"confirm": "не та фамилия"})
    tenant_a.student.refresh_from_db()
    assert wrong.status_code == 200
    assert tenant_a.student.deleted_at is None

    right = admin_client.post(url, {"confirm": tenant_a.student.last_name})
    tenant_a.student.refresh_from_db()
    assert right.status_code == 302
    assert tenant_a.student.deleted_at is not None


def test_student_edit_moves_between_groups_without_duplicating(admin_client, tenant_a):
    from apps.journal.models import Group

    other = Group.all_objects.create(
        organization=tenant_a.organization, academic_year=tenant_a.year,
        name="Класс 10", grade_level=10,
    )
    admin_client.post(
        reverse("cabinet:student_edit", args=[tenant_a.student.pk]),
        {
            "last_name": tenant_a.student.last_name, "first_name": tenant_a.student.first_name,
            "middle_name": "", "grade_level": "10", "birth_date": "",
            "status": "enrolled", "enrolled_on": "", "attestation_partner": "", "note": "",
            "group": str(other.pk),
        },
    )

    from apps.journal.models import GroupMembership

    memberships = GroupMembership.all_objects.filter(student=tenant_a.student)
    assert memberships.count() == 1
    assert memberships.first().group == other


# ─── Педагоги и сотрудники ──────────────────────────────────────────────────

def test_admin_creates_teacher_with_rate(admin_client, tenant_a):
    response = admin_client.post(
        reverse("cabinet:teacher_create"),
        {
            "last_name": "Крылов", "first_name": "Олег", "middle_name": "",
            "phone": "", "email": "", "hourly_rate": "1200", "public_title": "",
            "subjects": [str(tenant_a.subject.pk)],
        },
    )

    teacher = Teacher.all_objects.get(
        organization=tenant_a.organization, user__last_name="Крылов"
    )
    from apps.core.tenancy import organization_context

    assert teacher.hourly_rate == 1200
    with organization_context(tenant_a.organization):
        assert tenant_a.subject in teacher.subjects.all()
    assert "krylov.o@" in response.content.decode()


def test_only_owner_can_create_staff(client, tenant_a):
    """Администратор, заводящий себе администраторов, — не роль, а дыра."""
    from django.test import override_settings

    from apps.accounts.models import Membership

    user, credentials = onboarding.issue_account(
        organization=tenant_a.organization, role=Role.ADMIN,
        last_name="Админов", first_name="Пётр",
    )
    client.defaults["HTTP_HOST"] = tenant_a.host
    with override_settings(TWO_FACTOR_ENABLED=False):
        client.post(
            reverse("accounts:login"),
            {"username": credentials.login, "password": credentials.password},
        )
        response = client.get(reverse("cabinet:staff_create"))

    assert response.status_code == 403
    assert Membership.objects.filter(organization=tenant_a.organization).count() >= 1


def test_owner_creates_admin(admin_client, tenant_a):
    admin_client.post(
        reverse("cabinet:staff_create"),
        {
            "last_name": "Новикова", "first_name": "Ольга", "middle_name": "",
            "phone": "", "email": "", "role": "admin",
        },
    )

    assert Membership.objects.filter(
        organization=tenant_a.organization, role=Role.ADMIN, user__last_name="Новикова"
    ).exists()


def test_people_pages_are_closed_for_parents(client, tenant_a):
    _login(client, tenant_a, tenant_a.parent_user)

    for name, args in [
        ("cabinet:student_create", []),
        ("cabinet:teachers", []),
        ("cabinet:staff", []),
        ("cabinet:student_card", [tenant_a.student.pk]),
    ]:
        response = client.get(reverse(name, args=args))
        assert response.status_code in (302, 403), name


def test_payment_can_be_charged_from_the_card(admin_client, tenant_a):
    from apps.journal.models import Payment

    admin_client.post(
        reverse("cabinet:payment_create", args=[tenant_a.student.pk]),
        {
            "title": "Сентябрь", "period_start": "2026-09-01", "period_end": "2026-09-30",
            "amount": "40000", "due_on": "2026-09-05", "status": "planned",
        },
    )

    payment = Payment.all_objects.get(student=tenant_a.student, title="Сентябрь")
    assert payment.amount == 40000
    assert payment.organization == tenant_a.organization
