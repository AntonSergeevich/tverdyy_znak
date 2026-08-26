"""
Юридические ограничения текстов (ТЗ 1.2).

Эти правила нарушаются незаметно — при правке текстов в шаблонах.
Поэтому они проверяются тестом, а не глазами на ревью.
"""
from __future__ import annotations

import re

import pytest
from django.urls import reverse

PUBLIC_PAGES = [
    "public:landing",
    "public:career",
    "public:thanks",
    "public:legal_privacy",
]

# «Школа» допустима только про аккредитованную школу-партнёра.
SCHOOL_ALLOWED_CONTEXT = ("аккредитован", "партнёр", "партнер")

# Запрет из ТЗ 1.2 — не называть школой СЕБЯ. Биография педагога, где
# сказано «опыт работы в школе», этого запрета не нарушает: речь о прошлом
# месте работы человека, а не о центре. Поэтому строгая проверка идёт по
# странице без блока педагогов, а по всей странице — проверка самоназвания.
SELF_SCHOOL_PATTERNS = [
    r"наш[аейуио]*\s+школ",
    r"наш[ей]*\s+школ",
    r"мы\s*[—-]?\s*школа",
    r"школа\s+«?твёрдый\s+знак",
    r"школ[аыуе]\s+для\s+подростк",
    r"частн[аяойую]+\s+школа\b(?![^.]*аккредит)",
]

FORBIDDEN_PROMISES = [
    "гарантируем", "гарантия результата", "сдадим на", "поднимем балл",
    "гарантируем поступление", "обязательно поступит",
]

FORBIDDEN_TONE = [
    "снимем с вас все проблемы", "доверьте нам ребёнка", "доверьте нам ребенка",
]


def _text(client_a, url_name: str) -> str:
    response = client_a.get(reverse(url_name))
    assert response.status_code == 200
    return response.content.decode()


def _without_teacher_bios(body: str) -> str:
    """Страница без блока педагогов: там допустимы биографии с прошлым опытом."""
    start = body.find('id="pedagogi"')
    if start == -1:
        return body
    end = body.find("</section>", start)
    return body[:start] + body[end:]


@pytest.mark.parametrize("url_name", PUBLIC_PAGES)
def test_word_school_only_about_accredited_partner(client_a, url_name):
    body = _without_teacher_bios(_text(client_a, url_name))
    sentences = re.split(r"(?<=[.!?])\s+|\n", body)
    offending = [
        sentence.strip()
        for sentence in sentences
        if re.search(r"школ", sentence, re.IGNORECASE)
        and not any(marker in sentence.lower() for marker in SCHOOL_ALLOWED_CONTEXT)
    ]
    assert not offending, f"Слово «школа» вне контекста партнёра: {offending[:3]}"


@pytest.mark.parametrize("url_name", PUBLIC_PAGES)
def test_center_never_calls_itself_a_school(client_a, url_name):
    """Проверка действует и на биографии педагогов: себя школой не называем."""
    body = _text(client_a, url_name).lower()
    found = [pattern for pattern in SELF_SCHOOL_PATTERNS if re.search(pattern, body)]
    assert not found, f"Центр назван школой: {found}"


@pytest.mark.parametrize("url_name", PUBLIC_PAGES)
def test_no_result_guarantees(client_a, url_name):
    body = _text(client_a, url_name).lower()
    found = [phrase for phrase in FORBIDDEN_PROMISES if phrase in body]
    assert not found, f"Обещание результата в текстах: {found}"


@pytest.mark.parametrize("url_name", PUBLIC_PAGES)
def test_no_service_mass_market_tone(client_a, url_name):
    body = _text(client_a, url_name).lower()
    found = [phrase for phrase in FORBIDDEN_TONE if phrase in body]
    assert not found, f"Тон сервисного масс-маркета: {found}"


