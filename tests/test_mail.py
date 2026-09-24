"""Verifikasi email & setel ulang password: tautan, masa berlaku, sekali pakai."""
import tempfile
import os
import unittest
from pathlib import Path


class TestTautanSurel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        from app import auth, db, mailer, users
        self._orig = db.DB_PATH
        db.DB_PATH = str(Path(self.tmp.name) / "monetary.db")
        db._ready.clear(); db._system_ready.clear()
        db.init_book(db.DB_PATH); db.init_system()
        db.set_app_setting("secret", "rahasia-untuk-tes")
        self.db, self.users, self.auth, self.mailer = db, users, auth, mailer

    def tearDown(self):
        self.db.set_book("")
        self.db.DB_PATH = self._orig
        self.db._ready.clear(); self.db._system_ready.clear()
        self.tmp.cleanup()

    def test_tautan_terbaca_kembali(self):
        tok = self.auth.make_link("verify", {"i": 7, "e": "a@b.com"})
        self.assertEqual(self.auth.read_link("verify", tok, 3600)["i"], 7)

    def test_tautan_kedaluwarsa_ditolak(self):
        tok = self.auth.make_link("reset", {"i": 1})
        self.assertEqual(self.auth.read_link("reset", tok, -1), {})

    def test_tautan_salah_tujuan_ditolak(self):
        tok = self.auth.make_link("verify", {"i": 1})
        self.assertEqual(self.auth.read_link("reset", tok, 3600), {})

    def test_tautan_diubah_ditolak(self):
        tok = self.auth.make_link("verify", {"i": 1})
        self.assertEqual(self.auth.read_link("verify", tok[:-3] + "xyz", 3600), {})

    def test_surel_mati_kalau_belum_dikonfigurasi(self):
        self.assertFalse(self.mailer.is_enabled())
        ok, err = self.mailer.send("a@b.com", "x", "y", ["z"])
        self.assertFalse(ok)

    def test_konfigurasi_surel_disimpan(self):
        self.mailer.save_config("re_kunci", "kirim@contoh.com", "Muara")
        self.assertTrue(self.mailer.is_enabled())
        self.mailer.save_config("", "kirim2@contoh.com", "Muara")   # kosong = kunci lama dipakai
        self.assertEqual(self.mailer.config()["api_key"], "re_kunci")
        self.assertEqual(self.mailer.config()["sender"], "kirim2@contoh.com")

    def test_isi_surel_memuat_tautan(self):
        html = self.mailer.render("Judul", ["baris"], ("Klik", "https://contoh/x?token=abc"))
        self.assertIn("https://contoh/x?token=abc", html)
        self.assertIn("Judul", html)

    def test_setel_ulang_hanya_sekali_pakai(self):
        """Tautan lama harus mati setelah password diganti — dijaga oleh session_epoch."""
        u = self.users.create("orang@mail.com", password_hash=self.auth.make_hash("lama12345"))
        token_data = {"i": u["id"], "e": u["session_epoch"], "p": (u["password_hash"] or "")[:16]}
        self.users.set_password(u["id"], self.auth.make_hash("baru12345"))
        sekarang = self.users.by_id(u["id"])
        self.assertNotEqual(int(token_data["e"]), int(sekarang["session_epoch"]))
        self.assertNotEqual(token_data["p"], (sekarang["password_hash"] or "")[:16])

    def test_verifikasi_menandai_akun(self):
        u = self.users.create("orang@mail.com", password_hash=self.auth.make_hash("lama12345"))
        self.assertEqual(u["email_verified"], 0)
        self.users.mark_verified(u["id"])
        self.assertEqual(self.users.by_id(u["id"])["email_verified"], 1)


if __name__ == "__main__":
    unittest.main()


class SumberKonfigurasi(unittest.TestCase):
    """Environment jadi bawaan, sama seperti kredensial Google."""

    def muat(self, simpanan=None, **env):
        import importlib, os
        from app import mailer
        for k in ("RESEND_API_KEY", "MAIL_SENDER", "MAIL_NAME"):
            os.environ.pop(k, None)
        os.environ.update(env)

        def bersihkan():
            for k in ("RESEND_API_KEY", "MAIL_SENDER", "MAIL_NAME"):
                os.environ.pop(k, None)
            importlib.reload(mailer)          # kembalikan get_app_setting yang asli
        self.addCleanup(bersihkan)
        importlib.reload(mailer)
        simpanan = simpanan or {}
        mailer.get_app_setting = lambda key, default="": simpanan.get(key, default)
        return mailer

    def test_environment_menyalakan_pengiriman(self):
        m = self.muat(RESEND_API_KEY="re_abc", MAIL_SENDER="muara@contoh.com")
        self.assertTrue(m.is_enabled())
        self.assertTrue(m.from_env())
        self.assertEqual(m.config()["name"], "Muara")

    def test_environment_menang_atas_nilai_lama_di_database(self):
        """Konfigurasi ini tidak bisa lagi diketik lewat Setelan, jadi
        environment yang berlaku dan nilai lama di database hanya cadangan."""
        m = self.muat({"resend_key": "re_lama"}, RESEND_API_KEY="re_env", MAIL_SENDER="muara@contoh.com")
        self.assertEqual(m.config()["api_key"], "re_env")

    def test_nilai_lama_dipakai_kalau_environment_kosong(self):
        m = self.muat({"resend_key": "re_lama", "mail_from": "a@b.c"})
        self.assertEqual(m.config()["api_key"], "re_lama")
        self.assertTrue(m.is_enabled())

    def test_tanpa_alamat_pengirim_belum_aktif(self):
        m = self.muat(RESEND_API_KEY="re_abc")
        self.assertFalse(m.is_enabled())
