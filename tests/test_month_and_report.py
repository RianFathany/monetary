"""Ringkasan bulan, posisi aset, dan indikator laporan."""
import unittest

from app.db import asset_view
from app.main import month_summary
from app.report import build_metrics, render_rules
from tests.helpers import acc, add, make_db


def snapshot(db, month, account, symbol, amount):
    db.execute("INSERT INTO asset_snapshots(month_key,account_id,symbol,amount) VALUES (?,?,?,?)",
               (month, acc(db, account), symbol, amount))


class RingkasanBulan(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.addCleanup(self.db.close)
        add(self.db, "2026-01", "income", 20_000_000, "Kas", category="Gaji")
        add(self.db, "2026-01", "expense", 5_000_000, "Kas", category="Belanja")
        add(self.db, "2026-01", "transfer", 6_000_000, "Kas", to_account="Dana Darurat")

    def test_transfer_tidak_masuk_pemasukan_atau_pengeluaran(self):
        s = month_summary(self.db, "2026-01")
        self.assertEqual(s["income"], 20_000_000)
        self.assertEqual(s["expense"], 5_000_000)

    def test_yang_ditabung_dihitung_bersih(self):
        add(self.db, "2026-01", "transfer", 1_000_000, "Dana Darurat", to_account="Kas")
        s = month_summary(self.db, "2026-01")
        self.assertEqual(s["saved"], 5_000_000)

    def test_tagihan_belum_dibayar_terhitung_terpisah(self):
        add(self.db, "2026-01", "expense", 2_000_000, "Kas", category="Belanja", status="planned")
        s = month_summary(self.db, "2026-01")
        self.assertEqual(s["unpaid"], 2_000_000)
        self.assertEqual(s["expense"], 7_000_000, "yang belum dibayar tetap masuk total pengeluaran")


class PosisiAset(unittest.TestCase):
    def setUp(self):
        self.db = make_db((("Kas", "cash", 0), ("Dana Darurat", "savings", 0), ("Saham", "investment", 10_000_000)))
        self.addCleanup(self.db.close)

    def test_untung_dihitung_dari_modal_bukan_dari_nol(self):
        add(self.db, "2026-01", "transfer", 5_000_000, "Kas", to_account="Saham")
        snapshot(self.db, "2026-01", "Saham", "BBRI", 18_000_000)
        pot = next(p for p in asset_view(self.db, "2026-01")["pots"] if p["name"] == "Saham")
        self.assertEqual(pot["invested"], 15_000_000, "saldo awal + setoran")
        self.assertEqual(pot["value"], 18_000_000)
        self.assertEqual(pot["gain"], 3_000_000)

    def test_bulan_tanpa_snapshot_memakai_yang_terakhir_dan_ditandai(self):
        snapshot(self.db, "2026-01", "Saham", "BBRI", 12_000_000)
        v = asset_view(self.db, "2026-03")
        self.assertEqual(v["snap_month"], "2026-01")
        self.assertTrue(next(p for p in v["pots"] if p["name"] == "Saham")["stale"])

    def test_total_aset_tabungan_plus_nilai_pasar(self):
        add(self.db, "2026-01", "transfer", 4_000_000, "Kas", to_account="Dana Darurat")
        snapshot(self.db, "2026-01", "Saham", "BBRI", 12_000_000)
        self.assertEqual(asset_view(self.db, "2026-01")["total"], 16_000_000)


class IndikatorLaporan(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.addCleanup(self.db.close)
        for m in ("2025-10", "2025-11", "2025-12"):
            add(self.db, m, "income", 20_000_000, "Kas", category="Gaji")
            add(self.db, m, "expense", 10_000_000, "Kas", category="Belanja")

    def test_tingkat_menabung(self):
        add(self.db, "2026-01", "income", 20_000_000, "Kas", category="Gaji")
        add(self.db, "2026-01", "expense", 15_000_000, "Kas", category="Belanja")
        self.assertAlmostEqual(build_metrics(self.db, "2026-01")["savings_rate"], 0.25)

    def test_rasio_cicilan_hanya_dari_kategori_bertanda(self):
        add(self.db, "2026-01", "income", 20_000_000, "Kas", category="Gaji")
        add(self.db, "2026-01", "expense", 7_000_000, "Kas", category="Cicilan Rumah")
        add(self.db, "2026-01", "expense", 3_000_000, "Kas", category="Belanja")
        m = build_metrics(self.db, "2026-01")
        self.assertEqual(m["debt"], 7_000_000)
        self.assertAlmostEqual(m["debt_ratio"], 0.35)

    def test_cakupan_dana_darurat_dibanding_rata_rata_tiga_bulan(self):
        add(self.db, "2026-01", "transfer", 30_000_000, "Kas", to_account="Dana Darurat")
        self.assertAlmostEqual(build_metrics(self.db, "2026-01")["cover_months"], 3.0)

    def test_kategori_melonjak_terdeteksi(self):
        add(self.db, "2026-01", "income", 20_000_000, "Kas", category="Gaji")
        add(self.db, "2026-01", "expense", 20_000_000, "Kas", category="Belanja")
        names = [c["name"] for c in build_metrics(self.db, "2026-01")["spikes"]]
        self.assertIn("Belanja", names)

    def test_defisit_disebut_di_ringkasan(self):
        add(self.db, "2026-01", "income", 5_000_000, "Kas", category="Gaji")
        add(self.db, "2026-01", "expense", 9_000_000, "Kas", category="Belanja")
        r = render_rules(build_metrics(self.db, "2026-01"))
        self.assertIn("defisit", r["summary"].lower())
        self.assertTrue(r["health"])


if __name__ == "__main__":
    unittest.main()
