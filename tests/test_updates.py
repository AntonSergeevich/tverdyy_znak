"""
Обновления кабинета: окно «Что нового» и страница версий.

Окно показывается один раз на версию и только тем, кто пользовался
кабинетом до неё. Закрыл — сервер помнит, на другом устройстве не всплывёт.
Каждому — про его роль.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.journal import releases
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db

DIALOG = "data-whats-new"


@pytest.fixture
def logged_in(tenant_a):
    """Свой браузер на каждого: в одном тесте бывает и педагог, и родитель."""
    from django.test import Client, override_settings

    def _login(user):
        client = Client()
        client.defaults["HTTP_HOST"] = tenant_a.host
        with override_settings(TWO_FACTOR_ENABLED=False):
            client.post(reverse("accounts:login"), {"username": user.email, "password": PASSWORD})
        return client

    return _login


def _old_timer(user):
    """Пользователь, пришедший в кабинет задолго до текущей версии."""
    User.objects.filter(pk=user.pk).update(
        created_at=timezone.now() - dt.timedelta(days=400), release_seen=""
    )
    user.refresh_from_db()
    return user


def _home(browser, name):
    return browser.get(reverse(name)).content.decode()


def test_dialog_appears_once_for_an_old_timer(logged_in, tenant_a):
    browser = logged_in(_old_timer(tenant_a.teacher_user))

    body = _home(browser, "cabinet:teacher_today")
    assert DIALOG in body
    assert releases.CURRENT.version in body

    assert browser.post(reverse("cabinet:updates_seen")).status_code == 204

    assert DIALOG not in _home(browser, "cabinet:teacher_today")
    tenant_a.teacher_user.refresh_from_db()
    assert tenant_a.teacher_user.release_seen == releases.CURRENT.version


def test_newcomer_is_not_told_what_changed(logged_in, tenant_a):
    """Для того, кто пришёл после выхода версии, так было всегда."""
    User.objects.filter(pk=tenant_a.parent_user.pk).update(
        created_at=timezone.make_aware(
            dt.datetime.combine(releases.CURRENT.date, dt.time(12))
        ),
        release_seen="",
    )

    assert DIALOG not in _home(logged_in(tenant_a.parent_user), "cabinet:parent_home")


def test_dialog_speaks_about_the_reader_role(logged_in, tenant_a):
    teacher = _home(logged_in(_old_timer(tenant_a.teacher_user)), "cabinet:teacher_today")
    parent = _home(logged_in(_old_timer(tenant_a.parent_user)), "cabinet:parent_home")

    # Первый пункт, который окно покажет педагогу, но не родителю.
    shown_to_teacher = [
        change
        for release in releases.RELEASES if release.announce
        for change in release.changes if change.is_for({releases.TEACHER})
    ][:5]
    for_staff = next(
        change.title for change in shown_to_teacher
        if change.roles and releases.PARENT not in change.roles
    )
    assert for_staff in teacher
    assert for_staff not in parent


def test_updates_page_lists_versions_and_counts_as_read(logged_in, tenant_a):
    user = _old_timer(tenant_a.student_user)
    browser = logged_in(user)

    body = browser.get(reverse("cabinet:updates")).content.decode()

    for release in releases.RELEASES:
        assert f'id="{release.anchor}"' in body
    user.refresh_from_db()
    assert user.release_seen == releases.CURRENT.version
    assert DIALOG not in _home(browser, "cabinet:student_home")


def test_account_menu_marks_unread_updates(logged_in, tenant_a):
    browser = logged_in(_old_timer(tenant_a.owner_user))

    assert "data-release-dot" in _home(browser, "cabinet:dashboard")
    browser.post(reverse("cabinet:updates_seen"))
    assert "data-release-dot" not in _home(browser, "cabinet:dashboard")


def test_missed_versions_are_told_together():
    """Пропустил несколько версий — узнает про все в одном окне; история 1.x — никогда."""
    announced = [release for release in releases.RELEASES if release.announce]
    assert len(announced) >= 2
    user = User(release_seen="", created_at=timezone.now() - dt.timedelta(days=400))
    assert releases.unseen_releases(user) == announced

    user.release_seen = announced[1].version
    assert releases.unseen_releases(user) == announced[:1]

    user.release_seen = releases.CURRENT.version
    assert releases.unseen_releases(user) == []


def test_versions_are_unique_and_newest_first():
    versions = [release.version for release in releases.RELEASES]
    assert len(versions) == len(set(versions))
    dates = [release.date for release in releases.RELEASES]
    assert dates == sorted(dates, reverse=True)


def test_every_picture_of_every_version_exists():
    """
    На проде статика собрана с манифестом: ссылка на картинку, которой нет,
    — это не пустая рамка, а ошибка 500 на каждой странице кабинета.
    """
    static_root = Path(settings.BASE_DIR) / "static"
    missing = [
        media.src
        for release in releases.RELEASES
        for change in release.changes
        for media in change.media
        if not (static_root / media.src).is_file()
    ]
    assert missing == []


def test_lesson_page_is_split_into_tabs(logged_in, tenant_a):
    body = logged_in(tenant_a.teacher_user).get(
        reverse("cabinet:lesson_journal", args=[tenant_a.lesson.pk])
    ).content.decode()

    for name in ("ucheniki", "domashnee", "raboty"):
        assert f'data-tab="{name}"' in body
        assert f'data-tab-panel="{name}"' in body
    # Тема — над вкладками, видна на любой.
    assert body.index('id="lesson-topic"') < body.index("data-tabs")
