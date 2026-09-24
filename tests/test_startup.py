"""Perilaku saat aplikasi start: menolak skema lama, atau mengadopsi database siap-pakai."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import db as dbmod
from app.schema import apply_schema, seed_defaults

LEGACY = """
CREATE TABLE emergency_fund (id INTEGER PRIMARY KEY, month_key TEXT, amount INTEGER);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
"""


class Start(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "monetary.db"
        legacy = sqlite3.connect(self.path)
        legacy.executescript(LEGACY)
        legacy.commit()
        legacy.close()

    def tearDown(self):
        self.tmp.cleanup()

    def prepared(self):
        p = self.path.with_name("monetary-v2.db")
        con = sqlite3.connect(p)
        apply_schema(con)
        seed_defaults(con)
        con.execute("INSERT INTO accounts(name,type) VALUES ('Kas','cash')")
        con.commit()
        con.close()
        return p

    def test_menolak_jalan_di_atas_skema_lama(self):
        with mock.patch.object(dbmod, "DB_PATH", str(self.path)):
            with self.assertRaises(RuntimeError):
                dbmod.init_db()

    def test_mengadopsi_database_siap_pakai_dan_menyimpan_yang_lama(self):
        self.prepared()
        with mock.patch.object(dbmod, "DB_PATH", str(self.path)):
            dbmod.init_db()
            with dbmod.get_db() as db:
                self.assertTrue(db.execute("SELECT 1 FROM sqlite_master WHERE name='accounts'").fetchone())
        self.assertTrue(self.path.with_name("monetary-v1-backup.db").exists(), "database lama harus disimpan")
        self.assertFalse(self.path.with_name("monetary-v2.db").exists(), "berkas siap-pakai sudah dipakai")

    def test_tidak_mengadopsi_berkas_yang_bukan_skema_baru(self):
        bogus = self.path.with_name("monetary-v2.db")
        con = sqlite3.connect(bogus)
        con.executescript(LEGACY)
        con.commit()
        con.close()
        with mock.patch.object(dbmod, "DB_PATH", str(self.path)):
            with self.assertRaises(RuntimeError):
                dbmod.init_db()

    def test_database_baru_dibuat_lengkap_dengan_bawaan(self):
        fresh = Path(self.tmp.name) / "baru.db"
        with mock.patch.object(dbmod, "DB_PATH", str(fresh)):
            dbmod.init_db()
            with dbmod.get_db() as db:
                self.assertGreater(db.execute("SELECT COUNT(*) c FROM categories").fetchone()["c"], 0)
                self.assertGreater(db.execute("SELECT COUNT(*) c FROM accounts").fetchone()["c"], 0)


if __name__ == "__main__":
    unittest.main()


class PengalihanDomain(unittest.TestCase):
    """Domain lama dialihkan permanen; tanpa setelan, tidak ada yang dialihkan."""

    def muat(self, canonical="", legacy=""):
        import importlib, os
        from app import main
        os.environ["CANONICAL_HOST"] = canonical
        os.environ["REDIRECT_HOSTS"] = legacy
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ("CANONICAL_HOST", "REDIRECT_HOSTS")])
        return importlib.reload(main)

    def test_tanpa_setelan_tidak_mengalihkan(self):
        m = self.muat()
        self.assertEqual(m.LEGACY_HOSTS, set())
        self.assertEqual(m.CANONICAL_HOST, "")

    def test_daftar_dibaca_dari_environment(self):
        m = self.muat(canonical="muara.contoh.com", legacy="lama.contoh.com, Lain.Contoh.com")
        self.assertEqual(m.CANONICAL_HOST, "muara.contoh.com")
        self.assertEqual(m.LEGACY_HOSTS, {"lama.contoh.com", "lain.contoh.com"})

    def alihkan(self, m, method, host):
        """Jalankan middleware pengalih untuk satu permintaan buatan."""
        import asyncio
        from starlette.requests import Request

        scope = {"type": "http", "method": method, "path": "/lang", "scheme": "https",
                 "server": (host, 443), "query_string": b"", "root_path": "",
                 "headers": [(b"host", host.encode())]}

        async def berikutnya(_):
            raise AssertionError("tidak boleh sampai ke aplikasi")

        return asyncio.run(m._canonical_host(Request(scope), berikutnya))

    def test_post_dari_domain_lama_memakai_308(self):
        """301 dan 302 diubah peramban jadi GET tanpa body, jadi setiap form yang
        dikirim dari domain lama akan mendarat sebagai GET dan berakhir 405.
        308 mempertahankan metode dan isinya."""
        m = self.muat(canonical="muara.contoh.com", legacy="lama.contoh.com")
        r = self.alihkan(m, "POST", "lama.contoh.com")
        self.assertEqual(r.status_code, 308)
        self.assertEqual(r.headers["location"], "https://muara.contoh.com/lang")

    def test_get_dari_domain_lama_tetap_301(self):
        m = self.muat(canonical="muara.contoh.com", legacy="lama.contoh.com")
        self.assertEqual(self.alihkan(m, "GET", "lama.contoh.com").status_code, 301)

    def test_host_utama_tidak_ikut_dialihkan(self):
        m = self.muat(canonical="muara.contoh.com", legacy="lama.contoh.com")
        self.assertNotIn(m.CANONICAL_HOST, m.LEGACY_HOSTS)


class BacaEnvFile(unittest.TestCase):
    """`.env` dibaca saat start, tapi tidak pernah menimpa environment asli."""

    def jalankan(self, isi, sudah_ada=None):
        import os, tempfile
        from pathlib import Path
        from app import main
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / ".env").write_text(isi)
        asli = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(asli)))
        for k, v in (sudah_ada or {}).items():
            os.environ[k] = v
        base_asli = main.BASE
        main.BASE = Path(tmp.name) / "app"
        self.addCleanup(lambda: setattr(main, "BASE", base_asli))
        main._load_env_file()
        return os.environ

    def test_nilai_dibaca(self):
        env = self.jalankan("RESEND_API_KEY=re_dari_berkas\nMAIL_SENDER=a@b.c\n")
        self.assertEqual(env["RESEND_API_KEY"], "re_dari_berkas")
        self.assertEqual(env["MAIL_SENDER"], "a@b.c")

    def test_environment_asli_menang(self):
        env = self.jalankan("RESEND_API_KEY=re_berkas\n", {"RESEND_API_KEY": "re_env"})
        self.assertEqual(env["RESEND_API_KEY"], "re_env")

    def test_komentar_dan_baris_kosong_diabaikan(self):
        env = self.jalankan("# catatan\n\nMAIL_NAME=Muara\n")
        self.assertEqual(env["MAIL_NAME"], "Muara")
        self.assertNotIn("# catatan", env)

    def test_tanda_kutip_dilepas(self):
        env = self.jalankan('MAIL_SENDER="a@b.c"\n')
        self.assertEqual(env["MAIL_SENDER"], "a@b.c")
