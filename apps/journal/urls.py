from django.urls import path

from apps.journal.views import common, exports, manage, parent, student, teacher

app_name = "cabinet"

urlpatterns = [
    path("", common.home, name="home"),

    # Педагог
    path("pedagog/", teacher.today, name="teacher_today"),
    path("pedagog/zanyatie/<uuid:lesson_id>/", teacher.lesson_journal, name="lesson_journal"),
    path("pedagog/zanyatie/<uuid:lesson_id>/ball/", teacher.grade_save, name="grade_save"),
    path("pedagog/zanyatie/<uuid:lesson_id>/ocenivanie/", teacher.lesson_toggle_graded, name="lesson_toggle_graded"),
    path("pedagog/zanyatie/<uuid:lesson_id>/tema/", teacher.lesson_topic_save, name="lesson_topic_save"),
    path(
        "pedagog/modul/<int:module_id>/<int:subject_id>/<int:group_id>/",
        teacher.module_plan, name="module_plan",
    ),
    path(
        "pedagog/modul/<int:module_id>/<int:subject_id>/<int:group_id>/deystvie/",
        teacher.module_plan_action, name="module_plan_action",
    ),

    # Родитель
    path("roditel/", parent.parent_home, name="parent_home"),
    path("roditel/rebenok/<uuid:student_id>/", parent.parent_child, name="parent_child"),

    # Ученик
    path("uchenik/", student.student_home, name="student_home"),
    path("uchenik/cel/", student.goal_create, name="goal_create"),
    path("uchenik/cel/<uuid:goal_id>/", student.goal_toggle, name="goal_toggle"),
    path("uchenik/sostoyanie/", student.mood_save, name="mood_save"),

    # Администратор и владелец
    path("panel/", manage.dashboard, name="dashboard"),
    path("zayavki/", manage.leads, name="leads"),
    path("zayavki/<uuid:lead_id>/status/", manage.lead_status, name="lead_status"),
    path("ucheniki/", manage.students, name="students"),
    path("ucheniki/<uuid:student_id>/vosstanovit/", manage.student_restore, name="student_restore"),
    path("fot/", manage.payroll, name="payroll"),
    path("oplaty/<uuid:payment_id>/otmetit/", manage.payment_mark_paid, name="payment_mark_paid"),

    # Выгрузки
    path("eksport/modul/<int:module_id>/", exports.module_performance, name="export_module"),
    path("eksport/ucheniki/", exports.students, name="export_students"),
    path("eksport/fot/", exports.payroll, name="export_payroll"),
    path("eksport/celi/<uuid:student_id>/", exports.student_goals, name="export_goals"),
]
