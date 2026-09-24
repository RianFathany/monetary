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

    def test_host_utama_tidak_ikut_dialihkan(self):
        m = self.muat(canonical="muara.contoh.com", legacy="lama.contoh.com")
        self.assertNotIn(m.CANONICAL_HOST, m.LEGACY_HOSTS)
