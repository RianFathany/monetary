"""CSRF: POST tanpa token yang cocok harus ditolak, GET tidak terganggu."""
import asyncio
import unittest

from app import csrf


class Panggilan:
    """Aplikasi ASGI palsu yang mencatat body yang diterimanya."""

    def __init__(self):
        self.dipanggil = False
        self.body = None

    async def __call__(self, scope, receive, send):
        self.dipanggil = True
        data = b""
        more = True
        while more:
            m = await receive()
            data += m.get("body", b"")
            more = m.get("more_body", False)
        self.body = data
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


def jalankan(method="POST", cookie="", field="", body=None, ctype="application/x-www-form-urlencoded"):
    app = Panggilan()
    mw = csrf.CSRFMiddleware(app)
    headers = [(b"content-type", ctype.encode())]
    if cookie:
        headers.append((b"cookie", f"{csrf.COOKIE}={cookie}".encode()))
    payload = body if body is not None else f"a=1&{csrf.FIELD}={field}".encode()
    scope = {"type": "http", "method": method, "headers": headers, "path": "/x"}
    keluar = []

    async def receive():
        return {"type": "http.request", "body": payload, "more_body": False}

    async def send(message):
        keluar.append(message)

    asyncio.run(mw(scope, receive, send))
    status = next((m["status"] for m in keluar if m["type"] == "http.response.start"), None)
    return app, status


class TestCSRF(unittest.TestCase):
    def test_token_cocok_diteruskan(self):
        app, status = jalankan(cookie="abc123", field="abc123")
        self.assertTrue(app.dipanggil)
        self.assertEqual(status, 200)

    def test_tanpa_token_ditolak(self):
        app, status = jalankan(cookie="abc123", field="")
        self.assertFalse(app.dipanggil)
        self.assertEqual(status, 403)

    def test_token_salah_ditolak(self):
        app, status = jalankan(cookie="abc123", field="tebakan")
        self.assertFalse(app.dipanggil)
        self.assertEqual(status, 403)

    def test_tanpa_cookie_ditolak(self):
        app, status = jalankan(cookie="", field="abc123")
        self.assertFalse(app.dipanggil)
        self.assertEqual(status, 403)

    def test_get_tidak_diperiksa(self):
        app, status = jalankan(method="GET", cookie="", field="")
        self.assertTrue(app.dipanggil)
        self.assertEqual(status, 200)

    def test_body_diteruskan_utuh(self):
        """Middleware membaca body untuk memeriksa token — aplikasi tetap harus menerimanya."""
        body = f"jumlah=25000&{csrf.FIELD}=tok".encode()
        app, status = jalankan(cookie="tok", field="tok", body=body)
        self.assertEqual(app.body, body)

    def test_token_baru_selalu_berbeda(self):
        self.assertNotEqual(csrf.new_token(), csrf.new_token())
        self.assertGreater(len(csrf.new_token()), 30)

    def test_cookie_dibaca_dari_deretan_cookie(self):
        scope = {"headers": [(b"cookie", b"lain=1; monetary_csrf=nilai; x=2")]}
        self.assertEqual(csrf.token_from(scope), "nilai")


if __name__ == "__main__":
    unittest.main()
