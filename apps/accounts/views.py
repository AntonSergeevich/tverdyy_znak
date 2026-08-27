"""Вход, второй фактор, выход. Бизнес-логики здесь минимум."""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout, update_session_auth_hash
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from apps.accounts import totp
from apps.accounts.forms import (
    LoginForm,
    PasswordChangeForm,
    TwoFactorForm,
    TwoFactorSetupForm,
)
from apps.accounts.impersonation import (
    SESSION_KEY as IMPERSONATE_KEY,
    can_impersonate,
    may_be_impersonated,
)
from apps.accounts.models import Membership, Role, TwoFactorDevice
from apps.core.audit import AuditAction, log_audit

PENDING_USER_KEY = "_2fa_pending_user"


def _next_url(request) -> str:
    candidate = request.POST.get("next") or request.GET.get("next")
    if candidate and candidate.startswith("/") and not candidate.startswith("//"):
        return candidate
    return reverse("cabinet:home")


@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect(_next_url(request))

    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = authenticate(
            request,
            username=form.cleaned_data["username"],
            password=form.cleaned_data["password"],
        )
        if user is None:
            log_audit(
                action=AuditAction.LOGIN_FAILED, request=request,
                login=form.cleaned_data["username"][:100],
            )
            form.add_error(None, "Не подходит email, телефон или пароль.")
        elif user.requires_two_factor:
            request.session[PENDING_USER_KEY] = str(user.pk)
            request.session["_2fa_next"] = _next_url(request)
            return redirect("accounts:two_factor")
        else:
            login(request, user)
            _mark_login(request, user)
            return redirect(_next_url(request))

    return render(request, "accounts/login.html", {"form": form, "next": _next_url(request)})


def _mark_login(request, user) -> None:
    user.last_activity_at = timezone.now()
    user.save(update_fields=["last_activity_at", "updated_at"])
    log_audit(action=AuditAction.LOGIN, request=request, actor=user)


def _pending_user(request):
    user_id = request.session.get(PENDING_USER_KEY)
    if not user_id:
        return None
    return get_user_model().objects.filter(pk=user_id, is_active=True).first()


@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def two_factor_view(request):
    """
    Второй фактор для владельца, администратора и админа платформы (ТЗ 8.2).

    Если устройство ещё не подключено — сразу ведём на подключение,
    иначе привилегированная роль осталась бы с одним паролем.
    """
    user = _pending_user(request)
    if user is None:
        return redirect("accounts:login")

    device = getattr(user, "totp_device", None)
    if device is None or not device.is_confirmed:
        return redirect("accounts:two_factor_setup")

    form = TwoFactorForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        code = form.cleaned_data["code"]
        counter = totp.verify(device.secret, code, last_used_counter=device.last_used_counter)
        if counter is not None:
            device.last_used_counter = counter
            device.save(update_fields=["last_used_counter", "updated_at"])
            return _finish_two_factor(request, user)
        if device.consume_recovery_code(code):
            messages.warning(request, "Использован резервный код. Сгенерируйте новые в профиле.")
            return _finish_two_factor(request, user)
        log_audit(action=AuditAction.LOGIN_FAILED, request=request, actor=user, stage="2fa")
        form.add_error("code", "Код не подошёл. Проверьте время на устройстве.")

    return render(request, "accounts/two_factor.html", {"form": form})


def _finish_two_factor(request, user):
    next_url = request.session.pop("_2fa_next", None)
    request.session.pop(PENDING_USER_KEY, None)
    login(request, user, backend="apps.accounts.backends.EmailOrPhoneBackend")
    _mark_login(request, user)
    return redirect(next_url or reverse("cabinet:home"))


@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def two_factor_setup_view(request):
    user = request.user if request.user.is_authenticated else _pending_user(request)
    if user is None:
        return redirect("accounts:login")

    device, _ = TwoFactorDevice.objects.get_or_create(
        user=user, defaults={"secret": totp.generate_secret()}
    )
    if not device.is_confirmed and not device.secret:
        device.secret = totp.generate_secret()
        device.save(update_fields=["secret", "updated_at"])

    form = TwoFactorSetupForm(request.POST or None)
    recovery_codes = None
    if request.method == "POST" and form.is_valid():
        counter = totp.verify(device.secret, form.cleaned_data["code"])
        if counter is not None:
            device.last_used_counter = counter
            device.confirm()
            recovery_codes = device.generate_recovery_codes()
            log_audit(action=AuditAction.PERMISSION_CHANGED, request=request, actor=user, change="2fa_enabled")
            return render(
                request,
                "accounts/two_factor_setup.html",
                {"device": device, "recovery_codes": recovery_codes, "confirmed": True},
            )
        form.add_error("code", "Код не подошёл. Проверьте, что добавили ключ целиком.")

    organization = getattr(request, "organization", None)
    # Издателя пишем латиницей: кириллица в otpauth-ссылке разбухает
    # в процентном кодировании — QR становится плотнее и хуже сканируется,
    # а часть приложений показывает её как мусор.
    issuer = (organization.primary_domain or organization.slug) if organization else "tverdyy-znak.ru"
    uri = totp.provisioning_uri(
        device.secret,
        account=user.login or str(user.pk),
        issuer=issuer,
    )
    return render(
        request,
        "accounts/two_factor_setup.html",
        {
            "form": form,
            "device": device,
            "uri": uri,
            "qr_svg": totp.qr_svg(uri),
            # Секрет группами по четыре: так его реально перепечатать руками,
            # если камера не работает.
            "secret_groups": [device.secret[i:i + 4] for i in range(0, len(device.secret), 4)],
            "confirmed": device.is_confirmed,
        },
    )