@pytest.mark.parametrize("url_name", PUBLIC_PAGES)
def test_no_license_or_tax_deduction_claims(client_a, url_name):
    body = _text(client_a, url_name).lower()
    for word in ("маткапитал", "материнский капитал", "налоговый вычет"):
        assert word not in body, f"Упоминание «{word}» запрещено"


def test_price_visible_on_first_screen(client_a, tenant_a):
    """Цена не скрывается: она видна на первом экране."""
    body = _text(client_a, "public:landing")
    hero = body.split('id="dlya-kogo"')[0]
    assert "70 000" in hero.replace(" ", " ")


def test_title_does_not_call_center_a_school(client_a):
    body = _text(client_a, "public:landing")
    title = re.search(r"<title>(.*?)</title>", body, re.S).group(1)
    assert "школ" not in title.lower()
    assert "центр" in title.lower()


def test_requisites_present_in_footer(client_a):
    body = _text(client_a, "public:landing")
    assert "ОГРНИП" in body
    assert "ИНН" in body


def test_single_target_action(client_a):
    """Все призывы ведут в одну форму заявки."""
    body = _text(client_a, "public:landing")
    assert body.count('id="zayavka"') == 1
    assert 'href="#zayavka"' in body


def test_teacher_cards_are_published_with_bio(client_a, tenant_a):
    """Карточки педагогов выводятся с должностью и описанием."""
    from apps.core.tenancy import organization_context
    from apps.site_public.models import TeacherCard

    with organization_context(tenant_a.organization):
        TeacherCard.objects.create(
            organization=tenant_a.organization,
            full_name="Манасян Сергей Керопович",
            subject_line="Математика, физика, информатика",
            experience="Стаж более 30 лет",
            bio="Опыт работы в школе и вузе. Учит думать, а не зубрить.",
            position=10,
        )
    body = _text(client_a, "public:landing")
    assert "Манасян Сергей Керопович" in body
    assert "Математика, физика, информатика" in body
    assert "Учит думать" in body


def test_bank_details_never_appear_on_public_pages(client_a, tenant_a):
    """
    Расчётный счёт живёт только в кабинете родителя.

    В подвале сайта — наименование, ИНН, ОГРНИП и адрес, не больше.
    """
    organization = tenant_a.organization
    organization.bank_account = "40802810820001048577"
    organization.bank_corr_account = "30101810745374525104"
    organization.bank_bik = "044525104"
    organization.save()

    for url_name in PUBLIC_PAGES:
        body = _text(client_a, url_name)
        assert organization.bank_account not in body
        assert organization.bank_corr_account not in body
        assert organization.bank_bik not in body


