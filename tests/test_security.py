"""Tujuh perbaikan keamanan sebelum aplikasi ini dibuka untuk umum.

Tiap tes di sini menjaga satu lubang yang pernah ada. Kalau ada yang gagal,
artinya lubangnya kembali — bukan sekadar gaya kode yang berubah.
"""
import asyncio
import os
import unittest

from app import auth, backup, csrf, db


class Permintaan:
    """Request palsu: cukup punya headers dan client, itu yang dibaca auth."""

    class _Klien:
        def __init__(self, host):
            self.host = host

    def __init__(self, headers=None, host="10.0.0.9"):
        self.headers = headers or {}
        self.client = self._Klien(host)


class TestBukuGagalTertutup(unittest.TestCase):
    """Nama buku kosong dulu jatuh ke buku pemilik, tanpa pesan galat."""

    def test_nama_kosong_melempar(self):
        with self.assertRaises(ValueError):
            db.book_file("")

    def test_nama_dengan_path_melempar(self):
        for nakal in ["../system.db", "a/b.db", "..\\x.db"]:
            with self.assertRaises(ValueError):
                db.book_file(nakal)

    def test_nama_wajar_tetap_jalan(self):
        self.assertTrue(db.book_file("book-7.db").endswith("book-7.db"))


class TestPembatasLogin(unittest.TestCase):
    """X-Forwarded-For dikirim klien. Entri pertama bebas dipalsukan; yang
    dipakai harus entri terakhir, yang ditambahkan proxy di depan kita."""

    def setUp(self):
        auth._fails.clear()

    def test_memakai_entri_terakhir(self):
        r = Permintaan({"x-forwarded-for": "1.1.1.1, 203.0.113.7"})
        self.assertEqual(auth.client_key(r), "203.0.113.7")

    def test_palsu_di_depan_tidak_menambah_jatah(self):
        for i in range(auth.FAIL_MAX):
            auth.note_failure(Permintaan({"x-forwarded-for": f"9.9.9.{i}, 203.0.113.7"}))
        # alamat palsunya berganti tiap kali, tapi yang asli sama: tetap terkunci
        self.assertGreater(auth.locked_for(Permintaan({"x-forwarded-for": "8.8.8.8, 203.0.113.7"})), 0)

    def test_tanpa_header_pakai_alamat_koneksi(self):
        self.assertEqual(auth.client_key(Permintaan(host="198.51.100.4")), "198.51.100.4")

    def test_penguncian_per_akun(self):
        for i in range(auth.FAIL_MAX):
            auth.note_failure(Permintaan(host=f"198.51.100.{i}"), "korban@contoh.id")
        # alamat baru yang belum pernah gagal, tapi akun yang sama sudah terkunci
        self.assertGreater(auth.locked_for(Permintaan(host="203.0.113.99"), "korban@contoh.id"), 0)
        self.assertEqual(auth.locked_for(Permintaan(host="203.0.113.99"), "lain@contoh.id"), 0)

    def test_berhasil_menghapus_kedua_kunci(self):
        r = Permintaan(host="198.51.100.1")
        auth.note_failure(r, "a@b.c")
        auth.note_success(r, "a@b.c")
        self.assertEqual(auth.locked_for(r, "a@b.c"), 0)

    def test_kunci_tidak_menumpuk_tanpa_batas(self):
        for i in range(auth.FAIL_KEYS_MAX + 200):
            auth.note_failure(Permintaan(host=f"10.{i // 256}.{i % 256}.1"))
        self.assertLessEqual(len(auth._fails), auth.FAIL_KEYS_MAX)


class TestBatasUkuranBody(unittest.TestCase):
    """Body dibaca habis ke memori sebelum token diperiksa, jadi harus dibatasi
    sebelum dibaca — bukan sesudah."""

    def _jalankan(self, panjang_diklaim, potongan):
        dipanggil = []

        async def app(scope, receive, send):
            dipanggil.append(True)

        headers = [(b"content-type", b"application/x-www-form-urlencoded")]
        if panjang_diklaim is not None:
            headers.append((b"content-length", str(panjang_diklaim).encode()))
        scope = {"type": "http", "method": "POST", "headers": headers, "path": "/x"}
        sisa = list(potongan)
        keluar = []

        async def receive():
            body = sisa.pop(0) if sisa else b""
            return {"type": "http.request", "body": body, "more_body": bool(sisa)}

        async def send(m):
            keluar.append(m)

        asyncio.run(csrf.CSRFMiddleware(app)(scope, receive, send))
        status = next((m["status"] for m in keluar if m["type"] == "http.response.start"), None)
        return bool(dipanggil), status

    def test_content_length_besar_ditolak_lebih_dulu(self):
        lanjut, status = self._jalankan(csrf.MAX_BODY + 1, [b"x"])
        self.assertFalse(lanjut)
        self.assertEqual(status, 413)

    def test_content_length_berbohong_tetap_ketahuan(self):
        besar = b"x" * (1024 * 1024)
        lanjut, status = self._jalankan(10, [besar] * 20)
        self.assertFalse(lanjut)
        self.assertEqual(status, 413)

    def test_body_wajar_tetap_diperiksa_seperti_biasa(self):
        lanjut, status = self._jalankan(20, [b"a=1"])
        self.assertFalse(lanjut)       # ditolak karena token, bukan karena ukuran
        self.assertEqual(status, 403)


class TestCadanganTerenkripsi(unittest.TestCase):
    """Satu arsip memuat keuangan semua pengguna."""

    def setUp(self):
        self._asli = backup.ENCRYPTION_KEY

    def tearDown(self):
        backup.ENCRYPTION_KEY = self._asli

    def test_tanpa_kunci_tidak_dienkripsi(self):
        backup.ENCRYPTION_KEY = ""
        self.assertFalse(backup.encryption_ready())
        self.assertTrue(backup.object_key({"prefix": "p"}).endswith(".tar.gz"))

    def test_dengan_kunci_isi_berubah_dan_bisa_dipulihkan(self):
        backup.ENCRYPTION_KEY = "kunci uji coba"
        isi = b"buku pengguna" * 500
        tersegel = backup.seal(isi)
        self.assertNotIn(b"buku pengguna", tersegel)
        self.assertEqual(backup.unseal(tersegel), isi)
        self.assertTrue(backup.object_key({"prefix": "p"}).endswith(".tar.gz.enc"))

    def test_kunci_salah_tidak_bisa_membuka(self):
        from cryptography.fernet import InvalidToken
        backup.ENCRYPTION_KEY = "kunci benar"
        tersegel = backup.seal(b"rahasia")
        backup.ENCRYPTION_KEY = "kunci lain"
        with self.assertRaises(InvalidToken):
            backup.unseal(tersegel)


if __name__ == "__main__":
    unittest.main()
