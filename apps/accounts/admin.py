from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from apps.accounts.models import Membership, TwoFactorDevice, User


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 1
    autocomplete_fields = ["organization"]


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ("last_name", "first_name")
    list_display = ("__str__", "email", "phone", "is_active", "is_staff")
    list_filter = ("is_active", "is_staff", "is_superuser", "memberships__role")
    search_fields = ("email", "phone", "last_name", "first_name")
    inlines = [MembershipInline]
    fieldsets = (
        (None, {"fields": ("email", "phone", "password")}),
        ("ФИО", {"fields": ("last_name", "first_name", "middle_name")}),
        ("Права", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Служебное", {"fields": ("last_login", "last_activity_at")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "phone", "last_name", "first_name", "password1", "password2"),
        }),
    )
    readonly_fields = ("last_login", "last_activity_at")


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "organization", "role", "is_active")
    list_filter = ("role", "is_active", "organization")
    search_fields = ("user__email", "user__last_name")


@admin.register(TwoFactorDevice)
class TwoFactorDeviceAdmin(admin.ModelAdmin):
    list_display = ("user", "is_confirmed", "confirmed_at")
    readonly_fields = ("secret", "recovery_codes", "last_used_counter")