def test_no_multiline_hash_comments_in_templates():
    """
    Комментарий {# … #} в Django однострочный.

    Записанный в несколько строк, он не вырезается, а выводится на страницу
    как обычный текст — так служебная пометка уже попадала на прод.
    Для многострочных комментариев есть {% comment %}.
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parent.parent / "templates"
    offenders = []
    for path in sorted(root.rglob("*.html")):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"\{#.*?#\}", text, re.S):
            if "\n" in match.group(0):
                line = text[: match.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(root)}:{line}")
    assert not offenders, (
        "Многострочные {# #} попадут на страницу как текст. "
        f"Заменить на {{% comment %}}: {offenders}"
    )


def test_link_preview_meta_is_usable(client_a):
    """
    Превью ссылки в мессенджерах.

    Две ошибки, из-за которых картинки не было вовсе: SVG вместо PNG
    (его не показывает ни Telegram, ни ВКонтакте) и относительный путь,
    который они не разворачивают.
    """
    import re

    body = _text(client_a, "public:landing")
    tags = dict(
        re.findall(r'<meta (?:property|name)="((?:og|twitter):[^"]+)" content="([^"]*)"', body)
    )

    image = tags.get("og:image", "")
    assert image.startswith("http"), "og:image должен быть абсолютным адресом"
    assert ".png" in image, "og:image должен быть растровым: SVG в превью не показывают"
    assert tags.get("og:image:width") == "1200"
    assert tags.get("og:image:height") == "630"
    assert tags.get("twitter:image", "").startswith("http")

    assert "Семейный класс" in tags.get("og:title", "")
    assert tags.get("og:url", "").startswith("http")
    assert tags.get("twitter:card") == "summary_large_image"


def test_og_cover_file_exists_and_is_png():
    """Файл обложки должен лежать в статике: собирается scripts/build_og_image.py."""
    import pathlib

    cover = pathlib.Path(__file__).resolve().parent.parent / "static" / "img" / "og-cover.png"
    assert cover.exists(), "Нет static/img/og-cover.png — соберите: python scripts/build_og_image.py"
    assert cover.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_shell_scripts_have_no_carriage_returns():
    """
    Скрипты для сервера хранятся в LF.

    Для bash \\r — часть слова: он падает на
    «cd: /srv/tverdyy-znak\\r: No such file or directory», и понять это
    по выводу почти нельзя. Так уже ломался деплой дважды.
    """
    from pathlib import Path

    for script in sorted(Path("deploy/scripts").glob("*.sh")):
        assert b"\r" not in script.read_bytes(), f"{script}: перевод строки CRLF"


def test_deploy_script_checks_that_push_succeeded():
    """
    Отклонённый git push не должен приводить к выкату старого коммита.

    Ровно это и произошло: скрипт напечатал «Запушено», выкатил
    предыдущую версию, и полчаса ушло на поиски того, почему изменение
    «не доехало».
    """
    from pathlib import Path

    script = Path("deploy/deploy.ps1").read_text(encoding="utf-8-sig")
    push = script.index("git push origin $Branch")
    deploy = script.index("ssh $Server \"command -v tz-deploy")

    assert push < deploy
    assert "$LASTEXITCODE" in script[push:deploy]


def _make_cards(tenant, count, featured_name="Основатель Центра"):
    from apps.site_public.models import TeacherCard

    TeacherCard.all_objects.create(
        organization=tenant.organization, full_name=featured_name,
        subject_line="Основатель", bio="Про основателя.", is_featured=True, position=10,
    )
    for index in range(count):
        TeacherCard.all_objects.create(
            organization=tenant.organization, full_name=f"Педагог {index}",
            subject_line=f"Предмет {index}", bio=f"Про педагога {index}.",
            position=100 + index,
        )


def test_landing_shows_founder_large_and_the_rest_compactly(client, tenant_a):
    """
    Главная не должна превращаться в стену одинаковых карточек.

    Основатель — крупным блоком с полным текстом, остальные — лентой.
    При двадцати педагогах одинаковая сетка перестаёт читаться.
    """
    _make_cards(tenant_a, 3)
    client.defaults["HTTP_HOST"] = tenant_a.host
    body = client.get(reverse("public:landing")).content.decode()

    assert "teacher-lead" in body
    assert "Основатель Центра" in body
    assert "teacher-chip" in body
    assert "Педагог 0" in body


def test_landing_links_to_the_full_list_only_when_it_does_not_fit(client, tenant_a):
    from apps.site_public.views import TEACHERS_ON_LANDING

    _make_cards(tenant_a, TEACHERS_ON_LANDING)
    client.defaults["HTTP_HOST"] = tenant_a.host
    fits = client.get(reverse("public:landing")).content.decode()
    assert "Весь состав" not in fits

    from apps.site_public.models import TeacherCard

    TeacherCard.all_objects.create(
        organization=tenant_a.organization, full_name="Лишний педагог",
        subject_line="Предмет", position=900,
    )
    overflow = client.get(reverse("public:landing")).content.decode()
    assert "Весь состав" in overflow


def test_teacher_chip_is_a_real_link_so_it_works_without_javascript(client, tenant_a):
    """
    Мини-карточка — ссылка на страницу состава с якорем.

    Диалог открывает скрипт, но без него человек должен попасть туда же
    и прочитать то же самое — и поисковик тоже.
    """
    _make_cards(tenant_a, 2)
    client.defaults["HTTP_HOST"] = tenant_a.host
    body = client.get(reverse("public:landing")).content.decode()

    assert f'href="{reverse("public:teachers")}#card-' in body


def test_teachers_page_shows_everyone_with_anchors(client, tenant_a):
    from apps.site_public.models import TeacherCard

    _make_cards(tenant_a, 12)
    client.defaults["HTTP_HOST"] = tenant_a.host
    body = client.get(reverse("public:teachers")).content.decode()

    for card in TeacherCard.all_objects.filter(organization=tenant_a.organization):
        assert card.full_name in body
        assert f'id="card-{card.pk}"' in body


def test_teachers_page_does_not_leak_another_organization(client, tenant_a, tenant_b):
    _make_cards(tenant_a, 2)
    _make_cards(tenant_b, 2, featured_name="Чужой основатель")

    client.defaults["HTTP_HOST"] = tenant_a.host
    body = client.get(reverse("public:teachers")).content.decode()

    assert "Чужой основатель" not in body


def test_programme_table_lists_only_academic_subjects(client, tenant_a):
    """
    Обед и утренний круг стоят в расписании, но не в программе ФГОС.

    Они попадали в публичную таблицу строками с нулём часов — выглядело
    так, будто центр отчитывается об обеде как об учебной дисциплине.
    """
    from apps.journal.models import Subject, SubjectKind

    Subject.all_objects.create(
        organization=tenant_a.organization, academic_year=tenant_a.year,
        name="Обед", kind=SubjectKind.ACTIVITY, weekly_hours=0,
    )
    client.defaults["HTTP_HOST"] = tenant_a.host
    body = client.get(reverse("public:landing")).content.decode()

    programme = body[body.index('id="programma"'):body.index('id="pedagogi"')]
    assert tenant_a.subject.name in programme
    assert "Обед" not in programme


def test_map_query_is_specific_enough_to_find_the_place(tenant_a):
    """
    Виджету карт короткого адреса мало: он открывается обзором страны.

    В подвале адрес должен остаться коротким, поэтому строку для карты
    собираем отдельно.
    """
    tenant_a.organization.address = "Красноярск, ул. Весны, 10"
    assert tenant_a.organization.map_query == "Россия, Красноярск, ул. Весны, 10"

    tenant_a.organization.address = ""
    assert tenant_a.organization.map_query == ""


def test_map_is_not_offered_without_an_address(client, tenant_a):
    tenant_a.organization.address = ""
    tenant_a.organization.save(update_fields=["address"])

    client.defaults["HTTP_HOST"] = tenant_a.host
    body = client.get(reverse("public:landing")).content.decode()

    # Скрипт-обработчик в разметке остаётся всегда, а вот кнопки,
    # которая обещает карту, без адреса быть не должно.
    assert 'class="map-teaser"' not in body
    assert "Открыть в Яндекс.Картах" not in body


@pytest.mark.parametrize(
    "number, expected",
    [
        (1, "урок"), (2, "урока"), (4, "урока"), (5, "уроков"),
        (11, "уроков"), (12, "уроков"), (14, "уроков"),
        (21, "урок"), (22, "урока"), (33, "урока"), (100, "уроков"),
        (0, "уроков"),
    ],
)
def test_russian_plural(number, expected):
    """
    Встроенный pluralize знает две формы и на трёх молча отдаёт пустоту.

    На сайте это выглядело как «Всего 33 урок в неделю» и
    «Весь состав — 9 педагог».
    """
    from apps.site_public.templatetags.public_extras import plural

    assert plural(number, "урок,урока,уроков") == expected


def test_programme_total_is_declined(client, tenant_a):
    client.defaults["HTTP_HOST"] = tenant_a.host
    body = client.get(reverse("public:landing")).content.decode()

    hours = tenant_a.subject.weekly_hours
    assert f"{hours}</strong> урок" in body
