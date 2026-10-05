"""Halaman Kebijakan Privasi & Persyaratan Layanan.

Dibutuhkan Google saat consent screen dipublikasikan, dan memang wajar ada begitu
orang lain ikut memakai. Isinya ditulis apa adanya: apa yang disimpan, di mana,
siapa yang bisa melihat, dan bagaimana menghapusnya.
"""
from .i18n import t

UPDATED = "5 Oktober 2026"
CONTACT = "mrianfathany08@gmail.com"


def _p(*paragraphs) -> str:
    return "".join(f"<p>{x}</p>" for x in paragraphs)


def privacy(host: str) -> str:
    return (
        f"<h3>{t('Data apa yang disimpan')}</h3>"
        + _p(t("Dari Google, aplikasi hanya menerima <b>alamat email</b> dan <b>nama</b> Anda saat masuk. "
               "Izin yang diminta untuk masuk hanya <code>openid</code>, <code>email</code>, dan <code>profile</code>."),
             t("Selebihnya adalah data yang Anda masukkan sendiri: transaksi, kategori, kantong, "
               "nilai aset, dan catatan bulanan."))
        + f"<h3>{t('Akses Gmail (opsional)')}</h3>"
        + _p(t("Kalau Anda menyambungkan Gmail lewat Setelan → Sumber Email, aplikasi meminta izin "
               "<code>gmail.readonly</code> untuk akun itu saja. Yang dibaca hanya email yang cocok dengan "
               "aturan yang Anda buat sendiri (alamat pengirim dan kata di subjek), untuk diubah menjadi draf "
               "transaksi. Tidak ada email yang dikirim, dihapus, atau ditandai."),
             t("Dari email yang cocok, yang disimpan hanya pengirim, subjek, potongan isi, dan hasil bacaannya "
               "(nominal, tanggal, keterangan) di file database Anda. Token akses disimpan terenkripsi. Data dari "
               "Gmail tidak dipakai untuk iklan, tidak dijual, tidak dibagikan, dan tidak dipakai untuk melatih "
               "model AI apa pun."),
             t('Penggunaan informasi yang diterima dari Google API mematuhi <a href="https://developers.google.com/'
               'terms/api-services-user-data-policy">Google API Services User Data Policy</a>, termasuk ketentuan '
               'Limited Use. Memutus sambungan di Setelan mencabut izinnya di Google dan menghapus token beserta '
               'aturannya.'))
        + f"<h3>{t('Di mana disimpan')}</h3>"
        + _p(t("Di satu server di Singapura (Fly.io), dalam <b>file database terpisah milik Anda sendiri</b>. "
               "Pengguna lain memakai file yang berbeda, jadi catatan keuangan Anda tidak pernah tercampur "
               "dan tidak terlihat oleh pengguna lain."),
             t("Pemilik aplikasi dapat mengelola akun (menonaktifkan, menghapus) dan secara teknis memiliki "
               "akses ke server tempat file itu berada. Kalau itu tidak Anda inginkan, jangan memasukkan "
               "data yang sensitif bagi Anda."))
        + f"<h3>{t('Apa yang tidak dilakukan')}</h3>"
        + _p(t("Tidak ada iklan, tidak ada pelacak pihak ketiga, tidak ada analitik. Data Anda tidak dijual, "
               "tidak dibagikan, dan tidak dikirim ke layanan lain. Satu-satunya panggilan keluar adalah ke "
               "Google saat Anda masuk atau menyinkronkan Gmail yang Anda sambungkan, dan ke layanan cuaca terbuka (Open-Meteo) untuk menampilkan cuaca "
               "di halaman masuk."))
        + f"<h3>{t('Cookie')}</h3>"
        + _p(t("Satu cookie sesi bertanda tangan supaya Anda tetap masuk selama 30 hari, dan penyimpanan "
               "lokal peramban untuk pilihan tema terang/gelap. Tidak ada cookie iklan."))
        + f"<h3>{t('Menghapus data Anda')}</h3>"
        + _p(t("Buka Setelan → Akun → Hapus akun. File database Anda dihapus dari server saat itu juga, "
               "beserta seluruh isinya. Tindakan ini tidak bisa dibatalkan. Sebelum menghapus, Anda bisa "
               "mengunduh salinan lengkap lewat Setelan → Backup & ekspor."),
             t("Pertanyaan atau permintaan lain bisa dikirim ke {email}.").replace("{email}", f"<a href='mailto:{CONTACT}'>{CONTACT}</a>"))
    )


def terms(host: str) -> str:
    return (
        f"<h3>{t('Layanan apa ini')}</h3>"
        + _p(t("Muara adalah aplikasi pencatat keuangan pribadi yang dibuat dan dijalankan oleh "
               "satu orang, gratis, dan disediakan apa adanya (<i>as is</i>). Tidak ada jaminan "
               "ketersediaan, dan bisa berubah atau berhenti kapan saja."))
        + f"<h3>{t('Tanggung jawab Anda')}</h3>"
        + _p(t("Anda bertanggung jawab atas isi catatan Anda sendiri dan atas keamanan akun Google yang "
               "dipakai masuk. Jangan memakai aplikasi ini untuk hal yang melanggar hukum."))
        + f"<h3>{t('Angka di aplikasi ini bukan nasihat keuangan')}</h3>"
        + _p(t("Ringkasan, indikator kesehatan, dan saran dihitung dengan aturan sederhana dari angka yang "
               "Anda masukkan sendiri. Gunakan sebagai alat bantu, bukan sebagai nasihat keuangan, pajak, "
               "atau investasi."))
        + f"<h3>{t('Cadangan data')}</h3>"
        + _p(t("Server membuat snapshot volume harian, tetapi itu bukan jaminan. Unduh cadangan Anda "
               "sendiri secara berkala lewat Setelan → Backup & ekspor."))
        + f"<h3>{t('Penghentian akun')}</h3>"
        + _p(t("Anda bisa menghapus akun kapan saja lewat Setelan → Akun. Pemilik aplikasi dapat "
               "menonaktifkan akun yang menyalahgunakan layanan."),
             t("Pertanyaan atau permintaan lain bisa dikirim ke {email}.").replace("{email}", f"<a href='mailto:{CONTACT}'>{CONTACT}</a>"))
    )
