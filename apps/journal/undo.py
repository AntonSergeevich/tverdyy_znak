"""
«Отменить» вместо «Вы уверены?».

Мелкие удаления — убрать ученика из группы, удалить пустую работу —
делаются сразу, без вопроса, а на несколько секунд появляется плашка
с кнопкой «Отменить». Вопрос «Вы уверены?» учит нажимать «Да» не глядя;
отмена исправляет ошибку, когда её уже видно.

Удалённое при этом должно возвращаться целиком. Поэтому отмену предлагаем
только там, где это правда: членство в группе восстанавливается заново,
работа удалена мягко. Где вернуть всё нельзя (работа вместе с баллами,
удаление ученика с его персональными данными), подтверждение остаётся.

Предложение живёт в сессии до следующей страницы: действие уходит
переадресацией, и плашка должна приехать вместе со страницей, на которую
вернули.
"""
from __future__ import annotations

from functools import cached_property

SESSION_KEY = "undo_offer"


def offer(request, text: str, url: str, fields: dict | None = None) -> None:
    request.session[SESSION_KEY] = {
        "text": text,
        "url": url,
        "fields": {key: str(value) for key, value in (fields or {}).items()},
    }


class _Offer:
    """Достаётся из сессии один раз — когда шаблон о нём спросил."""

    def __init__(self, request):
        self._request = request

    @cached_property
    def item(self) -> dict | None:
        session = getattr(self._request, "session", None)
        if session is None:
            return None
        return session.pop(SESSION_KEY, None)


def undo_offer(request) -> dict:
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return {}
    return {"undo": _Offer(request)}
