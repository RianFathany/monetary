"""Konversi bentuk lama ke skema v2.

Yang dikunci di sini bukan cuma pemetaan kategori, tapi hal yang paling mudah
salah: satu kejadian yang di spreadsheet tercatat dua kali (di kolom kas dan di
kolom dana darurat) tidak boleh dihitung dua kali.
"""
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

V1 = """
CREATE TABLE categories (id INTEGER PRIMARY KEY, name TEXT, kind TEXT, sort INTEGER DEFAULT 100,
                         active INTEGER DEFAULT 1, UNIQUE(name, kind));
CREATE TABLE transactions (id INTEGER PRIMARY KEY, month_key TEXT, kind TEXT, tx_date TEXT,
                           category_id INTEGER, description TEXT, amount INTEGER,
                           status TEXT DEFAULT 'paid', to_fund INTEGER DEFAULT 0);
CREATE TABLE emergency_fund (id INTEGER PRIMARY KEY, month_key TEXT, tx_date TEXT, description TEXT,
                             amount INTEGER, linked_tx_id INTEGER);
CREATE TABLE assets (id INTEGER PRIMARY KEY, month_key TEXT, category TEXT, symbol TEXT, amount INTEGER,
                     UNIQUE(month_key, category, symbol));
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
"""


def build_v1(path, transactions, fund_rows, opening_cash=0, opening_fund=0, assets=()):
    db = sqlite3.connect(path)
    db.executescript(V1)
    cats = {}
    for _, kind, name, _ in transactions:
        if name not in cats:
            db.execute("INSERT OR IGNORE INTO categories(name, kind) VALUES (?,?)", (name, kind))
            cats[name] = db.execute("SELECT id FROM categories WHERE name=? AND kind=?", (name, kind)).fetchone()[0]
    for month, kind, name, amount in transactions:
        db.execute("INSERT INTO transactions(month_key, kind, category_id, description, amount) VALUES (?,?,?,?,?)",
                   (month, kind, cats[name], name, amount))
    for month, desc, amount in fund_rows:
        db.execute("INSERT INTO emergency_fund(month_key, description, amount) VALUES (?,?,?)", (month, desc, amount))
    for month, cat, sym, amt in assets:
        db.execute("INSERT INTO assets(month_key, category, symbol, amount) VALUES (?,?,?,?)", (month, cat, sym, amt))
    for k, v in (("opening_balance", opening_cash), ("opening_emergency", opening_fund), ("first_month", "2025-11")):
        db.execute("INSERT INTO settings(key, value) VALUES (?,?)", (k, str(v)))
    db.commit()
    db.close()


