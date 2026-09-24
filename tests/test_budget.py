"""Anggaran: sisa jatah, kategori jebol, dan pengeluaran di luar anggaran."""
import unittest

from app import budget
from app.money import SCALE
from tests.helpers import add, cat, make_db


class TestAnggaran(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.addCleanup(self.db.close)
        self.makan = cat(self.db, "Makan & Minum")
        self.transport = cat(self.db, "Transport")

    def belanja(self, kategori, jumlah, bulan="2026-09"):
        # add() di helpers sudah mengubah rupiah ke satuan simpan; mengalikan
        # lagi di sini membuat angkanya seratus kali lipat.
        add(self.db, bulan, "expense", jumlah, "Kas", category=kategori)

    def test_tanpa_anggaran_semua_kategori_tetap_muncul(self):
        """Yang belum diatur harus kelihatan, bukan hilang dari daftar."""
        baris = budget.untuk_bulan(self.db, "2026-09")
        self.assertGreater(len(baris), 5)
        self.assertTrue(all(not b["diatur"] for b in baris))

    def test_sisa_jatah(self):
        budget.simpan(self.db, "2026-09", {self.makan: 2_000_000 * SCALE})
        self.belanja("Makan & Minum", 750_000)
        b = [x for x in budget.untuk_bulan(self.db, "2026-09") if x["id"] == self.makan][0]
        self.assertEqual(b["terpakai"], 750_000 * SCALE)
        self.assertEqual(b["sisa"], 1_250_000 * SCALE)
        self.assertEqual(b["persen"], 38)
        self.assertFalse(b["lewat"])

    def test_jebol_ditandai(self):
        budget.simpan(self.db, "2026-09", {self.transport: 500_000 * SCALE})
        self.belanja("Transport", 650_000)
        b = [x for x in budget.untuk_bulan(self.db, "2026-09") if x["id"] == self.transport][0]
        self.assertTrue(b["lewat"])
        self.assertEqual(b["sisa"], -150_000 * SCALE)

    def test_bulan_lain_tidak_ikut_terhitung(self):
        budget.simpan(self.db, "2026-09", {self.makan: 1_000_000 * SCALE})
        self.belanja("Makan & Minum", 900_000, bulan="2026-08")
        b = [x for x in budget.untuk_bulan(self.db, "2026-09") if x["id"] == self.makan][0]
        self.assertEqual(b["terpakai"], 0)

    def test_pengeluaran_di_luar_anggaran_tidak_disembunyikan(self):
        """Menyembunyikannya membuat sisa anggaran terlihat lebih lega dari
        kenyataan — kebohongan yang paling mahal di aplikasi keuangan."""
        budget.simpan(self.db, "2026-09", {self.makan: 1_000_000 * SCALE})
        self.belanja("Makan & Minum", 200_000)
        self.belanja("Transport", 300_000)
        r = budget.ringkas(self.db, "2026-09")
        self.assertEqual(r["terpakai"], 200_000 * SCALE)
        self.assertEqual(r["di_luar"], 300_000 * SCALE)

    def test_nol_berarti_tidak_dianggarkan(self):
        budget.simpan(self.db, "2026-09", {self.makan: 500_000 * SCALE})
        budget.simpan(self.db, "2026-09", {self.makan: 0})
        self.assertFalse(budget.ringkas(self.db, "2026-09")["ada"])

    def test_salin_dari_bulan_lain(self):
        budget.simpan(self.db, "2026-08", {self.makan: 1_500_000 * SCALE,
                                           self.transport: 400_000 * SCALE})
        budget.salin(self.db, "2026-08", "2026-09")
        r = budget.ringkas(self.db, "2026-09")
        self.assertEqual(r["jumlah"], 2)
        self.assertEqual(r["rencana"], 1_900_000 * SCALE)

    def test_salin_menimpa_yang_sudah_ada(self):
        budget.simpan(self.db, "2026-08", {self.makan: 1_000_000 * SCALE})
        budget.simpan(self.db, "2026-09", {self.makan: 9_000_000 * SCALE})
        budget.salin(self.db, "2026-08", "2026-09")
        self.assertEqual(budget.ringkas(self.db, "2026-09")["rencana"], 1_000_000 * SCALE)

    def test_bulan_terdekat_untuk_tombol_salin(self):
        budget.simpan(self.db, "2026-07", {self.makan: 1000})
        budget.simpan(self.db, "2026-08", {self.makan: 2000})
        self.assertEqual(budget.bulan_terdekat(self.db, "2026-09"), "2026-08")
        self.assertEqual(budget.bulan_terdekat(self.db, "2026-07"), "")

    def test_definisinya_sama_dengan_laporan(self):
        """Dua tempat yang menghitung hal sama dengan cara berbeda pada akhirnya
        selalu berselisih, dan pemiliknya yang kena getahnya."""
        from app import report
        budget.simpan(self.db, "2026-09", {self.makan: 5_000_000 * SCALE})
        self.belanja("Makan & Minum", 1_234_000)
        m = report.build_metrics(self.db, "2026-09")
        dari_laporan = [c for c in m["categories"] if c["name"] == "Makan & Minum"][0]["value"]
        dari_anggaran = budget.terpakai(self.db, "2026-09")[self.makan]
        self.assertEqual(dari_laporan, dari_anggaran)


if __name__ == "__main__":
    unittest.main()
