"""Sumber email: pencarian Gmail, pembaca email bank, sinkron, dan draf.

Jaringan diganti `FakeApi`, jadi tes ini tidak pernah menghubungi Google.
Contoh email di bawah buatan sendiri dengan bentuk yang umum; begitu ada
contoh asli BCA, Mega, dan Livin, tambahkan di sini sebagai tes per bank.
"""
import base64
import os
import unittest
from unittest import mock

from app import gmail, inbox, mailparse
from tests.helpers import acc, make_db, rp

KEY = {"EMAIL_TOKEN_KEY": "kunci-uji", "GOOGLE_CLIENT_ID": "cid", "GOOGLE_CLIENT_SECRET": "sec"}


class FakeApi:
    """Pengganti app/gmail.py untuk sinkron."""
    Gagal = gmail.Gagal
    query = staticmethod(gmail.query)

    def __init__(self, messages, fail=None):
        self.messages = messages           # {id: dict(epoch, sender, subject, text)}
        self.fail = fail
        self.queries = []
        self.revoked = []

    def unseal(self, blob):
        return gmail.unseal(blob)

    def access_token(self, refresh):
        if self.fail:
            raise self.fail
        return "akses"

    def list_ids(self, token, q, limit):
        self.queries.append(q)
        return list(self.messages)

    def fetch(self, token, mid):
        return dict(id=mid, **self.messages[mid])

    def revoke(self, token):
        self.revoked.append(token)


BCA_CC = """Yth. Bapak/Ibu
Transaksi Kartu Kredit BCA Anda
Tanggal : 03-10-2026 19:21:05
Merchant : TOKOPEDIA JAKARTA
Nominal : Rp 1.250.000,00
Sisa limit : Rp 18.750.000,00"""

LIVIN = """Transfer Berhasil
Penerima | BUDI SANTOSO
Total Pembayaran | Rp 350.000
Tanggal Transaksi | 4 Okt 2026"""

MASUK = """Dana masuk ke rekening Anda
Jumlah : IDR 5.000.000
Keterangan : GAJI OKTOBER"""


class TestQuery(unittest.TestCase):
    def test_pengirim_subjek_dan_waktu(self):
        q = gmail.query("notif@bca.co.id", "transaksi, transfer", 1700000000)
        self.assertEqual(q, "from:(notif@bca.co.id) subject:(transaksi OR transfer) after:1700000000")

    def test_tanpa_kata_kunci(self):
        self.assertEqual(gmail.query("bankmega.com", "", 5), "from:(bankmega.com) after:5")

    def test_karakter_pencarian_dibuang(self):
        """Tanda kurung atau titik dua di isian tidak boleh mengubah arti pencarian."""
        q = gmail.query('x@y.com) OR from:(*', 'a"b) OR -x', 1)
        # sisa kata kunci jadi satu frasa berkutip: OR di dalamnya hanya teks
        self.assertEqual(q, 'from:(x@y.com) subject:("a b OR x") after:1')

    def test_kata_kunci_berspasi_dikutip(self):
        self.assertIn('"kartu kredit"', gmail.query("a@b.com", "kartu kredit", 1))


