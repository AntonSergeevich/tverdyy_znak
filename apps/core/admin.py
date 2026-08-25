"""
Админка платформы.

Тенант-менеджеры фильтруют по текущей организации, а в админке её нет.
Поэтому все ModelAdmin доменных моделей наследуют TenantAdmin и работают
через all_objects — это единственное разрешённое место без фильтра.
"""
from __future__ import annotations

from django.contrib import admin

from apps.core.models import AuditLog, Consent, Organization, OrganizationDomain


class TenantAdmin(admin.ModelAdmin):
    """База для доменных моделей: полный доступ, фильтр по организации в списке."""

    def get_queryset(self, request):
        queryset = self.model.all_objects.all()
        ordering = self.get_ordering(request)
        if ordering:
            queryset = queryset.order_by(*ordering)
        return queryset


class OrganizationDomainInline(admin.TabularInline):
    model = OrganizationDomain
    extra = 1


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "timezone", "is_active", "price_full_month")
    search_fields = ("name", "slug", "legal_name", "inn")
    list_filter = ("is_active",)
    inlines = [OrganizationDomainInline]
    fieldsets = (
        (None, {"fields": ("name", "slug", "is_active", "timezone")}),
        ("Реквизиты", {"fields": ("legal_name", "inn", "ogrnip", "address")}),
        ("Контакты", {"fields": ("contact_phone", "contact_email", "telegram_chat_id")}),
        ("Банковские реквизиты", {
            "fields": ("bank_name", "bank_bik", "bank_account", "bank_corr_account"),
            "description": "Видны только в кабинете родителя, на публичных страницах их нет.",
        }),
        ("Оценивание", {
            "fields": ("module_max_points", "lesson_max_points", "grade_backdate_days"),
            "description": "Пороги уровней настраиваются в шкале оценивания.",
        }),
        ("Хранение данных", {"fields": ("data_retention_days", "lead_retention_days")}),
        ("Публичные цены", {
            "fields": ("price_full_month", "price_program_month", "price_mentor_month",
                       "price_entry_year", "price_career", "tutors_reference_price",
                       "tutors_reference_note"),
        }),
    )


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor_label", "action", "object_type", "object_id", "ip")
    list_filter = ("action", "organization")
    search_fields = ("actor_label", "object_id", "ip")
    date_hierarchy = "created_at"
    readonly_fields = [field.name for field in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        # Журнал доступа не удаляется вместе с основными данными (ТЗ 8.4).
        return False


@admin.register(Consent)
class ConsentAdmin(admin.ModelAdmin):
    list_display = ("granted_at", "consent_type", "subject_label", "document_version", "revoked_at")
    list_filter = ("consent_type", "organization")
    search_fields = ("subject_label",)
    date_hierarchy = "granted_at"
