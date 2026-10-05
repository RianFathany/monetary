"""Library bank (app/banks.py), logo statis, dan pencocokan logo dari teks."""
import os
import unittest
from pathlib import Path
from unittest import mock

from app import banks, inbox, mailparse
from tests.helpers import acc, make_db

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"


class TestLibrary(unittest.TestCase):
    def test_kunci_unik_dan_lengkap(self):
        keys = [b["key"] for b in banks.ALL]
        self.assertEqual(len(keys), len(set(keys)))
        for b in banks.ALL:
            self.assertTrue(b["name"] and b["short"] and b["domain"] and b["sender"], b["key"])
            self.assertIn(b["region"], ("id", "intl"))

    def test_semua_bank_punya_profil_dan_logo(self):
        for b in banks.ALL:
            p = mailparse.PROFILES[b["key"]]
            self.assertEqual(p["label"], b["name"])
            self.assertEqual(p["logo"], f"/static/banks/{b['key']}.png")
            self.assertTrue((STATIC / "banks" / f"{b['key']}.png").is_file(), b["key"])

    def test_bank_khusus_tetap_pakai_label_sendiri(self):
        self.assertIn("nilai transaksi", mailparse.PROFILES["mega"]["nominal"])
        self.assertIn("total pembayaran", mailparse.PROFILES["livin"]["nominal"])
        self.assertEqual(mailparse.PROFILES["bri"]["nominal"], mailparse.UMUM["nominal"])

    def test_bank_lain_terbaca_dengan_label_umum(self):
        teks = "Transaksi berhasil\nPenerima : TOKO ABC\nNominal : Rp 75.000"
        p = mailparse.parse(teks, "Notifikasi", "bri", 0)
        self.assertEqual(p["amount"], 7500000)
        self.assertEqual(p["description"], "TOKO ABC")

    def test_umum_selalu_ada_dan_tanpa_logo(self):
        self.assertEqual(mailparse.PROFILES["umum"]["logo"], "")
        self.assertEqual(mailparse.PROFILES["umum"]["sender"], "")


class TestLogoDariTeks(unittest.TestCase):
    def test_nama_bank_dikenali(self):
        cases = {"BNI": "bni", "Bayar CC BCA": "bca", "CC Mega": "mega", "BCA Operasional": "bca",
                 "Transfer ke Bank Jago": "jago", "Mandiri": "livin", "Livin' by Mandiri": "livin",
                 "Bank Mega Syariah": "megasyariah", "tagihan bri bulan ini": "bri"}
        for teks, key in cases.items():
            self.assertEqual(mailparse.bank_logo(teks), f"/static/banks/{key}.png", teks)

    def test_kata_biasa_tidak_dikira_bank(self):
        for teks in ("Gaji raya", "blu jeans", "jago masak", "Operasional", "Tagihan Kartu", "", None,
                     "wise investment", "BCAX", "megah"):
            self.assertEqual(mailparse.bank_logo(teks), "", teks)

    def test_nama_terpanjang_menang(self):
        self.assertEqual(mailparse.bank_logo("BTPN Syariah"), "/static/banks/btpnsyariah.png")


class TestAturanBankBaru(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.dict(os.environ, {"EMAIL_TOKEN_KEY": "kunci-uji"})
        patch.start()
        self.addCleanup(patch.stop)
        self.db = make_db(accounts=(("Kas", "cash", 0),))
        self.addCleanup(self.db.close)
        self.sid = inbox.save_source(self.db, "a@gmail.com", "refresh")

    def test_bank_dari_library_tersimpan_dengan_isian_bawaan(self):
        rid = inbox.add_rule(self.db, self.sid, "", "", "bri", acc(self.db, "Kas"))
        r = self.db.execute("SELECT * FROM email_rules WHERE id=?", (rid,)).fetchone()
        self.assertEqual((r["parser"], r["sender"]), ("bri", "bri.co.id"))
        self.assertTrue(r["keywords"])

    def test_kunci_tak_dikenal_jadi_umum(self):
        rid = inbox.add_rule(self.db, self.sid, "x.co.id", "transaksi", "ngawur", None)
        self.assertEqual(self.db.execute("SELECT parser FROM email_rules WHERE id=?", (rid,)).fetchone()[0], "umum")


if __name__ == "__main__":
    unittest.main()
