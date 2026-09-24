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
    dict(slug="bulan", judul="Bulan", untuk="Tempat mencatat dan melihat satu bulan berjalan.", isi=[
        "Angka besar di atas adalah sisa kas bulan itu — sudah dipotong semua pengeluaran yang tercatat, termasuk tagihan yang belum kamu tandai dibayar.",
        "Tiga tombol di bawah: <b>Keluar</b> untuk pengeluaran, <b>Masuk</b> untuk pemasukan, <b>Pindah</b> untuk transfer antar kantong.",
        "Kalau kategori yang kamu pilih punya anggaran, sisa jatahnya muncul saat itu juga dan ikut berubah selagi nominalnya diketik.",
        "Geser baris ke kiri untuk menghapus. Tagihan yang belum dibayar muncul terpisah di kartu Tagihan bulan ini.",
    ]),
    dict(slug="kantong", judul="Kantong", untuk="Daftar tempat uangmu berada: rekening, dompet, tabungan, kartu.", isi=[
        "Tiap kantong punya jenis — kas, tabungan, investasi, atau kartu kredit. Jenisnya menentukan bagaimana dia dihitung: hanya kas yang masuk hitungan sisa kas.",
        "Saldo awal diisi sekali. Sesudahnya saldo bergerak sendiri mengikuti transaksi.",
        "Pindah uang antar kantong dicatat sebagai transfer, bukan pengeluaran — supaya memindahkan uang ke tabungan tidak terbaca sebagai belanja.",
    ]),
    dict(slug="anggaran", judul="Anggaran", untuk="Jatah belanja per kategori supaya ketahuan sebelum jebol, bukan sesudah.", isi=[
        "Isi jatah hanya untuk kategori yang ingin kamu jaga. Yang dikosongkan tidak dihitung sama sekali.",
        "Batang progresnya memerah saat terlampaui, dan sisa jatahnya ikut muncul saat kamu mencatat pengeluaran.",
        "Ada baris <i>di luar kategori yang dianggarkan</i> — itu pengeluaran di kategori tanpa jatah. Ditampilkan supaya sisa jatah tidak terbaca lebih lega daripada kenyataan.",
        "Tombol <b>Salin dari</b> menyalin anggaran bulan sebelumnya. Menunya bisa disembunyikan lewat Setelan → Tampilan kalau tidak dipakai.",
    ]),
    dict(slug="laporan", judul="Laporan", untuk="Cerita satu bulan dalam kalimat, bukan tabel angka.", isi=[
        "Menyebutkan berapa yang masuk dan keluar, kategori mana yang melonjak dibanding tiga bulan sebelumnya, dan apa yang perlu diperhatikan.",
        "Ikut menghitung rasio menabung, rasio cicilan terhadap pemasukan, dan berapa bulan dana daruratmu sanggup menutupi pengeluaran.",
        "Kategori bertanda <b>cicilan</b> yang dipakai menghitung rasio cicilan; tandanya diatur di Setelan → Kategori.",
    ]),
    dict(slug="ringkasan", judul="Ringkasan", untuk="Mencari dan menjumlahkan transaksi lintas bulan.", isi=[
        "Saring per tahun, jenis, kategori, atau kata kunci. Totalnya ikut menyesuaikan.",
        "Dipakai saat ingin menjawab pertanyaan seperti “setahun ini habis berapa untuk transport”.",
    ]),
    dict(slug="aset", judul="Aset", untuk="Nilai barang dan investasi yang tidak bergerak tiap hari.", isi=[
        "Diisi sebagai foto nilai per bulan — emas, reksa dana, saham, kendaraan. Bukan transaksi, melainkan nilai terakhir yang kamu ketahui.",
        "Berguna untuk melihat kekayaan bersih, bukan sekadar sisa kas.",
    ]),
    dict(slug="dokumen", judul="Dokumen", untuk="Rekening koran dan tagihan kartu yang diimpor dari berkas bank.", isi=[
        "Menerima PDF e-statement (termasuk yang terkunci password), XLSX, dan CSV. Berkas dan passwordnya tidak pernah disimpan di server.",
        "Aplikasi memecah isinya jadi tanggal, keterangan, dan nominal, lalu menampilkannya untuk kamu periksa. Baris yang tidak terbaca ikut ditampilkan, tidak dibuang diam-diam.",
        "Saat disimpan, dokumen menyumbang <b>satu</b> pengeluaran di bulan tujuan sebesar totalnya — bukan puluhan baris. Yang keluar dari kantongmu bulan itu memang satu pembayaran tagihan.",
        "Matikan <i>Catat sebagai pengeluaran</i> kalau dokumen itu cuma untuk dilihat. Rinciannya tetap tersimpan tanpa menambah angka apa pun.",
    ]),
    dict(slug="setelan", judul="Setelan", untuk="Pengaturan buku, tampilan, pengguna, dan cadangan.", isi=[
        "<b>Rapikan</b> — transaksi hasil impor atau migrasi yang perlu kamu periksa sekali. Aplikasi hanya menyarankan kategori; perubahannya tetap butuh klikmu.",
        "<b>Mata uang</b> — berlaku per buku. Pemisah ribuan dan desimalnya ikut bahasa yang dipilih.",
        "<b>Kategori</b> — tambah, ubah, tandai mana yang cicilan. Kategori bawaan tidak bisa dihapus karena dipakai menampung entri saat kategori lain dihapus.",
        "<b>Template rutin</b> — hal yang berulang tiap bulan seperti KPR atau gaji. Dipakai tombol “Isi bulan ini”.",
        "<b>Buku</b> — bulan pertama yang dicatat.",
        "<b>Tampilan</b> — menu mana yang muncul di navigasi.",
        "<b>Backup &amp; ekspor</b> — unduh berkas database utuh, ekspor Excel, atau buka halaman impor.",
        "<b>Pengguna</b> — hanya untuk superadmin. Tiap orang yang mendaftar mendapat bukunya sendiri dan tidak bisa melihat bukumu.",
        "<b>Cadangan otomatis</b> — status cadangan harian ke penyimpanan di luar server. Kuncinya diatur lewat environment, bukan lewat halaman ini.",
        "<b>Akun</b> — ganti password, hapus akun sendiri, dan tautan ke kebijakan privasi.",
    ]),
]

