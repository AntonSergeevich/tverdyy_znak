"""
Минимальный TOTP (RFC 6238) без внешних зависимостей.

Достаточно для второго фактора привилегированных ролей: совместим
с Google Authenticator, Aegis, 1Password.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP_SECONDS = 30
DIGITS = 6
ALLOWED_DRIFT_STEPS = 1  # ±30 секунд


def generate_secret(length: int = 20) -> str:
    return base64.b32encode(secrets.token_bytes(length)).decode("ascii").rstrip("=")


def _code_for_counter(secret: str, counter: int) -> str:
    padding = "=" * (-len(secret) % 8)
    key = base64.b32decode(secret + padding, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10 ** DIGITS)).zfill(DIGITS)


def current_counter(at: float | None = None) -> int:
    return int((at if at is not None else time.time()) // STEP_SECONDS)


def code_now(secret: str, at: float | None = None) -> str:
    return _code_for_counter(secret, current_counter(at))


def verify(secret: str, code: str, *, last_used_counter: int = 0, at: float | None = None) -> int | None:
    """
    Возвращает использованный counter при успехе, иначе None.

    Counter возвращается, чтобы вызывающий код сохранил его и не дал
    переиспользовать один и тот же код повторно.
    """
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit() or len(code) != DIGITS:
        return None
    now = current_counter(at)
    for drift in range(-ALLOWED_DRIFT_STEPS, ALLOWED_DRIFT_STEPS + 1):
        counter = now + drift
        if counter <= last_used_counter:
            continue
        if hmac.compare_digest(_code_for_counter(secret, counter), code):
            return counter
    return None


def provisioning_uri(secret: str, account: str, issuer: str) -> str:
    label = quote(f"{issuer}:{account}")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}"
        f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}"
    )
