"""Ringkasan bulan, posisi aset, dan indikator laporan."""
import tempfile
import unittest
from pathlib import Path

from app.db import asset_view
from app.main import month_summary
from app.report import build_metrics, render_rules
from tests.helpers import acc, add, cat, make_db, rp


def snapshot(db, month, account, symbol, amount):
    db.execute("INSERT INTO asset_snapshots(month_key,account_id,symbol,amount) VALUES (?,?,?,?)",
               (month, acc(db, account), symbol, rp(amount)))


class RingkasanBulan(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.addCleanup(self.db.close)
        add(self.db, "2026-01", "income", 20_000_000, "Kas", category="Gaji")
        add(self.db, "2026-01", "expense", 5_000_000, "Kas", category="Belanja")
        add(self.db, "2026-01", "transfer", 6_000_000, "Kas", to_account="Dana Darurat")

    def test_transfer_tidak_masuk_pemasukan_atau_pengeluaran(self):
        s = month_summary(self.db, "2026-01")
        self.assertEqual(s["income"], rp(20_000_000))
        self.assertEqual(s["expense"], rp(5_000_000))

    def test_yang_ditabung_dihitung_bersih(self):
        add(self.db, "2026-01", "transfer", 1_000_000, "Dana Darurat", to_account="Kas")
        s = month_summary(self.db, "2026-01")
        self.assertEqual(s["saved"], rp(5_000_000))

    def test_tagihan_belum_dibayar_terhitung_terpisah(self):
        add(self.db, "2026-01", "expense", 2_000_000, "Kas", category="Belanja", status="planned")
        s = month_summary(self.db, "2026-01")
        self.assertEqual(s["unpaid"], rp(2_000_000))
        self.assertEqual(s["expense"], rp(7_000_000), "yang belum dibayar tetap masuk total pengeluaran")


class PosisiAset(unittest.TestCase):
    def setUp(self):
        self.db = make_db((("Kas", "cash", 0), ("Dana Darurat", "savings", 0), ("Saham", "investment", 10_000_000)))
        self.addCleanup(self.db.close)

    def test_untung_dihitung_dari_modal_bukan_dari_nol(self):
        add(self.db, "2026-01", "transfer", 5_000_000, "Kas", to_account="Saham")
        snapshot(self.db, "2026-01", "Saham", "BBRI", 18_000_000)
        pot = next(p for p in asset_view(self.db, "2026-01")["pots"] if p["name"] == "Saham")
        self.assertEqual(pot["invested"], rp(15_000_000), "saldo awal + setoran")
        self.assertEqual(pot["value"], rp(18_000_000))
        self.assertEqual(pot["gain"], rp(3_000_000))

    def test_bulan_tanpa_snapshot_memakai_yang_terakhir_dan_ditandai(self):
        snapshot(self.db, "2026-01", "Saham", "BBRI", 12_000_000)
        v = asset_view(self.db, "2026-03")
        self.assertEqual(v["snap_month"], "2026-01")
        self.assertTrue(next(p for p in v["pots"] if p["name"] == "Saham")["stale"])

    def test_total_aset_tabungan_plus_nilai_pasar(self):
        add(self.db, "2026-01", "transfer", 4_000_000, "Kas", to_account="Dana Darurat")
        snapshot(self.db, "2026-01", "Saham", "BBRI", 12_000_000)
        self.assertEqual(asset_view(self.db, "2026-01")["total"], rp(16_000_000))


class IndikatorLaporan(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.addCleanup(self.db.close)
        for m in ("2025-10", "2025-11", "2025-12"):
            add(self.db, m, "income", 20_000_000, "Kas", category="Gaji")
            add(self.db, m, "expense", 10_000_000, "Kas", category="Belanja")

    def test_surplus_bukan_setoran(self):
        """Sisa yang mengendap di rekening harian bukan uang yang ditabung."""
        add(self.db, "2026-01", "income", 20_000_000, "Kas", category="Gaji")
        add(self.db, "2026-01", "expense", 15_000_000, "Kas", category="Belanja")
        m = build_metrics(self.db, "2026-01")
        self.assertAlmostEqual(m["surplus_rate"], 0.25)
        self.assertEqual(m["saved"], 0)
        self.assertAlmostEqual(m["saved_rate"], 0.0)

    def test_setoran_dihitung_dari_transfer_ke_tabungan(self):
        add(self.db, "2026-01", "income", 20_000_000, "Kas", category="Gaji")
        add(self.db, "2026-01", "expense", 15_000_000, "Kas", category="Belanja")
        add(self.db, "2026-01", "transfer", 4_000_000, "Kas", to_account="Dana Darurat")
        m = build_metrics(self.db, "2026-01")
        self.assertAlmostEqual(m["surplus_rate"], 0.25, msg="transfer tidak mengubah surplus")
        self.assertAlmostEqual(m["saved_rate"], 0.20)

    def test_rasio_cicilan_hanya_dari_kategori_bertanda(self):
        add(self.db, "2026-01", "income", 20_000_000, "Kas", category="Gaji")
        add(self.db, "2026-01", "expense", 7_000_000, "Kas", category="Cicilan Rumah")
        add(self.db, "2026-01", "expense", 3_000_000, "Kas", category="Belanja")
        m = build_metrics(self.db, "2026-01")
        self.assertEqual(m["debt"], rp(7_000_000))
        self.assertAlmostEqual(m["debt_ratio"], 0.35)

    def test_tagihan_kartu_di_luar_rasio_cicilan(self):
        """Besarnya mengikuti belanja bulan itu, bukan kewajiban tetap."""
        add(self.db, "2026-01", "income", 20_000_000, "Kas", category="Gaji")
        add(self.db, "2026-01", "expense", 7_000_000, "Kas", category="Cicilan Rumah")
        add(self.db, "2026-01", "expense", 9_000_000, "Kas", category="Tagihan Kartu")
        m = build_metrics(self.db, "2026-01")
        self.assertEqual(m["debt"], rp(7_000_000))
        self.assertEqual(m["card"], rp(9_000_000))
        self.assertAlmostEqual(m["debt_ratio"], 0.35)

    def test_rasio_cicilan_dibagi_pemasukan_rata_rata(self):
        """Bulan bonus tidak boleh membuat cicilan terlihat mendadak ringan."""
        add(self.db, "2026-01", "income", 60_000_000, "Kas", category="Bonus & THR")
        add(self.db, "2026-01", "expense", 7_000_000, "Kas", category="Cicilan Rumah")
        m = build_metrics(self.db, "2026-01")
        self.assertEqual(m["debt_base"], rp(20_000_000), "rata-rata tiga bulan sebelumnya")
        self.assertAlmostEqual(m["debt_ratio"], 0.35)

    def test_cakupan_dana_darurat_dibanding_rata_rata_tiga_bulan(self):
        add(self.db, "2026-01", "transfer", 30_000_000, "Kas", to_account="Dana Darurat")
        self.assertAlmostEqual(build_metrics(self.db, "2026-01")["cover_months"], 3.0)

    def test_tabungan_tujuan_tidak_ikut_dihitung_dana_darurat(self):
        self.db.execute("INSERT INTO accounts(name, type, sort) VALUES ('Tabungan Liburan','savings',40)")
        add(self.db, "2026-01", "transfer", 30_000_000, "Kas", to_account="Dana Darurat")
        add(self.db, "2026-01", "transfer", 50_000_000, "Kas", to_account="Tabungan Liburan")
        m = build_metrics(self.db, "2026-01")
        self.assertEqual(m["fund"], rp(80_000_000), "seluruh tabungan tetap dilaporkan apa adanya")
        self.assertEqual(m["emergency"], rp(30_000_000))
        self.assertAlmostEqual(m["cover_months"], 3.0)

    def test_tanpa_kantong_bertanda_cakupan_tidak_dikarang(self):
        self.db.execute("UPDATE accounts SET is_emergency=0")
        add(self.db, "2026-01", "transfer", 30_000_000, "Kas", to_account="Dana Darurat")
        m = build_metrics(self.db, "2026-01")
        self.assertFalse(m["emergency_set"])
        self.assertIsNone(m["emergency"])
        self.assertEqual(m["cover_months"], 0)
        nilai = {h["label"]: h["value"] for h in render_rules(m)["health"]}
        self.assertEqual(nilai["Cakupan dana darurat"], "–")

    def test_kategori_melonjak_terdeteksi(self):
        add(self.db, "2026-01", "income", 20_000_000, "Kas", category="Gaji")
        add(self.db, "2026-01", "expense", 20_000_000, "Kas", category="Belanja")
        names = [c["name"] for c in build_metrics(self.db, "2026-01")["spikes"]]
        self.assertIn("Belanja", names)

    def test_proyeksi_memakai_rata_rata_bukan_jumlah_template(self):
        """Template rutin sudah ikut terhitung di rata-rata. Menjumlahkannya lagi
        berarti menghitung KPR dua kali — dan proyeksinya jadi jauh meleset."""
        self.db.execute(
            "INSERT INTO recurring(type, account_id, category_id, description, amount)"
            " VALUES ('expense',?,?,'Cicilan Rumah',?)",
            (acc(self.db, "Kas"), cat(self.db, "Cicilan Rumah"), rp(4_000_000)))
        m = build_metrics(self.db, "2026-01")
        self.assertEqual(m["proj_income"], rp(20_000_000))
        self.assertEqual(m["proj_expense"], rp(10_000_000), "bukan 10jt + 4jt")
        self.assertEqual(m["proj_net"], rp(10_000_000))
        self.assertEqual(len(m["scheduled"]), 1, "template tetap didaftar sebagai keterangan")

    def test_proyeksi_sisa_kas_bertumpu_pada_kas_sekarang(self):
        m = build_metrics(self.db, "2026-01")
        self.assertEqual(m["proj_cash"], m["cash"] + m["proj_net"])
        self.assertEqual(m["next_month"], "2026-02")

    def test_kas_bertahan_hanya_dihitung_saat_defisit(self):
        self.assertIsNone(build_metrics(self.db, "2026-01")["months_left"],
                          "surplus: angka bertahan tidak berarti apa-apa")

    def test_kas_bertahan_saat_defisit(self):
        db = make_db((("Kas", "cash", 30_000_000), ("Dana Darurat", "savings", 0)))
        self.addCleanup(db.close)
        for bln in ("2025-10", "2025-11", "2025-12"):
            add(db, bln, "income", 5_000_000, "Kas", category="Gaji")
            add(db, bln, "expense", 10_000_000, "Kas", category="Belanja")
        m = build_metrics(db, "2026-01")
        self.assertEqual(m["proj_net"], rp(-5_000_000))
        self.assertEqual(m["months_left"], 3, "kas 30jt − 15jt terpakai, defisit 5jt/bln")

    def test_riwayat_pendek_ditandai_kasar(self):
        db = make_db()
        self.addCleanup(db.close)
        add(db, "2026-01", "income", 9_000_000, "Kas", category="Gaji")
        r = render_rules(build_metrics(db, "2026-01"))
        self.assertTrue(r["proyeksi"]["kasar"])
        self.assertIn("1", r["proyeksi"]["basis"])

    def test_riwayat_cukup_tidak_ditandai_kasar(self):
        add(self.db, "2026-01", "income", 20_000_000, "Kas", category="Gaji")
        r = render_rules(build_metrics(self.db, "2026-01"))
        self.assertFalse(r["proyeksi"]["kasar"])

    def test_defisit_disebut_di_ringkasan(self):
        add(self.db, "2026-01", "income", 5_000_000, "Kas", category="Gaji")
        add(self.db, "2026-01", "expense", 9_000_000, "Kas", category="Belanja")
        r = render_rules(build_metrics(self.db, "2026-01"))
        self.assertIn("defisit", r["summary"].lower())
        self.assertTrue(r["health"])


if __name__ == "__main__":
    unittest.main()


class TestTagihan(unittest.TestCase):
    """Tagihan = pengeluaran 'planned'; urutan dan penanda jatuh temponya."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        from app import db
        self._orig = db.DB_PATH
        db.DB_PATH = str(Path(self.tmp.name) / "monetary.db")
        db._ready.clear(); db._system_ready.clear()
        db.init_book(db.DB_PATH)
        self.db = db
        from app.main import bills
        self.bills = bills

    def tearDown(self):
        self.db.set_book("")
        self.db.DB_PATH = self._orig
        self.db._ready.clear(); self.db._system_ready.clear()
        self.tmp.cleanup()

    def _tx(self, desc, amount, tx_date, status="planned"):
        with self.db.get_db() as c:
            acc = c.execute("SELECT id FROM accounts LIMIT 1").fetchone()["id"]
            cat = c.execute("SELECT id FROM categories WHERE kind='expense' LIMIT 1").fetchone()["id"]
            c.execute("INSERT INTO transactions(month_key,type,tx_date,account_id,category_id,description,amount,status)"
                      " VALUES ('2026-09','expense',?,?,?,?,?,?)", (tx_date, acc, cat, desc, rp(amount), status))

    def test_hanya_yang_belum_dibayar(self):
        self._tx("belum", 1000, "2026-09-10")
        self._tx("sudah", 2000, "2026-09-11", status="paid")
        with self.db.get_db() as c:
            b = self.bills(c, "2026-09", today="2026-09-12")
        self.assertEqual(b["count"], 1)
        self.assertEqual(b["total"], rp(1000))
        self.assertEqual(b["rows"][0]["description"], "belum")

    def test_penanda_jatuh_tempo(self):
        self._tx("telat", 1000, "2026-09-05")
        self._tx("hari ini", 2000, "2026-09-12")
        self._tx("minggu ini", 3000, "2026-09-15")
        self._tx("nanti", 4000, "2026-09-28")
        self._tx("tanpa tanggal", 5000, None)
        with self.db.get_db() as c:
            b = self.bills(c, "2026-09", today="2026-09-12")
        state = {r["description"]: r["state"] for r in b["rows"]}
        self.assertEqual(state["telat"], "late")
        self.assertEqual(state["hari ini"], "today")
        self.assertEqual(state["minggu ini"], "soon")
        self.assertEqual(state["nanti"], "later")
        self.assertEqual(state["tanpa tanggal"], "later")
        self.assertEqual(b["late"], 1)
        self.assertEqual(b["soon"], 2)          # hari ini + minggu ini

    def test_urutan_menurut_jatuh_tempo(self):
        self._tx("c", 1000, "2026-09-20")
        self._tx("a", 1000, "2026-09-02")
        self._tx("b", 1000, "2026-09-10")
        self._tx("z", 1000, None)
        with self.db.get_db() as c:
            b = self.bills(c, "2026-09", today="2026-09-12")
        self.assertEqual([r["description"] for r in b["rows"]], ["a", "b", "c", "z"])

    def test_selisih_hari(self):
        self._tx("x", 1000, "2026-09-09")
        with self.db.get_db() as c:
            b = self.bills(c, "2026-09", today="2026-09-12")
        self.assertEqual(b["rows"][0]["due"], -3)

    def test_bulan_tanpa_tagihan(self):
        with self.db.get_db() as c:
            b = self.bills(c, "2026-09", today="2026-09-12")
        self.assertEqual(b["count"], 0)
        self.assertEqual(b["total"], 0)


class TestUsulanDeskripsi(unittest.TestCase):
    """Usulan diambil dari riwayat buku itu sendiri: yang sering dipakai lebih dulu,
    dan nilai yang ikut terbawa berasal dari entri terakhirnya."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        from app import db
        self._orig = db.DB_PATH
        db.DB_PATH = str(Path(self.tmp.name) / "monetary.db")
        db._ready.clear(); db._system_ready.clear()
        db.init_book(db.DB_PATH)
        self.db = db
        from app.main import recent_entries
        self.recent = recent_entries

    def tearDown(self):
        self.db.set_book("")
        self.db.DB_PATH = self._orig
        self.db._ready.clear(); self.db._system_ready.clear()
        self.tmp.cleanup()

    def _tx(self, desc, amount, tx_date, type_="expense", cat=None):
        with self.db.get_db() as c:
            acc = c.execute("SELECT id FROM accounts LIMIT 1").fetchone()["id"]
            if cat is None:
                cat = c.execute("SELECT id FROM categories WHERE kind='expense' LIMIT 1").fetchone()["id"]
            c.execute("INSERT INTO transactions(month_key,type,tx_date,account_id,category_id,description,amount)"
                      " VALUES ('2026-09',?,?,?,?,?,?)", (type_, tx_date, acc, cat, desc, rp(amount)))

    def _cari(self, q, type_="expense"):
        with self.db.get_db() as c:
            return self.recent(c, type_, q)

    def test_yang_sering_dipakai_di_atas(self):
        for i in range(3):
            self._tx("Kopi pagi", 25000, f"2026-09-0{i+1}")
        self._tx("Kopi sore", 30000, "2026-09-05")
        hasil = self._cari("kopi")
        self.assertEqual(hasil[0]["description"], "Kopi pagi")
        self.assertEqual(hasil[0]["n"], 3)

    def test_nilai_dari_entri_terakhir(self):
        self._tx("Bensin", 50000, "2026-09-01")
        self._tx("Bensin", 75000, "2026-09-20")
        self.assertEqual(self._cari("bensin")[0]["amount"], rp(75000))

    def test_satu_baris_per_deskripsi(self):
        for i in range(4):
            self._tx("Listrik", 100000, f"2026-09-1{i}")
        self.assertEqual(len(self._cari("listrik")), 1)

    def test_tidak_membedakan_besar_kecil_huruf(self):
        self._tx("Tagihan Air", 60000, "2026-09-02")
        self.assertEqual(len(self._cari("tagihan air")), 1)
        self.assertEqual(len(self._cari("TAGIHAN")), 1)

    def test_jenis_lain_tidak_ikut(self):
        self._tx("Gaji", 5000000, "2026-09-01", type_="income",
                 cat=None if False else 1)
        self.assertEqual(self._cari("gaji", "expense"), [])

    def test_deskripsi_kosong_diabaikan(self):
        self._tx("   ", 1000, "2026-09-01")
        self.assertEqual(self._cari("  "), [])
