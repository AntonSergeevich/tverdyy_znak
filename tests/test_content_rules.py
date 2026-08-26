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
    """
    Педагог на сайте — та же запись, что в журнале.

    Заводить человека второй раз, отдельной публичной карточкой, больше
    не нужно: два источника правды об одном педагоге однажды расходятся.
    """
    tenant_a.teacher.subject_line = "Математика, физика, информатика"
    tenant_a.teacher.experience = "Стаж более 30 лет"
    tenant_a.teacher.bio = "Опыт работы в школе и вузе. Учит думать, а не зубрить."
    tenant_a.teacher.is_published = True
    tenant_a.teacher.save()

    body = _text(client_a, "public:landing")
    assert tenant_a.teacher.user.full_name in body
    assert "Математика, физика, информатика" in body
    assert "Учит думать" in body


def test_unpublished_teacher_stays_out_of_the_site(client_a, tenant_a):
    """
    Пока галочка не поставлена, педагог виден только в кабинете.

    Иначе каждый заведённый человек мгновенно попадал бы на главную —
    вместе с недописанным текстом и без фотографии.
    """
    tenant_a.teacher.bio = "Черновик описания."
    tenant_a.teacher.is_published = False
    tenant_a.teacher.save()

    body = _text(client_a, "public:landing")
    assert "Черновик описания" not in body


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
    """
    Публикуемые педагоги — записи журнала, а не отдельные карточки.

    Человека заводят один раз, галочка «показывать на сайте» решает,
    попадает ли он на главную.
    """
    from decimal import Decimal

    from django.contrib.auth import get_user_model

    from apps.accounts.models import Membership, Role
    from apps.journal.models import Teacher

    User = get_user_model()

    def make(last_name, first_name, *, featured=False, position=100, subject_line=""):
        # Логин уникален на всю базу, а фикстуры создают одинаковые
        # фамилии в двух организациях — добавляем код арендатора.
        user = User.objects.create_user(
            username=f"{tenant.organization.slug}-{last_name.lower()}{position}",
            password="x", last_name=last_name, first_name=first_name,
        )
        Membership.objects.create(
            user=user, organization=tenant.organization, role=Role.TEACHER
        )
        return Teacher.all_objects.create(
            organization=tenant.organization, user=user, hourly_rate=Decimal("0.00"),
            subject_line=subject_line or "Предмет", bio=f"Про {last_name}.",
            is_published=True, is_featured=featured, public_position=position,
        )

    parts = featured_name.split()
    make(parts[0], parts[1] if len(parts) > 1 else "И", featured=True, position=10,
         subject_line="Основатель")
    for index in range(count):
        make(f"Педагог{index}", "Имя", position=100 + index,
             subject_line=f"Предмет {index}")


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
    assert "Педагог0" in body


