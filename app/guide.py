"""Panduan: apa saja menu di aplikasi ini dan untuk apa.

Ditulis di sini, bukan di template, karena isinya prosa panjang dua bahasa —
sama seperti `legal.py`. Menaruhnya di template berarti ratusan `_()` yang
harus dicocokkan satu per satu di kamus, dan teks panjang paling sering
dilupakan saat kamusnya diperbarui.

Satu aturan saat menambah entri: tulis dulu **untuk apa**, baru **caranya**.
Orang membuka panduan karena tidak tahu menu itu gunanya apa, bukan karena
tidak tahu tombolnya di mana.
"""
from .i18n import get_lang

MENU_ID = [
    dict(slug="bulan", judul="Bulan", untuk="Catat dan lihat satu bulan.", isi=[
        "Angka besar = sisa kas, tagihan yang belum dibayar sudah dipotong.",
        "Karena itu wajar kalau beda dengan saldo m-banking — ini yang aman dipakai.",
        "Tiga tombol: <b>Keluar</b>, <b>Masuk</b>, <b>Pindah</b>.",
        "Geser baris ke kiri untuk hapus.",
    ]),
    dict(slug="kantong", judul="Kantong", untuk="Tempat uangmu berada.", isi=[
        "Rekening, dompet, tabungan, kartu.",
        "Saldo awal diisi sekali, sesudahnya jalan sendiri.",
        "Pindah antar kantong = transfer, bukan belanja.",
        "Tandai mana yang <b>dana darurat</b> — itu yang dipakai Laporan menghitung ketahananmu.",
        "Kartu kredit &amp; paylater mengurangi kekayaan bersih.",
        "Beri <b>target</b> pada tabungan atau investasi — yang tampil sisanya, bukan persennya.",
    ]),
    dict(slug="anggaran", judul="Anggaran", untuk="Jatah belanja per kategori.", isi=[
        "Isi yang ingin dijaga. Sisanya diabaikan.",
        "Merah berarti jebol.",
        "Sisa jatah muncul saat kamu mencatat.",
    ]),
    dict(slug="laporan", judul="Laporan", untuk="Bulanmu dalam kalimat.", isi=[
        "Masuk, keluar, kategori yang melonjak.",
        "<b>Surplus</b> = sisa. <b>Setoran</b> = yang benar-benar dipindahkan. Dua hal berbeda.",
        "Rasio cicilan dan ketahanan dana darurat.",
    ]),
    dict(slug="ringkasan", judul="Ringkasan", untuk="Cari transaksi lintas bulan.", isi=[
        "Saring tahun, jenis, kategori, kata kunci.",
        "Totalnya ikut menyesuaikan.",
    ]),
    dict(slug="aset", judul="Aset", untuk="Nilai barang dan investasi.", isi=[
        "Diisi per bulan, bukan per transaksi.",
        "Untuk melihat kekayaan bersih, bukan cuma kas.",
    ]),
    dict(slug="dokumen", judul="Dokumen", untuk="Impor rekening koran dan tagihan.", isi=[
        "PDF terkunci, XLSX, CSV.",
        "Jadi <b>satu</b> pengeluaran, bukan puluhan baris.",
        "Bisa disimpan tanpa ikut dicatat.",
        "Mau terinci per gesekan? Catat lewat kantong <b>Kartu kredit</b>, bukan dari sini.",
    ]),
    dict(slug="setelan", judul="Setelan", untuk="Atur buku, tampilan, pengguna.", isi=[
        "Kategori, template rutin, mata uang.",
        "Cadangan otomatis dan ekspor.",
        "Ganti password, hapus akun.",
    ]),
]

