"""Masuk dengan Google: daftar izin, pemeriksaan token, dan state."""
import base64
import json
import os
import time
import unittest

from app import oauth


def id_token(payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return "header." + body + ".signature"


class TestDaftarEmail(unittest.TestCase):
    def test_pisah_koma_spasi_baris(self):
        self.assertEqual(oauth.emails("a@x.com, b@y.com\nc@z.com d@w.com"),
                         ["a@x.com", "b@y.com", "c@z.com", "d@w.com"])

    def test_huruf_besar_dan_duplikat(self):
        self.assertEqual(oauth.emails("A@X.com, a@x.com"), ["a@x.com"])

    def test_bukan_email_diabaikan(self):
        self.assertEqual(oauth.emails("bukan-email, a@x.com"), ["a@x.com"])


class TestKlaimToken(unittest.TestCase):
    def payload(self, **over):
        p = dict(iss="https://accounts.google.com", aud="cid", exp=int(time.time()) + 600,
                 email="a@x.com", email_verified=True)
        p.update(over)
        return p

    def test_token_sah(self):
        self.assertEqual(oauth.claims(id_token(self.payload()), "cid")["email"], "a@x.com")

    def test_penerbit_salah(self):
        with self.assertRaises(ValueError):
            oauth.claims(id_token(self.payload(iss="https://evil.example")), "cid")

    def test_tujuan_salah(self):
        with self.assertRaises(ValueError):
            oauth.claims(id_token(self.payload(aud="aplikasi-lain")), "cid")

    def test_kedaluwarsa(self):
        with self.assertRaises(ValueError):
            oauth.claims(id_token(self.payload(exp=int(time.time()) - 10)), "cid")

    def test_token_cacat(self):
        with self.assertRaises(ValueError):
            oauth.claims("bukan token", "cid")


class TestIzinMasuk(unittest.TestCase):
    """Daftar izin memetakan email ke buku pemilik; email lain bukan berarti ditolak,
    tapi didaftarkan dengan bukunya sendiri (lihat tests/test_users.py)."""

    def setUp(self):
        self._real = oauth.get_app_setting
        oauth.get_app_setting = lambda key, default="": {
            "google_client_id": "cid", "google_client_secret": "sec",
            "google_allowed": "boleh@gmail.com"}.get(key, default)

    def tearDown(self):
        oauth.get_app_setting = self._real

    def test_email_terverifikasi(self):
        self.assertEqual(oauth.verified_email(dict(email="Boleh@gmail.com", email_verified=True)),
                         "boleh@gmail.com")

    def test_email_belum_terverifikasi_ditolak(self):
        self.assertEqual(oauth.verified_email(dict(email="boleh@gmail.com", email_verified=False)), "")

    def test_daftar_izin(self):
        self.assertTrue(oauth.in_allowlist("BOLEH@gmail.com"))
        self.assertFalse(oauth.in_allowlist("orang@gmail.com"))

    def test_aktif_bila_client_id_dan_secret_ada(self):
        self.assertTrue(oauth.is_enabled())
        # Daftar email kosong tetap aktif: itu cuma penentu pewaris buku pemilik.
        oauth.get_app_setting = lambda key, default="": {
            "google_client_id": "cid", "google_client_secret": "sec"}.get(key, default)
        self.assertTrue(oauth.is_enabled())
        # Tanpa secret, tombolnya mati.
        oauth.get_app_setting = lambda key, default="": {
            "google_client_id": "cid"}.get(key, default)
        self.assertFalse(oauth.is_enabled())


class TestPembatasLogin(unittest.TestCase):
    """Percobaan password yang gagal berulang harus dikunci sementara."""

    class Req:
        def __init__(self, ip="1.2.3.4"):
            self.headers = {}
            self.client = type("c", (), {"host": ip})()

    def setUp(self):
        from app import auth
        self.auth = auth
        auth._fails.clear()

    def tearDown(self):
        self.auth._fails.clear()

    def test_belum_dikunci_di_bawah_batas(self):
        r = self.Req()
        for _ in range(self.auth.FAIL_MAX - 1):
            self.auth.note_failure(r)
        self.assertEqual(self.auth.locked_for(r), 0)

    def test_dikunci_setelah_batas(self):
        r = self.Req()
        for _ in range(self.auth.FAIL_MAX):
            self.auth.note_failure(r)
        self.assertGreater(self.auth.locked_for(r), 0)

    def test_berhasil_menghapus_catatan(self):
        r = self.Req()
        for _ in range(self.auth.FAIL_MAX):
            self.auth.note_failure(r)
        self.auth.note_success(r)
        self.assertEqual(self.auth.locked_for(r), 0)

    def test_alamat_lain_tidak_ikut_terkunci(self):
        r1, r2 = self.Req("1.1.1.1"), self.Req("2.2.2.2")
        for _ in range(self.auth.FAIL_MAX):
            self.auth.note_failure(r1)
        self.assertEqual(self.auth.locked_for(r2), 0)


class SumberKredensial(unittest.TestCase):
    """Environment jadi bawaan supaya tombol Google muncul sendiri di server baru."""

    def setUp(self):
        from app import db as dbmod, oauth
        self.oauth, self.dbmod = oauth, dbmod
        self.simpanan = {}
        self.env_awal = {k: os.environ.get(k) for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET")}
        self.addCleanup(self.pulihkan)
        dbmod.get_app_setting = lambda key, default="": self.simpanan.get(key, default)

    def pulihkan(self):
        import importlib
        from app import db as dbmod
        importlib.reload(dbmod)
        for k, v in self.env_awal.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def pakai(self, **env):
        for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
            os.environ.pop(k, None)
        os.environ.update(env)
        import importlib
        from app import oauth
        importlib.reload(oauth)
        oauth.get_app_setting = lambda key, default="": self.simpanan.get(key, default)
        return oauth

    def test_environment_menyalakan_tombol(self):
        o = self.pakai(GOOGLE_CLIENT_ID="abc.apps.googleusercontent.com", GOOGLE_CLIENT_SECRET="GOCSPX-rahasia")
        self.assertTrue(o.is_enabled())
        self.assertTrue(o.from_env())

    def test_setelan_menang_atas_environment(self):
        self.simpanan["google_client_id"] = "dari-setelan"
        o = self.pakai(GOOGLE_CLIENT_ID="dari-env", GOOGLE_CLIENT_SECRET="GOCSPX-rahasia")
        self.assertEqual(o.config()["client_id"], "dari-setelan")
        self.assertFalse(o.from_env())

    def test_tanpa_keduanya_tombol_mati(self):
        o = self.pakai()
        self.assertFalse(o.is_enabled())

    def test_id_saja_tanpa_secret_belum_cukup(self):
        o = self.pakai(GOOGLE_CLIENT_ID="abc.apps.googleusercontent.com")
        self.assertFalse(o.is_enabled())
