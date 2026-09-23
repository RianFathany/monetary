"""Pemisahan data antar pengguna: satu file buku per orang."""
import tempfile
import unittest
from pathlib import Path


class TestBukuTerpisah(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        from app import db
        self._orig = db.DB_PATH
        db.DB_PATH = str(base / "monetary.db")     # data_dir()/books_dir()/system_path() ikut pindah
        from app import users
        self.db, self.users = db, users
        db.init_book(db.DB_PATH)
        db.init_system()
        db.set_book("")

    def tearDown(self):
        self.db.set_book("")
        self.db.DB_PATH = self._orig
        self.tmp.cleanup()

    def _tx(self, note, amount):
        with self.db.get_db() as c:
            acc = c.execute("SELECT id FROM accounts LIMIT 1").fetchone()["id"]
            c.execute("INSERT INTO transactions(ledger_id, type, amount, month_key, account_id, description) "
                      "VALUES (1,'expense',?, '2026-09', ?, ?)", (amount, acc, note))

    def _notes(self):
        with self.db.get_db() as c:
            return [r["description"] for r in c.execute("SELECT description FROM transactions")]

    def test_pendaftar_baru_dapat_buku_kosong(self):
        u = self.users.create("orang@gmail.com", "Orang")
        self.assertTrue(Path(self.users.path_for(u)).exists())
        self.db.set_book(self.users.path_for(u))
        self.assertEqual(self._notes(), [])
        with self.db.get_db() as c:                     # tapi template bawaan terisi
            self.assertGreater(c.execute("SELECT COUNT(*) c FROM categories").fetchone()["c"], 0)
            self.assertGreater(c.execute("SELECT COUNT(*) c FROM accounts").fetchone()["c"], 0)

    def test_data_tidak_tercampur(self):
        self._tx("punya pemilik", 100)                  # buku pemilik
        u = self.users.create("orang@gmail.com")
        self.db.set_book(self.users.path_for(u))
        self._tx("punya orang lain", 200)
        self.assertEqual(self._notes(), ["punya orang lain"])
        self.db.set_book("")                            # kembali ke buku pemilik
        self.assertEqual(self._notes(), ["punya pemilik"])

    def test_email_di_daftar_izin_menempel_ke_buku_pemilik(self):
        u = self.users.claim_owner("saya@gmail.com", "Saya")
        self.assertEqual(Path(self.users.path_for(u)).name, "monetary.db")
        self.assertTrue(u["is_owner"])

    def test_setiap_pendaftar_dapat_file_berbeda(self):
        a = self.users.create("a@gmail.com")
        b = self.users.create("b@gmail.com")
        self.assertNotEqual(self.users.path_for(a), self.users.path_for(b))

    def test_pengguna_nonaktif(self):
        u = self.users.create("orang@gmail.com")
        self.users.set_active(u["id"], False)
        self.assertEqual(self.users.by_email("orang@gmail.com")["active"], 0)

    def test_pemilik_tidak_bisa_dinonaktifkan(self):
        o = self.users.owner()
        self.users.set_active(o["id"], False)
        self.assertEqual(self.users.owner()["active"], 1)

    def test_setelan_aplikasi_di_system_db(self):
        self.db.set_app_setting("password_hash", "xxx")
        self.db.set_book(self.users.path_for(self.users.create("c@gmail.com")))
        self.assertEqual(self.db.get_app_setting("password_hash"), "xxx")   # tetap terbaca dari buku mana pun


if __name__ == "__main__":
    unittest.main()


class TestIndeksDipakai(unittest.TestCase):
    """Query halaman bulan harus memakai indeks, bukan memindai seluruh tabel."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        from app import db
        self._orig = db.DB_PATH
        db.DB_PATH = str(Path(self.tmp.name) / "monetary.db")
        db.init_book(db.DB_PATH)
        self.db = db

    def tearDown(self):
        self.db.DB_PATH = self._orig
        self.tmp.cleanup()

    def plan(self, sql, args=()):
        with self.db.get_db() as c:
            return " ".join(r["detail"] for r in c.execute("EXPLAIN QUERY PLAN " + sql, args))

    def test_ringkasan_bulan_pakai_indeks(self):
        p = self.plan("SELECT SUM(amount) FROM transactions WHERE deleted_at IS NULL AND month_key=? "
                      "AND type='expense'", ("2026-09",))
        self.assertIn("idx_tx_month", p)
        self.assertNotIn("SCAN transactions", p)

    def test_daftar_bulan_pakai_indeks(self):
        p = self.plan("SELECT * FROM transactions WHERE deleted_at IS NULL AND month_key=?", ("2026-09",))
        self.assertIn("idx_tx_month", p)

    def test_perapihan_pakai_indeks(self):
        p = self.plan("SELECT * FROM transactions WHERE deleted_at IS NULL AND needs_review=1 AND month_key=?",
                      ("2026-09",))
        self.assertIn("idx_tx", p)


class TestPembaruanSkema(unittest.TestCase):
    """Update aplikasi harus sampai ke buku SEMUA pengguna, bukan hanya pemilik."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        from app import db, schema, users
        self._orig = db.DB_PATH
        db.DB_PATH = str(Path(self.tmp.name) / "monetary.db")
        db._ready.clear()
        db._system_ready.clear()
        db.init_book(db.DB_PATH)
        db.init_system()
        self.db, self.schema, self.users = db, schema, users

    def tearDown(self):
        self.db.set_book("")
        self.db.DB_PATH = self._orig
        self.db._ready.clear()
        self.db._system_ready.clear()
        self.tmp.cleanup()

    def _make_old(self, path):
        """Turunkan satu buku ke keadaan 'versi lama': tanpa indeks baru, versi tertinggal."""
        with self.db.get_db(path) as c:
            c.execute("DROP INDEX IF EXISTS idx_tx_month")
            c.execute("UPDATE settings SET value='1' WHERE key='schema_version'")
        self.db._ready.discard(path)

    def test_buku_pengguna_lain_ikut_naik_versi(self):
        u = self.users.create("orang@gmail.com")
        book = self.users.path_for(u)
        self._make_old(book)
        self._make_old(self.db.DB_PATH)

        naik = self.db.upgrade_all_books()
        self.assertEqual(len(naik), 2)                       # pemilik + pengguna
        for path in (self.db.DB_PATH, book):
            with self.db.get_db(path) as c:
                self.assertEqual(self.schema.book_version(c), self.schema.SCHEMA_VERSION)
                idx = {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index'")}
                self.assertIn("idx_tx_month", idx)

    def test_migrasi_kolom_baru_sampai_ke_semua_buku(self):
        """Simulasi rilis berikutnya: kolom baru di MIGRATIONS harus ada di tiap buku."""
        u = self.users.create("orang@gmail.com")
        book = self.users.path_for(u)
        self.schema.MIGRATIONS[self.schema.SCHEMA_VERSION + 1] = [
            "ALTER TABLE transactions ADD COLUMN catatan_uji TEXT"]
        real_version = self.schema.SCHEMA_VERSION
        try:
            self.schema.SCHEMA_VERSION += 1
            self.db.SCHEMA_VERSION = self.schema.SCHEMA_VERSION
            self.db._ready.clear()
            self.db.upgrade_all_books()
            for path in (self.db.DB_PATH, book):
                with self.db.get_db(path) as c:
                    cols = {r["name"] for r in c.execute("PRAGMA table_info(transactions)")}
                    self.assertIn("catatan_uji", cols, path)
        finally:
            self.schema.MIGRATIONS.pop(real_version + 1, None)
            self.schema.SCHEMA_VERSION = real_version
            self.db.SCHEMA_VERSION = real_version

    def test_membuka_buku_lama_langsung_memperbaikinya(self):
        """Tanpa restart pun: begitu buku dibuka, versinya dinaikkan."""
        u = self.users.create("orang@gmail.com")
        book = self.users.path_for(u)
        self._make_old(book)
        self.db.set_book(book)                               # seperti middleware saat ada permintaan
        with self.db.get_db(book) as c:
            self.assertEqual(self.schema.book_version(c), self.schema.SCHEMA_VERSION)

    def test_pemeriksaan_versi_hanya_sekali_per_proses(self):
        u = self.users.create("orang@gmail.com")
        book = self.users.path_for(u)
        self.db.set_book(book)
        self.assertIn(book, self.db._ready)


class TestHapusAkun(unittest.TestCase):
    """Pengguna boleh menghapus akunnya sendiri; pemilik tidak."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        from app import db, users
        self._orig = db.DB_PATH
        db.DB_PATH = str(Path(self.tmp.name) / "monetary.db")
        db._ready.clear(); db._system_ready.clear()
        db.init_book(db.DB_PATH); db.init_system()
        self.db, self.users = db, users

    def tearDown(self):
        self.db.set_book("")
        self.db.DB_PATH = self._orig
        self.db._ready.clear(); self.db._system_ready.clear()
        self.tmp.cleanup()

    def test_hapus_akun_ikut_menghapus_bukunya(self):
        u = self.users.create("orang@gmail.com")
        book = Path(self.users.path_for(u))
        self.assertTrue(book.exists())
        self.assertTrue(self.users.delete(u["id"]))
        self.assertFalse(book.exists())
        self.assertIsNone(self.users.by_email("orang@gmail.com"))

    def test_buku_pengguna_lain_tidak_ikut_terhapus(self):
        a = self.users.create("a@gmail.com")
        b = self.users.create("b@gmail.com")
        self.users.delete(a["id"])
        self.assertTrue(Path(self.users.path_for(b)).exists())
        self.assertTrue(Path(self.db.DB_PATH).exists())

    def test_pemilik_tidak_bisa_dihapus(self):
        o = self.users.owner()
        self.assertFalse(self.users.delete(o["id"]))
        self.assertTrue(Path(self.db.DB_PATH).exists())
        self.assertIsNotNone(self.users.owner())


class TestDaftarEmailPassword(unittest.TestCase):
    """Pendaftaran tanpa Google: akun + buku sendiri, dan aturan pengambilalihan
    saat kelak email yang sama dibuktikan lewat Google."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        from app import auth, db, users
        self._orig = db.DB_PATH
        db.DB_PATH = str(Path(self.tmp.name) / "monetary.db")
        db._ready.clear(); db._system_ready.clear()
        db.init_book(db.DB_PATH); db.init_system()
        self.db, self.users, self.auth = db, users, auth

    def tearDown(self):
        self.db.set_book("")
        self.db.DB_PATH = self._orig
        self.db._ready.clear(); self.db._system_ready.clear()
        self.tmp.cleanup()

    def test_email_divalidasi(self):
        self.assertTrue(self.users.valid_email("a@b.co"))
        for bad in ("", "a@b", "a b@c.com", "tanpa-at.com", "a@@b.com"):
            self.assertFalse(self.users.valid_email(bad), bad)

    def test_daftar_membuat_akun_dan_buku(self):
        u = self.users.create("baru@mail.com", "Baru", password_hash=self.auth.make_hash("rahasia123"))
        self.assertTrue(Path(self.users.path_for(u)).exists())
        self.assertEqual(u["email_verified"], 0)
        self.assertTrue(self.auth.check_hash("rahasia123", u["password_hash"]))
        self.assertFalse(self.auth.check_hash("salah", u["password_hash"]))

    def test_google_mengambil_alih_akun_email_yang_belum_terbukti(self):
        """Orang yang mendaftar memakai email orang lain kehilangan aksesnya begitu
        pemilik email sebenarnya masuk lewat Google."""
        u = self.users.create("korban@mail.com", password_hash=self.auth.make_hash("passwordpenipu"))
        self.users.mark_verified(u["id"], clear_password=True)
        u2 = self.users.by_email("korban@mail.com")
        self.assertEqual(u2["email_verified"], 1)
        self.assertIsNone(u2["password_hash"])
        self.assertGreater(u2["session_epoch"], u["session_epoch"])   # sesi lamanya dicabut

    def test_ganti_password_mencabut_sesi_lama(self):
        u = self.users.create("orang@mail.com", password_hash=self.auth.make_hash("lama12345"))
        self.users.set_password(u["id"], self.auth.make_hash("baru12345"))
        self.assertEqual(self.users.epoch(u["id"]), u["session_epoch"] + 1)

    def test_akun_google_tanpa_password(self):
        u = self.users.create("sso@mail.com", email_verified=True)
        self.assertIsNone(u["password_hash"])
        self.assertEqual(u["email_verified"], 1)


class TestSuperadmin(unittest.TestCase):
    """Hanya satu email yang boleh memegang buku utama; sisanya pengguna biasa."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        from app import db, users
        self._orig = db.DB_PATH
        db.DB_PATH = str(Path(self.tmp.name) / "monetary.db")
        db._ready.clear(); db._system_ready.clear()
        db.init_book(db.DB_PATH); db.init_system()
        self.db, self.users = db, users
        db.set_app_setting("owner_email", "bos@gmail.com")

    def tearDown(self):
        self.db.set_book("")
        self.db.DB_PATH = self._orig
        self.db._ready.clear(); self.db._system_ready.clear()
        self.tmp.cleanup()

    def test_email_superadmin_memegang_buku_utama(self):
        u = self.users.claim_owner("bos@gmail.com", "Bos")
        self.assertTrue(u["is_owner"])
        self.assertEqual(Path(self.users.path_for(u)).name, "monetary.db")

    def test_email_lain_di_daftar_izin_bukan_superadmin(self):
        lain = self.users.claim_owner("pasangan@gmail.com", "Pasangan")
        self.assertFalse(lain["is_owner"])
        self.assertEqual(Path(self.users.path_for(lain)).name, "monetary.db")   # buku sama
        self.assertEqual(self.users.owner()["email"], "owner")                  # kursi pemilik tetap kosong

    def test_superadmin_tetap_dia_meski_orang_lain_masuk_duluan(self):
        self.users.claim_owner("pasangan@gmail.com")
        u = self.users.claim_owner("bos@gmail.com")
        self.assertTrue(u["is_owner"])

    def test_batas_jumlah_akun_menutup_pendaftaran(self):
        self.db.set_app_setting("max_users", "2")
        self.assertTrue(self.users.signup_open())          # baru pemilik
        self.users.create("a@mail.com")
        self.assertFalse(self.users.signup_open())         # sudah 2 akun
        self.db.set_app_setting("max_users", "10")
        self.assertTrue(self.users.signup_open())

    def test_sakelar_pendaftaran_tetap_berlaku(self):
        self.db.set_app_setting("allow_signup", "0")
        self.assertFalse(self.users.signup_open())
