"""Dokumen impor: yang dicatat menambah satu pengeluaran, yang tidak, tidak sama sekali."""
import unittest

from app import documents
from app.money import SCALE
from tests.helpers import make_db


def baris(*nilai):
    return [dict(tanggal="2026-09-01", keterangan=f"BELANJA {i}", nilai=n * SCALE, masuk=False)
            for i, n in enumerate(nilai, start=1)]


class TestSimpan(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.addCleanup(self.db.close)

    def total_pengeluaran(self):
        r = self.db.execute("SELECT COALESCE(SUM(amount),0) s FROM transactions "
                            "WHERE type='expense' AND deleted_at IS NULL").fetchone()
        return r["s"]

    def test_dicatat_membuat_satu_pengeluaran(self):
        documents.simpan(self.db, "BNI", "2026-09", "bni.pdf", baris(35_000, 100_000))
        n = self.db.execute("SELECT COUNT(*) c FROM transactions WHERE deleted_at IS NULL").fetchone()["c"]
        self.assertEqual(n, 1)                                  # satu, bukan dua
        self.assertEqual(self.total_pengeluaran(), 135_000 * SCALE)

    def test_pengeluarannya_ditandai_perlu_dicek(self):
        """Impor itu tebakan mesin; pemiliknya harus melihatnya sekali."""
        documents.simpan(self.db, "BNI", "2026-09", "x.pdf", baris(50_000))
        r = self.db.execute("SELECT needs_review, description FROM transactions").fetchone()
        self.assertEqual(r["needs_review"], 1)
        self.assertEqual(r["description"], "BNI")

    def test_analisa_saja_tidak_menambah_apa_pun(self):
        doc = documents.simpan(self.db, "BCA", "2026-09", "koran.pdf", baris(200_000), catat=False)
        self.assertEqual(self.total_pengeluaran(), 0)
        d, rows = documents.ambil(self.db, doc)
        self.assertIsNone(d["tx_id"])
        self.assertEqual(len(rows), 1)                          # rinciannya tetap utuh

    def test_rincian_tersimpan_lengkap(self):
        doc = documents.simpan(self.db, "MEGA", "2026-09", "m.pdf", baris(10_000, 20_000, 30_000))
        _, rows = documents.ambil(self.db, doc)
        self.assertEqual([r["amount"] for r in rows], [10_000 * SCALE, 20_000 * SCALE, 30_000 * SCALE])

    def test_pemasukan_mengurangi_tagihan(self):
        """Pembayaran atau refund di dalam tagihan mengurangi yang harus dibayar."""
        b = baris(100_000)
        b.append(dict(tanggal="2026-09-05", keterangan="PEMBAYARAN", nilai=40_000 * SCALE, masuk=True))
        documents.simpan(self.db, "BNI", "2026-09", "x.pdf", b)
        self.assertEqual(self.total_pengeluaran(), 60_000 * SCALE)

    def test_tagihan_nol_ditolak_kalau_mau_dicatat(self):
        b = [dict(tanggal="2026-09-01", keterangan="A", nilai=10_000 * SCALE, masuk=True)]
        with self.assertRaises(ValueError):
            documents.simpan(self.db, "BNI", "2026-09", "x.pdf", b)

    def test_tanpa_kartu_ditolak(self):
        with self.assertRaises(ValueError):
            documents.simpan(self.db, "  ", "2026-09", "x.pdf", baris(1000))


class TestSaldoKantong(unittest.TestCase):
    """Pengeluaran tanpa account_id muncul di laporan tapi tidak mengurangi
    kantong mana pun — tagihan yang tidak dibayar dari uang siapa-siapa.
    Persis bug yang lolos karena tidak ada tes yang melihat saldo."""

    def setUp(self):
        self.db = make_db()
        self.addCleanup(self.db.close)

    def saldo(self, nama):
        return self.db.execute("SELECT balance FROM account_balances WHERE name=?", (nama,)).fetchone()["balance"]

    def test_saldo_kas_berkurang(self):
        awal = self.saldo("Kas")
        documents.simpan(self.db, "BNI", "2026-09", "x.pdf", baris(135_000))
        self.assertEqual(self.saldo("Kas"), awal - 135_000 * SCALE)

    def test_bisa_dibayar_dari_kantong_lain(self):
        lain = self.db.execute("SELECT id, name FROM accounts WHERE name='Dana Darurat'").fetchone()
        awal_kas, awal_lain = self.saldo("Kas"), self.saldo("Dana Darurat")
        documents.simpan(self.db, "BNI", "2026-09", "x.pdf", baris(50_000), account_id=lain["id"])
        self.assertEqual(self.saldo("Kas"), awal_kas)
        self.assertEqual(self.saldo("Dana Darurat"), awal_lain - 50_000 * SCALE)

    def test_analisa_saja_tidak_menyentuh_saldo(self):
        awal = self.saldo("Kas")
        documents.simpan(self.db, "BCA", "2026-09", "x.pdf", baris(999_000), catat=False)
        self.assertEqual(self.saldo("Kas"), awal)

    def test_hapus_mengembalikan_saldo(self):
        awal = self.saldo("Kas")
        doc = documents.simpan(self.db, "BNI", "2026-09", "x.pdf", baris(70_000))
        documents.hapus(self.db, doc)
        self.assertEqual(self.saldo("Kas"), awal)


class TestHapus(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.addCleanup(self.db.close)

    def test_pengeluarannya_ikut_hilang(self):
        doc = documents.simpan(self.db, "BNI", "2026-09", "x.pdf", baris(75_000))
        documents.hapus(self.db, doc)
        sisa = self.db.execute("SELECT COUNT(*) c FROM transactions WHERE deleted_at IS NULL").fetchone()["c"]
        self.assertEqual(sisa, 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) c FROM document_rows").fetchone()["c"], 0)

    def test_dokumen_analisa_saja_aman_dihapus(self):
        doc = documents.simpan(self.db, "BCA", "2026-09", "x.pdf", baris(1000), catat=False)
        self.assertTrue(documents.hapus(self.db, doc))

    def test_dokumen_tidak_ada(self):
        self.assertFalse(documents.hapus(self.db, 999))


class TestKartuTerpakai(unittest.TestCase):
    """Daftar kartunya datang dari riwayat sendiri, bukan daftar bank karangan."""

    def setUp(self):
        self.db = make_db()
        self.addCleanup(self.db.close)

    def test_dari_transaksi_lama(self):
        kid = documents.kategori_id(self.db)
        for nama in ("BNI", "Kredivo"):
            self.db.execute("INSERT INTO transactions(month_key,type,category_id,description,amount) "
                            "VALUES ('2026-08','expense',?,?,?)", (kid, nama, 1000))
        self.assertEqual(documents.kartu_terpakai(self.db), ["BNI", "Kredivo"])

    def test_dari_dokumen_ikut_muncul(self):
        documents.simpan(self.db, "MEGA", "2026-09", "x.pdf", baris(5000), catat=False)
        self.assertIn("MEGA", documents.kartu_terpakai(self.db))

    def test_tanpa_riwayat_kosong(self):
        self.assertEqual(documents.kartu_terpakai(self.db), [])


class TestDariJson(unittest.TestCase):
    """Isinya datang dari peramban, jadi diperiksa ulang meski ini buku sendiri."""

    def test_baris_wajar(self):
        b = documents.dari_json('[{"tanggal":"2026-09-01","keterangan":"KOPI","nilai":3500000,"masuk":false}]')
        self.assertEqual(len(b), 1)
        self.assertEqual(b[0]["nilai"], 3500000)

    def test_json_rusak_jadi_kosong(self):
        self.assertEqual(documents.dari_json("{bukan json"), [])
        self.assertEqual(documents.dari_json(""), [])

    def test_nilai_nol_atau_minus_dibuang(self):
        self.assertEqual(documents.dari_json('[{"nilai":0},{"nilai":-5}]'), [])

    def test_nilai_bukan_angka_dibuang(self):
        self.assertEqual(documents.dari_json('[{"nilai":"banyak"}]'), [])

    def test_keterangan_dipotong(self):
        b = documents.dari_json('[{"nilai":100,"keterangan":"' + "x" * 500 + '"}]')
        self.assertEqual(len(b[0]["keterangan"]), 200)


if __name__ == "__main__":
    unittest.main()
