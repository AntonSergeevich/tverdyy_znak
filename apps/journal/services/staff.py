"""
Роли сотрудника в организации.

Роль — это не поле человека, а строка членства: один и тот же человек
бывает и владельцем, и педагогом сразу. Именно так устроен центр: Алина
ведёт утренний круг и при этом им руководит. Поэтому роли меняются
набором галочек, а не переключателем «или-или».

Проверки здесь, а не во вью: снять с организации последнего владельца
или запереть самого себя одинаково нельзя, откуда бы это ни пришло.
"""
from __future__ import annotations

from django.core.exceptions import ValidationError

from apps.accounts.models import Membership, PRIVILEGED_ROLES, Role

# Роли, которые заводятся и меняются в разделе «Сотрудники».
STAFF_ROLE_CHOICES = [
    (Role.OWNER, "владелец"),
    (Role.ADMIN, "администратор"),
    (Role.TEACHER, "педагог"),
]
PLATFORM_ROLE_CHOICE = (Role.PLATFORM_ADMIN, "администратор платформы")


def role_choices(*, with_platform_admin: bool = False) -> list[tuple[str, str]]:
    choices = list(STAFF_ROLE_CHOICES)
    if with_platform_admin:
        choices.append(PLATFORM_ROLE_CHOICE)
    return choices


def current_roles(user, organization) -> set[str]:
    return set(
        user.memberships.filter(organization=organization, is_active=True).values_list(
            "role", flat=True
        )
    )


def check_role_change(*, actor, target, organization, roles: set[str]) -> None:
    """
    Можно ли так поменять роли. Бросает ValidationError с человеческим текстом.
    """
    before = current_roles(target, organization)
    if before == roles:
        return

    actor_is_owner = actor.is_superuser or actor.has_role(organization, Role.OWNER)
    actor_is_platform = actor.is_superuser or actor.has_role(
        organization, Role.PLATFORM_ADMIN
    )

    if not (actor_is_owner or actor_is_platform):
        raise ValidationError("Менять роли может только владелец.")

    # Роль сопровождения платформы — не из кабинета центра.
    if (Role.PLATFORM_ADMIN in roles) != (Role.PLATFORM_ADMIN in before):
        if not actor_is_platform:
            raise ValidationError(
                "Роль администратора платформы выдаёт только администратор платформы."
            )

    # Трогать владельца может только владелец: иначе роль администратора
    # превращается в способ добраться до владельца.
    if (before | roles) & {Role.OWNER, Role.PLATFORM_ADMIN} and not (
        actor_is_owner or actor_is_platform
    ):
        raise ValidationError("Права владельца меняет только владелец.")

    if Role.OWNER in before and Role.OWNER not in roles:
        others = (
            Membership.objects.filter(
                organization=organization, role=Role.OWNER, is_active=True
            )
            .exclude(user=target)
            .exists()
        )
        if not others:
            raise ValidationError(
                "Это последний владелец организации. Сначала назначьте другого."
            )

    # Снять права с самого себя — верный способ запереть за собой дверь.
    if target.pk == actor.pk and not (roles & set(PRIVILEGED_ROLES)):
        raise ValidationError(
            "Нельзя снять права с самого себя — попросите об этом другого владельца."
        )


def set_roles(*, target, organization, roles: set[str]) -> None:
    """Привести членства к заданному набору. Лишние гасим, недостающие заводим."""
    Membership.objects.filter(organization=organization, user=target).exclude(
        role__in=roles
    ).update(is_active=False)
    for role in roles:
        membership, created = Membership.objects.get_or_create(
            user=target, organization=organization, role=role,
            defaults={"is_active": True},
        )
        if not created and not membership.is_active:
            membership.is_active = True
            membership.save(update_fields=["is_active"])
