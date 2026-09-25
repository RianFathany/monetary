"""Template rutin yang tidak boleh dobel, dan buku lama yang naik ke skema v6.

Dua hal yang sama-sama cuma ketahuan kalau diuji: tombol "isi bulan ini" ada di
dua halaman dan bisa ditekan berkali-kali, dan buku yang sudah dipakai berbulan-
bulan harus tetap bisa dibuka setelah aplikasinya diperbarui.
"""
import sqlite3
import unittest

from unittest import mock

from app import schema as schemamod
from app.main import fill_from_recurring
from app.schema import SCHEMA_VERSION, book_version, upgrade
from tests.helpers import acc, add, cat, make_db, rp

# Bentuk buku sebelum v6: tanpa accounts.is_emergency dan transactions.recurring_id.
# Sengaja ditulis ulang di sini, bukan diambil dari app.schema, supaya tes ini
# tetap menggambarkan buku lama meski skemanya nanti berubah lagi.
V5 = """
CREATE TABLE ledgers (id INTEGER PRIMARY KEY, name TEXT NOT NULL, currency TEXT NOT NULL DEFAULT 'IDR',
                      created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE accounts (id INTEGER PRIMARY KEY, ledger_id INTEGER NOT NULL DEFAULT 1,
                       name TEXT NOT NULL, type TEXT NOT NULL, opening_balance INTEGER NOT NULL DEFAULT 0,
                       note TEXT, sort INTEGER NOT NULL DEFAULT 100, active INTEGER NOT NULL DEFAULT 1,
                       created_at TEXT NOT NULL DEFAULT (datetime('now')),
                       updated_at TEXT NOT NULL DEFAULT (datetime('now')), deleted_at TEXT,
                       UNIQUE(ledger_id, name));
CREATE TABLE categories (id INTEGER PRIMARY KEY, ledger_id INTEGER NOT NULL DEFAULT 1, name TEXT NOT NULL,
                         kind TEXT NOT NULL, parent_id INTEGER, icon TEXT, color TEXT,
                         is_debt INTEGER NOT NULL DEFAULT 0, is_system INTEGER NOT NULL DEFAULT 0,
                         sort INTEGER NOT NULL DEFAULT 100, active INTEGER NOT NULL DEFAULT 1,
                         created_at TEXT NOT NULL DEFAULT (datetime('now')),
                         updated_at TEXT NOT NULL DEFAULT (datetime('now')), deleted_at TEXT,
                         UNIQUE(ledger_id, name, kind));
CREATE TABLE transactions (id INTEGER PRIMARY KEY, ledger_id INTEGER NOT NULL DEFAULT 1,
                           month_key TEXT NOT NULL, type TEXT NOT NULL, tx_date TEXT, account_id INTEGER,
                           to_account_id INTEGER, category_id INTEGER, description TEXT,
                           amount INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'paid',
                           needs_review INTEGER NOT NULL DEFAULT 0,
                           created_at TEXT NOT NULL DEFAULT (datetime('now')),
                           updated_at TEXT NOT NULL DEFAULT (datetime('now')), deleted_at TEXT);
CREATE TABLE reports (id INTEGER PRIMARY KEY, ledger_id INTEGER NOT NULL DEFAULT 1, month_key TEXT NOT NULL,
                      engine TEXT NOT NULL DEFAULT 'rules', content_json TEXT NOT NULL,
                      generated_at TEXT NOT NULL DEFAULT (datetime('now')), UNIQUE(ledger_id, month_key, engine));
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
INSERT INTO ledgers(id, name) VALUES (1, 'Pribadi');
INSERT INTO settings(key, value) VALUES ('schema_version','5'), ('money_scale','100');
INSERT INTO accounts(name, type, sort) VALUES ('Kas Utama','cash',10), ('Dana Darurat','savings',20),
                                              ('Tabungan Rumah','savings',30);
INSERT INTO categories(name, kind, sort, is_debt) VALUES ('Tagihan Kartu','expense',60,1),
                                                         ('Cicilan Rumah','expense',50,1);
INSERT INTO transactions(month_key, type, account_id, category_id, amount)
       VALUES ('2026-01','expense',1,1,500000);
INSERT INTO reports(month_key, content_json) VALUES ('2026-01','{"lama":true}');
"""


