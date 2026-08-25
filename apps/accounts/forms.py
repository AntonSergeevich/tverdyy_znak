from __future__ import annotations

from django import forms


class LoginForm(forms.Form):
    username = forms.CharField(
        label="Email или телефон",
        widget=forms.TextInput(attrs={"autocomplete": "username", "autofocus": "autofocus"}),
    )
    password = forms.CharField(
        label="Пароль", widget=forms.PasswordInput(attrs={"autocomplete": "current-password"})
    )


class TwoFactorForm(forms.Form):
    code = forms.CharField(
        label="Код из приложения",
        max_length=16,
        widget=forms.TextInput(
            attrs={"inputmode": "numeric", "autocomplete": "one-time-code", "autofocus": "autofocus"}
        ),
    )


class TwoFactorSetupForm(TwoFactorForm):
    """Подтверждение вновь подключённого устройства."""
