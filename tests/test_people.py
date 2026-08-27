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


def test_login_is_short_and_stays_unique(db, tenant_a):
    """
    Логин диктуют по телефону, поэтому это фамилия, а не адрес почты.

    Имя добавляется только при совпадении фамилий: «sokolova»,
    потом «sokolova.m», потом «sokolova.m2».
    """
    assert onboarding.build_login("Петрова", "Мария") == "petrova"

    get_user_model().objects.create_user(username="petrova", password="x")
    assert onboarding.build_login("Петрова", "Мария") == "petrova.m"

    get_user_model().objects.create_user(username="petrova.m", password="x")
    assert onboarding.build_login("Петрова", "Мария") == "petrova.m2"


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
    assert student.user.username == "sokolova"
    assert "sokolova" in body
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
        reverse("cabinet:staff_create"),
        {
            "last_name": "Крылов", "first_name": "Олег", "middle_name": "",
            "phone": "", "email": "", "role": "teacher",
            "teacher-hourly_rate": "1200", "teacher-public_position": "100",
            "teacher-subjects": [str(tenant_a.subject.pk)],
        },
    )

    teacher = Teacher.all_objects.get(
        organization=tenant_a.organization, user__last_name="Крылов"
    )
    from apps.core.tenancy import organization_context

    assert teacher.hourly_rate == 1200
    with organization_context(tenant_a.organization):
        assert tenant_a.subject in teacher.subjects.all()
    assert "krylov" in response.content.decode()


def test_admin_can_only_add_teachers(client, tenant_a):
    """
    Администратор, заводящий себе администраторов, — не роль, а дыра.

    Педагогов он заводит: это его работа. Владельцев и администраторов —
    нет, такой роли в списке для него просто не будет.
    """
    from django.test import override_settings

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
        body = client.get(reverse("cabinet:staff_create")).content.decode()
        sneaky = client.post(
            reverse("cabinet:staff_create"),
            {
                "last_name": "Свой", "first_name": "Человек", "middle_name": "",
                "phone": "", "email": "", "role": "owner",
            },
        )

    assert 'value="teacher"' in body
    assert 'value="owner"' not in body
    assert not Membership.objects.filter(
        organization=tenant_a.organization, role=Role.OWNER, user__last_name="Свой"
    ).exists()
    assert sneaky.status_code == 200


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


# ─── Кабинет родителя и отзывы ──────────────────────────────────────────────

def test_parent_sees_overall_progress(client, tenant_a):
    """
    Родителю нужен один ответ на «как дела», а не только разбор по предметам.
    """
    from decimal import Decimal

    from apps.journal.models import ModuleResult

    ModuleResult.all_objects.create(
        organization=tenant_a.organization, student=tenant_a.student,
        subject=tenant_a.subject, module=tenant_a.module,
        total_points=Decimal("72.00"), is_passed=True,
    )
    _login(client, tenant_a, tenant_a.parent_user)
    body = client.get(reverse("cabinet:parent_home")).content.decode()

    assert "Всего за модуль" in body
    assert "Зачётов закрыто: 1 из 1" in body


def test_parent_sees_only_teachers_of_their_child(client, tenant_a, tenant_b):
    _login(client, tenant_a, tenant_a.parent_user)
    body = client.get(reverse("cabinet:parent_teachers")).content.decode()

    assert tenant_a.teacher.user.full_name in body
    assert tenant_b.teacher.user.full_name not in body


def test_review_can_be_left_only_about_own_teacher(client, tenant_a, tenant_b):
    _login(client, tenant_a, tenant_a.parent_user)

    mine = client.get(reverse("cabinet:review_create", args=[tenant_a.teacher.pk]))
    assert mine.status_code == 200

    foreign = client.get(reverse("cabinet:review_create", args=[tenant_b.teacher.pk]))
    assert foreign.status_code in (403, 404)


def test_review_waits_for_moderation_before_appearing_on_the_site(client, tenant_a):
    """
    Публичная страница — зона ответственности центра.

    Отзыв появляется на сайте только после того, как его кто-то прочитал.
    """
    from apps.site_public.models import TeacherReview

    # Отзыв виден на сайте только у опубликованного педагога — как и он сам.
    tenant_a.teacher.is_published = True
    tenant_a.teacher.subject_line = "Математика"
    tenant_a.teacher.save()

    _login(client, tenant_a, tenant_a.parent_user)
    client.post(
        reverse("cabinet:review_create", args=[tenant_a.teacher.pk]),
        {"rating": "5", "text": "Ребёнок перестал бояться математики."},
    )

    review = TeacherReview.all_objects.get(teacher=tenant_a.teacher)
    assert review.status == TeacherReview.Status.PENDING

    public = client.get(reverse("public:landing")).content.decode()
    assert "перестал бояться" not in public

    review.status = TeacherReview.Status.PUBLISHED
    review.save(update_fields=["status"])
    published = client.get(reverse("public:landing")).content.decode()
    assert "перестал бояться" in published


def test_review_signature_hides_the_family_name(client, tenant_a):
    from apps.site_public.models import TeacherReview

    _login(client, tenant_a, tenant_a.parent_user)
    client.post(
        reverse("cabinet:review_create", args=[tenant_a.teacher.pk]),
        {"rating": "4", "text": "Хороший педагог."},
    )
    review = TeacherReview.all_objects.get(teacher=tenant_a.teacher)

    assert tenant_a.parent_user.last_name not in review.author_label
    assert tenant_a.parent_user.first_name in review.author_label


def test_editing_a_review_sends_it_back_to_moderation(client, tenant_a):
    from apps.site_public.models import TeacherReview

    _login(client, tenant_a, tenant_a.parent_user)
    url = reverse("cabinet:review_create", args=[tenant_a.teacher.pk])
    client.post(url, {"rating": "5", "text": "Первый вариант."})

    review = TeacherReview.all_objects.get(teacher=tenant_a.teacher)
    review.status = TeacherReview.Status.PUBLISHED
    review.save(update_fields=["status"])

    client.post(url, {"rating": "3", "text": "Передумал."})
    review.refresh_from_db()

    assert review.status == TeacherReview.Status.PENDING
    assert TeacherReview.all_objects.filter(teacher=tenant_a.teacher).count() == 1


def test_parent_can_be_added_to_an_existing_child(admin_client, tenant_a):
    from apps.journal.models import StudentParent

    response = admin_client.post(
        reverse("cabinet:parent_invite", args=[tenant_a.student.pk]),
        {
            "last_name": "Второв", "first_name": "Пётр", "middle_name": "",
            "phone": "", "email": "", "relation": "папа", "is_primary_contact": "",
        },
    )

    assert response.status_code == 200
    assert "vtorov" in response.content.decode()
    assert StudentParent.all_objects.filter(
        student=tenant_a.student, parent__last_name="Второв"
    ).exists()
