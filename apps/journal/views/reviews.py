"""
Отзывы родителей о педагогах.

Оставить отзыв можно только из кабинета и только про того, кто учит
твоего ребёнка. Публикует администратор: публичная страница — зона
ответственности организации, и то, что там появляется, должен кто-то
прочитать. Это не цензура, а ответственность за свой сайт.
"""
from __future__ import annotations

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.accounts.models import Role
from apps.accounts.permissions import role_required
from apps.core.audit import AuditAction, log_audit
from apps.journal.access import accessible_students
from apps.journal.models import Teacher
from apps.site_public.models import TeacherReview

MANAGER_ROLES = ("admin", "owner", "platform_admin")


class ReviewForm(forms.ModelForm):
    class Meta:
        model = TeacherReview
        fields = ["rating", "text"]
        widgets = {
            "rating": forms.RadioSelect(
                choices=[(n, "★" * n) for n in range(5, 0, -1)]
            ),
            "text": forms.Textarea(attrs={"rows": 5, "placeholder":
                                          "Что получается у педагога, что помогло ребёнку"}),
        }
        labels = {"rating": "Оценка", "text": "Отзыв"}


def _teaches_me_or_my_child(user, organization, teacher: Teacher) -> bool:
    """
    Отзыв — только о том, кто реально ведёт занятия.

    Для родителя это педагог его ребёнка, для ученика — его собственный.
    accessible_students отвечает на оба вопроса одинаково, поэтому
    отдельной ветки для роли здесь нет.
    """
    students = accessible_students(user, organization)
    return teacher.lessons.filter(group__memberships__student__in=students).exists()


@login_required
@role_required("parent", "student")
@require_http_methods(["GET", "POST"])
def review_create(request, teacher_id):
    organization = request.organization
    teacher = get_object_or_404(Teacher.objects.select_related("user"), pk=teacher_id)

    if not _teaches_me_or_my_child(request.user, organization, teacher):
        raise PermissionDenied("Отзыв можно оставить только о том, кто ведёт занятия.")

    existing = TeacherReview.objects.filter(teacher=teacher, author=request.user).first()
    form = ReviewForm(request.POST or None, instance=existing)

    if request.method == "POST" and form.is_valid():
        review = form.save(commit=False)
        review.organization = organization
        review.teacher = teacher
        review.author = request.user
        review.author_label = _signature(request.user, organization)
        # Правка возвращает отзыв на проверку: опубликованный текст
        # не должен меняться на сайте без ведома администратора.
        review.status = TeacherReview.Status.PENDING
        review.moderated_by = None
        review.moderated_at = None
        review.save()

        log_audit(action=AuditAction.PERMISSION_CHANGED, request=request, obj=review,
                  change="review_submitted")
        messages.success(
            request,
            "Спасибо. Отзыв появится на сайте после проверки — обычно в течение дня.",
        )
        return redirect("cabinet:parent_teachers")

    return render(
        request,
        "cabinet/parent/review_form.html",
        {"form": form, "teacher": teacher, "existing": existing},
    )


def _signature(user, organization) -> str:
    """
    Как отзыв подписан на сайте: «Анна М., родитель ученика 9 класса».

    Фамилию целиком не публикуем: это отзыв о педагоге, а не документ,
    и полное имя здесь ничего не добавляет, зато делает семью узнаваемой.
    """
    initial = f"{user.last_name[:1]}." if user.last_name else ""
    name = f"{user.first_name} {initial}".strip() or "Аноним"

    students = list(accessible_students(user, organization)[:1])
    if not students:
        return name
    grade = students[0].grade_level
    if user.has_role(organization, Role.STUDENT):
        return f"{name}, ученик {grade} класса"
    return f"{name}, родитель ученика {grade} класса"


@login_required
@role_required(*MANAGER_ROLES)
def review_queue(request):
    """Что ждёт проверки и что уже на сайте."""
    reviews = (
        TeacherReview.objects.select_related("teacher__user", "author")
        .order_by("status", "-created_at")
    )
    return render(
        request,
        "cabinet/manage/reviews.html",
        {
            "pending": [r for r in reviews if r.status == TeacherReview.Status.PENDING],
            "decided": [r for r in reviews if r.status != TeacherReview.Status.PENDING],
        },
    )


@login_required
@role_required(*MANAGER_ROLES)
@require_http_methods(["POST"])
def review_decide(request, review_id):
    review = get_object_or_404(TeacherReview.objects.all(), pk=review_id)
    decision = request.POST.get("decision")
    if decision not in (TeacherReview.Status.PUBLISHED, TeacherReview.Status.REJECTED):
        raise PermissionDenied("Неизвестное решение.")

    review.status = decision
    review.moderated_by = request.user
    review.moderated_at = timezone.now()
    review.save(update_fields=["status", "moderated_by", "moderated_at", "updated_at"])

    log_audit(action=AuditAction.PERMISSION_CHANGED, request=request, obj=review,
              change=f"review_{decision}")
    messages.success(
        request,
        "Отзыв опубликован." if decision == TeacherReview.Status.PUBLISHED else "Отзыв отклонён.",
    )
    return redirect("cabinet:review_queue")
