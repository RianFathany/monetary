"""Login satu pengguna. Password (hash PBKDF2) dan secret cookie disimpan di tabel settings,
jadi tidak perlu .env. MONETARY_PASSWORD di env hanya dipakai sebagai bootstrap pertama kali."""
import hashlib
import hmac
import os
import secrets

from fastapi import Request
from itsdangerous import BadSignature, URLSafeTimedSerializer

from .db import get_db, get_setting, set_setting

COOKIE = "monetary_session"
MAX_AGE = 60 * 60 * 24 * 30  # 30 hari
_ITER = 200_000


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITER)


def make_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    return salt.hex() + "$" + _hash(password, salt).hex()


def verify(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$", 1)
    except ValueError:
        return False
    return hmac.compare_digest(_hash(password, bytes.fromhex(salt_hex)), bytes.fromhex(digest_hex))


def bootstrap() -> None:
    """Dipanggil saat startup: buat secret cookie, dan ambil password dari env bila belum ada di DB."""
    with get_db() as db:
        if not get_setting(db, "secret"):
            set_setting(db, "secret", secrets.token_hex(32))
        if not get_setting(db, "password_hash") and os.environ.get("MONETARY_PASSWORD"):
            set_setting(db, "password_hash", make_hash(os.environ["MONETARY_PASSWORD"]))


def is_configured() -> bool:
    with get_db() as db:
        return bool(get_setting(db, "password_hash"))


def check_password(candidate: str) -> bool:
    with get_db() as db:
        stored = get_setting(db, "password_hash")
    return bool(stored) and verify(candidate, stored)


def set_password(new: str) -> None:
    with get_db() as db:
        set_setting(db, "password_hash", make_hash(new))


def _signer() -> URLSafeTimedSerializer:
    with get_db() as db:
        secret = get_setting(db, "secret")
    return URLSafeTimedSerializer(secret, salt="monetary-login")


def make_token() -> str:
    return _signer().dumps({"u": "owner"})


def is_authed(request: Request) -> bool:
    tok = request.cookies.get(COOKIE)
    if not tok:
        return False
    try:
        _signer().loads(tok, max_age=MAX_AGE)
        return True
    except BadSignature:
        return False
