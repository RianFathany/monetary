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
from pathlib import Path
from datetime import date, datetime, timezone, timedelta

from . import banks, statement

WIB = timezone(timedelta(hours=7))

# Label nominal dan keterangan per bank. Urutan berarti: yang di depan dicoba dulu.
UMUM = dict(
    nominal=("nominal transaksi", "jumlah transaksi", "total transaksi", "nominal", "jumlah",
             "total", "amount", "sebesar"),
    keterangan=("nama merchant", "merchant", "nama toko", "penerima", "nama penerima", "tujuan",
                "rekening tujuan", "keterangan", "berita", "deskripsi", "description", "pembayaran"),
)

# sender + keywords = isian bawaan saat pengguna memilih bank di Setelan. Pengirim
# sengaja domain, bukan alamat lengkap: bank memakai beberapa alamat notifikasi,
# dan from:(domain) di Gmail menangkap semuanya. Email promo dari domain yang sama
# disaring kata kunci subjek, lalu parser (nominal kosong = tetap draf, bukan transaksi).
# Tiga bank di bawah punya label baca sendiri; bank lain dari app/banks.py memakai label umum.
KHUSUS = {
    "bca": dict(color="#0060AF", mark="BCA", keywords="transaksi, transfer, pembayaran, notifikasi",
                nominal=("nominal", "jumlah") + UMUM["nominal"],
                keterangan=("merchant", "nama penerima", "keterangan") + UMUM["keterangan"]),
    "mega": dict(color="#E8731A", mark="mega", keywords="transaksi, tagihan, pembayaran",
                 nominal=("nilai transaksi", "jumlah tagihan") + UMUM["nominal"],
                 keterangan=("merchant", "lokasi transaksi") + UMUM["keterangan"]),
    "livin": dict(color="#003D79", mark="mdr", keywords="berhasil, transaksi, transfer, pembayaran, top up",
                  nominal=("nominal transaksi", "total pembayaran") + UMUM["nominal"],
                  keterangan=("penerima", "nama penerima", "tujuan transaksi") + UMUM["keterangan"]),
}

# Logo asli diunduh sekali ke app/static/banks/<kunci>.png (scripts/fetch_bank_logos.py).
# Tidak ada file = kotak warna + singkatan; aplikasi tidak pernah memanggil layanan logo saat berjalan.
_LOGO_DIR = Path(__file__).parent / "static" / "banks"

PROFILES = {}
for _b in banks.ALL:
    _p = dict(label=_b["name"], short=_b["short"], sender=_b["sender"], region=_b["region"],
              color="", mark=_b["short"][:4], keywords="transaksi, transfer, pembayaran", **UMUM)
    _p.update(KHUSUS.get(_b["key"], {}))
    _p["logo"] = f"/static/banks/{_b['key']}.png" if (_LOGO_DIR / f"{_b['key']}.png").is_file() else ""
    PROFILES[_b["key"]] = _p
PROFILES["umum"] = dict(label="Bank lain", short="Lainnya", mark="", color="", sender="", region="",
                        keywords="transaksi", logo="", **UMUM)

# Logo bank untuk baris transaksi/kantong: dicocokkan dari teks (keterangan atau nama kantong).
# Kata yang juga kata biasa (raya, jago, blu, wise, ...) hanya cocok lewat nama lengkapnya,
# supaya "Gaji raya" tidak dapat logo Bank Raya.
_SAMAR = {"raya", "neo", "blu", "allo", "jago", "wise", "krom", "hana", "citi", "chase", "dki", "jatim",
          "jateng", "nagari", "sumut", "permata", "panin", "mnc", "raya", "superbank", "line", "anz", "sc", "qnb"}
_ALIAS = []
for _k, _p in PROFILES.items():
    if not _p.get("logo"):
        continue
    names = {_p["label"].lower(), _p["short"].lower()}
    if _p["short"].lower() not in _SAMAR:
        names.add(_k)
    if _k == "livin":
        names |= {"mandiri", "livin", "bank mandiri"}
    names = {n for n in names if n not in _SAMAR and len(n) >= 3}
    _ALIAS += [(n, _p["logo"]) for n in names]
_ALIAS.sort(key=lambda a: -len(a[0]))      # nama terpanjang dulu: "bank mega syariah" sebelum "mega"


def bank_logo(text) -> str:
    """Path logo bank yang disebut di teks, atau "" kalau tidak ada."""
    if not text:
        return ""
    t = " " + " ".join(re.findall(r"[a-z0-9']+", str(text).lower())) + " "
    for name, logo in _ALIAS:
        if f" {name} " in t:
            return logo
    return ""


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
