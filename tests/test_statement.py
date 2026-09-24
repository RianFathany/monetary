"""Pembaca berkas bank: PDF terkunci, XLSX, CSV, dan penolakan yang jelas."""
import io
import unittest

from app import statement


def _buat_pdf(baris, password=None) -> bytes:
    """PDF minimal yang ditulis tangan: cukup untuk menguji jalur baca kita
    sendiri, tanpa menyeret pustaka pembuat PDF ke dalam dependensi tes."""
    isi = "BT /F1 12 Tf 40 700 Td (" + ") Tj 0 -16 Td (".join(baris) + ") Tj ET"
    objek = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(isi)} >>\nstream\n{isi}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    posisi = []
    for i, o in enumerate(objek, start=1):
        posisi.append(out.tell())
        out.write(f"{i} 0 obj\n{o}\nendobj\n".encode())
    awal_xref = out.tell()
    out.write(f"xref\n0 {len(objek) + 1}\n0000000000 65535 f \n".encode())
    for p in posisi:
        out.write(f"{p:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objek) + 1} /Root 1 0 R >>\nstartxref\n{awal_xref}\n%%EOF\n".encode())
    mentah = out.getvalue()

    if password is None:
        return mentah
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(mentah)))
    w.encrypt(password, algorithm="AES-128")
    kunci = io.BytesIO()
    w.write(kunci)
    return kunci.getvalue()


class TestPDF(unittest.TestCase):
    def test_pdf_biasa_terbaca(self):
        baris = statement.ekstrak("mutasi.pdf", _buat_pdf(["01/09 KOPI 35.000", "02/09 BENSIN 100.000"]))
        self.assertTrue(any("KOPI" in b for b in baris), baris)

    def test_pdf_terkunci_butuh_password(self):
        blob = _buat_pdf(["01/09 KOPI 35.000"], password="rahasia")
        with self.assertRaises(statement.Gagal) as e:
            statement.ekstrak("mutasi.pdf", blob)
        self.assertIn("terkunci", str(e.exception).lower())

    def test_password_salah_ditolak_dengan_jelas(self):
        blob = _buat_pdf(["01/09 KOPI 35.000"], password="rahasia")
        with self.assertRaises(statement.Gagal) as e:
            statement.ekstrak("mutasi.pdf", blob, password="ngawur")
        self.assertIn("salah", str(e.exception).lower())

    def test_password_benar_membuka(self):
        blob = _buat_pdf(["01/09 KOPI 35.000"], password="rahasia")
        baris = statement.ekstrak("mutasi.pdf", blob, password="rahasia")
        self.assertTrue(any("KOPI" in b for b in baris), baris)

    def test_bukan_pdf_ditolak(self):
        with self.assertRaises(statement.Gagal):
            statement.ekstrak("mutasi.pdf", b"%PDF-1.4 ini bukan pdf beneran")


class TestCSV(unittest.TestCase):
    def test_koma(self):
        blob = b"Tanggal,Keterangan,Jumlah\n01/09/2026,KOPI KENANGAN,35000\n"
        baris = statement.ekstrak("mutasi.csv", blob)
        self.assertEqual(len(baris), 2)
        self.assertIn("KOPI KENANGAN", baris[1])

    def test_titik_koma_ikut_terbaca(self):
        blob = b"Tanggal;Keterangan;Jumlah\n01/09/2026;BENSIN;100000\n"
        self.assertIn("BENSIN", statement.ekstrak("mutasi.csv", blob)[1])

    def test_huruf_latin_tidak_menjatuhkan(self):
        blob = "Tanggal,Keterangan\n01/09,CAFÉ MÉLANGE\n".encode("cp1252")
        self.assertTrue(any("CAF" in b for b in statement.ekstrak("m.csv", blob)))

    def test_csv_kosong_ditolak(self):
        with self.assertRaises(statement.Gagal):
            statement.ekstrak("mutasi.csv", b"\n\n")


class TestXLSX(unittest.TestCase):
    def blob(self, rows):
        from openpyxl import Workbook
        wb = Workbook()
        for r in rows:
            wb.active.append(r)
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def test_terbaca(self):
        baris = statement.ekstrak("mutasi.xlsx", self.blob([("Tanggal", "Ket", "Jumlah"),
                                                            ("01/09/2026", "KOPI", 35000)]))
        self.assertIn("KOPI", baris[1])

    def test_baris_kosong_dilewati(self):
        baris = statement.ekstrak("m.xlsx", self.blob([("A",), (None,), ("B",)]))
        self.assertEqual(len(baris), 2)