MENU_EN = [
    dict(slug="bulan", judul="Month", untuk="Record and read one month.", isi=[
        "Big figure = cash left, with unpaid bills already deducted.",
        "So it will differ from your bank balance — this is what is safe to spend.",
        "Three buttons: <b>Out</b>, <b>In</b>, <b>Move</b>.",
        "Swipe a row left to delete.",
    ]),
    dict(slug="kantong", judul="Pockets", untuk="Where your money sits.", isi=[
        "Accounts, wallets, savings, cards.",
        "Opening balance once, then it moves on its own.",
        "Between pockets = transfer, not spending.",
        "Mark which one is your <b>emergency fund</b> — the Report uses it to work out your cover.",
        "Credit cards &amp; paylater reduce your net worth.",
        "Give savings or investments a <b>target</b> — it shows what is left, not a percentage.",
    ]),
    dict(slug="anggaran", judul="Budget", untuk="A spending allowance per category.", isi=[
        "Set the ones you want to watch. The rest are ignored.",
        "Red means over.",
        "The remainder shows up while you record.",
    ]),
    dict(slug="laporan", judul="Report", untuk="Your month in sentences.", isi=[
        "In, out, and which categories spiked.",
        "<b>Surplus</b> = what is left. <b>Moved to savings</b> = what actually shifted. Not the same thing.",
        "Debt ratio and emergency fund cover.",
    ]),
    dict(slug="ringkasan", judul="Overview", untuk="Search across months.", isi=[
        "Filter by year, type, category, keyword.",
        "The total follows your filter.",
    ]),
    dict(slug="aset", judul="Assets", untuk="What your things are worth.", isi=[
        "Entered monthly, not per transaction.",
        "For net worth, not just cash.",
    ]),
    dict(slug="dokumen", judul="Documents", untuk="Import statements and card bills.", isi=[
        "Locked PDF, XLSX, CSV.",
        "Becomes <b>one</b> expense, not dozens of rows.",
        "Can be stored without being recorded.",
        "Want it itemised? Record through a <b>Credit card</b> pocket instead.",
    ]),
    dict(slug="setelan", judul="Settings", untuk="Book, display, users.", isi=[
        "Categories, recurring templates, currency.",
        "Automatic backup and export.",
        "Change password, delete account.",
    ]),
]


# Alamat menunya, dipisah dari teks supaya tidak perlu ditulis dua kali dan
# tidak bisa berbeda antar bahasa.
TAUTAN = {
    "bulan": "/", "kantong": "/accounts", "anggaran": "/anggaran", "laporan": "/report",
    "ringkasan": "/overview", "aset": "/assets", "dokumen": "/dokumen", "setelan": "/settings",
}

# Warna ikon: (hue, saturasi glyph, saturasi latar).
#
# Sebelumnya hue diambil dari hash nama menunya, jadi Aset kebetulan merah muda
# dan Anggaran kebetulan ungu. Mata menangkap bahwa warnanya tidak berarti apa-apa
# meski tidak bisa menyebutkan sebabnya — dan ganti nama menu berarti ganti warna
# tanpa ada yang meminta. Sekarang dipatok, dan tiap warna punya alasan:
#
#   Bulan      biru      warna utama aplikasi, ini halaman yang paling sering dibuka
#   Kantong    hijau     uang yang diam
#   Anggaran   amber     jatah dan batas — warna yang sama dengan peringatan
#   Laporan    ungu      analisis, bukan pencatatan
#   Ringkasan  cyan      penelusuran
#   Aset       hijau daun uang yang tumbuh; dibedakan dari Kantong yang diam
#   Dokumen    terakota  kertas
#   Setelan    netral    ini perkakas, bukan datamu — sengaja nyaris tanpa warna
#
# Hue tetangga dijaga berjauhan supaya dua kartu yang bersebelahan tidak pernah
# terbaca sebagai warna yang sama.
WARNA = {
    "bulan":     (212, 55, 70),
    "kantong":   (150, 55, 70),
    "anggaran":  (38, 62, 75),
    "laporan":   (268, 52, 68),
    "ringkasan": (192, 55, 70),
    "aset":      (96, 50, 62),
    "dokumen":   (14, 58, 70),
    "setelan":   (232, 12, 14),
}


def gaya(slug: str) -> str:
    """Custom property warna ikon, siap ditempel ke atribut style."""
    h, s, b = WARNA.get(slug, (220, 55, 70))
    return f"--h:{h};--gs:{s}%;--gb:{b}%"


def menus() -> list:
    daftar = MENU_EN if get_lang() == "en" else MENU_ID
    return [dict(m, tautan=TAUTAN.get(m["slug"], "/"), gaya=gaya(m["slug"])) for m in daftar]
