"""Публичный сайт: лендинг, заявка, «спасибо», правовые страницы."""
from __future__ import annotations

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from apps.site_public.forms import LeadForm
from apps.site_public.models import FaqItem, LegalDocument, TeacherCard
from apps.site_public.services.leads import check_rate_limit, create_lead

# Пороги и тексты 100-балльной шкалы для интерактива на первом экране.
# Значения перенесены из утверждённого макета дословно.
SCALE_LEVELS = [
    {
        "max": 40, "name": "база", "focus": "разбор основ", "retake": "нужна",
        "hint": "0–40 — предмет держится на пересказе. Модуль закрывается повторной "
                "попыткой, а не оценкой в журнале.",
    },
    {
        "max": 70, "name": "уверенно", "focus": "типовые задачи", "retake": "не нужна",
        "hint": "41–70 — типовые задачи ОГЭ и ЕГЭ решаются самостоятельно. Наставник "
                "смещает время на слабые темы.",
    },
    {
        "max": 85, "name": "сильно", "focus": "вторая часть", "retake": "не нужна",
        "hint": "71–85 — вторая часть экзамена в работе. Появляется запас на профильные "
                "задания.",
    },
    {
        "max": 100, "name": "глубоко", "focus": "профиль и проект", "retake": "не нужна",
        "hint": "86–100 — уровень олимпиад и профиля. Часть часов уходит в проект "
                "и профориентацию.",
    },
]
INITIAL_SCORE = 64

SEGMENTS = [
    {
        "value": "self_study",
        "title": "Ушёл на самообразование",
        "text": "Есть свобода, но нет структуры и дат. Собираем режим и аттестацию.",
        "cta": "Обсудить самообразование",
    },
    {
        "value": "exams",
        "title": "Готовится к ОГЭ или ЕГЭ",
        "text": "Модули по 5 недель вместо разрозненных занятий у четырёх репетиторов.",
        "cta": "Разобрать подготовку к экзамену",
    },
    {
        "value": "career",
        "title": "Не выбрал направление",
        "text": "Профориентация как отдельная работа: интересы, проба, план на 11 класс.",
        "cta": "Записаться на профориентацию",
    },
]


def _landing_context(request, form=None) -> dict:
    organization = request.organization
    return {
        "form": form or LeadForm(),
        "scale_levels": SCALE_LEVELS,
        "initial_score": INITIAL_SCORE,
        "segments": SEGMENTS,
        "faq_items": FaqItem.objects.filter(is_published=True),
        "teacher_cards": TeacherCard.objects.filter(is_published=True),
        "organization": organization,
        "canonical_path": reverse("public:landing"),
    }


def landing(request):
    return render(request, "public/landing.html", _landing_context(request))


def career(request):
    """Профориентация как отдельный продукт с тем же единственным CTA."""
    context = _landing_context(request)
    context["canonical_path"] = reverse("public:career")
    return render(request, "public/career.html", context)


@require_http_methods(["POST"])
def lead_create(request):
    """
    Приём заявки.

    Отвечает и обычным POST, и HTMX: во втором случае возвращает
    перерисованную форму с ошибками либо просит браузер перейти на «спасибо».
    """
    limit = check_rate_limit(request)
    form = LeadForm(request.POST)

    if not limit.allowed:
        form.add_error(
            None,
            "Слишком много заявок с одного адреса. Позвоните нам — так будет быстрее.",
        )
    elif form.is_valid():
        create_lead(form=form, request=request, organization=request.organization)
        if request.headers.get("HX-Request"):
            response = HttpResponse(status=204)
            response["HX-Redirect"] = reverse("public:thanks")
            return response
        return redirect("public:thanks")

    if request.headers.get("HX-Request"):
        return render(request, "public/partials/lead_form.html", {"form": form}, status=422)
    context = _landing_context(request, form=form)
    return render(request, "public/landing.html", context, status=422)


def thanks(request):
    return render(request, "public/thanks.html", {"organization": request.organization})


def legal(request, kind: str):
    document = LegalDocument.objects.filter(kind=kind).first()
    return render(
        request,
        "public/legal.html",
        {
            "document": document,
            "kind": kind,
            "kind_label": dict(LegalDocument.Kind.choices).get(kind, ""),
            "policy_version": settings.LEGAL_DOC_VERSION,
        },
    )


def robots_txt(request):
    organization = request.organization
    host = organization.primary_domain if organization else request.get_host()
    lines = [
        "User-agent: *",
        "Disallow: /kabinet/",
        "Disallow: /admin/",
        "Disallow: /vhod/",
        "Allow: /",
        "",
        f"Sitemap: https://{host}/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")
