from django.contrib import admin

from apps.core.admin import TenantAdmin
from apps.site_public.models import FaqItem, Lead, LegalDocument, TeacherCard


@admin.register(Lead)
class LeadAdmin(TenantAdmin):
    list_display = ("created_at", "name", "phone_display", "grade", "status", "organization")
    list_filter = ("organization", "status", "grade", "call_window")
    search_fields = ("name", "phone")
    date_hierarchy = "created_at"
    readonly_fields = (
        "consent_at", "policy_version", "utm_source", "utm_medium", "utm_campaign",
        "utm_content", "utm_term", "referrer", "page_path", "ip", "user_agent", "notified_at",
    )


@admin.register(FaqItem)
class FaqItemAdmin(TenantAdmin):
    list_display = ("question", "position", "is_published", "organization")
    list_filter = ("organization", "is_published")


@admin.register(TeacherCard)
class TeacherCardAdmin(TenantAdmin):
    list_display = ("full_name", "subject_line", "position", "is_published")
    list_filter = ("organization", "is_published")


@admin.register(LegalDocument)
class LegalDocumentAdmin(TenantAdmin):
    list_display = ("title", "kind", "version", "edited_on", "organization")
    list_filter = ("organization", "kind")
