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
        "Angka besar = sisa kas. Tagihan sudah dipotong.",
        "Tiga tombol: <b>Keluar</b>, <b>Masuk</b>, <b>Pindah</b>.",
        "Geser baris ke kiri untuk hapus.",
    ]),
    dict(slug="kantong", judul="Kantong", untuk="Tempat uangmu berada.", isi=[
        "Rekening, dompet, tabungan, kartu.",
        "Saldo awal diisi sekali, sesudahnya jalan sendiri.",
        "Pindah antar kantong = transfer, bukan belanja.",
    ]),
    dict(slug="anggaran", judul="Anggaran", untuk="Jatah belanja per kategori.", isi=[
        "Isi yang ingin dijaga. Sisanya diabaikan.",
        "Merah berarti jebol.",
        "Sisa jatah muncul saat kamu mencatat.",
    ]),
    dict(slug="laporan", judul="Laporan", untuk="Bulanmu dalam kalimat.", isi=[
        "Masuk, keluar, kategori yang melonjak.",
        "Rasio menabung, cicilan, ketahanan dana darurat.",
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
    ]),
    dict(slug="setelan", judul="Setelan", untuk="Atur buku, tampilan, pengguna.", isi=[
        "Kategori, template rutin, mata uang.",
        "Cadangan otomatis dan ekspor.",
        "Ganti password, hapus akun.",
    ]),
]

MENU_EN = [
    dict(slug="bulan", judul="Month", untuk="Record and read one month.", isi=[
        "Big figure = cash left. Bills already deducted.",
        "Three buttons: <b>Out</b>, <b>In</b>, <b>Move</b>.",
        "Swipe a row left to delete.",
    ]),
    dict(slug="kantong", judul="Pockets", untuk="Where your money sits.", isi=[
        "Accounts, wallets, savings, cards.",
        "Opening balance once, then it moves on its own.",
        "Between pockets = transfer, not spending.",
    ]),
    dict(slug="anggaran", judul="Budget", untuk="A spending allowance per category.", isi=[
        "Set the ones you want to watch. The rest are ignored.",
        "Red means over.",
        "The remainder shows up while you record.",
    ]),
    dict(slug="laporan", judul="Report", untuk="Your month in sentences.", isi=[
        "In, out, and which categories spiked.",
        "Savings rate, debt ratio, emergency fund cover.",
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


def menus() -> list:
    daftar = MENU_EN if get_lang() == "en" else MENU_ID
    return [dict(m, tautan=TAUTAN.get(m["slug"], "/")) for m in daftar]