@never_cache
@csrf_protect
@login_required
@require_http_methods(["GET", "POST"])
def profile_view(request):
    """
    Свой профиль: чем входить, как сменить пароль, что со вторым фактором.

    Пароли в центре раздаёт администратор — без этой страницы человек
    навсегда оставался бы с придуманным за него паролем, а найти
    настройку двухфакторки было бы вовсе неоткуда.
    """
    user = request.user
    form = PasswordChangeForm(user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        # Смена пароля выкидывает из всех сессий, включая текущую.
        # Без этого человек меняет пароль и тут же оказывается на входе.
        update_session_auth_hash(request, user)
        log_audit(action=AuditAction.PASSWORD_CHANGED, request=request, actor=user)
        messages.success(request, "Пароль изменён. На других устройствах придётся войти заново.")
        return redirect("accounts:profile")

    device = TwoFactorDevice.objects.filter(user=user).first()
    organization = getattr(request, "organization", None)
    return render(
        request,
        "accounts/profile.html",
        {
            "form": form,
            "device": device,
            "two_factor_required": user.requires_two_factor,
            "roles": sorted(
                Role(role).label for role in user.roles_in(organization)
            ) if organization else [],
        },
    )


# ── Просмотр от чужого лица ─────────────────────────────────────────────────

def _real_user(request):
    """
    Кто на самом деле нажимает кнопку.

    Пока просмотр включён, request.user — это тот, чей кабинет смотрят.
    Право проверяем по настоящему человеку, иначе переключиться на другой
    кабинет было бы нельзя: маска сама себе прав не даёт.
    """
    return getattr(request, "impersonator", None) or request.user


def _impersonation_guard(request):
    """Право на просмотр — у администратора платформы, и только у него."""
    if not can_impersonate(_real_user(request), getattr(request, "organization", None)):
        raise PermissionDenied("Просмотр чужого кабинета доступен администратору платформы.")


@never_cache
@login_required
def impersonate_list(request):
    """
    Кого можно посмотреть.

    Список — по ролям, потому что смотрят обычно не человека, а роль:
    «что видит родитель», «что видит ученик».
    """
    _impersonation_guard(request)
    organization = request.organization

    memberships = (
        Membership.objects.filter(organization=organization, is_active=True)
        .select_related("user")
        .order_by("role", "user__last_name", "user__first_name")
    )
    groups: dict[str, list] = {}
    for membership in memberships:
        if not may_be_impersonated(membership.user, organization):
            continue
        groups.setdefault(Role(membership.role).label, []).append(membership.user)

    return render(
        request,
        "accounts/impersonate.html",
        {"groups": sorted(groups.items()), "viewing": getattr(request, "impersonator", None)},
    )


@never_cache
@csrf_protect
@login_required
@require_http_methods(["POST"])
def impersonate_start(request, user_id):
    """Включить просмотр кабинета этого человека."""
    _impersonation_guard(request)
    organization = request.organization

    target = get_object_or_404(
        get_user_model().objects.filter(
            memberships__organization=organization, memberships__is_active=True
        ).distinct(),
        pk=user_id,
    )
    if not may_be_impersonated(target, organization):
        raise PermissionDenied(
            "Так можно смотреть только тех, у кого нет прав администратора."
        )

    request.session[IMPERSONATE_KEY] = str(target.pk)
    log_audit(
        action=AuditAction.PERMISSION_CHANGED, request=request, actor=_real_user(request),
        obj=target, change="impersonation_started",
    )
    return redirect("cabinet:home")


@never_cache
@csrf_protect
@login_required
@require_http_methods(["POST"])
def impersonate_stop(request):
    """Вернуться к себе."""
    target_id = request.session.pop(IMPERSONATE_KEY, None)
    actor = _real_user(request)
    if target_id:
        log_audit(
            action=AuditAction.PERMISSION_CHANGED, request=request, actor=actor,
            change="impersonation_stopped", target=str(target_id),
        )
    return redirect("cabinet:home")


@require_http_methods(["POST", "GET"])
def logout_view(request):
    if request.user.is_authenticated:
        log_audit(action=AuditAction.LOGOUT, request=request, actor=request.user)
    logout(request)
    return redirect("public:landing")


def healthz(request) -> HttpResponse:
    return HttpResponse("ok", content_type="text/plain")
