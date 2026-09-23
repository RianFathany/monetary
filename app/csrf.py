"""Perlindungan CSRF: double-submit cookie.

Cookie `monetary_csrf` berisi nilai acak; setiap form POST harus mengirim nilai
yang sama di kolom tersembunyi `_csrf`. Situs lain bisa membuat browser korban
mengirim POST ke sini, tapi tidak bisa membaca cookie milik domain ini — jadi
tidak bisa menebak nilainya.

Ditulis sebagai middleware ASGI biasa (bukan BaseHTTPMiddleware) supaya bisa
membaca body untuk memeriksa token lalu mengulanginya ke aplikasi — hal yang
tidak bisa dilakukan middleware biasa tanpa menelan body permintaan.
"""
import hmac
import secrets
import urllib.parse

COOKIE = "monetary_csrf"
FIELD = "_csrf"
SAFE = {"GET", "HEAD", "OPTIONS", "TRACE"}
EXEMPT = ()                      # semua POST dilindungi; tidak ada pengecualian


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_from(scope) -> str:
    """Ambil token dari cookie permintaan, atau string kosong."""
    for name, value in scope.get("headers", []):
        if name == b"cookie":
            for part in value.decode("latin-1").split(";"):
                k, _, v = part.strip().partition("=")
                if k == COOKIE:
                    return v
    return ""


class CSRFMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in SAFE:
            await self.app(scope, receive, send)
            return

        body = b""
        more = True
        while more:                                   # baca habis body sekali
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body += message.get("body", b"")
            more = message.get("more_body", False)

        cookie = token_from(scope)
        sent = ""
        ctype = ""
        for name, value in scope.get("headers", []):
            if name == b"content-type":
                ctype = value.decode("latin-1")
        if ctype.startswith("application/x-www-form-urlencoded"):
            form = urllib.parse.parse_qs(body.decode("utf-8", "replace"))
            sent = (form.get(FIELD) or [""])[0]

        if not cookie or not sent or not hmac.compare_digest(cookie, sent):
            await self._deny(send)
            return

        replayed = False

        async def replay():
            nonlocal replayed
            if replayed:
                return await receive()
            replayed = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay, send)

    async def _deny(self, send):
        html = (b"<!doctype html><meta charset=utf-8><title>403</title>"
                b"<body style='font-family:system-ui;padding:40px;line-height:1.6'>"
                b"<h1 style='font-size:18px'>Permintaan ditolak</h1>"
                b"<p>Formulir ini kedaluwarsa atau dikirim dari halaman lain. "
                b"Muat ulang halaman, lalu coba lagi.</p>"
                b"<p><a href='/'>Kembali</a></p>")
        await send({"type": "http.response.start", "status": 403,
                    "headers": [(b"content-type", b"text/html; charset=utf-8"),
                                (b"content-length", str(len(html)).encode())]})
        await send({"type": "http.response.body", "body": html})
