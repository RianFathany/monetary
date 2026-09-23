"""Cadangan: tanda tangan S3, isi arsip, retensi, penjadwalan."""
import datetime
import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from app import s3


class TestTandaTanganS3(unittest.TestCase):
    """Dicocokkan dengan contoh resmi dokumentasi AWS SigV4."""

    def test_contoh_resmi_aws(self):
        headers = s3.sign(
            "GET", "https://examplebucket.s3.amazonaws.com/test.txt",
            "AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "us-east-1",
            b"", {"range": "bytes=0-9"},
            now=datetime.datetime(2013, 5, 24, tzinfo=datetime.timezone.utc))
        self.assertIn("Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41",
                      headers["Authorization"])

    def test_kunci_berbeda_tanda_tangan_berbeda(self):
        args = ("PUT", "https://x.example.com/b/k", "AKIA", "rahasia", "auto", b"isi")
        a = s3.sign(*args, now=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc))
        b = s3.sign("PUT", "https://x.example.com/b/k", "AKIA", "lain", "auto", b"isi",
                    now=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc))
        self.assertNotEqual(a["Authorization"], b["Authorization"])

    def test_alamat_objek(self):
        cfg = dict(endpoint="https://x.r2.cloudflarestorage.com/", bucket="ember")
        self.assertEqual(s3.object_url(cfg, "monetary/a b.tar.gz"),
                         "https://x.r2.cloudflarestorage.com/ember/monetary/a%20b.tar.gz")


class TestArsip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        from app import backup, db, users
        self._orig = db.DB_PATH
        db.DB_PATH = str(Path(self.tmp.name) / "monetary.db")
        db._ready.clear(); db._system_ready.clear()
        db.init_book(db.DB_PATH); db.init_system()
        self.db, self.users, self.backup = db, users, backup

    def tearDown(self):
        self.db.set_book("")
        self.db.DB_PATH = self._orig
        self.db._ready.clear(); self.db._system_ready.clear()
        self.tmp.cleanup()

    def test_arsip_memuat_semua_buku(self):
        self.users.create("a@mail.com")
        self.users.create("b@mail.com")
        blob, count = self.backup.archive()
        with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
            names = sorted(tar.getnames())
        self.assertEqual(count, 4)                       # system + pemilik + 2 pengguna
        self.assertIn("system.db", names)
        self.assertIn("monetary.db", names)
        self.assertEqual(len([n for n in names if n.startswith("book-")]), 2)

    def test_arsip_bisa_dibuka_kembali_sebagai_database(self):
        import sqlite3
        blob, _ = self.backup.archive()
        with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
            tar.extractall(self.tmp.name + "/pulih", filter="data")
        conn = sqlite3.connect(self.tmp.name + "/pulih/monetary.db")
        self.assertGreater(conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0], 0)
        conn.close()

    def test_belum_diatur_berarti_tidak_jalan(self):
        self.assertFalse(self.backup.is_enabled())
        self.assertFalse(self.backup.due())
        ok, err = self.backup.run()
        self.assertFalse(ok)

    def test_nama_objek_berurut_waktu(self):
        cfg = dict(prefix="monetary/")
        k1 = self.backup.object_key(cfg, datetime.datetime(2026, 1, 1, 3, 0))
        k2 = self.backup.object_key(cfg, datetime.datetime(2026, 1, 2, 3, 0))
        self.assertLess(k1, k2)                          # urutan nama = urutan waktu, dipakai retensi
        self.assertTrue(k1.startswith("monetary/") and k1.endswith(".tar.gz"))

    def test_jadwal_jatuh_tempo(self):
        for key, val in (("backup_endpoint", "https://x"), ("backup_bucket", "b"),
                         ("backup_key", "k"), ("backup_secret", "s")):
            self.db.set_app_setting(key, val)
        self.assertTrue(self.backup.due())               # belum pernah
        now = datetime.datetime.now(datetime.timezone.utc)
        self.db.set_app_setting("backup_last_at", now.strftime("%Y-%m-%d %H:%M"))
        self.assertFalse(self.backup.due())              # baru saja
        lama = now - datetime.timedelta(hours=25)
        self.db.set_app_setting("backup_last_at", lama.strftime("%Y-%m-%d %H:%M"))
        self.assertTrue(self.backup.due())               # lewat 24 jam


if __name__ == "__main__":
    unittest.main()
