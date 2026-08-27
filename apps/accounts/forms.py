from __future__ import annotations

from django import forms


class LoginForm(forms.Form):
    username = forms.CharField(
        label="Логин, email или телефон",
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


class PasswordChangeForm(forms.Form):
    """
    Смена своего пароля.

    Пароли раздаёт администратор, и человек входит с чужой выдумкой —
    поменять её он должен уметь сам, не звоня в центр. Старый пароль
    спрашиваем обязательно: сессию мог оставить открытой кто угодно.
    """

    current_password = forms.CharField(
        label="Текущий пароль",
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )
    new_password = forms.CharField(
        label="Новый пароль",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="Не короче 10 символов, не только цифры и не похож на ваше имя.",
    )
    new_password_again = forms.CharField(
        label="Новый пароль ещё раз",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_current_password(self):
        value = self.cleaned_data["current_password"]
        if not self.user.check_password(value):
            raise forms.ValidationError("Текущий пароль не подошёл.")
        return value

    def clean(self):
        from django.contrib.auth.password_validation import validate_password

        data = super().clean()
        first = data.get("new_password")
        second = data.get("new_password_again")
        if first and second and first != second:
            self.add_error("new_password_again", "Пароли не совпали.")
            return data
        if first:
            try:
                validate_password(first, self.user)
            except forms.ValidationError as error:
                self.add_error("new_password", error)
        return data

    def save(self):
        self.user.set_password(self.cleaned_data["new_password"])
        self.user.save(update_fields=["password", "updated_at"])
        return self.user
