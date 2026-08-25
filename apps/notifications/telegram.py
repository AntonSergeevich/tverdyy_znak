"""Тонкий клиент Telegram Bot API. Токен и chat_id — только из окружения."""
from __future__ import annotations

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot{token}/sendMessage"
TIMEOUT_SECONDS = 10


class TelegramError(RuntimeError):
    pass


def send_message(text: str, chat_id: str | None = None, *, token: str | None = None) -> dict:
    token = token or settings.TG_BOT_TOKEN
    chat_id = chat_id or settings.TG_CHAT_ID
    if not token or not chat_id:
        raise TelegramError("TG_BOT_TOKEN или TG_CHAT_ID не настроены")

    response = requests.post(
        API_URL.format(token=token),
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise TelegramError(f"Telegram ответил {response.status_code}: {response.text[:300]}")
    payload = response.json()
    if not payload.get("ok"):
        raise TelegramError(f"Telegram отклонил сообщение: {payload}")
    return payload