class TestPenjaga(unittest.TestCase):
    def test_berkas_kosong(self):
        with self.assertRaises(statement.Gagal):
            statement.ekstrak("m.pdf", b"")

    def test_terlalu_besar_ditolak_sebelum_dibaca(self):
        """Mesinnya 256 MB. Berkas besar yang dibuka sekaligus bisa menjatuhkan
        aplikasi, dan cadangan harian ikut berhenti."""
        with self.assertRaises(statement.Gagal) as e:
            statement.ekstrak("m.pdf", b"x" * (statement.MAKS_BYTE + 1))
        self.assertIn("besar", str(e.exception).lower())

    def test_format_asing_ditolak(self):
        with self.assertRaises(statement.Gagal) as e:
            statement.ekstrak("mutasi.docx", b"\x00\x01rusak")
        self.assertIn("PDF", str(e.exception))


class TestNominal(unittest.TestCase):
    """Bank Indonesia mencetak 1.234.567,00; sebagian mencetak gaya Inggris."""

    def rp(self, n):
        from app.money import SCALE
        return n * SCALE

    def test_gaya_indonesia(self):
        self.assertEqual(statement.angka("1.234.567,00"), self.rp(1234567))

    def test_gaya_inggris(self):
        self.assertEqual(statement.angka("1,234,567.00"), self.rp(1234567))

    def test_tanpa_pemisah(self):
        self.assertEqual(statement.angka("35000"), self.rp(35000))

    def test_dengan_label_mata_uang(self):
        self.assertEqual(statement.angka("Rp 250.000"), self.rp(250000))

    def test_desimal_tidak_dianggap_ribuan(self):
        self.assertEqual(statement.angka("12,50"), self.rp(12) + 50 * 1)

    def test_bukan_angka(self):
        self.assertIsNone(statement.angka("SALDO AWAL"))
        self.assertIsNone(statement.angka(""))


class TestTanggal(unittest.TestCase):
    def test_garis_miring(self):
        self.assertEqual(statement.tanggal("01/09/2026 KOPI"), "2026-09-01")

    def test_nama_bulan_indonesia(self):
        self.assertEqual(statement.tanggal("05 Sep 2026 X"), "2026-09-05")
        self.assertEqual(statement.tanggal("17 Agu 2026 X"), "2026-08-17")

    def test_tahun_dua_digit(self):
        self.assertEqual(statement.tanggal("12-03-25 Y"), "2025-03-12")

    def test_tanpa_tahun_pakai_bawaan(self):
        self.assertEqual(statement.tanggal("07/11 BENSIN", tahun=2024), "2024-11-07")

    def test_tanggal_mustahil_ditolak(self):
        self.assertIsNone(statement.tanggal("45/99/2026"))

    def test_tanpa_tanggal(self):
        self.assertIsNone(statement.tanggal("SALDO AKHIR 1.000.000"))


class TestPecah(unittest.TestCase):
    def test_baris_biasa(self):
        tx, sisa = statement.pecah(["01/09/2026 KOPI KENANGAN 35.000"])
        self.assertEqual(len(tx), 1)
        self.assertEqual(tx[0]["tanggal"], "2026-09-01")
        self.assertIn("KOPI KENANGAN", tx[0]["keterangan"])
        self.assertFalse(tx[0]["masuk"])

    def test_angka_terakhir_dianggap_saldo(self):
        """Hampir semua rekening koran mencetak kolom saldo di paling kanan."""
        tx, _ = statement.pecah(["01/09/2026 KOPI 35.000 1.250.000"])
        from app.money import SCALE
        self.assertEqual(tx[0]["nilai"], 35000 * SCALE)
        self.assertEqual(tx[0]["saldo"], 1250000 * SCALE)

    def test_penanda_kredit_jadi_pemasukan(self):
        tx, _ = statement.pecah(["05/09/2026 GAJI CR 8.500.000"])
        self.assertTrue(tx[0]["masuk"])

    def test_penanda_debit_tetap_pengeluaran(self):
        tx, _ = statement.pecah(["05/09/2026 TARIK TUNAI DB 500.000"])
        self.assertFalse(tx[0]["masuk"])

    def test_baris_tanpa_angka_masuk_sisa(self):
        tx, sisa = statement.pecah(["SALDO AWAL", "Halaman 1 dari 3"])
        self.assertEqual(tx, [])
        self.assertEqual(len(sisa), 2)

    def test_yang_tidak_terbaca_tidak_dibuang(self):
        """Membuang diam-diam lebih berbahaya daripada mengaku belum bisa baca."""
        baris = ["01/09/2026 KOPI 35.000", "REKENING KORAN SEPTEMBER", "02/09/2026 BENSIN 100.000"]
        tx, sisa = statement.pecah(baris)
        self.assertEqual(len(tx) + len(sisa), len(baris))


if __name__ == "__main__":
    unittest.main()