MENU_EN = [
    dict(slug="bulan", judul="Month", untuk="Where you record and read a single month.", isi=[
        "The big figure at the top is the cash left for that month — already net of every recorded expense, including bills you have not marked as paid.",
        "Three buttons below: <b>Out</b> for an expense, <b>In</b> for income, <b>Move</b> for a transfer between pockets.",
        "If the category you pick has a budget, its remaining allowance appears right there and updates as you type the amount.",
        "Swipe a row left to delete it. Unpaid bills get their own card at the top.",
    ]),
    dict(slug="kantong", judul="Pockets", untuk="Where your money sits: accounts, wallets, savings, cards.", isi=[
        "Every pocket has a type — cash, savings, investment or credit card. The type decides how it counts: only cash feeds the month's cash figure.",
        "Opening balance is entered once. After that the balance moves on its own with your transactions.",
        "Moving money between pockets is recorded as a transfer, not an expense — so putting money into savings does not read as spending.",
    ]),
    dict(slug="anggaran", judul="Budget", untuk="A spending allowance per category, so you find out before you overspend.", isi=[
        "Only set an allowance for the categories you want to watch. Anything left empty is not counted at all.",
        "The progress bar turns red once you pass it, and the remaining allowance shows up while you record an expense.",
        "There is a line for <i>outside budgeted categories</i> — spending in categories with no allowance. It is shown so the remaining figure never looks roomier than reality.",
        "<b>Copy from</b> brings last month's budget across. The menu can be hidden in Settings → Display if you do not use it.",
    ]),
    dict(slug="laporan", judul="Report", untuk="The month told in sentences rather than a table.", isi=[
        "It says what came in and went out, which categories spiked against the previous three months, and what deserves attention.",
        "It also works out your savings rate, debt-to-income ratio, and how many months your emergency fund would cover.",
        "Categories marked <b>debt</b> feed the debt ratio; the mark is set in Settings → Categories.",
    ]),
    dict(slug="ringkasan", judul="Overview", untuk="Search and total transactions across months.", isi=[
        "Filter by year, type, category or keyword. The total follows your filter.",
        "Use it to answer things like “how much went on transport this year”.",
    ]),
    dict(slug="aset", judul="Assets", untuk="The value of things that do not move day to day.", isi=[
        "Recorded as a monthly snapshot — gold, funds, shares, a vehicle. Not transactions, just the latest value you know of.",
        "Useful for seeing net worth rather than only the cash left.",
    ]),
    dict(slug="dokumen", judul="Documents", untuk="Bank statements and card bills imported from a file.", isi=[
        "Accepts PDF e-statements (including password-locked ones), XLSX and CSV. Neither the file nor its password is ever stored on the server.",
        "The app splits the contents into date, description and amount for you to check. Lines it could not read are shown too, never dropped quietly.",
        "When saved, a document contributes <b>one</b> expense in its target month, for its total — not dozens of rows. What actually left your pocket that month was a single bill payment.",
        "Turn off <i>Record as an expense</i> if the document is only meant to be looked at. The detail is still stored without adding to any figure.",
    ]),
    dict(slug="setelan", judul="Settings", untuk="Book, display, users and backup settings.", isi=[
        "<b>Tidy up</b> — transactions from an import or migration that need one look from you. The app only suggests a category; the change still needs your click.",
        "<b>Currency</b> — per book. Thousand and decimal separators follow the chosen language.",
        "<b>Categories</b> — add, rename, mark which ones are debt. Built-in categories cannot be deleted because they catch entries when another category is removed.",
        "<b>Recurring templates</b> — things that repeat every month, like a mortgage or salary. Used by the “Fill this month” button.",
        "<b>Book</b> — the first month you record.",
        "<b>Display</b> — which menus appear in the navigation.",
        "<b>Backup &amp; export</b> — download the whole database file, export to Excel, or open the import page.",
        "<b>Users</b> — superadmin only. Everyone who signs up gets their own book and cannot see yours.",
        "<b>Automatic backup</b> — the status of the daily backup to storage outside the server. Its keys are set through the environment, not this page.",
        "<b>Account</b> — change password, delete your own account, and links to the privacy policy.",
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
