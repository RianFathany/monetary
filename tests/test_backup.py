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


class SumberKonfigurasi(unittest.TestCase):
    """Environment satu-satunya tempat mengatur, sama seperti Resend dan Google."""

    KUNCI = ("BACKUP_ENDPOINT", "BACKUP_BUCKET", "BACKUP_KEY", "BACKUP_SECRET",
             "BACKUP_REGION", "BACKUP_PREFIX", "BACKUP_KEEP", "BACKUP_EVERY_HOURS")

    def muat(self, simpanan=None, **env):
        import importlib, os
        from app import backup
        for k in self.KUNCI:
            os.environ.pop(k, None)
        os.environ.update(env)

        def bersihkan():
            for k in self.KUNCI:
                os.environ.pop(k, None)
            importlib.reload(backup)          # kembalikan get_app_setting yang asli
        self.addCleanup(bersihkan)
        importlib.reload(backup)
        simpanan = simpanan or {}
        backup.get_app_setting = lambda key, default="": simpanan.get(key, default)
        return backup

    def lengkap(self, **tambahan):
        return dict(BACKUP_ENDPOINT="https://x.r2.cloudflarestorage.com", BACKUP_BUCKET="ember",
                    BACKUP_KEY="AKIA", BACKUP_SECRET="rahasia", **tambahan)

    def test_environment_menyalakan_cadangan(self):
        b = self.muat(**self.lengkap())
        self.assertTrue(b.is_enabled())
        self.assertTrue(b.from_env())
        self.assertEqual(b.config()["region"], "auto")
        self.assertEqual(b.config()["prefix"], "monetary/")
        self.assertEqual(b.config()["keep"], 14)

    def test_environment_menang_atas_nilai_lama_di_database(self):
        """Konfigurasi ini tidak bisa lagi diketik lewat Setelan, jadi
        environment yang berlaku dan nilai lama di database hanya cadangan."""
        b = self.muat({"backup_bucket": "ember-lama"}, **self.lengkap())
        self.assertEqual(b.config()["bucket"], "ember")

    def test_nilai_lama_dipakai_kalau_environment_kosong(self):
        b = self.muat({"backup_endpoint": "https://lama", "backup_bucket": "ember",
                       "backup_key": "AKIA", "backup_secret": "rahasia"})
        self.assertTrue(b.is_enabled())
        self.assertFalse(b.from_env())
        self.assertEqual(b.config()["endpoint"], "https://lama")

    def test_setengah_terisi_belum_menyala(self):
        b = self.muat(BACKUP_ENDPOINT="https://x", BACKUP_BUCKET="ember")
        self.assertFalse(b.is_enabled())

    def test_angka_ngawur_jatuh_ke_bawaan(self):
        """Salah ketik di environment tidak boleh mematikan cadangan."""
        b = self.muat(**self.lengkap(BACKUP_KEEP="banyak", BACKUP_EVERY_HOURS=""))
        self.assertEqual(b.config()["keep"], 14)
        self.assertEqual(b.config()["every_hours"], 24)

    def test_angka_dijepit_ke_rentang_wajar(self):
        b = self.muat(**self.lengkap(BACKUP_KEEP="0", BACKUP_EVERY_HOURS="99999"))
        self.assertEqual(b.config()["keep"], 1)
        self.assertEqual(b.config()["every_hours"], 24 * 30)


class EmberPalsu:
    """Penyimpanan S3 di dalam memori. Yang dipalsukan cuma lapis jaringannya —
    penandatanganan, penyusunan URL, dan pembacaan daftar objek tetap yang asli."""

    def __init__(self, status=200):
        self.objects = {}
        self.status = status
        self.calls = []

    def request(self, method, url, cfg, payload=b"", extra=None, timeout=60):
        import urllib.parse
        self.calls.append(method)
        if method == "GET" and "list-type=2" in url:
            keys = "".join(f"<Key>{k}</Key>" for k in sorted(self.objects))
            return 200, f"<ListBucketResult>{keys}</ListBucketResult>".encode()
        base = f"{cfg['endpoint'].rstrip('/')}/{cfg['bucket']}/"
        key = urllib.parse.unquote(url[len(base):])
        if method == "PUT":
            if self.status == 200:
                self.objects[key] = payload
            return self.status, b"" if self.status == 200 else b"<Error>AccessDenied</Error>"
        if method == "DELETE":
            self.objects.pop(key, None)
            return 204, b""
        return 400, b""