def migrate(src, dst):
    out = subprocess.run([sys.executable, "scripts/migrate_v2.py", "--src", str(src), "--dst", str(dst), "--apply"],
                         cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    db = sqlite3.connect(dst)
    db.row_factory = sqlite3.Row
    return db, out.stdout


class Migrasi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = Path(self.tmp.name) / "v1.db"
        self.dst = Path(self.tmp.name) / "v2.db"

    def tearDown(self):
        self.tmp.cleanup()

    def total(self, db, type_):
        return db.execute("SELECT COALESCE(SUM(amount),0) v FROM transactions WHERE type=?", (type_,)).fetchone()["v"]

    def saldo(self, db, type_):
        return db.execute("SELECT COALESCE(SUM(balance),0) v FROM account_balances WHERE type=?",
                          (type_,)).fetchone()["v"]

    def test_setoran_tabungan_jadi_transfer_bukan_belanja(self):
        build_v1(self.src,
                 [("2025-11", "income", "GAJI", 20_000_000), ("2025-11", "expense", "TABUNGAN", 5_000_000)],
                 [("2025-11", "tabungan", 5_000_000)])
        db, _ = migrate(self.src, self.dst)
        self.addCleanup(db.close)
        self.assertEqual(self.total(db, "expense"), 0)
        self.assertEqual(self.total(db, "transfer"), 5_000_000)

    def test_pasangan_kas_dan_dana_darurat_tidak_dihitung_dua_kali(self):
        build_v1(self.src,
                 [("2025-11", "income", "GAJI", 20_000_000), ("2025-11", "expense", "TABUNGAN", 5_000_000)],
                 [("2025-11", "tabungan", 5_000_000)])
        db, _ = migrate(self.src, self.dst)
        self.addCleanup(db.close)
        self.assertEqual(self.saldo(db, "savings"), 5_000_000, "bukan 10 juta")
        self.assertEqual(self.saldo(db, "cash"), 15_000_000)

    def test_satu_setoran_yang_dipecah_beberapa_baris_ikut_digabung(self):
        build_v1(self.src,
                 [("2025-11", "income", "GAJI", 30_000_000), ("2025-11", "expense", "TABUNGAN", 12_000_000)],
                 [("2025-11", "setoran awal", 10_000_000), ("2025-11", "titipan", 2_000_000)])
        db, _ = migrate(self.src, self.dst)
        self.addCleanup(db.close)
        self.assertEqual(self.saldo(db, "savings"), 12_000_000, "10 + 2 juta adalah rincian dari satu setoran 12 juta")

    def test_pemasukan_dari_dana_darurat_jadi_transfer(self):
        build_v1(self.src,
                 [("2025-11", "income", "GAJI", 10_000_000), ("2025-11", "income", "dari dana darurat", 4_000_000)],
                 [("2025-11", "support operasional", -4_000_000)], opening_fund=10_000_000)
        db, _ = migrate(self.src, self.dst)
        self.addCleanup(db.close)
        self.assertEqual(self.total(db, "income"), 10_000_000, "tarikan dana darurat bukan penghasilan")
        self.assertEqual(self.saldo(db, "savings"), 6_000_000)

    def test_tagihan_kartu_tetap_pengeluaran(self):
        build_v1(self.src, [("2025-11", "expense", "MEGA", 3_000_000), ("2025-11", "expense", "KPR", 11_000_000)], [])
        db, _ = migrate(self.src, self.dst)
        self.addCleanup(db.close)
        self.assertEqual(self.total(db, "expense"), 14_000_000)
        names = {r["name"] for r in db.execute(
            "SELECT c.name FROM transactions t JOIN categories c ON c.id=t.category_id")}
        self.assertEqual(names, {"Tagihan Kartu", "Cicilan Rumah"})

    def test_pemeriksaan_akhir_cocok_dengan_hitungan_lama(self):
        build_v1(self.src,
                 [("2025-11", "income", "GAJI", 20_000_000), ("2025-11", "expense", "OTHER", 3_000_000),
                  ("2025-11", "expense", "TABUNGAN", 5_000_000), ("2025-12", "expense", "MEGA", 2_000_000)],
                 [("2025-11", "tabungan", 5_000_000), ("2025-12", "mega", -1_000_000)],
                 opening_cash=1_000_000, opening_fund=2_000_000)
        db, out = migrate(self.src, self.dst)
        self.addCleanup(db.close)
        self.assertIn("COCOK", out)
        self.assertNotIn("MELESET", out)
        # kas lama: 1jt + 20jt - (3+5+2)jt = 11jt ; dana darurat: 2jt + 5jt - 1jt = 6jt
        self.assertEqual(self.saldo(db, "cash"), 11_000_000)
        self.assertEqual(self.saldo(db, "savings"), 6_000_000)

    def test_posisi_investasi_awal_jadi_modal_bukan_untung(self):
        build_v1(self.src, [("2025-11", "income", "GAJI", 5_000_000)], [],
                 assets=[("2025-11", "SAHAM", "BBRI", 50_000_000)])
        db, _ = migrate(self.src, self.dst)
        self.addCleanup(db.close)
        saham = db.execute("SELECT opening_balance FROM accounts WHERE name='Saham'").fetchone()["opening_balance"]
        self.assertEqual(saham, 50_000_000)


class TestNaikVersi(unittest.TestCase):
    """Buku lama dapat tabel baru tanpa nominalnya dikalikan ulang.

    Ini persis jebakan yang pernah menggigit: nomor versi naik, migrasinya
    jalan, dan seluruh saldo ikut dikalikan untuk kedua kalinya. Penjaganya
    penanda money_scale, bukan nomor versi — tes ini yang memastikannya.
    """

    def buku_v3(self):
        import sqlite3
        from app import schema
        c = sqlite3.connect(":memory:")
        schema.apply_schema(c)
        schema.seed_defaults(c)
        from app.money import SCALE
        for k, v in (("schema_version", "3"), ("money_scale", str(SCALE))):
            c.execute("INSERT INTO settings(key,value) VALUES (?,?) "
                      "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v))
        return c

    def test_tabel_dokumen_lahir(self):
        from app import schema
        c = self.buku_v3()
        schema.upgrade(c)
        tabel = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for nama in ("documents", "document_rows", "budgets"):
            self.assertIn(nama, tabel)
        self.assertEqual(schema.book_version(c), schema.SCHEMA_VERSION)

    def test_nominal_tidak_dikalikan_dua_kali(self):
        from app import schema
        from app.money import SCALE
        c = self.buku_v3()
        c.execute("INSERT INTO accounts(name,type,opening_balance,sort) VALUES ('Kas','cash',?,10)",
                  (1_000_000 * SCALE,))
        schema.upgrade(c)
        saldo = c.execute("SELECT opening_balance FROM accounts WHERE name='Kas'").fetchone()[0]
        self.assertEqual(saldo, 1_000_000 * SCALE)

    def test_tanpa_penanda_skala_nominal_justru_dikalikan(self):
        """Sisi lain dari penjaga yang sama: buku tanpa penanda memang harus
        dikalikan, karena artinya dia belum pernah dinaikkan ke satuan
        perseratus. Yang berbahaya bukan mengalikan, tapi mengalikan dua kali."""
        import sqlite3
        from app import schema
        from app.money import SCALE
        c = sqlite3.connect(":memory:")
        schema.apply_schema(c)
        schema.seed_defaults(c)
        c.execute("DELETE FROM settings WHERE key='money_scale'")
        c.execute("INSERT INTO accounts(name,type,opening_balance,sort) VALUES ('Kas','cash',5000,10)")
        schema.upgrade(c)
        self.assertEqual(c.execute("SELECT opening_balance FROM accounts WHERE name='Kas'").fetchone()[0],
                         5000 * SCALE)

    def test_dijalankan_dua_kali_tetap_aman(self):
        from app import schema
        c = self.buku_v3()
        schema.upgrade(c)
        self.assertEqual(schema.upgrade(c), schema.SCHEMA_VERSION)


class TestBukuPemilikIkutMigrasi(unittest.TestCase):
    """init_db() dulu menulis nomor versi tanpa menjalankan MIGRATIONS.

    Selama migrasinya kebetulan kosong tidak ada yang tahu. Migrasi pertama
    yang berisi SQL sungguhan akan dilewati diam-diam — hanya untuk buku
    pemilik, sementara buku pengguna lain menjalankannya. Dua buku dengan
    nomor versi sama tapi isi berbeda adalah bentuk kerusakan yang paling
    sulit dilacak.
    """

    def setUp(self):
        import tempfile
        from pathlib import Path as P
        from app import db, schema
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.schema = db, schema
        self._path = db.DB_PATH
        db.DB_PATH = str(P(self.tmp.name) / "monetary.db")
        db._ready.clear(); db._system_ready.clear()

        def pulihkan():
            db.set_book("")
            db.DB_PATH = self._path
            db._ready.clear(); db._system_ready.clear()
        self.addCleanup(pulihkan)

    def test_migrasi_berisi_sql_ikut_dijalankan(self):
        """Buku pemilik ikut jalur yang sama dengan buku pengguna lain.

        Dulu nomor versinya ditulis langsung di `init_db` tanpa menjalankan
        MIGRATIONS, jadi migrasi pertama yang berisi SQL akan dilewati diam-diam
        hanya untuk buku ini.
        """
        from unittest import mock
        from app import schema
        baru = schema.SCHEMA_VERSION + 1

        self.db.init_db()                                  # buku baru, versi terbaru
        self.db._ready.clear(); self.db._system_ready.clear()

        asli = dict(schema.MIGRATIONS)
        schema.MIGRATIONS[baru] = ["ALTER TABLE transactions ADD COLUMN penanda_uji TEXT"]
        self.addCleanup(lambda: (schema.MIGRATIONS.clear(), schema.MIGRATIONS.update(asli)))

        with mock.patch.object(schema, "SCHEMA_VERSION", baru):
            self.db.init_db()                              # migrasinya harus ikut jalan
            with self.db.get_db() as conn:
                kolom = {r[1] for r in conn.execute("PRAGMA table_info(transactions)")}
                self.assertEqual(schema.book_version(conn), baru)
        self.assertIn("penanda_uji", kolom)

    def test_migrasi_yang_sudah_jalan_tidak_diulang_walau_versi_dimundurkan(self):
        """Nomor versi bukan lagi yang menentukan. Buku yang daftarnya bilang
        migrasi itu sudah jalan tidak boleh menjalankannya dua kali — kalau
        isinya mengubah data, pengulangan berarti menimpa pilihan pemiliknya."""
        from app import schema
        self.db.init_db()
        with self.db.get_db() as conn:
            conn.execute("UPDATE categories SET is_debt=1 WHERE name='Tagihan Kartu'")
            conn.execute("INSERT INTO settings(key,value) VALUES ('schema_version','5') "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value")
        self.db._ready.clear(); self.db._system_ready.clear()

        self.db.init_db()
        with self.db.get_db() as conn:
            self.assertEqual(conn.execute(
                "SELECT is_debt v FROM categories WHERE name='Tagihan Kartu'").fetchone()["v"], 1)
            self.assertEqual(schema.book_version(conn), schema.SCHEMA_VERSION)

    def test_buku_baru_dapat_kantong_bawaan(self):
        self.db.init_db()
        with self.db.get_db() as conn:
            n = conn.execute("SELECT COUNT(*) c FROM accounts").fetchone()["c"]
        self.assertGreater(n, 0)

    def test_versi_dan_penanda_skala_terpasang(self):
        from app.money import SCALE
        self.db.init_db()
        with self.db.get_db() as conn:
            self.assertEqual(self.schema.book_version(conn), self.schema.SCHEMA_VERSION)
            r = conn.execute("SELECT value FROM settings WHERE key='money_scale'").fetchone()
        self.assertEqual(r["value"], str(SCALE))


if __name__ == "__main__":
    unittest.main()
