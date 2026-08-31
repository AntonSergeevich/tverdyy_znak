"""
Кабинет педагога.

Оптимизирован под одну задачу: быстро выставить баллы после занятия (ТЗ 5.3).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Prefetch
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.accounts.permissions import role_required
from apps.core.audit import AuditAction, log_audit
from apps.journal.access import (
    accessible_groups,
    assert_can_grade,
    get_lesson_or_403,
    is_manager,
    teacher_profile,
)
from apps.journal.models import (
    Grade,
    GradeItem,
    GradeItemKind,
    Group,
    Lesson,
    Module,
    Student,
    Subject,
)
from apps.journal.services import ktp as ktp_service
from apps.journal.services.grading import (
    create_default_structure,
    points_budget,
    set_grade,
    validate_grade_item,
)
from apps.journal.services.suggestions import (
    previous_homework,
    previous_lesson,
    recent_topics,
)


@login_required
@role_required("teacher", "admin", "owner", "platform_admin")
def today(request):
    """Список своих занятий на сегодня — в один тап открывается журнал."""
    organization = request.organization
    day = timezone.localdate()
    profile = teacher_profile(request.user, organization)

    lessons = (
        Lesson.objects.filter(starts_at__date=day)
        .select_related("subject", "group", "module", "teacher", "teacher__user")
        .prefetch_related("grade_item")
        .order_by("starts_at")
    )
    if profile is not None:
        lessons = lessons.filter(teacher=profile)

    upcoming = (
        Lesson.objects.filter(starts_at__date__gt=day)
        .select_related("subject", "group", "module")
        .order_by("starts_at")
    )
    if profile is not None:
        upcoming = upcoming.filter(teacher=profile)
    upcoming = upcoming[:8]

    return render(
        request,
        "cabinet/teacher/today.html",
        {
            "day": day,
            "lessons": list(lessons),
            "upcoming": list(upcoming),
            "teacher": profile,
            "groups": accessible_groups(request.user, organization).select_related("academic_year"),
        },
    )


def _lesson_rows(lesson: Lesson):
    """Ученики группы и их баллы за занятие — один запрос вместо N."""
    grade_item = getattr(lesson, "grade_item", None)
    grades = {}
    if grade_item is not None:
        grades = {
            grade.student_id: grade
            for grade in Grade.objects.filter(grade_item=grade_item).select_related("student")
        }
    students = (
        Student.objects.filter(group_memberships__group=lesson.group)
        .order_by("last_name", "first_name")
        .distinct()
    )
    return [{"student": student, "grade": grades.get(student.id)} for student in students]


@login_required
@role_required("teacher", "admin", "owner", "platform_admin")
def lesson_journal(request, lesson_id):
    organization = request.organization
    lesson = get_lesson_or_403(request.user, organization, lesson_id)
    assert_can_grade(request.user, organization, lesson)

    grade_item = getattr(lesson, "grade_item", None)
    budget = points_budget(lesson.module, lesson.subject, lesson.group)
    plan_entry = ktp_service.entry_for(lesson)

    log_audit(action=AuditAction.VIEW_STUDENT, request=request, obj=lesson, scope="lesson_journal")

    return render(
        request,
        "cabinet/teacher/lesson_journal.html",
        {
            "lesson": lesson,
            "grade_item": grade_item,
            "homework": getattr(lesson, "homework", None),
            "rows": _lesson_rows(lesson),
            "budget": budget,
            # Кому есть куда идти за составом группы: педагог его не правит,
            # и кнопка, ведущая в отказ, хуже её отсутствия.
            "can_manage": is_manager(request.user, organization),
            # Подсказки «как в прошлый раз»: половина того, что педагог
            # печатает, уже была напечатана — тема идёт по учебнику подряд,
            # задание того же вида. Предлагаем, но не подставляем молча.
            "recent_topics": recent_topics(
                subject=lesson.subject, group=lesson.group, exclude_lesson=lesson
            ),
            "previous_lesson": previous_lesson(lesson),
            "previous_homework": previous_homework(lesson),
            # Тема из КТП: если занятию сопоставлена строка плана, её текст
            # подставляется в поле. Не как подсказка сбоку, а прямо в поле —
            # план для того и составляли, чтобы не сочинять тему заново.
            "plan_entry": plan_entry,
        },
    )


@login_required
def homework_photo(request, lesson_id):
    """
    Фото листа с задачами.

    Роль здесь не проверяется списком: снимок нужен прежде всего ученику и
    родителю — это их задание. Кому занятие доступно, решает
    `get_lesson_or_403` по тем же правилам, что и везде, а без роли
    выборка занятий пуста, и никому ничего не достанется.

    Файл лежит вне MEDIA_ROOT и отдаётся отсюда, а не веб-сервером: на
    снимке страницы бывает и фамилия, и почерк.
    """
    organization = request.organization
    lesson = get_lesson_or_403(request.user, organization, lesson_id)
    homework = getattr(lesson, "homework", None)
    if homework is None or not homework.photo:
        raise Http404("Фотографии к этому заданию нет.")
    return FileResponse(homework.photo.open("rb"))


@login_required
@role_required("teacher", "admin", "owner", "platform_admin")
@require_http_methods(["POST"])
def lesson_toggle_graded(request, lesson_id):
    """
    Отметить занятие как оцениваемое и создать под него элемент оценивания.

    Баллы за поведение не начисляются — тип элемента всегда «занятие».
    """
    organization = request.organization
    lesson = get_lesson_or_403(request.user, organization, lesson_id)
    assert_can_grade(request.user, organization, lesson)

    make_graded = request.POST.get("is_graded") == "1"
    error = ""
    if make_graded and not hasattr(lesson, "grade_item"):
        item = GradeItem(
            organization=organization,
            module=lesson.module,
            subject=lesson.subject,
            group=lesson.group,
            lesson=lesson,
            kind=GradeItemKind.LESSON,
            title=lesson.topic or "Занятие с оцениванием",
            max_points=organization.lesson_max_points,
            due_date=lesson.local_date,
        )
        lesson.is_graded = True
        try:
            validate_grade_item(item)
            item.save()
            lesson.save(update_fields=["is_graded", "updated_at"])
        except ValidationError as exc:
            lesson.is_graded = False
            error = "; ".join(m for msgs in exc.message_dict.values() for m in msgs)
    elif not make_graded:
        item = getattr(lesson, "grade_item", None)
        if item is not None and Grade.objects.filter(grade_item=item).exists():
            error = "Сначала удалите выставленные баллы за это занятие."
        else:
            if item is not None:
                item.delete()
            lesson.is_graded = False
            lesson.save(update_fields=["is_graded", "updated_at"])

    lesson.refresh_from_db()
    # Вместе с шапкой возвращаем и список учеников: включили оценивание —
    # круги для баллов должны появиться сразу, а не после перезагрузки.
    # Список уезжает отдельным куском (hx-swap-oob), потому что одним
    # запросом меняются два места на экране, а между ними лежат тема и
    # домашнее задание — их трогать нельзя, там может быть недописанное.
    return render(
        request,
        "cabinet/teacher/partials/lesson_toggled.html",
        {
            "lesson": lesson,
            "grade_item": getattr(lesson, "grade_item", None),
            "budget": points_budget(lesson.module, lesson.subject, lesson.group),
            "rows": _lesson_rows(lesson),
            "can_manage": is_manager(request.user, organization),
            "error": error,
        },
    )


@login_required
@role_required("teacher", "admin", "owner", "platform_admin")
@require_http_methods(["POST"])
def grade_save(request, lesson_id):
    """
    Автосохранение балла из журнала занятия (HTMX).

    Возвращает строку ученика с индикатором сохранения. Ошибку показываем
    рядом с полем, а не общим алертом: педагог должен видеть, что именно не так.
    """
    organization = request.organization
    lesson = get_lesson_or_403(request.user, organization, lesson_id)
    assert_can_grade(request.user, organization, lesson)

    grade_item = getattr(lesson, "grade_item", None)
    if grade_item is None:
        raise PermissionDenied("Занятие без оценивания: сначала отметьте его как оцениваемое.")

    student = get_object_or_404(
        Student.objects.filter(group_memberships__group=lesson.group).distinct(),
        pk=request.POST.get("student"),
    )

    raw = (request.POST.get("points") or "").strip().replace(",", ".")
    comment = (request.POST.get("comment") or "").strip()
    error = ""
    grade = None
    try:
        points = Decimal(raw) if raw else None
    except InvalidOperation:
        points, error = None, "Балл должен быть числом."

    if not error:
        try:
            grade = set_grade(
                student=student, grade_item=grade_item, points=points,
                actor=request.user, comment=comment, request=request,
            )
        except (ValidationError, PermissionDenied) as exc:
            error = _first_message(exc)
            grade = Grade.objects.filter(grade_item=grade_item, student=student).first()

    return render(
        request,
        "cabinet/teacher/partials/grade_row.html",
        {
            "lesson": lesson,
            "grade_item": grade_item,
            "row": {"student": student, "grade": grade},
            "error": error,
            "saved": not error,
        },
        status=422 if error else 200,
    )


def _first_message(exc) -> str:
    if isinstance(exc, ValidationError):
        if hasattr(exc, "message_dict"):
            return next(
                (m for msgs in exc.message_dict.values() for m in msgs), "Не удалось сохранить."
            )
        return "; ".join(exc.messages)
    return str(exc)


@login_required
@role_required("teacher", "admin", "owner", "platform_admin")
def module_plan(request, module_id, subject_id, group_id):
    """
    Планирование модуля: какие занятия с оцениванием и на сколько баллов.

    Счётчик остатка от 100 виден постоянно, превышение блокируется сервисом.
    """
    organization = request.organization
    module = get_object_or_404(Module.objects.select_related("academic_year"), pk=module_id)
    subject = get_object_or_404(Subject, pk=subject_id)
    group = get_object_or_404(
        accessible_groups(request.user, organization), pk=group_id
    )

    items = (
        GradeItem.objects.filter(module=module, subject=subject, group=group)
        .select_related("lesson")
        .order_by("position", "due_date")
    )
    lessons = list(
        Lesson.objects.filter(module=module, subject=subject, group=group)
        .select_related("teacher", "teacher__user")
        .prefetch_related("grade_item")
        .order_by("starts_at")
    )
    # В планировании видны все занятия предмета, в том числе чужие: иначе
    # не понять, где в модуле дыра. Но править чужую тему нельзя, и поле
    # для неё показывать незачем — оно молча не сохранится.
    profile = teacher_profile(request.user, organization)
    manager = is_manager(request.user, organization)
    for lesson in lessons:
        lesson.can_edit = manager or (profile is not None and lesson.teacher_id == profile.id)

    return render(
        request,
        "cabinet/teacher/module_plan.html",
        {
            "module": module,
            "subject": subject,
            "group": group,
            "items": list(items),
            "lessons": lessons,
            "budget": points_budget(module, subject, group),
            "kinds": GradeItemKind.choices,
            "recent_topics": recent_topics(subject=subject, group=group),
        },
    )


@login_required
@role_required("teacher", "admin", "owner", "platform_admin")
@require_http_methods(["POST"])
def module_plan_action(request, module_id, subject_id, group_id):
    organization = request.organization
    module = get_object_or_404(Module, pk=module_id)
    subject = get_object_or_404(Subject, pk=subject_id)
    group = get_object_or_404(accessible_groups(request.user, organization), pk=group_id)
    action = request.POST.get("action")
    error = ""

    try:
        if action == "default_structure":
            create_default_structure(module, subject, group, actor=request.user)
        elif action == "add_item":
            item = GradeItem(
                organization=organization, module=module, subject=subject, group=group,
                kind=request.POST.get("kind") or GradeItemKind.QUIZ,
                title=(request.POST.get("title") or "").strip(),
                max_points=Decimal((request.POST.get("max_points") or "0").replace(",", ".")),
                due_date=request.POST.get("due_date") or None,
            )
            item.full_clean(exclude=["lesson"])
            item.save()
        elif action == "delete_item":
            item = get_object_or_404(
                GradeItem.objects.filter(module=module, subject=subject, group=group),
                pk=request.POST.get("item"),
            )
            if Grade.objects.filter(grade_item=item).exists():
                error = "По этой работе уже есть баллы. Сначала удалите их."
            else:
                item.delete()
    except (ValidationError, InvalidOperation) as exc:
        error = _first_message(exc) if isinstance(exc, ValidationError) else "Введите число баллов."

    items = (
        GradeItem.objects.filter(module=module, subject=subject, group=group)
        .select_related("lesson")
        .order_by("position", "due_date")
    )
    return render(
        request,
        "cabinet/teacher/partials/plan_items.html",
        {
            "module": module, "subject": subject, "group": group,
            "items": list(items),
            "budget": points_budget(module, subject, group),
            "kinds": GradeItemKind.choices,
            "error": error,
        },
    )


@login_required
@role_required("teacher", "admin", "owner", "platform_admin")
@require_http_methods(["POST"])
def lesson_topic_save(request, lesson_id):
    """
    Тема занятия.

    Правится и в планировании модуля, и в самом журнале занятия — вид
    ответа зависит от того, откуда пришли. Сохраняется на лету: тему
    дописывают между делом, и кнопка «сохранить» здесь только повод
    забыть на неё нажать.
    """
    organization = request.organization
    lesson = get_lesson_or_403(request.user, organization, lesson_id)
    assert_can_grade(request.user, organization, lesson)
    lesson.topic = (request.POST.get("topic") or "").strip()[:250]
    lesson.save(update_fields=["topic", "updated_at"])
    # Правка уходит и в КТП: держать в плане одно, а в журнале другое
    # значит завести два разных плана.
    in_plan = ktp_service.sync_topic_from_lesson(lesson)

    if request.POST.get("view") == "journal":
        # Отвечаем коротко: страницу трогать не надо, браузеру достаточно
        # знать, что сохранилось. Подменять поле во время набора нельзя —
        # теряется курсор, а на телефоне закрывается клавиатура.
        return JsonResponse({"saved": True, "in_plan": in_plan})
    return render(
        request,
        "cabinet/teacher/partials/topic_cell.html",
        {"lesson": lesson, "saved": True, "in_plan": in_plan},
    )


@login_required
@role_required("teacher", "admin", "owner", "platform_admin")
@require_http_methods(["POST"])
def lesson_homework_save(request, lesson_id):
    """
    Домашнее задание к занятию.

    Пустой текст означает «задания нет»: убрать случайно заданное должно
    быть так же просто, как задать.
    """
    from apps.journal.services import homework as homework_service

    organization = request.organization
    lesson = get_lesson_or_403(request.user, organization, lesson_id)
    assert_can_grade(request.user, organization, lesson)

    text = request.POST.get("text") or ""
    due_date = homework_service.parse_date(request.POST.get("due_date"))
    max_points = homework_service.parse_points(request.POST.get("max_points"))
    photo = request.FILES.get("photo")
    drop_photo = request.POST.get("drop_photo") == "1"

    error = ""
    try:
        homework = homework_service.save_homework(
            lesson=lesson, text=text, due_date=due_date,
            max_points=max_points, actor=request.user,
            photo=photo, drop_photo=drop_photo,
        )
    except ValidationError as exc:
        # Сотня на модуль не резиновая. Показываем ровно то, что мешает,
        # и оставляем введённое на экране — переписывать заново незачем.
        homework = getattr(lesson, "homework", None)
        error = "; ".join(m for messages in exc.message_dict.values() for m in messages)

    log_audit(action=AuditAction.PERMISSION_CHANGED, request=request, obj=lesson,
              change="homework_saved")
    return render(
        request,
        "cabinet/teacher/partials/lesson_homework_form.html",
        {
            "lesson": lesson,
            "homework": homework,
            "saved": not error,
            "error": error,
            "draft": {"text": text, "due_date": request.POST.get("due_date"),
                      "max_points": request.POST.get("max_points")},
            "previous_homework": previous_homework(lesson),
        },
    )


@login_required
@role_required("teacher", "admin", "owner", "platform_admin")
@require_http_methods(["POST"])
def grade_bulk(request, lesson_id):
    """
    Поставить один балл всем сразу.

    После занятия у большинства класса балл одинаковый, и вводить его
    по одному — двадцать кликов ради одного числа. Ставим всем, а
    исключения педагог правит по одному, как и раньше.

    Кому балл уже стоит, по умолчанию не трогаем: перезаписать чужую
    работу молча — худшее, что может сделать «удобная» кнопка.
    """
    organization = request.organization
    lesson = get_lesson_or_403(request.user, organization, lesson_id)
    assert_can_grade(request.user, organization, lesson)

    grade_item = getattr(lesson, "grade_item", None)
    if grade_item is None:
        raise PermissionDenied("Занятие без оценивания: сначала отметьте его как оцениваемое.")

    raw = (request.POST.get("points") or "").strip().replace(",", ".")
    overwrite = request.POST.get("overwrite") == "1"
    try:
        points = Decimal(raw)
    except InvalidOperation:
        points = None

    error = ""
    changed = 0
    if points is None:
        error = "Балл должен быть числом."
    else:
        for row in _lesson_rows(lesson):
            if row["grade"] is not None and not overwrite:
                continue
            try:
                set_grade(
                    student=row["student"], grade_item=grade_item, points=points,
                    actor=request.user, comment="", request=request,
                )
                changed += 1
            except (ValidationError, PermissionDenied) as exc:
                error = getattr(exc, "message", None) or str(exc)
                break

    return render(
        request,
        "cabinet/teacher/partials/journal_body.html",
        {
            "lesson": lesson,
            "grade_item": grade_item,
            "rows": _lesson_rows(lesson),
            "budget": points_budget(lesson.module, lesson.subject, lesson.group),
            "can_manage": is_manager(request.user, organization),
            "bulk_error": error,
            "bulk_changed": changed,
        },
    )


@login_required
@role_required("teacher", "admin", "owner", "platform_admin")
def my_hours(request):
    """
    Свои часы и оплата за период.

    Педагог в центре получает за час, но видел эти цифры только владелец
    в разделе ФОТ. Свои — человек имеет право видеть сам, не спрашивая:
    сойтись они должны заранее, а не в день выплаты.
    """
    from apps.journal.views.manage import _period

    organization = request.organization
    profile = teacher_profile(request.user, organization)
    start, end = _period(request)

    if profile is None:
        return render(
            request,
            "cabinet/teacher/hours.html",
            {"start": start, "end": end, "teacher": None},
        )

    lessons = list(
        Lesson.objects.filter(
            teacher=profile, starts_at__date__gte=start, starts_at__date__lte=end
        )
        .select_related("subject", "group")
        .order_by("starts_at")
    )
    minutes = sum(lesson.duration_minutes for lesson in lessons)
    hours = (Decimal(minutes) / Decimal(60)).quantize(Decimal("0.01"))

    return render(
        request,
        "cabinet/teacher/hours.html",
        {
            "teacher": profile,
            "start": start,
            "end": end,
            "lessons": lessons,
            "hours": hours,
            "rate": profile.hourly_rate,
            "amount": (hours * profile.hourly_rate).quantize(Decimal("0.01")),
            "reviews": profile.published_reviews,
        },
    )
