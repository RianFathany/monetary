"""Baca isi berkas yang dikirim bank: PDF e-statement, XLSX, atau CSV.

Dua langkah: mengubah berkas jadi baris teks, lalu memecah baris itu jadi
tanggal, keterangan, dan nominal. Aturan pemecahnya umum dulu, bukan per bank —
dan setiap baris yang tidak terbaca ikut ditampilkan apa adanya, supaya yang
meleset kelihatan dan bisa dibetulkan. Diam-diam membuang baris yang tidak cocok
jauh lebih berbahaya daripada mengakui belum bisa membacanya.

Berkas dan passwordnya hanya ada di memori. Tidak pernah ditulis ke volume,
tidak pernah masuk log, tidak disimpan di database. E-statement memuat nomor
rekening dan seluruh riwayat belanja; satu-satunya tempat aman untuknya adalah
tidak di mana-mana.

Ada batas ukuran karena mesinnya 256 MB: berkas besar yang dibuka sekaligus di
memori bisa menjatuhkan seluruh aplikasi, dan cadangan pun ikut berhenti.
"""
import csv
import io
import re
import zipfile
from datetime import date

from .money import SCALE

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


# ---------- memecah baris jadi transaksi ----------
#
# Aturannya sengaja umum dulu, bukan per bank. Setiap baris yang tidak terbaca
# ditampilkan apa adanya di halaman, jadi yang meleset kelihatan dan bisa
# dibetulkan — lebih jujur daripada diam-diam membuang baris yang tidak cocok.

BULAN = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "mei": 5, "may": 5, "jun": 6,
         "jul": 7, "agu": 8, "aug": 8, "sep": 9, "okt": 10, "oct": 10,
         "nov": 11, "des": 12, "dec": 12}

RE_TGL_ANGKA = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{2,4}))?\b")
RE_TGL_NAMA = re.compile(r"\b(\d{1,2})[ \-]([A-Za-z]{3})[A-Za-z]*[ \-]?(\d{2,4})?\b")
RE_NOMINAL = re.compile(r"(?<![\w/.,-])(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+[.,]\d{2}|\d{3,})(?![\d/])")
RE_ARAH_KELUAR = re.compile(r"\b(db|dr|debit|debet)\b", re.I)
RE_ARAH_MASUK = re.compile(r"\b(cr|kr|kredit|credit)\b", re.I)


def angka(teks: str):
    """'1.234.567,00', '1,234,567.00', '35000' -> satuan perseratus, atau None.

    Pemisah ribuan di Indonesia titik dan desimalnya koma, tapi banyak bank
    mencetak gaya Inggris. Yang dipakai: pemisah terakhir adalah desimal kalau
    diikuti satu atau dua angka; selain itu semuanya pemisah ribuan.
    """
    t = re.sub(r"[^\d.,-]", "", teks or "").strip("-")
    if not t or not any(c.isdigit() for c in t):
        return None
    titik, koma = t.rfind("."), t.rfind(",")
    pisah = max(titik, koma)
    if pisah >= 0 and len(t) - pisah - 1 in (1, 2) and t.count(t[pisah]) == 1 and pisah > 0:
        utuh, pecahan = t[:pisah], t[pisah + 1:]
    else:
        utuh, pecahan = t, ""
    utuh = re.sub(r"[.,]", "", utuh)
    if not utuh.isdigit():
        return None
    nilai = int(utuh) * SCALE
    if pecahan.isdigit():
        nilai += int(pecahan.ljust(2, "0")[:2]) * (SCALE // 100)
    return nilai


def tanggal(teks: str, tahun: int = 0):
    """ISO yyyy-mm-dd dari potongan awal baris, atau None."""
    tahun = tahun or date.today().year
    m = RE_TGL_NAMA.search(teks)
    if m and m.group(2).lower()[:3] in BULAN:
        hari, bulan = int(m.group(1)), BULAN[m.group(2).lower()[:3]]
        thn = int(m.group(3)) if m.group(3) else tahun
    else:
        m = RE_TGL_ANGKA.search(teks)
        if not m:
            return None
        hari, bulan = int(m.group(1)), int(m.group(2))
        thn = int(m.group(3)) if m.group(3) else tahun
    if thn < 100:
        thn += 2000
    if not (1 <= hari <= 31 and 1 <= bulan <= 12 and 2000 <= thn <= 2100):
        return None
    try:
        return date(thn, bulan, hari).isoformat()
    except ValueError:
        return None


def pecah(baris: list, tahun: int = 0) -> tuple:
    """(transaksi, baris_sisa).

    Satu baris dianggap transaksi kalau ada tanggal **dan** nominal. Kalau
    nominalnya lebih dari satu, yang terakhir dianggap saldo berjalan — hampir
    semua rekening koran mencetak kolom saldo di paling kanan.
    """
    hasil, sisa = [], []
    for b in baris:
        tgl = tanggal(b, tahun)
        angkanya = [a for a in (angka(m.group(1)) for m in RE_NOMINAL.finditer(b)) if a]
        if not tgl or not angkanya:
            sisa.append(b)
            continue
        saldo = angkanya[-1] if len(angkanya) > 1 else None
        nilai = angkanya[-2] if len(angkanya) > 1 else angkanya[0]
        ket = b
        for m in RE_TGL_NAMA.finditer(b):
            ket = ket.replace(m.group(0), " ", 1)
        for m in RE_TGL_ANGKA.finditer(b):
            ket = ket.replace(m.group(0), " ", 1)
        for m in RE_NOMINAL.finditer(b):
            ket = ket.replace(m.group(1), " ", 1)
        ket = " ".join(ket.replace("|", " ").split()).strip(" -·")
        masuk = bool(RE_ARAH_MASUK.search(b)) and not RE_ARAH_KELUAR.search(b)
        hasil.append(dict(tanggal=tgl, keterangan=ket or "—", nilai=nilai,
                          saldo=saldo, masuk=masuk, mentah=b))
    return hasil, sisa
