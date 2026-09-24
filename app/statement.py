"""Baca isi berkas yang dikirim bank: PDF e-statement, XLSX, atau CSV.

Yang dikerjakan di sini baru satu hal — mengubah berkas jadi baris-baris teks.
Memecah baris itu menjadi transaksi adalah urusan parser per bank, karena tiap
bank menyusun kolomnya sendiri dan tidak ada gunanya berpura-pura ada satu
bentuk baku.

Berkas dan passwordnya hanya ada di memori. Tidak pernah ditulis ke volume,
tidak pernah masuk log, tidak disimpan di database. E-statement memuat nomor
rekening dan seluruh riwayat belanja; satu-satunya tempat aman untuknya adalah
tidak di mana-mana.

Ada batas ukuran karena mesinnya 256 MB: berkas besar yang dibuka sekaligus di
memori bisa menjatuhkan seluruh aplikasi, dan cadangan pun ikut berhenti.
"""
import csv
import io
import zipfile

MAKS_BYTE = 8 * 1024 * 1024        # 8 MB; e-statement sebulan jauh di bawah ini
MAKS_BARIS = 5000                  # penjaga kalau ada berkas yang isinya ribuan halaman


class Gagal(Exception):
    """Alasan yang bisa ditunjukkan ke pengguna apa adanya."""


def _teks_pdf(blob: bytes, password: str) -> list:
    try:
        from pypdf import PdfReader
        from pypdf.errors import DependencyError, PdfReadError
    except ImportError:                                 # pragma: no cover
        raise Gagal("Pembaca PDF belum terpasang di server.")

    try:
        reader = PdfReader(io.BytesIO(blob))
    except PdfReadError:
        raise Gagal("Berkas ini tidak terbaca sebagai PDF.")

    if reader.is_encrypted:
        if not password:
            raise Gagal("PDF ini terkunci. Isi passwordnya.")
        try:
            if not reader.decrypt(password):
                raise Gagal("Password PDF salah.")
        except DependencyError:
            raise Gagal("Jenis enkripsi PDF ini belum didukung server.")
        except (PdfReadError, NotImplementedError):
            raise Gagal("Jenis enkripsi PDF ini belum didukung server.")

    baris = []
    for halaman in reader.pages:
        try:
            teks = halaman.extract_text() or ""
        except Exception:                               # satu halaman rusak tidak boleh menggagalkan semuanya
            teks = ""
        for b in teks.splitlines():
            b = " ".join(b.split())
            if b:
                baris.append(b)
    if not baris:
        raise Gagal("PDF terbaca tapi tidak ada teks di dalamnya — "
                    "kemungkinan hasil pindaian, bukan e-statement asli.")
    return baris


def _teks_xlsx(blob: bytes) -> list:
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(blob), read_only=True, data_only=True)
    except (zipfile.BadZipFile, KeyError, ValueError):
        raise Gagal("Berkas ini tidak terbaca sebagai XLSX.")
    baris = []
    for ws in wb.worksheets:
        for sel in ws.iter_rows(values_only=True):
            isi = [str(s).strip() for s in sel if s is not None and str(s).strip()]
            if isi:
                baris.append(" | ".join(isi))
            if len(baris) >= MAKS_BARIS:
                break
    wb.close()
    if not baris:
        raise Gagal("Berkas XLSX-nya kosong.")
    return baris


def _teks_csv(blob: bytes) -> list:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            teks = blob.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:                                               # pragma: no cover
        raise Gagal("Berkas CSV-nya tidak terbaca.")

    contoh = teks[:4096]
    try:
        dialek = csv.Sniffer().sniff(contoh, delimiters=",;\t|")
    except csv.Error:
        dialek = csv.excel                              # koma, tebakan paling umum
    baris = []
    for sel in csv.reader(io.StringIO(teks), dialek):
        isi = [s.strip() for s in sel if s and s.strip()]
        if isi:
            baris.append(" | ".join(isi))
        if len(baris) >= MAKS_BARIS:
            break
    if not baris:
        raise Gagal("Berkas CSV-nya kosong.")
    return baris


def ekstrak(nama: str, blob: bytes, password: str = "") -> list:
    """Baris teks dari berkas, atau Gagal dengan alasan yang bisa dibaca orang."""
    if not blob:
        raise Gagal("Berkasnya kosong.")
    if len(blob) > MAKS_BYTE:
        raise Gagal(f"Berkasnya terlalu besar ({len(blob) // (1024 * 1024)} MB). "
                    f"Batasnya {MAKS_BYTE // (1024 * 1024)} MB.")

    akhiran = (nama or "").lower().rsplit(".", 1)[-1]
    if akhiran == "pdf" or blob[:5] == b"%PDF-":
        return _teks_pdf(blob, password)
    if akhiran == "xlsx" or blob[:2] == b"PK":
        return _teks_xlsx(blob)
    if akhiran in ("csv", "txt"):
        return _teks_csv(blob)
    raise Gagal("Format yang didukung: PDF, XLSX, dan CSV.")
