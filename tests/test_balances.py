"""Aturan uang: transfer bukan belanja, saldo selalu turunan dari transaksi."""
import unittest

from app.db import balance_upto
from tests.helpers import acc, add, make_db


class Saldo(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.addCleanup(self.db.close)

    def test_pemasukan_menambah_kas(self):
        add(self.db, "2026-01", "income", 10_000_000, "Kas", category="Gaji")
        self.assertEqual(balance_upto(self.db, "2026-01"), 10_000_000)

    def test_pengeluaran_mengurangi_kas(self):
        add(self.db, "2026-01", "income", 10_000_000, "Kas", category="Gaji")
        add(self.db, "2026-01", "expense", 3_000_000, "Kas", category="Belanja")
        self.assertEqual(balance_upto(self.db, "2026-01"), 7_000_000)

    def test_transfer_ke_tabungan_memindah_bukan_menghabiskan(self):
        add(self.db, "2026-01", "income", 10_000_000, "Kas", category="Gaji")
        add(self.db, "2026-01", "transfer", 4_000_000, "Kas", to_account="Dana Darurat")
        self.assertEqual(balance_upto(self.db, "2026-01"), 6_000_000)
        self.assertEqual(balance_upto(self.db, "2026-01", ("savings",)), 4_000_000)

    def test_transfer_antar_kantong_sejenis_tidak_mengubah_total(self):
        db = make_db((("Kas", "cash", 5_000_000), ("BCA", "cash", 0), ("Dana Darurat", "savings", 0)))
        self.addCleanup(db.close)
        add(db, "2026-01", "transfer", 2_000_000, "Kas", to_account="BCA")
        self.assertEqual(balance_upto(db, "2026-01"), 5_000_000)

    def test_saldo_awal_ikut_dihitung(self):
        db = make_db((("Kas", "cash", 1_500_000), ("Dana Darurat", "savings", 0)))
        self.addCleanup(db.close)
        self.assertEqual(balance_upto(db, "2026-01"), 1_500_000)

    def test_saldo_kumulatif_sampai_bulan_yang_diminta(self):
        add(self.db, "2026-01", "income", 10_000_000, "Kas", category="Gaji")
        add(self.db, "2026-02", "expense", 2_000_000, "Kas", category="Belanja")
        self.assertEqual(balance_upto(self.db, "2026-01"), 10_000_000)
        self.assertEqual(balance_upto(self.db, "2026-02"), 8_000_000)

    def test_transaksi_terhapus_tidak_ikut(self):
        tid = add(self.db, "2026-01", "income", 10_000_000, "Kas", category="Gaji")
        add(self.db, "2026-01", "expense", 1_000_000, "Kas", category="Belanja")
        self.db.execute("UPDATE transactions SET deleted_at=datetime('now') WHERE id=?", (tid,))
        self.assertEqual(balance_upto(self.db, "2026-01"), -1_000_000)

    def test_skema_menolak_transfer_ke_kantong_sendiri(self):
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO transactions(month_key,type,amount,account_id,to_account_id)"
                            " VALUES ('2026-01','transfer',1000,?,?)", (acc(self.db, "Kas"), acc(self.db, "Kas")))

    def test_skema_menolak_transfer_berkategori(self):
        import sqlite3
        from tests.helpers import cat
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO transactions(month_key,type,amount,account_id,to_account_id,category_id)"
                            " VALUES ('2026-01','transfer',1000,?,?,?)",
                            (acc(self.db, "Kas"), acc(self.db, "Dana Darurat"), cat(self.db, "Belanja")))


if __name__ == "__main__":
    unittest.main()