class TestParser(unittest.TestCase):
    def test_kartu_kredit_bca(self):
        p = mailparse.parse(BCA_CC, "Notifikasi Transaksi", "bca")
        self.assertEqual(p["amount"], rp(1_250_000))            # bukan sisa limit
        self.assertEqual(p["type"], "expense")                  # "kartu kredit" bukan uang masuk
        self.assertEqual(p["tx_date"], "2026-10-03")
        self.assertEqual(p["description"], "TOKOPEDIA JAKARTA")

    def test_livin_tabel(self):
        p = mailparse.parse(LIVIN, "Transfer Berhasil", "livin")
        self.assertEqual(p["amount"], rp(350_000))
        self.assertEqual(p["description"], "BUDI SANTOSO")
        self.assertEqual(p["tx_date"], "2026-10-04")

    def test_uang_masuk(self):
        p = mailparse.parse(MASUK, "Notifikasi", "umum")
        self.assertEqual(p["type"], "income")
        self.assertEqual(p["amount"], rp(5_000_000))

    def test_tidak_terbaca_tetap_jadi_draf(self):
        p = mailparse.parse("Promo akhir pekan, diskon besar!", "Promo", "umum", received_epoch=1759600000)
        self.assertIsNone(p["amount"])
        self.assertEqual(p["description"], "Promo")
        self.assertTrue(p["tx_date"])                           # jatuh ke tanggal email diterima

    def test_html_ke_teks(self):
        html = "<table><tr><td>Nominal</td><td>Rp&nbsp;75.000</td></tr><tr><td>Merchant</td><td>KOPI</td></tr></table>"
        teks = gmail.html_to_text(html)
        p = mailparse.parse(teks, "x")
        self.assertEqual(p["amount"], rp(75_000))
        self.assertEqual(p["description"], "KOPI")

    def test_isi_multipart(self):
        enc = lambda s: base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")
        payload = {"mimeType": "multipart/alternative", "parts": [
            {"mimeType": "text/html", "body": {"data": enc("<p>abaikan</p>")}},
            {"mimeType": "text/plain", "body": {"data": enc("Nominal : Rp 10.000")}}]}
        self.assertEqual(gmail.body_text(payload), "Nominal : Rp 10.000")


class EnvKey(unittest.TestCase):
    """Kunci uji berlaku juga di setUp (patch di tingkat kelas hanya membungkus metode tes)."""
    def setUp(self):
        p = mock.patch.dict(os.environ, KEY)
        p.start()
        self.addCleanup(p.stop)


class TestToken(EnvKey):
    def test_terenkripsi_dan_bisa_dibuka(self):
        blob = gmail.seal("refresh-123")
        self.assertNotIn("refresh-123", blob)
        self.assertEqual(gmail.unseal(blob), "refresh-123")

    def test_kunci_berganti_minta_sambung_ulang(self):
        blob = gmail.seal("refresh-123")
        with mock.patch.dict(os.environ, {"EMAIL_TOKEN_KEY": "kunci-lain"}):
            with self.assertRaises(gmail.PerluSambungUlang):
                gmail.unseal(blob)

    def test_tanpa_kunci_fitur_mati(self):
        with mock.patch.dict(os.environ, {"EMAIL_TOKEN_KEY": ""}):
            self.assertFalse(gmail.is_enabled())
            self.assertIn("EMAIL_TOKEN_KEY", gmail.missing())
            with self.assertRaises(gmail.Gagal):
                gmail.seal("x")


