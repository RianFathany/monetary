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


if __name__ == "__main__":
    unittest.main()
