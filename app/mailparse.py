"""Membaca isi email notifikasi bank jadi satu calon transaksi.

Setiap bank punya format email sendiri, tapi isinya hampir selalu sama:
nominal, tanggal, nama merchant/penerima, dan arah (uang keluar atau masuk).
Karena itu parsernya satu, dan tiap bank hanya menambahkan label yang dipakai
di emailnya. Profil BCA, Bank Mega, dan Livin di bawah masih tebakan dari
format yang umum; setelah ada contoh email asli, labelnya disesuaikan di sini.

Yang tidak terbaca tidak dibuang. Draf tetap dibuat dengan nominal kosong,
supaya pemilik buku melihatnya dan bisa mengisi sendiri — sama seperti baris
sisa di halaman Impor.
"""
import re
from datetime import date, datetime, timezone, timedelta

from . import statement

WIB = timezone(timedelta(hours=7))

# Label nominal dan keterangan per bank. Urutan berarti: yang di depan dicoba dulu.
UMUM = dict(
    nominal=("nominal transaksi", "jumlah transaksi", "total transaksi", "nominal", "jumlah",
             "total", "amount", "sebesar"),
    keterangan=("nama merchant", "merchant", "nama toko", "penerima", "nama penerima", "tujuan",
                "rekening tujuan", "keterangan", "berita", "deskripsi", "description", "pembayaran"),
)

PROFILES = {
    "umum": dict(label="Umum", **UMUM),
    "bca": dict(label="BCA", nominal=("nominal", "jumlah") + UMUM["nominal"],
                keterangan=("merchant", "nama penerima", "keterangan") + UMUM["keterangan"]),
    "mega": dict(label="Bank Mega", nominal=("nilai transaksi", "jumlah tagihan") + UMUM["nominal"],
                 keterangan=("merchant", "lokasi transaksi") + UMUM["keterangan"]),
    "livin": dict(label="Livin' by Mandiri", nominal=("nominal transaksi", "total pembayaran") + UMUM["nominal"],
                  keterangan=("penerima", "nama penerima", "tujuan transaksi") + UMUM["keterangan"]),
}

RE_MATA_UANG = re.compile(r"(?:Rp\.?|IDR)\s*([\d][\d.,]*)", re.I)
RE_ANGKA = re.compile(r"([\d][\d.,]*\d|\d)")
# "kartu kredit" dan "credit card" bukan uang masuk; dibuang dulu sebelum mencari arah.
RE_BUKAN_ARAH = re.compile(r"kartu kredit|credit card|limit kredit", re.I)
RE_MASUK = re.compile(r"\b(dana masuk|uang masuk|transfer masuk|menerima|diterima|telah masuk|"
                      r"incoming|received|refund|pengembalian dana|cashback)\b", re.I)
RE_TANGGAL_LABEL = re.compile(r"(tanggal|tgl|date|waktu)", re.I)


def _setelah_label(lines: list, labels: tuple):
    """Nilai di sebelah label: 'Merchant : TOKO X', 'Merchant | TOKO X', atau baris berikutnya."""
    for label in labels:
        pola = re.compile(rf"^\s*{re.escape(label)}\b\s*(?:[:|=-]\s*)?(.*)$", re.I)
        for i, b in enumerate(lines):
            m = pola.match(b)
            if not m:
                continue
            nilai = m.group(1).strip(" :|-")
            if not nilai and i + 1 < len(lines):
                nilai = lines[i + 1].strip(" :|-")
            if nilai:
                return nilai
    return None


def nominal(lines: list, labels: tuple):
    """Satuan perseratus, atau None. Label lebih dipercaya daripada 'Rp' pertama,
    karena email kartu kredit sering memuat sisa limit sebelum nominal belanjanya."""
    nilai = _setelah_label(lines, labels)
    if nilai:
        m = RE_MATA_UANG.search(nilai) or RE_ANGKA.search(nilai)
        if m and (v := statement.angka(m.group(1))):
            return v
    for b in lines:
        m = RE_MATA_UANG.search(b)
        if m and (v := statement.angka(m.group(1))):
            return v
    return None


def tanggal(lines: list, received_epoch: int) -> str:
    """Tanggal transaksi dari isi email; kalau tidak ada, tanggal email diterima (WIB)."""
    tahun = date.today().year
    for b in lines:
        if RE_TANGGAL_LABEL.search(b) and (t := statement.tanggal(b, tahun)):
            return t
    if received_epoch:
        return datetime.fromtimestamp(received_epoch, WIB).date().isoformat()
    return date.today().isoformat()


def arah(teks: str) -> str:
    return "income" if RE_MASUK.search(RE_BUKAN_ARAH.sub(" ", teks)) else "expense"


def parse(text: str, subject: str = "", parser: str = "umum", received_epoch: int = 0) -> dict:
    """{type, amount, tx_date, description}. amount None = tidak terbaca."""
    prof = PROFILES.get(parser) or PROFILES["umum"]
    lines = [" ".join(b.split()) for b in (text or "").splitlines() if b.strip()]
    ket = _setelah_label(lines, prof["keterangan"])
    if ket:
        ket = RE_MATA_UANG.sub("", ket).strip(" :|-") or None
    return dict(
        type=arah(f"{subject}\n{text}"),
        amount=nominal(lines, prof["nominal"]),
        tx_date=tanggal(lines, received_epoch),
        description=(ket or subject or "").strip()[:120] or None,
    )


def snippet(text: str, limit: int = 600) -> str:
    """Potongan isi untuk ditampilkan di draf, supaya pemilik bisa memeriksa bacaannya."""
    return " · ".join(b.strip() for b in (text or "").splitlines() if b.strip())[:limit]
