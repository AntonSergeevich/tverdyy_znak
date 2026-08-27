"""
Просмотр кабинета от лица другого человека.

Нужен тому, кто отвечает за платформу: проверить, что на самом деле видит
ученик, родитель или педагог. Иначе это делается чужим паролем — а тогда
в журнале остаётся, что заходил сам человек, и разобрать потом, кто что
сделал, невозможно.

За этими экранами персональные данные детей, поэтому правила жёсткие:

— включает только администратор платформы. Владелец и администратор
  центра — не могут: у них своя работа, и читать переписку ребёнка с
  наставником от его имени им незачем;
— смотреть можно только тех, у кого нет привилегированной роли. Иначе
  просмотр от лица владельца — это способ стать владельцем;
— пока смотришь, ничего изменить нельзя: любой запрос на изменение
  отклоняется. Проверка — это чтение;
— скрытые цели ученика остаются скрытыми. Ребёнку в интерфейсе обещано,
  что их не видит никто, и просмотр от его лица — не повод нарушить
  обещание;
— вход и выход пишутся в журнал действий.
"""
from __future__ import annotations

from apps.accounts.models import PRIVILEGED_ROLES, Role

SESSION_KEY = "_impersonate_user_id"


def can_impersonate(user, organization) -> bool:
    """Кто вправе смотреть чужими глазами."""
    if user is None or not user.is_authenticated or organization is None:
        return False
    return user.is_superuser or user.has_role(organization, Role.PLATFORM_ADMIN)


def may_be_impersonated(user, organization) -> bool:
    """
    Кого можно смотреть.

    Привилегированные роли исключены не из вежливости: без этого просмотр
    от лица владельца был бы способом им стать.
    """
    if user is None or organization is None or not user.is_active:
        return False
    if user.is_superuser:
        return False
    memberships = user.memberships.filter(organization=organization, is_active=True)
    # Членство в этой организации обязательно: иначе подделанный номер в
    # сессии открыл бы кабинет человека из чужого центра.
    if not memberships.exists():
        return False
    return not memberships.filter(role__in=PRIVILEGED_ROLES).exists()


def is_impersonating(request) -> bool:
    return getattr(request, "impersonator", None) is not None
