"""Draf email: transfer ke rekening sendiri, "dana masuk" dobel, dan Setujui semua."""
import os
import unittest
from unittest import mock

from app import inbox
from tests.helpers import acc, cat, make_db, rp


class Base(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.dict(os.environ, {"EMAIL_TOKEN_KEY": "kunci-uji"})
        patch.start()
        self.addCleanup(patch.stop)
        self.db = make_db(accounts=(("Mandiri", "cash", 0), ("BCA Operasional", "cash", 0)))
        self.addCleanup(self.db.close)
        self.sid = inbox.save_source(self.db, "a@gmail.com", "refresh")
        self.mdr, self.bca = acc(self.db, "Mandiri"), acc(self.db, "BCA Operasional")
        self.n = 0

    def draft(self, type_, amount, desc, date="2026-10-04", account=None):
        self.n += 1
        return self.db.execute(
            "INSERT INTO email_drafts(source_id, gmail_id, source_email, type, tx_date, amount, description, account_id) "
            "VALUES (?,?,?,?,?,?,?,?)", (self.sid, f"g{self.n}", "a@gmail.com", type_, date, amount, desc,
                                         account or self.mdr)).lastrowid

    def kinds(self):
        return inbox.classify(self.db, inbox.drafts(self.db))


class TestKenali(Base):
    def test_tanpa_nama_tidak_menebak(self):
        d = self.draft("expense", rp(2_000_000), "RIAN FATHANY")
        self.assertEqual(self.kinds()[d], "")

    def test_transfer_dan_pasangan_dobel(self):
        inbox.save_own_names(self.db, " Rian  Fathany ,M Rian")
        out = self.draft("expense", rp(2_000_000), "Transfer ke RIAN FATHANY")
        inn = self.draft("income", rp(2_000_000), "Dana masuk", date="2026-10-05", account=self.bca)
        jauh = self.draft("income", rp(2_000_000), "Dana masuk", date="2026-10-09", account=self.bca)
        belanja = self.draft("expense", rp(48_000), "GRAB")
        k = self.kinds()
        self.assertEqual((k[out], k[inn], k[jauh], k[belanja]), ("transfer", "dup", "", ""))

    def test_nama_harus_utuh_sebagai_kata(self):
        inbox.save_own_names(self.db, "Rian")
        d = self.draft("expense", rp(10_000), "BRIANNA STORE")
        self.assertEqual(self.kinds()[d], "")

    def test_dobel_dari_transfer_yang_sudah_dicatat(self):
        inbox.save_own_names(self.db, "Rian Fathany")
        self.db.execute("INSERT INTO transactions(month_key, type, tx_date, account_id, to_account_id, amount, status) "
                        "VALUES ('2026-10','transfer',date('now'),?,?,?,'paid')", (self.mdr, self.bca, rp(500_000)))
        inn = self.draft("income", rp(500_000), "Dana masuk", date=self.db.execute("SELECT date('now')").fetchone()[0])
        self.assertEqual(self.kinds()[inn], "dup")


class TestSetujuiTransfer(Base):
    def test_transfer_tercatat_dan_pasangannya_dibuang(self):
        inbox.save_own_names(self.db, "Rian Fathany")
        out = self.draft("expense", rp(2_000_000), "RIAN FATHANY")
        inn = self.draft("income", rp(2_000_000), "Dana masuk", date="2026-10-05", account=self.bca)
        tx = inbox.approve(self.db, out, "transfer", rp(2_000_000), "2026-10-04", "Ke BCA", self.mdr, None, self.bca)
        t = self.db.execute("SELECT * FROM transactions WHERE id=?", (tx,)).fetchone()
        self.assertEqual((t["type"], t["account_id"], t["to_account_id"], t["category_id"], t["needs_review"]),
                         ("transfer", self.mdr, self.bca, None, 0))
        st = {r["id"]: r["status"] for r in self.db.execute("SELECT id, status FROM email_drafts")}
        self.assertEqual((st[out], st[inn]), ("approved", "dismissed"))

    def test_transfer_ke_kantong_sama_ditolak(self):
        d = self.draft("expense", rp(1_000), "x")
        with self.assertRaises(ValueError):
            inbox.approve(self.db, d, "transfer", rp(1_000), "2026-10-04", "", self.mdr, None, self.mdr)
        with self.assertRaises(ValueError):
            inbox.approve(self.db, d, "transfer", rp(1_000), "2026-10-04", "", self.mdr, None, None)


class TestSetujuiSemua(Base):
    def test_hanya_yang_lengkap(self):
        inbox.save_own_names(self.db, "Rian Fathany")
        ok = self.draft("expense", rp(48_000), "GRAB")
        kosong = self.draft("expense", None, "Notifikasi")
        tf = self.draft("expense", rp(2_000_000), "RIAN FATHANY")
        rows = inbox.drafts(self.db)
        cats = {"expense": {"Transport": cat(self.db, "Transport")}, "income": {}}
        res = inbox.approve_all(self.db, rows, inbox.classify(self.db, rows), cats)
        self.assertEqual(res, dict(done=1, skipped=2))
        st = {r["id"]: r["status"] for r in self.db.execute("SELECT id, status FROM email_drafts")}
        self.assertEqual((st[ok], st[kosong], st[tf]), ("approved", "pending", "pending"))


if __name__ == "__main__":
    unittest.main()
