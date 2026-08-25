from django.contrib import admin

from apps.core.admin import TenantAdmin
from apps.notifications.models import Notification


@admin.register(Notification)
class NotificationAdmin(TenantAdmin):
    list_display = ("created_at", "channel", "kind", "recipient", "status", "attempts")
    list_filter = ("organization", "channel", "status")
    search_fields = ("recipient", "subject_id")
    readonly_fields = ("attempts", "sent_at", "last_error")
