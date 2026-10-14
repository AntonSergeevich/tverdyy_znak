"""
Обновления кабинета: страница версий и отметка «окно прочитано».

Сами заметки к версиям лежат в `apps.journal.releases`.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from apps.journal import releases


@login_required
def updates(request):
    """
    Все версии — новые сверху, каждому только то, что касается его.

    Открыл страницу — значит, про текущую версию уже знает: окно после
    этого не всплывает.
    """
    audiences = releases.audiences(request.user, request.organization)
    unseen = {release.version for release in releases.unseen_releases(request.user)}
    entries = [
        {
            "release": release,
            "changes": release.changes_for(audiences),
            "is_new": release.version in unseen,
        }
        for release in releases.RELEASES
    ]
    if not request.impersonator:
        releases.mark_seen(request.user)
    return render(request, "cabinet/updates.html", {
        "entries": entries,
        "sees_everything": releases.MANAGER in audiences,
    })


@login_required
@require_POST
def updates_seen(request):
    """Окно «Что нового» закрыто — больше его про эту версию не показывать."""
    if not request.impersonator:
        releases.mark_seen(request.user)
    return HttpResponse(status=204)
