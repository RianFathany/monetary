"""Single-user login: password from env, signed session cookie."""
import hmac
import os

from fastapi import Request
from itsdangerous import BadSignature, URLSafeTimedSerializer

PASSWORD = os.environ.get("MONETARY_PASSWORD", "")
SECRET = os.environ.get("MONETARY_SECRET", "dev-secret-change-me")
COOKIE = "monetary_session"
MAX_AGE = 60 * 60 * 24 * 30  # 30 hari

_signer = URLSafeTimedSerializer(SECRET, salt="monetary-login")


def check_password(candidate: str) -> bool:
    if not PASSWORD:
        return False
    return hmac.compare_digest(candidate.encode(), PASSWORD.encode())


def make_token() -> str:
    return _signer.dumps({"u": "owner"})


def is_authed(request: Request) -> bool:
    tok = request.cookies.get(COOKIE)
    if not tok:
        return False
    try:
        _signer.loads(tok, max_age=MAX_AGE)
        return True
    except BadSignature:
        return False
