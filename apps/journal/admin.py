from django.contrib import admin

from apps.core.admin import TenantAdmin
from apps.journal.models import (
    AcademicYear,
    Goal,
    Grade,
    GradeItem,
    GradingScale,
    Group,
    GroupMembership,
    Lesson,
    Module,
    ModuleResult,
    MoodEntry,
    Parent,
    Payment,
    Student,
    StudentParent,
    Subject,
    Teacher,
)


@admin.register(AcademicYear)
class AcademicYearAdmin(TenantAdmin):
    list_display = ("title", "organization", "starts_on", "ends_on", "is_current")
    list_filter = ("organization", "is_current")


@admin.register(Subject)
class SubjectAdmin(TenantAdmin):
    list_display = ("name", "academic_year", "weekly_hours", "position")
    list_filter = ("organization", "academic_year")
    search_fields = ("name",)


@admin.register(Module)
class ModuleAdmin(TenantAdmin):
    list_display = ("__str__", "academic_year", "kind", "starts_on", "ends_on", "focus")
    list_filter = ("organization", "academic_year", "kind")


@admin.register(Group)
class GroupAdmin(TenantAdmin):
    list_display = ("name", "kind", "academic_year", "grade_level")
    list_filter = ("organization", "kind")
    search_fields = ("name",)


class StudentParentInline(admin.TabularInline):
    model = StudentParent
    extra = 1
    raw_id_fields = ("parent",)


class GroupMembershipInline(admin.TabularInline):
    model = GroupMembership
    extra = 1


@admin.register(Student)
class StudentAdmin(TenantAdmin):
    list_display = ("full_name", "grade_level", "status", "organization", "deleted_at")
    list_filter = ("organization", "status", "grade_level")
    search_fields = ("last_name", "first_name")
    inlines = [StudentParentInline, GroupMembershipInline]
    # Дата рождения и документ шифруются на уровне поля: в списке их нет намеренно.
    fields = (
        "organization", "last_name", "first_name", "middle_name", "grade_level",
        "birth_date", "document_info", "attestation_partner", "status", "enrolled_on",
        "user", "note", "deleted_at",
    )


@admin.register(Parent)
class ParentAdmin(TenantAdmin):
    list_display = ("__str__", "phone", "email", "organization")
    search_fields = ("last_name", "phone", "email")
    list_filter = ("organization",)


@admin.register(Teacher)
class TeacherAdmin(TenantAdmin):
    list_display = ("__str__", "hourly_rate", "organization")
    list_filter = ("organization",)
    filter_horizontal = ("subjects",)


@admin.register(GradingScale)
class GradingScaleAdmin(TenantAdmin):
    list_display = (
        "name", "organization", "module_max_points", "pass_from",
        "base_from", "elevated_from", "advanced_from",
    )
    list_filter = ("organization",)


@admin.register(Lesson)
class LessonAdmin(TenantAdmin):
    list_display = ("starts_at", "subject", "group", "teacher", "is_graded", "topic")
    list_filter = ("organization", "is_graded", "subject", "group")
    date_hierarchy = "starts_at"


@admin.register(GradeItem)
class GradeItemAdmin(TenantAdmin):
    list_display = ("__str__", "kind", "module", "subject", "group", "max_points", "due_date")
    list_filter = ("organization", "kind", "module", "subject")


@admin.register(Grade)
class GradeAdmin(TenantAdmin):
    list_display = ("student", "grade_item", "points", "given_by", "graded_at", "deleted_at")
    list_filter = ("organization",)
    search_fields = ("student__last_name",)
    date_hierarchy = "graded_at"


@admin.register(ModuleResult)
class ModuleResultAdmin(TenantAdmin):
    list_display = ("student", "subject", "module", "total_points", "level", "is_passed")
    list_filter = ("organization", "level", "is_passed", "module")
    readonly_fields = ("total_points", "planned_points", "level", "is_passed", "gap_to_next_level")


@admin.register(Payment)
class PaymentAdmin(TenantAdmin):
    list_display = ("student", "title", "amount", "status", "period_start", "paid_on")
    list_filter = ("organization", "status")


@admin.register(Goal)
class GoalAdmin(TenantAdmin):
    list_display = ("title", "student", "kind", "visibility", "status")
    list_filter = ("organization", "kind", "visibility", "status")


@admin.register(MoodEntry)
class MoodEntryAdmin(TenantAdmin):
    list_display = ("student", "day", "value")
    list_filter = ("organization", "value")
    date_hierarchy = "day"