class TestSinkron(EnvKey):
    def setUp(self):
        super().setUp()
        self.db = make_db(accounts=(("BCA Operasional", "cash", 0), ("CC Mega", "credit", 0)))
        self.addCleanup(self.db.close)
        self.sid = inbox.save_source(self.db, "Akun09@gmail.com", "refresh-09")
        self.rid = inbox.add_rule(self.db, self.sid, "notif@bca.co.id", "transaksi", "bca",
                                  acc(self.db, "BCA Operasional"))
        self.api = FakeApi({
            "m1": dict(epoch=1759600000, sender="BCA <notif@bca.co.id>", subject="Transaksi", text=BCA_CC),
            "m2": dict(epoch=1759600100, sender="BCA <notif@bca.co.id>", subject="Transaksi", text="tanpa angka"),
        })

    def test_token_tidak_sampai_ke_template(self):
        self.assertNotIn("token_enc", inbox.sources(self.db)[0])

    def test_hanya_menulis_draf(self):
        res = inbox.sync(self.db, self.api, now=1759700000)
        self.assertEqual((res["new"], res["unread"]), (2, 1))
        self.assertEqual(self.db.execute("SELECT COUNT(*) c FROM transactions").fetchone()["c"], 0)
        d = inbox.drafts(self.db)
        self.assertEqual(len(d), 2)
        self.assertEqual({x["account_id"] for x in d}, {acc(self.db, "BCA Operasional")})

    def test_tidak_dobel(self):
        inbox.sync(self.db, self.api, now=1759700000)
        res = inbox.sync(self.db, self.api, now=1759800000)
        self.assertEqual(res["new"], 0)
        self.assertEqual(len(inbox.drafts(self.db)), 2)

    def test_yang_dibuang_tidak_kembali(self):
        inbox.sync(self.db, self.api, now=1759700000)
        for d in inbox.drafts(self.db):
            inbox.dismiss(self.db, d["id"])
        inbox.sync(self.db, self.api, now=1759800000)
        self.assertEqual(inbox.pending_count(self.db), 0)

    def test_sinkron_pertama_mundur_sebulan_lalu_lanjut(self):
        inbox.sync(self.db, self.api, now=1759700000)
        self.assertIn(f"after:{1759700000 - 30 * 86400}", self.api.queries[0])
        inbox.sync(self.db, self.api, now=1759800000)
        self.assertIn(f"after:{1759700000 - 86400}", self.api.queries[1])

    def test_token_ditolak_minta_sambung_ulang(self):
        api = FakeApi({}, fail=gmail.PerluSambungUlang("dicabut"))
        res = inbox.sync(self.db, api, now=1759700000)
        self.assertEqual(res["reauth"], 1)
        self.assertEqual(inbox.sources(self.db)[0]["status"], "reauth")
        self.assertEqual(inbox.sync(self.db, self.api)["new"], 0)    # tidak dicoba lagi sampai disambung ulang

    def test_sambung_ulang_memulihkan_tanpa_hapus_aturan(self):
        self.db.execute("UPDATE email_sources SET status='reauth'")
        inbox.save_source(self.db, "akun09@gmail.com", "refresh-baru")
        s = inbox.sources(self.db)
        self.assertEqual((len(s), s[0]["status"], len(s[0]["rules"])), (1, "ok", 1))

    def test_setujui_jadi_transaksi(self):
        inbox.sync(self.db, self.api, now=1759700000)
        d = [x for x in inbox.drafts(self.db) if x["amount"]][0]
        tx = inbox.approve(self.db, d["id"], "expense", d["amount"], d["tx_date"], d["description"],
                           d["account_id"], None)
        t = self.db.execute("SELECT * FROM transactions WHERE id=?", (tx,)).fetchone()
        self.assertEqual((t["amount"], t["month_key"], t["needs_review"]), (rp(1_250_000), "2026-10", 1))
        self.assertEqual(inbox.pending_count(self.db), 1)
        with self.assertRaises(ValueError):                         # tidak bisa disetujui dua kali
            inbox.approve(self.db, d["id"], "expense", d["amount"], d["tx_date"], "", d["account_id"], None)

    def test_setujui_tanpa_nominal_ditolak(self):
        inbox.sync(self.db, self.api, now=1759700000)
        d = [x for x in inbox.drafts(self.db) if not x["amount"]][0]
        with self.assertRaises(ValueError):
            inbox.approve(self.db, d["id"], "expense", 0, "2026-10-04", "", d["account_id"], None)

    def test_putus_mencabut_izin(self):
        inbox.sync(self.db, self.api, now=1759700000)
        d = inbox.drafts(self.db)[0]
        inbox.approve(self.db, d["id"], "expense", rp(1000), "2026-10-04", "", d["account_id"], None)
        inbox.delete_source(self.db, self.sid, self.api)
        self.assertEqual(self.api.revoked, ["refresh-09"])
        self.assertEqual(inbox.sources(self.db), [])
        self.assertEqual(inbox.pending_count(self.db), 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) c FROM email_drafts WHERE status='approved'")
                         .fetchone()["c"], 1)                       # jejak transaksi tetap


if __name__ == "__main__":
    unittest.main()
