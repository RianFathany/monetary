"""Login satu pengguna. Password (hash PBKDF2) dan secret cookie disimpan di tabel settings,
jadi tidak perlu .env. MONETARY_PASSWORD di env hanya dipakai sebagai bootstrap pertama kali."""
import hashlib
import hmac
import os
import secrets
import time

from fastapi import Request
from itsdangerous import BadSignature, URLSafeTimedSerializer

from .db import get_app_setting, set_app_setting

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
    """Dipanggil saat startup: buat secret cookie, dan ambil password dari env bila belum ada."""
    if not get_app_setting("secret"):
        set_app_setting("secret", secrets.token_hex(32))
    if not get_app_setting("password_hash") and os.environ.get("MONETARY_PASSWORD"):
        set_app_setting("password_hash", make_hash(os.environ["MONETARY_PASSWORD"]))


def is_configured() -> bool:
    return bool(get_app_setting("password_hash"))


def check_password(candidate: str) -> bool:
    stored = get_app_setting("password_hash")
    return bool(stored) and verify(candidate, stored)


def set_password(new: str) -> None:
    """Ganti password sekaligus memutar secret cookie: semua sesi lama (perangkat
    lain, cookie yang tercuri) langsung tidak berlaku."""
    set_app_setting("password_hash", make_hash(new))
    set_app_setting("secret", secrets.token_hex(32))


# --- pembatas percobaan login ---
# Satu mesin, satu proses: cukup disimpan di memori. Hilang saat restart, dan itu
# tidak masalah — tujuannya memperlambat tebakan beruntun, bukan mengunci permanen.
FAIL_MAX = 5           # percobaan gagal
FAIL_WINDOW = 900      # dalam 15 menit
LOCK_FOR = 900         # dikunci 15 menit
_fails: dict = {}


def _now() -> float:
    return time.time()


def client_key(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() or (request.client.host if request.client else "?"))


def locked_for(request: Request) -> int:
    """Sisa detik penguncian, 0 kalau masih boleh mencoba."""
    hits = [t for t in _fails.get(client_key(request), []) if _now() - t < FAIL_WINDOW]
    if len(hits) < FAIL_MAX:
        return 0
    return max(0, int(LOCK_FOR - (_now() - hits[-1])))


def note_failure(request: Request) -> None:
    k = client_key(request)
    _fails[k] = [t for t in _fails.get(k, []) if _now() - t < FAIL_WINDOW] + [_now()]


def note_success(request: Request) -> None:
    _fails.pop(client_key(request), None)


def _secret() -> str:
    return get_app_setting("secret")


def _signer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_secret(), salt="monetary-login")


def make_token(user_id=1, who: str = "owner", epoch: int = 0) -> str:
    """Cookie sesi: id pengguna (menentukan buku mana yang dibuka), catatan siapa,
    dan `epoch` — dinaikkan saat password diganti supaya sesi lama berhenti berlaku."""
    return _signer().dumps({"i": int(user_id), "u": who, "e": int(epoch)})


def session(request: Request) -> dict:
    try:
        data = _signer().loads(request.cookies.get(COOKIE, ""), max_age=MAX_AGE)
    except (BadSignature, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def whoami(request: Request) -> str:
    return session(request).get("u", "")


def user_id(request: Request) -> int:
    return int(session(request).get("i", 1) or 1)


def session_epoch(request: Request) -> int:
    return int(session(request).get("e", 0) or 0)


def check_hash(candidate: str, stored: str) -> bool:
    return bool(stored) and verify(candidate, stored)


def sign(data: dict) -> str:
    """Tanda tangani data singkat (dipakai state OAuth) dengan secret yang sama."""
    return URLSafeTimedSerializer(_secret(), salt="monetary-oauth").dumps(data)


def unsign(token: str, max_age: int) -> dict:
    try:
        return URLSafeTimedSerializer(_secret(), salt="monetary-oauth").loads(token, max_age=max_age)
    except (BadSignature, TypeError):
        return {}


def session_left(request: Request) -> int:
    """Sisa detik sebelum cookie sesi kedaluwarsa (0 = tidak/ belum masuk)."""
    tok = request.cookies.get(COOKIE)
    if not tok:
        return 0
    try:
        _, issued = _signer().loads(tok, max_age=MAX_AGE, return_timestamp=True)
    except (BadSignature, TypeError):
        return 0
    return max(0, int(MAX_AGE - (time.time() - issued.timestamp())))


def is_authed(request: Request) -> bool:
    tok = request.cookies.get(COOKIE)
    if not tok:
        return False
    try:
        _signer().loads(tok, max_age=MAX_AGE)
        return True
    except BadSignature:
        return False
