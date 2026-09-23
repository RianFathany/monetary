"""Mata uang: bentuk angka, pembacaan input, dan migrasi skala nominal."""
import unittest

from app import i18n, money
from app.schema import MONEY_SCALE, upgrade
from tests.helpers import add, make_db


class Bentuk(unittest.TestCase):
    def setUp(self):
        i18n.set_lang("id")
        money.set_currency("IDR")

    def test_rupiah_tanpa_desimal(self):
        self.assertEqual(money.fmt(1_888_800_000), "Rp 18.888.000")
        self.assertEqual(money.fmt(-450_000), "-Rp 4.500")

    def test_kosong_jadi_strip(self):
        self.assertEqual(money.fmt(None), "–")

    def test_simbol_huruf_diberi_jarak_lambang_menempel(self):
        money.set_currency("USD")
        self.assertEqual(money.fmt(1250), "$12,50")      # lambang menempel
        money.set_currency("MYR")
        self.assertEqual(money.fmt(2500), "RM 25,00")    # huruf pakai jarak

    def test_pemisah_ikut_bahasa_bukan_mata_uang(self):
        money.set_currency("USD")
        self.assertEqual(money.fmt(123_456_789), "$1.234.567,89")
        i18n.set_lang("en")
        self.assertEqual(money.fmt(123_456_789), "$1,234,567.89")

    def test_mata_uang_tanpa_sen_membulat(self):
        money.set_currency("JPY")
        self.assertEqual(money.fmt(500_000), "¥5.000")

    def test_mata_uang_tak_dikenal_jatuh_ke_bawaan(self):
        self.assertEqual(money.set_currency("XYZ"), "IDR")
        self.assertEqual(money.set_currency(""), "IDR")

    def test_kode_tanpa_lambang_memakai_kodenya(self):
        money.set_currency("BWP")
        self.assertTrue(money.fmt(10_000).startswith("BWP "))


class Ringkas(unittest.TestCase):
    def setUp(self):
        i18n.set_lang("id")
        money.set_currency("IDR")

    def test_juta_dan_miliar(self):
        self.assertEqual(money.short(1_888_800_000), "18,9 jt")
        self.assertEqual(money.short(250_000_000_000), "2,5 M")

    def test_di_bawah_seribu_tetap_lengkap_dengan_simbol(self):
        self.assertEqual(money.short(45_000), "Rp 450")

    def test_negatif_tetap_bertanda(self):
        self.assertTrue(money.short(-1_888_800_000).startswith("-"))


class Baca(unittest.TestCase):
    def setUp(self):
        i18n.set_lang("id")
        money.set_currency("IDR")

    def test_titik_ribuan_bukan_desimal(self):
        self.assertEqual(money.parse("18.888.000"), 1_888_800_000)

    def test_simbol_dan_spasi_diabaikan(self):
        self.assertEqual(money.parse("Rp 4.500"), 450_000)

    def test_kosong_jadi_nol(self):
        self.assertEqual(money.parse(""), 0)
        self.assertEqual(money.parse(None), 0)

    def test_negatif(self):
        self.assertEqual(money.parse("-2.400.000"), -240_000_000)

    def test_sen_dibaca_pada_mata_uang_bersen(self):
        money.set_currency("USD")
        self.assertEqual(money.parse("12,50"), 1250)
        self.assertEqual(money.parse("1.234,56"), 123_456)

    def test_sen_diabaikan_pada_rupiah(self):
        """'1.500' di rupiah berarti seribu lima ratus, bukan satu setengah."""
        self.assertEqual(money.parse("1.500"), 150_000)

    def test_bolak_balik(self):
        """Ditulis lalu dibaca lagi harus utuh — sejauh presisi mata uangnya.
        Rupiah tidak mengenal sen, jadi nilainya kelipatan satuan penuh."""
        for code, nilai in (("IDR", (0, 450_000, 4_480_000_000)),
                            ("JPY", (0, 500_000)),
                            ("USD", (0, 1250, 999_999)),
                            ("EUR", (0, 450, 123_456_789))):
            money.set_currency(code)
            for v in nilai:
                self.assertEqual(money.parse(money.plain(v)), v, f"{code} {v}")

    def test_rupiah_membuang_pecahan_yang_tak_bisa_ditulis(self):
        """1250 satuan simpan = Rp 12,50; rupiah tidak punya sen, jadi jadi Rp 12."""
        self.assertEqual(money.plain(1250), "12")
        self.assertEqual(money.parse("12"), 1200)


class SkalaNominal(unittest.TestCase):
    """Migrasi ke satuan perseratus: sekali jalan, tidak boleh dua kali."""

    def buku_lama(self):
        """Buku versi 2: nominal masih dalam rupiah utuh, tanpa penanda skala."""
        db = make_db()
        add(db, "2026-01", "income", 10_000_000, "Kas", category="Gaji")
        db.execute("UPDATE transactions SET amount = amount / ?", (MONEY_SCALE,))
        db.execute("UPDATE accounts SET opening_balance = opening_balance / ?", (MONEY_SCALE,))
        db.execute("DELETE FROM settings WHERE key='money_scale'")
        db.execute("UPDATE settings SET value='2' WHERE key='schema_version'")
        db.commit()
        return db

    def jumlah(self, db):
        return db.execute("SELECT SUM(amount) s FROM transactions").fetchone()["s"]

    def test_nominal_dikali_seratus_sekali(self):
        db = self.buku_lama()
        self.addCleanup(db.close)
        self.assertEqual(self.jumlah(db), 10_000_000)
        upgrade(db)
        self.assertEqual(self.jumlah(db), 1_000_000_000)

    def test_dijalankan_berkali_kali_tetap_sama(self):
        db = self.buku_lama()
        self.addCleanup(db.close)
        upgrade(db)
        sesudah = self.jumlah(db)
        for _ in range(3):
            upgrade(db)
        self.assertEqual(self.jumlah(db), sesudah)

    def test_versi_terlanjur_naik_tetap_diskalakan(self):
        """Kejadian nyata: nomor versi sempat naik tanpa migrasinya jalan."""
        db = self.buku_lama()
        self.addCleanup(db.close)
        db.execute("UPDATE settings SET value='3' WHERE key='schema_version'")
        db.commit()
        upgrade(db)
        self.assertEqual(self.jumlah(db), 1_000_000_000)

    def test_penanda_tertinggal_setelah_migrasi(self):
        db = self.buku_lama()
        self.addCleanup(db.close)
        upgrade(db)
        row = db.execute("SELECT value FROM settings WHERE key='money_scale'").fetchone()
        self.assertEqual(row["value"], str(MONEY_SCALE))

    def test_laporan_lama_dibuang(self):
        db = self.buku_lama()
        self.addCleanup(db.close)
        db.execute("INSERT INTO reports(month_key, engine, content_json) VALUES ('2026-01','rules','{}')")
        db.commit()
        upgrade(db)
        self.assertEqual(db.execute("SELECT COUNT(*) c FROM reports").fetchone()["c"], 0)


if __name__ == "__main__":
    unittest.main()
