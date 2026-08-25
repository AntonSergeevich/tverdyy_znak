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


@pytest.mark.parametrize("url_name", PUBLIC_PAGES)
def test_word_school_only_about_accredited_partner(client_a, url_name):
    body = _text(client_a, url_name)
    sentences = re.split(r"(?<=[.!?])\s+|\n", body)
    offending = [
        sentence.strip()
        for sentence in sentences
        if re.search(r"школ", sentence, re.IGNORECASE)
        and not any(marker in sentence.lower() for marker in SCHOOL_ALLOWED_CONTEXT)
    ]
    assert not offending, f"Слово «школа» вне контекста партнёра: {offending[:3]}"


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