class RutinTidakDobel(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.addCleanup(self.db.close)
        self.db.execute(
            "INSERT INTO recurring(type, account_id, category_id, description, amount, day_of_month)"
            " VALUES ('expense',?,?,'Cicilan Rumah',?,5)",
            (acc(self.db, "Kas"), cat(self.db, "Cicilan Rumah"), rp(5_000_000)))
        self.db.execute(
            "INSERT INTO recurring(type, account_id, category_id, description, amount)"
            " VALUES ('income',?,?,'Gaji',?)",
            (acc(self.db, "Kas"), cat(self.db, "Gaji", "income"), rp(20_000_000)))

    def jumlah(self, mk="2026-03"):
        return self.db.execute("SELECT COUNT(*) c FROM transactions WHERE month_key=? AND deleted_at IS NULL",
                               (mk,)).fetchone()["c"]

    def test_sekali_tekan_mengisi_semua_template(self):
        self.assertEqual(fill_from_recurring(self.db, "2026-03"), 2)
        self.assertEqual(self.jumlah(), 2)

    def test_tekan_dua_kali_tidak_menambah_apa_apa(self):
        fill_from_recurring(self.db, "2026-03")
        self.assertEqual(fill_from_recurring(self.db, "2026-03"), 0)
        self.assertEqual(self.jumlah(), 2)

    def test_nominal_yang_sudah_dibetulkan_tidak_ditimpa(self):
        """Yang dijaga asal-usulnya, bukan kemiripan angka atau deskripsinya."""
        fill_from_recurring(self.db, "2026-03")
        self.db.execute("UPDATE transactions SET amount=?, description='KPR Maret' WHERE month_key='2026-03'",
                        (rp(5_250_000),))
        self.assertEqual(fill_from_recurring(self.db, "2026-03"), 0)
        self.assertEqual(self.jumlah(), 2)

    def test_bulan_lain_tetap_bisa_diisi(self):
        fill_from_recurring(self.db, "2026-03")
        self.assertEqual(fill_from_recurring(self.db, "2026-04"), 2)

    def test_baris_yang_dihapus_boleh_diisi_ulang(self):
        """Hapus lunak berarti pemiliknya memang tidak mau baris itu — tapi kalau
        ia menekan tombolnya lagi, maksudnya jelas: isi ulang."""
        fill_from_recurring(self.db, "2026-03")
        self.db.execute("UPDATE transactions SET deleted_at=datetime('now') WHERE month_key='2026-03'")
        self.assertEqual(fill_from_recurring(self.db, "2026-03"), 2)

    def test_template_nonaktif_dilewati(self):
        self.db.execute("UPDATE recurring SET active=0 WHERE description='Gaji'")
        self.assertEqual(fill_from_recurring(self.db, "2026-03"), 1)

    def test_pengeluaran_masuk_sebagai_belum_dibayar(self):
        fill_from_recurring(self.db, "2026-03")
        status = {r["description"]: r["status"] for r in self.db.execute(
            "SELECT description, status FROM transactions WHERE month_key='2026-03'").fetchall()}
        self.assertEqual(status["Cicilan Rumah"], "planned")
        self.assertEqual(status["Gaji"], "paid")


class BukuLamaNaikKeV6(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.executescript(V5)

    def kolom(self, table):
        return {r[1] for r in self.db.execute(f"PRAGMA table_info({table})").fetchall()}

    def test_versi_naik(self):
        self.assertEqual(book_version(self.db), 5)
        self.assertEqual(upgrade(self.db), SCHEMA_VERSION)

    def test_kolom_baru_ditambahkan_bukan_dibuat_ulang(self):
        upgrade(self.db)
        self.assertIn("is_emergency", self.kolom("accounts"))
        self.assertIn("recurring_id", self.kolom("transactions"))
        self.assertEqual(self.db.execute("SELECT COUNT(*) c FROM transactions").fetchone()["c"], 1,
                         "transaksi lama harus utuh")

    def test_kantong_dana_darurat_ditebak_dari_namanya(self):
        """Buku lama tidak punya penandanya; kalau semua dianggap belum ditentukan,
        indikator yang tadinya jalan mendadak kosong tanpa sebab yang kelihatan."""
        upgrade(self.db)
        tanda = {r["name"]: r["is_emergency"] for r in self.db.execute(
            "SELECT name, is_emergency FROM accounts").fetchall()}
        self.assertEqual(tanda["Dana Darurat"], 1)
        self.assertEqual(tanda["Tabungan Rumah"], 0)
        self.assertEqual(tanda["Kas Utama"], 0)

    def test_tagihan_kartu_keluar_dari_rasio_cicilan(self):
        upgrade(self.db)
        flag = {r["name"]: r["is_debt"] for r in self.db.execute(
            "SELECT name, is_debt FROM categories WHERE kind='expense'").fetchall()}
        self.assertEqual(flag["Tagihan Kartu"], 0)
        self.assertEqual(flag["Cicilan Rumah"], 1, "cicilan tetap tidak ikut diubah")

    def test_laporan_tersimpan_dibuang(self):
        """Indikatornya sudah beda arti; menyisakan yang lama berarti dua versi
        angka untuk bulan yang sama."""
        upgrade(self.db)
        self.assertEqual(self.db.execute("SELECT COUNT(*) c FROM reports").fetchone()["c"], 0)

    def test_dijalankan_dua_kali_tetap_sama(self):
        upgrade(self.db)
        self.db.execute("UPDATE accounts SET is_emergency=0 WHERE name='Dana Darurat'")
        upgrade(self.db)          # sudah versi terbaru: tidak menjalankan migrasi lagi
        self.assertEqual(self.db.execute(
            "SELECT is_emergency v FROM accounts WHERE name='Dana Darurat'").fetchone()["v"], 0,
            "pilihan pemilik sesudah migrasi tidak boleh ditimpa lagi")

    def test_indeks_baru_terbentuk(self):
        upgrade(self.db)
        self.assertTrue(self.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_tx_recur'").fetchone())


class MigrasiDicatatSendiri(unittest.TestCase):
    """Yang dipercaya adalah daftar migrasi yang benar-benar jalan, bukan nomor versi.

    Kejadian nyatanya: `SCHEMA_VERSION` dinaikkan lebih dulu, aplikasi terlanjur
    membuka buku, nomornya tersimpan — lalu isi migrasinya ditulis dan tidak
    pernah jalan karena bukunya sudah "versi terbaru".
    """

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.executescript(V5)

    def daftar(self):
        row = self.db.execute("SELECT value FROM settings WHERE key='migrations_applied'").fetchone()
        return row["value"] if row else None

    # Nomor versi tidak ditulis mentah-mentah di sini: diturunkan dari MIGRATIONS
    # supaya menaikkan skema tidak mematahkan tes yang tidak ada urusannya.
    def test_daftar_ditulis_setelah_migrasi(self):
        upgrade(self.db)
        self.assertIn(str(max(schemamod.MIGRATIONS)), (self.daftar() or "").split(","))

    def test_buku_lama_dipercaya_lewat_nomor_versinya_sekali(self):
        """Buku v5 belum punya daftar: yang <= 5 dianggap sudah, sisanya dijalankan."""
        upgrade(self.db)
        self.assertEqual(self.daftar(), ",".join(str(v) for v in sorted(schemamod.MIGRATIONS)))

    def test_migrasi_yang_terlewat_tetap_dikejar(self):
        """Nomor versi sudah yang terbaru tapi daftarnya bilang migrasi terakhir
        belum jalan — harus tetap dikejar."""
        semua = sorted(schemamod.MIGRATIONS)
        # Migrasi yang dilewatkan dipilih dari isinya, bukan nomornya: yang
        # mengeluarkan Tagihan Kartu dari rasio cicilan, karena efeknya bisa
        # diperiksa. Menuliskan nomornya berarti tes ini patah tiap skema naik.
        kena = next(v for v in semua if any("Tagihan Kartu" in x for x in schemamod.MIGRATIONS[v]))
        self.db.execute("UPDATE settings SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))
        self.db.execute("INSERT INTO settings(key,value) VALUES ('migrations_applied',?)",
                        (",".join(str(v) for v in semua if v != kena),))
        self.assertEqual(book_version(self.db), SCHEMA_VERSION)
        upgrade(self.db)
        self.assertEqual(self.db.execute(
            "SELECT is_debt v FROM categories WHERE name='Tagihan Kartu'").fetchone()["v"], 0)
        self.assertEqual(self.daftar(), ",".join(str(v) for v in semua))

    def test_migrasi_baru_jalan_walau_nomor_versi_sudah_terlanjur_naik(self):
        """Persis kejadian tadi: nomor naik duluan, isinya menyusul kemudian."""
        upgrade(self.db)                                     # buku rapi di versi terbaru
        baru = SCHEMA_VERSION + 1
        dijalankan = []
        with mock.patch.dict(schemamod.MIGRATIONS,
                             {baru: ["UPDATE settings SET value='lewat' WHERE key='ledger_name'"]}):
            with mock.patch.object(schemamod, "SCHEMA_VERSION", baru):
                self.db.execute("UPDATE settings SET value=? WHERE key='schema_version'", (str(baru),))
                upgrade(self.db)                             # nomornya sudah naik, migrasinya belum pernah jalan
                dijalankan = (self.daftar() or "").split(",")
        self.assertIn(str(baru), dijalankan)
        self.assertEqual(self.db.execute(
            "SELECT value v FROM settings WHERE key='ledger_name'").fetchone()["v"], "lewat")

    def test_tidak_menjalankan_ulang_migrasi_yang_sudah_tercatat(self):
        upgrade(self.db)
        self.db.execute("UPDATE categories SET is_debt=1 WHERE name='Tagihan Kartu'")
        upgrade(self.db)
        self.assertEqual(self.db.execute(
            "SELECT is_debt v FROM categories WHERE name='Tagihan Kartu'").fetchone()["v"], 1,
            "pilihan pemilik sesudah migrasi tidak boleh ditimpa")


class TabunganTanpaNamaDaruratTidakDitandai(unittest.TestCase):
    """Buku yang kantong daruratnya bernama lain harus memilih sendiri —
    menebak terlalu jauh sama saja dengan mengarang angka ketahanan belanja."""

    def test_nama_tak_dikenal_dibiarkan_kosong(self):
        db = make_db((("Kas", "cash", 0), ("Jaga-jaga", "savings", 0)))
        self.addCleanup(db.close)
        add(db, "2026-01", "income", 10_000_000, "Kas", category="Gaji")
        self.assertEqual(db.execute("SELECT COUNT(*) c FROM accounts WHERE is_emergency=1").fetchone()["c"], 0)


if __name__ == "__main__":
    unittest.main()