def test_landing_links_to_the_full_list_only_when_it_does_not_fit(client, tenant_a):
    from apps.site_public.views import TEACHERS_ON_LANDING

    _make_cards(tenant_a, TEACHERS_ON_LANDING)
    client.defaults["HTTP_HOST"] = tenant_a.host
    fits = client.get(reverse("public:landing")).content.decode()
    assert "Весь состав" not in fits

    from decimal import Decimal

    from django.contrib.auth import get_user_model

    from apps.accounts.models import Membership, Role
    from apps.journal.models import Teacher

    extra_user = get_user_model().objects.create_user(
        username="lishniy", password="x", last_name="Лишний", first_name="Педагог"
    )
    Membership.objects.create(
        user=extra_user, organization=tenant_a.organization, role=Role.TEACHER
    )
    Teacher.all_objects.create(
        organization=tenant_a.organization, user=extra_user, hourly_rate=Decimal("0.00"),
        subject_line="Предмет", is_published=True, public_position=900,
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
    from apps.journal.models import Teacher

    _make_cards(tenant_a, 12)
    client.defaults["HTTP_HOST"] = tenant_a.host
    body = client.get(reverse("public:teachers")).content.decode()

    published = Teacher.all_objects.filter(
        organization=tenant_a.organization, is_published=True
    )
    for teacher in published:
        assert teacher.user.full_name in body
        assert f'id="card-{teacher.pk}"' in body


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


def test_deploy_does_not_run_migrations_twice():
    """
    Миграции применяет контейнер при старте, и только он.

    Скрипт выката однажды делал то же самое сразу после `up -d`,
    параллельно ещё стартующему контейнеру. Две миграции подрались
    за одну таблицу, и выкат упал на «relation already exists».
    """
    from pathlib import Path

    script = Path("deploy/scripts/remote-deploy.sh").read_text(encoding="utf-8")
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "manage.py migrate" in compose
    assert "manage.py migrate" not in script
    assert "up -d --wait" in script


def test_non_web_containers_do_not_inherit_the_http_healthcheck():
    """
    HEALTHCHECK из образа дёргает http://127.0.0.1:8000/healthz.

    У воркера, планировщика и бэкапов веб-сервера нет, и они вечно
    числились нездоровыми. Само по себе безвредно — до того дня, когда
    выкат стал ждать готовности всего стека и оборвался на полпути,
    не дойдя до перезагрузки nginx. Сайт остался с 502.
    """
    import yaml

    services = yaml.safe_load(open("docker-compose.yml", encoding="utf-8"))["services"]

    for name in ("worker", "beat", "backup"):
        check = services[name].get("healthcheck")
        assert check is not None, f"{name}: наследует проверку из образа"
        assert check.get("disable") or check.get("test"), name


def test_deploy_waits_for_web_only():
    """`--wait` без имени сервиса ждёт весь стек — один сосед валит выкат."""
    from pathlib import Path

    script = Path("deploy/scripts/remote-deploy.sh").read_text(encoding="utf-8")
    assert "up -d --wait web" in script


def test_deploy_checks_a_real_page_not_only_healthz():
    """
    Healthz отвечает «жив» и при сломанной странице.

    Он не трогает ни базу, ни шаблоны, поэтому после выката с
    отсутствующей таблицей он был зелёным, а посетитель видел 500.
    Выкат должен падать сам, а не у человека в браузере.
    """
    from pathlib import Path

    script = Path("deploy/scripts/remote-deploy.sh").read_text(encoding="utf-8")

    assert "check /healthz" in script
    assert "check /" in script


def test_legal_pages_show_requisites_from_the_organization_card(client_a, tenant_a):
    """
    Реквизиты на правовых страницах берутся из карточки организации.

    Вшитые в текст ИНН с адресом устаревают молча: текст правит владелец,
    а сверять его с договором никто не будет.
    """
    tenant_a.organization.legal_name = "ИП Проверкин Пётр Петрович"
    tenant_a.organization.inn = "241502815698"
    tenant_a.organization.ogrnip = "326246800106544"
    tenant_a.organization.save()

    for name in ("public:legal_privacy", "public:legal_consent", "public:legal_terms"):
        body = _text(client_a, name)
        assert "ИП Проверкин Пётр Петрович" in body, name
        assert "241502815698" in body, name
        assert "326246800106544" in body, name


def test_teacher_rating_appears_only_with_published_reviews(client_a, tenant_a):
    """
    «0.0 из 5» у нового педагога выглядит как плохая оценка,
    хотя означает «ещё никто не писал».
    """
    from apps.site_public.models import TeacherReview

    tenant_a.teacher.is_published = True
    tenant_a.teacher.subject_line = "Математика"
    tenant_a.teacher.save()

    assert "rating-badge" not in _text(client_a, "public:landing")

    TeacherReview.all_objects.create(
        organization=tenant_a.organization, teacher=tenant_a.teacher,
        author_label="Мария П.", rating=5, text="Отличный педагог.",
        status=TeacherReview.Status.PUBLISHED,
    )
    body = _text(client_a, "public:landing")
    assert "rating-badge" in body
    # Русская локаль печатает дробь через запятую — так и надо.
    assert "5,0" in body


def test_rating_ignores_reviews_that_are_not_published(client_a, tenant_a):
    """Среднее считается по тем же отзывам, что видны на сайте."""
    from apps.site_public.models import TeacherReview

    tenant_a.teacher.is_published = True
    tenant_a.teacher.save()

    TeacherReview.all_objects.create(
        organization=tenant_a.organization, teacher=tenant_a.teacher,
        author_label="Один", rating=5, text="Пять.",
        status=TeacherReview.Status.PUBLISHED,
    )
    TeacherReview.all_objects.create(
        organization=tenant_a.organization, teacher=tenant_a.teacher,
        author_label="Другой", rating=1, text="Один.",
        status=TeacherReview.Status.PENDING,
    )
    from apps.core.tenancy import organization_context

    tenant_a.teacher.refresh_from_db()
    # Отзывы читаются менеджером арендатора: без контекста он честно
    # отдаёт пустоту, и тест проверял бы не то.
    with organization_context(tenant_a.organization):
        assert tenant_a.teacher.rating == 5.0
        assert tenant_a.teacher.reviews_count == 1


def test_schedule_builder_speaks_human_language(admin_client_for_rules, tenant_a):
    """
    Экран открывает администратор центра, а не разработчик.

    Название команды в сообщении об ошибке для него — шум, из которого
    непонятно, что делать.
    """
    body = admin_client_for_rules.get(reverse("cabinet:schedule_builder")).content.decode()
    assert "bootstrap_organization" not in body


@pytest.fixture
def admin_client_for_rules(client, tenant_a):
    """Владелец без второго фактора: проверяем тексты, а не вход."""
    from django.test import override_settings

    from tests.conftest import PASSWORD

    with override_settings(TWO_FACTOR_ENABLED=False):
        client.defaults["HTTP_HOST"] = tenant_a.host
        client.post(
            reverse("accounts:login"),
            {"username": tenant_a.owner_user.email, "password": PASSWORD},
        )
        yield client