class TestUnggahDanRetensi(unittest.TestCase):
    """Jalur yang nanti benar-benar dipakai di produksi: arsip dibuat, dikirim,
    hasilnya dicatat, arsip lama dipangkas. Sebelum ini belum pernah diuji."""

    def setUp(self):
        from unittest import mock
        from app import backup, db, s3
        self.tmp = tempfile.TemporaryDirectory()
        self._orig = db.DB_PATH
        db.DB_PATH = str(Path(self.tmp.name) / "monetary.db")
        db._ready.clear(); db._system_ready.clear()
        db.init_book(db.DB_PATH); db.init_system()
        for key, val in (("backup_endpoint", "https://acc.r2.cloudflarestorage.com"),
                         ("backup_bucket", "muara-backup"), ("backup_key", "AKIA"),
                         ("backup_secret", "rahasia")):
            db.set_app_setting(key, val)
        self.db, self.backup = db, backup
        self.ember = EmberPalsu()
        patch = mock.patch.object(s3, "request", self.ember.request)
        patch.start()
        self.addCleanup(patch.stop)

    def tearDown(self):
        self.db.set_book("")
        self.db.DB_PATH = self._orig
        self.db._ready.clear(); self.db._system_ready.clear()
        self.tmp.cleanup()

    def test_cadangan_terkirim_dan_tercatat(self):
        ok, err = self.backup.run()
        self.assertTrue(ok, err)
        self.assertEqual(len(self.ember.objects), 1)
        key = next(iter(self.ember.objects))
        self.assertTrue(key.startswith("monetary/") and key.endswith(".tar.gz"))
        st = self.backup.status()
        self.assertTrue(st["ok"])
        self.assertGreater(st["size"], 0)
        self.assertEqual(st["books"], 2)                 # system + buku pemilik
        self.assertEqual(st["error"], "")

    def test_isi_yang_terkirim_memang_arsip_utuh(self):
        self.backup.run()
        blob = next(iter(self.ember.objects.values()))
        with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
            self.assertIn("system.db", tar.getnames())

    def test_arsip_lama_dipangkas(self):
        self.db.set_app_setting("backup_keep", "5")
        for i in range(20):
            self.ember.objects[f"monetary/monetary-202601{i:02d}-0300.tar.gz"] = b"lama"
        ok, _ = self.backup.run()
        self.assertTrue(ok)
        self.assertEqual(len(self.ember.objects), 5)
        sisa = sorted(self.ember.objects)
        self.assertEqual(sisa[-1], max(self.ember.objects))   # yang terbaru selalu selamat

    def test_gagal_unggah_tidak_menghapus_apa_pun(self):
        """Kalau kredensial dicabut, retensi harus diam — jangan sampai arsip
        lama ikut hilang justru saat yang baru tidak berhasil masuk."""
        self.ember.status = 403
        self.ember.objects["monetary/monetary-20260101-0300.tar.gz"] = b"lama"
        ok, err = self.backup.run()
        self.assertFalse(ok)
        self.assertIn("403", err)
        self.assertEqual(len(self.ember.objects), 1)
        self.assertNotIn("DELETE", self.ember.calls)
        self.assertFalse(self.backup.status()["ok"])

    def test_tidak_menumpuk_kalau_masih_jalan(self):
        self.backup._running.acquire()
        self.addCleanup(self.backup._running.release)
        ok, err = self.backup.run()
        self.assertFalse(ok)
        self.assertEqual(err, "already running")

    def test_berhasil_menunda_jadwal_berikutnya(self):
        self.assertTrue(self.backup.due())
        self.backup.run()
        self.assertFalse(self.backup.due())


class RuteSetelan(unittest.TestCase):
    def test_form_penyimpanan_sudah_tidak_ada(self):
        """Kunci penyimpanan tidak boleh bisa diketik lewat antarmuka: system.db
        ikut masuk ke dalam arsip yang ditulisnya."""
        from app.main import app
        jalur = {r.path for r in app.routes}
        self.assertNotIn("/settings/backup", jalur)
        self.assertIn("/settings/backup/run", jalur)


if __name__ == "__main__":
    unittest.main()
