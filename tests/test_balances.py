"""Aturan uang: transfer bukan belanja, saldo selalu turunan dari transaksi."""
import unittest

from app.db import (CASH_TYPES, DEBT_TYPES, balance_upto, emergency_fund, emergency_ids,
                    target_view)
from tests.helpers import acc, add, make_db, rp


class Saldo(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.addCleanup(self.db.close)

    def test_pemasukan_menambah_kas(self):
        add(self.db, "2026-01", "income", 10_000_000, "Kas", category="Gaji")
        self.assertEqual(balance_upto(self.db, "2026-01"), rp(10_000_000))

    def test_pengeluaran_mengurangi_kas(self):
        add(self.db, "2026-01", "income", 10_000_000, "Kas", category="Gaji")
        add(self.db, "2026-01", "expense", 3_000_000, "Kas", category="Belanja")
        self.assertEqual(balance_upto(self.db, "2026-01"), rp(7_000_000))

    def test_transfer_ke_tabungan_memindah_bukan_menghabiskan(self):
        add(self.db, "2026-01", "income", 10_000_000, "Kas", category="Gaji")
        add(self.db, "2026-01", "transfer", 4_000_000, "Kas", to_account="Dana Darurat")
        self.assertEqual(balance_upto(self.db, "2026-01"), rp(6_000_000))
        self.assertEqual(balance_upto(self.db, "2026-01", ("savings",)), rp(4_000_000))

    def test_transfer_antar_kantong_sejenis_tidak_mengubah_total(self):
        db = make_db((("Kas", "cash", 5_000_000), ("BCA", "cash", 0), ("Dana Darurat", "savings", 0)))
        self.addCleanup(db.close)
        add(db, "2026-01", "transfer", 2_000_000, "Kas", to_account="BCA")
        self.assertEqual(balance_upto(db, "2026-01"), rp(5_000_000))

    def test_saldo_awal_ikut_dihitung(self):
        db = make_db((("Kas", "cash", 1_500_000), ("Dana Darurat", "savings", 0)))
        self.addCleanup(db.close)
        self.assertEqual(balance_upto(db, "2026-01"), rp(1_500_000))

    def test_saldo_kumulatif_sampai_bulan_yang_diminta(self):
        add(self.db, "2026-01", "income", 10_000_000, "Kas", category="Gaji")
        add(self.db, "2026-02", "expense", 2_000_000, "Kas", category="Belanja")
        self.assertEqual(balance_upto(self.db, "2026-01"), rp(10_000_000))
        self.assertEqual(balance_upto(self.db, "2026-02"), rp(8_000_000))

    def test_transaksi_terhapus_tidak_ikut(self):
        tid = add(self.db, "2026-01", "income", 10_000_000, "Kas", category="Gaji")
        add(self.db, "2026-01", "expense", 1_000_000, "Kas", category="Belanja")
        self.db.execute("UPDATE transactions SET deleted_at=datetime('now') WHERE id=?", (tid,))
        self.assertEqual(balance_upto(self.db, "2026-01"), rp(-1_000_000))

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


class KantongUtang(unittest.TestCase):
    """Kartu kredit & paylater: saldonya negatif saat berutang, dan ikut
    mengurangi kekayaan bersih. Sebelum ini kantongnya bisa dibuat tapi
    diabaikan, jadi angka 'kekayaan bersih' cuma penjumlahan aset."""

    def setUp(self):
        self.db = make_db((("Kas", "cash", 20_000_000), ("Dana Darurat", "savings", 0),
                           ("Kartu BNI", "credit", 0)))
        self.addCleanup(self.db.close)

    def test_belanja_dari_kartu_jadi_utang(self):
        add(self.db, "2026-01", "expense", 3_000_000, "Kartu BNI", category="Belanja")
        self.assertEqual(balance_upto(self.db, "2026-01", DEBT_TYPES), rp(-3_000_000))
        self.assertEqual(balance_upto(self.db, "2026-01", CASH_TYPES), rp(20_000_000),
                         "belanja kartu belum menyentuh kas")

    def test_bayar_tagihan_memindahkan_utang_ke_kas(self):
        add(self.db, "2026-01", "expense", 3_000_000, "Kartu BNI", category="Belanja")
        add(self.db, "2026-02", "transfer", 3_000_000, "Kas", to_account="Kartu BNI")
        self.assertEqual(balance_upto(self.db, "2026-02", DEBT_TYPES), 0)
        self.assertEqual(balance_upto(self.db, "2026-02", CASH_TYPES), rp(17_000_000))

    def test_kekayaan_bersih_dikurangi_utang(self):
        add(self.db, "2026-01", "expense", 3_000_000, "Kartu BNI", category="Belanja")
        aset = balance_upto(self.db, "2026-01", CASH_TYPES) + balance_upto(self.db, "2026-01", ("savings",))
        bersih = aset + balance_upto(self.db, "2026-01", DEBT_TYPES)
        self.assertEqual(aset, rp(20_000_000))
        self.assertEqual(bersih, rp(17_000_000))


class DanaDaruratBertanda(unittest.TestCase):
    """Yang dihitung sebagai ketahanan belanja hanya kantong yang ditandai."""

    def setUp(self):
        self.db = make_db((("Kas", "cash", 0), ("Dana Darurat", "savings", 0),
                           ("Tabungan Liburan", "savings", 0)))
        self.addCleanup(self.db.close)
        add(self.db, "2026-01", "income", 50_000_000, "Kas", category="Gaji")
        add(self.db, "2026-01", "transfer", 10_000_000, "Kas", to_account="Dana Darurat")
        add(self.db, "2026-01", "transfer", 25_000_000, "Kas", to_account="Tabungan Liburan")

    def test_nama_yang_jelas_ditandai_sendiri(self):
        self.assertEqual(emergency_ids(self.db), [acc(self.db, "Dana Darurat")])

    def test_hanya_yang_bertanda_yang_dihitung(self):
        self.assertEqual(emergency_fund(self.db, "2026-01"), rp(10_000_000))
        self.assertEqual(balance_upto(self.db, "2026-01", ("savings",)), rp(35_000_000))

    def test_tanpa_tanda_hasilnya_none_bukan_nol(self):
        """None = belum ditentukan. Nol berarti dana daruratnya habis; dua hal
        yang sangat berbeda kalau ditampilkan ke pemiliknya."""
        self.db.execute("UPDATE accounts SET is_emergency=0")
        self.assertIsNone(emergency_fund(self.db, "2026-01"))

    def test_kantong_nonaktif_tetap_dihitung(self):
        """Uangnya masih ada; yang nonaktif cuma tidak muncul di pilihan input."""
        self.db.execute("UPDATE accounts SET active=0 WHERE name='Dana Darurat'")
        self.assertEqual(emergency_fund(self.db, "2026-01"), rp(10_000_000))


class TargetKantong(unittest.TestCase):
    """Kemajuan menuju target. Fungsinya murni supaya bisa diuji tanpa database —
    yang menentukan `nilai` adalah pemanggilnya, karena kantong investasi diukur
    dari nilai pasar sementara tabungan dari saldonya."""

    def test_tanpa_target_tidak_menghasilkan_apa_apa(self):
        self.assertEqual(target_view(0, rp(5_000_000)), {})
        self.assertEqual(target_view(-1, rp(5_000_000)), {})

    def test_sisa_dan_persen(self):
        t = target_view(rp(20_000_000), rp(15_000_000))
        self.assertEqual(t["sisa"], rp(5_000_000))
        self.assertEqual(t["persen"], 75)
        self.assertFalse(t["tercapai"])

    def test_tercapai_tidak_lewat_seratus_persen(self):
        """Bar yang melewati ujungnya bukan informasi tambahan, cuma rusak."""
        t = target_view(rp(10_000_000), rp(13_000_000))
        self.assertTrue(t["tercapai"])
        self.assertEqual(t["persen"], 100)
        self.assertEqual(t["sisa"], 0)
        self.assertEqual(t["lewat"], 130)

    def test_saldo_negatif_dijepit_ke_nol(self):
        t = target_view(rp(10_000_000), rp(-2_000_000))
        self.assertEqual(t["persen"], 0)
        self.assertEqual(t["sisa"], rp(10_000_000))

    def test_sisa_hari_dihitung_dari_tanggal_target(self):
        t = target_view(rp(10_000_000), rp(1_000_000), "2026-12-31", hari_ini="2026-12-01")
        self.assertEqual(t["sisa_hari"], 30)
        self.assertFalse(t["telat"])

    def test_lewat_tenggat_dan_belum_tercapai_ditandai_telat(self):
        t = target_view(rp(10_000_000), rp(4_000_000), "2026-01-31", hari_ini="2026-03-01")
        self.assertLess(t["sisa_hari"], 0)
        self.assertTrue(t["telat"])

    def test_lewat_tenggat_tapi_sudah_tercapai_bukan_telat(self):
        t = target_view(rp(10_000_000), rp(11_000_000), "2026-01-31", hari_ini="2026-03-01")
        self.assertTrue(t["tercapai"])
        self.assertFalse(t["telat"])

    def test_tanggal_ngawur_diabaikan_bukan_meledak(self):
        t = target_view(rp(10_000_000), rp(1_000_000), "31-12-2026")
        self.assertIsNone(t["sisa_hari"])
        self.assertFalse(t["telat"])


if __name__ == "__main__":
    unittest.main()
