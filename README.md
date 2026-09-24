# Muara

Catatan keuangan pribadi: kas, kantong (dana darurat, tabungan, investasi), dan snapshot aset.
Pengganti spreadsheet `MRFNIP - Cashflow.xlsx` — satu user, satu file SQLite, mobile-first.

Uang yang cuma **pindah tempat** (menabung, setor dana darurat, isi ulang rekening belanja)
dicatat sebagai transfer, bukan pengeluaran. Itu bedanya dengan spreadsheet asal, yang
menghitung setoran tabungan sebagai belanja sehingga angka bulanannya menggelembung.

## Jalankan lokal (tanpa Docker)

```bash
cd monetary
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --port 8765 --reload
# Pertama kali: set password sekali lewat
#   .venv/bin/python -c "from app import auth; auth.bootstrap(); auth.set_password('PASSWORD')"
# Setelah itu ganti lewat Setelan > Akun > Ganti password.
```

Buka http://127.0.0.1:8765

## Jalankan dengan Docker

```bash
docker compose up -d --build    # http://127.0.0.1:8765
# Set password pertama kali (sekali saja):
#   docker compose exec monetary python -c "from app import auth; auth.bootstrap(); auth.set_password('PASSWORD')"
```

Database ada di `./data/monetary.db` (volume). Backup = salin file itu.

## Tes

```bash
.venv/bin/python -m unittest discover -s tests -t .
```

31 tes, tanpa dependensi tambahan (`unittest` bawaan) dan tanpa menyentuh database
asli — tiap tes membuat datanya sendiri di memori. Yang dikunci: aturan saldo
(transfer memindah, bukan menghabiskan), ringkasan bulan, untung/rugi investasi
dihitung dari modal, indikator laporan, perilaku saat start (menolak skema lama,
mengadopsi database siap-pakai), dan konversi dari bentuk lama — termasuk kasus
satu kejadian yang tercatat dua kali di spreadsheet.

## Import dari spreadsheet

Spreadsheet memakai bentuk lama (kas & dana darurat sebagai dua kolom terpisah), jadi
impornya dua langkah: masuk ke database bentuk lama, lalu dikonversi ke skema aplikasi.

```bash
.venv/bin/python scripts/import_xlsx.py "../reference/MRFNIP - Cashflow (2).xlsx" --reset
.venv/bin/python scripts/migrate_v2.py --src data/monetary-v1.db          # pratinjau, tidak menulis
.venv/bin/python scripts/migrate_v2.py --src data/monetary-v1.db --apply  # tulis ke data/monetary-v2.db
```

Pratinjaunya menampilkan perbandingan tiap bulan, pasangan baris yang digabung, baris yang
perlu ditinjau, dan **pemeriksaan**: sisa kas & saldo dana darurat hasil konversi harus sama
persis dengan hitungan lama. Transaksi hasil tebakan ditandai `needs_review` dan muncul
sebagai label "cek" di aplikasi.

## Deploy ke Fly.io (muara.rianfathany.com)

```bash
brew install flyctl && fly auth login
cd monetary
fly launch --copy-config --no-deploy        # pakai fly.toml yang ada, region sin
fly volumes create monetary_data --size 1 --region sin
fly deploy
fly certs add muara.rianfathany.com         # lalu tambah A + AAAA di Cloudflare (DNS only, bukan proxied)
```

Domain lama tetap dilayani dan dialihkan permanen ke domain utama lewat
`CANONICAL_HOST` dan `REDIRECT_HOSTS` di `fly.toml`. Kosongkan keduanya kalau
tidak ada domain lama.

```bash
```

Setelah deploy, jalankan import sekali: `fly ssh console -C "python scripts/import_xlsx.py /tmp/cashflow.xlsx --reset"` (upload file dulu dengan `fly ssh sftp shell`), atau cukup salin `data/monetary.db` lokal ke volume.

## Bahasa

Antarmuka tersedia dalam **Bahasa Indonesia** (bawaan) dan **English**, diganti lewat
Setelan > Bahasa. Pilihannya disimpan di tabel `settings` (`lang`), dibaca sekali per
permintaan lewat middleware, lalu dipakai oleh:

- template — teks dibungkus `{{ _('...') }}`, kunci kamus = teks Indonesia apa adanya;
- filter angka & tanggal — `month_label`, `fmt_date`, `short` (jt/rb vs M/k);
- narasi laporan di `report.py` — `t("... {placeholder}", placeholder=...)`;
- JavaScript — string dikirim lewat `window.I18N` di `base.html`.

Menambah teks baru: tulis apa adanya dalam bahasa Indonesia, bungkus `_()`, lalu tambahkan
satu baris di `app/lang_en.py`. Tes `tests/test_i18n.py` gagal kalau ada yang terlewat.
Narasi laporan disimpan per bahasa (`engine = "rules:id"` / `"rules:en"`), jadi ganti bahasa
tidak membuat laporan lama dihitung ulang.

## Login

Satu password, disimpan sebagai hash PBKDF2 di tabel `settings` bersama secret cookie (dibuat otomatis) — tidak butuh `.env`. Ganti lewat Setelan › Akun. Cookie 30 hari. Halaman login memakai rule yang sama dengan rianfathany.com: klip Jakarta sesuai jam (pagi/siang/senja/malam) dan otomatis klip hujan bila sedang hujan (Open-Meteo), plus jam dan nama kota dari geolocation browser (fallback Jakarta). Klip disalin dari `application/assets/video/`. Tombol keluar ada di header kanan atas.

## Masuk dengan Google (opsional)

Tombol "Masuk dengan Google" di halaman login hanya muncul kalau Client ID, Client Secret,
dan daftar email sudah diisi di **Setelan → Akun → Masuk dengan Google**. Password tetap
jalan sebagai cadangan.

Sekali saja di [console.cloud.google.com](https://console.cloud.google.com):

1. **New Project** → beri nama (mis. `Muara`) → Create.
2. **APIs & Services → OAuth consent screen** → User type **External** → Create.
   Isi App name, User support email, Developer contact. Simpan. Biarkan status **Testing**.
3. Di halaman yang sama → **Audience / Test users → Add users** → masukkan email Google
   yang akan dipakai masuk. Mode Testing hanya melayani email di daftar ini (maks. 100).
4. **APIs & Services → Credentials → Create credentials → OAuth client ID** →
   Application type **Web application**.
5. **Authorized redirect URIs → Add URI**, isi keduanya:
   - `https://muara.rianfathany.com/auth/google/callback`
   - `http://127.0.0.1:8765/auth/google/callback` (untuk uji di laptop)
6. Create → salin **Client ID** dan **Client secret**.
7. Pasang kredensialnya di environment — **hanya di sana**, tidak ada formnya di
   aplikasi: `fly secrets set GOOGLE_CLIENT_ID=… GOOGLE_CLIENT_SECRET=… GOOGLE_ALLOWED=…`
   Di laptop, tulis di `.env`. Tombol "Masuk dengan Google" muncul sendiri begitu
   keduanya terbaca.
8. `GOOGLE_ALLOWED` berisi email yang mewarisi buku pemilik (pisahkan dengan koma).
   Email lain yang mendaftar dapat buku kosong sendiri.

Yang dipakai hanya scope `openid email profile`; aplikasi tidak meminta akses apa pun ke
data Google lain. Email harus berstatus terverifikasi di Google dan ada di daftar izin.

**Kalau sesi habis** (30 hari), halaman yang sedang terbuka tidak dilempar keluar: muncul
popup untuk mengisi password lagi, dan kiriman form yang tertahan dilanjutkan setelah itu.
Refresh halaman tetap mengarah ke `/login` seperti biasa.

## Banyak pengguna, data terpisah

Satu pengguna = **satu file database**. Pemisahannya di tingkat file, bukan kolom,
supaya tidak ada satu pun query yang bisa lupa menyaring milik siapa:

```
data/monetary.db      buku pemilik (data lama Anda, tidak berubah)
data/books/book-2.db  buku pengguna kedua, dst.
data/system.db        daftar pengguna + setelan aplikasi (password pemilik, secret, konfigurasi Google)
```

Alur masuk lewat Google:

| Email | Hasil |
|---|---|
| sudah terdaftar | masuk ke bukunya sendiri |
| ada di **daftar izin** (Setelan → Akun) | masuk ke **buku pemilik** — untuk pasangan/keluarga yang memang berbagi catatan |
| email lain, pendaftaran dibuka | dibuatkan **buku kosong** berisi kategori & kantong bawaan |
| email lain, pendaftaran ditutup | ditolak dengan pesan |


**Ukuran & kecepatan** (diukur 2026-09-23, data asli 336 transaksi):
halaman dirender 4–9 ms; dengan simulasi 10.416 transaksi (≈10 tahun) query terberat
tetap di bawah 2,5 ms. Buku kosong baru = 84 KB, jadi volume 1 GB di Fly muat belasan ribu
buku. Membuka koneksi per permintaan 0,33 ms — tidak perlu connection pool.

Indeks sengaja **parsial** (`WHERE deleted_at IS NULL`) dan mengikuti bentuk query yang
ada; versi lama yang berawalan `ledger_id` tidak pernah terpakai oleh query mana pun
(semua query memfilter `month_key`, bukan `ledger_id`) dan dibuang otomatis saat skema
diterapkan. Pragma: WAL, `synchronous=NORMAL`, `busy_timeout=5000`, cache 8 MB,
`temp_store=MEMORY`, plus `ANALYZE` sekali saat buku disiapkan.

**Update aplikasi = semua buku ikut naik versi.** Perubahan skema ditulis sekali di
`app/schema.py`:

```python
SCHEMA_VERSION = 3
MIGRATIONS = {3: ["ALTER TABLE transactions ADD COLUMN tag TEXT"]}
```

Saat aplikasi start, `upgrade_all_books()` menaikkan versi **setiap** file buku (pemilik
dan seluruh pengguna) dan mencatatnya di log; buku yang kebetulan tidak ikut — misalnya
dibuat oleh proses lain — diperbaiki begitu dibuka, karena `set_book()` memanggil
`ensure_book()` (sekali per buku per proses). Tabel/indeks baru cukup ditulis di `SCHEMA`
(semuanya `IF NOT EXISTS`); `MIGRATIONS` hanya untuk yang tidak bisa dinyatakan begitu,
seperti `ALTER TABLE`. Kategori bawaan yang baru ditambahkan ikut ter-seed ke buku lama.
Perilaku ini dijaga oleh `tests/test_users.py::TestPembaruanSkema`.


**Dua jalan masuk.** Pengguna bisa mendaftar lewat Google (SSO) atau lewat email +
password di `/register`. Keduanya menghasilkan hal yang sama: satu akun dan satu file
buku kosong.

Karena aplikasi ini tidak mengirim surel, email dari pendaftaran password **tidak
diverifikasi**. Risikonya jelas (orang bisa mendaftar memakai email orang lain), dan
ditangani begitu pemilik email sebenarnya masuk lewat Google: akunnya ditandai
terverifikasi, password lama dibuang, dan seluruh sesi lama dicabut — jadi pendaftar
semula kehilangan akses, sementara bukunya tetap utuh untuk pemilik email yang sah.

Kolom `users.session_epoch` dinaikkan setiap password diganti atau akun diambil alih;
cookie membawa angka itu, sehingga sesi di perangkat lain berhenti berlaku tanpa perlu
memutar secret aplikasi (yang akan mengeluarkan semua pengguna sekaligus).

Middleware menentukan file buku sekali per permintaan dari sesi (`app/main.py`,
`_book_and_language`), lalu semua query memakai `get_db()` seperti biasa tanpa tahu
siapa penggunanya. Setelan yang berlaku untuk seluruh aplikasi diambil lewat
`get_app_setting()` (system.db), setelan per buku tetap lewat `get_setting(db, ...)`.

Pemilik mengelola pengguna di **Setelan → Pengguna**: melihat daftar, menonaktifkan
akun (bukunya tidak dihapus), dan menutup pendaftaran baru. Ganti password dan
konfigurasi Google hanya bisa disentuh pemilik.

Selama OAuth consent screen Google masih mode **Testing**, hanya email yang Anda
daftarkan sebagai *test user* di Google yang bisa sampai ke halaman pendaftaran —
itu lapis pertama, tombol "Izinkan pendaftaran baru" lapis kedua.


**Membuka pendaftaran untuk umum** (Google Console → Audience → **Publish app**).
Karena scope-nya non-sensitif (`openid email profile`), tidak perlu verifikasi Google.
Yang diminta consent screen sudah tersedia di aplikasi:

| Kolom di Google | Isi |
|---|---|
| Application home page | `https://muara.rianfathany.com` |
| Privacy policy URL | `https://muara.rianfathany.com/privacy` |
| Terms of service URL | `https://muara.rianfathany.com/terms` |
| Authorized domain | `rianfathany.com` |

Kedua halaman itu dirender dari `app/legal.py` (dwibahasa, tanpa perlu login) dan
menyebut apa adanya: hanya email + nama yang diambil dari Google, data disimpan di
file terpisah per pengguna di Fly region Singapura, tidak ada iklan/pelacak, dan cara
menghapus akun. Pengguna non-pemilik bisa menghapus akunnya sendiri lewat
**Setelan → Akun → Hapus akun**: baris pengguna dan file bukunya hilang saat itu juga.

## Surel: verifikasi email & lupa password

Pengiriman lewat **Resend** (HTTPS, tanpa dependensi baru). API key dan alamat pengirim
diatur di **Setelan → Akun → Pengiriman surel** (superadmin), lengkap dengan tombol
"Kirim surel uji". Tanpa konfigurasi ini aplikasi tetap jalan — hanya saja tautan
verifikasi dan pemulihan password tidak terkirim, dan halaman `/forgot` mengatakannya
terus terang.

Persiapan sekali di Resend: tambah domain `rianfathany.com`, salin catatan SPF & DKIM ke
Cloudflare, tunggu terverifikasi, lalu buat API key.

| Alur | Masa berlaku | Aturannya |
|---|---|---|
| Verifikasi email (`/verify`) | 3 hari | Dikirim otomatis saat mendaftar pakai email+password; bisa dikirim ulang dari Setelan |
| Lupa password (`/forgot` → `/reset`) | 1 jam | Halaman selalu menjawab sama, terdaftar atau tidak, supaya alamat tidak bisa ditebak |

Token ditandatangani (itsdangerous) dan membawa `session_epoch` + potongan hash password
saat itu, jadi **sekali pakai**: begitu password berganti, tautan lama langsung mati.
Setelah reset berhasil, email otomatis dianggap terverifikasi (tautannya sampai ke kotak
masuk) dan semua sesi lama dicabut.

## Cadangan otomatis ke luar server

Volume Fly hanya punya snapshot harian milik Fly sendiri. Sejak aplikasi dipakai orang
lain, salinan di tempat kedua jadi wajib. Diatur di **Setelan → Cadangan otomatis**
(superadmin): endpoint S3, bucket, kunci, folder, berapa arsip disimpan, dan tiap berapa
jam.

- Isi arsip: `system.db` + **semua** file buku, masing-masing lewat `VACUUM INTO` supaya
  salinannya konsisten meski ada yang sedang menulis — bukan menyalin file mentah.
- Formatnya `.tar.gz` bernama `monetary-YYYYMMDD-HHMM.tar.gz`, jadi urutan nama = urutan
  waktu; retensi tinggal menghapus yang paling lama.
- Penyimpanan apa pun yang berbicara S3: **Cloudflare R2**, Backblaze B2, MinIO, AWS.
  Tanda tangan SigV4 ditulis sendiri di `app/s3.py` dengan `hmac`/`hashlib` bawaan —
  boto3 (±50 MB) tidak sepadan untuk mesin 256 MB. Kebenarannya diuji terhadap contoh
  resmi dokumentasi AWS (`tests/test_backup.py`).
- Penjadwalannya menumpang lalu lintas biasa: dicek maksimal sekali per 10 menit,
  dijalankan di thread terpisah. Mesin Fly berhenti sendiri saat menganggur, jadi cron
  di dalam proses tidak bisa diandalkan. Tombol **Cadangkan sekarang** selalu tersedia.

Memulihkan: unduh arsip, `tar xzf`, lalu taruh `monetary.db` (dan `data/books/*.db`,
`system.db` bila perlu) ke volume — tidak ada format khusus, isinya file SQLite biasa.

## CSRF

Setiap POST wajib membawa `_csrf` yang sama dengan cookie `monetary_csrf`
(*double-submit*). Situs lain bisa membuat peramban korban mengirim POST ke sini, tapi
tidak bisa membaca cookie milik domain ini, jadi tidak bisa menebak nilainya.

`app/csrf.py` sengaja middleware ASGI biasa, bukan `BaseHTTPMiddleware`: ia perlu membaca
body untuk memeriksa token, lalu **mengulang** body itu ke aplikasi — sesuatu yang tidak
bisa dilakukan middleware biasa tanpa menelan isi permintaan. Token disisipkan ke seluruh
form lewat `{{ csrf_field }}`, dan ke `fetch` di `app.js` lewat `window.CSRF`.

Permintaan yang ditolak mendapat halaman 403 berbahasa manusia ("formulir ini kedaluwarsa
atau dikirim dari halaman lain"), bukan tumpukan galat.

## Tagihan bulan ini

Pengeluaran berstatus **belum dibayar** (`status='planned'`) muncul sebagai kartu
tersendiri di halaman bulan, di atas kartu dana darurat — hanya kalau memang ada.
Urutannya menurut tanggal jatuh tempo, dan tiap baris diberi penanda dari selisih hari
terhadap hari ini:

| Keadaan | Tampilan |
|---|---|
| Tanggal sudah lewat | garis merah, "telat N hari", nominal merah |
| Jatuh tempo hari ini | garis kuning, "jatuh tempo hari ini" |
| ≤ 7 hari lagi | garis kuning, "N hari lagi" |
| Lebih jauh / tanpa tanggal | tanpa garis, tanggalnya saja |

Menandai lunas cukup satu ketuk (memakai rute `/tx/{id}/toggle` yang sudah ada), dan
template rutin yang diisi lewat "Isi bulan ini" otomatis masuk ke sini karena dibuat
dengan status `planned` beserta tanggal dari `day_of_month`.

## Usulan deskripsi

Mengetik dua huruf di kolom deskripsi memunculkan entri yang pernah dipakai di buku itu
sendiri (`GET /suggest?kind=&q=`). Memilih satu mengisi sekaligus **kategori, kantong,
dan nominal terakhirnya** — nominal hanya diisi kalau kolomnya masih kosong, supaya tidak
menimpa angka yang sudah diketik.

Urutannya: yang paling sering dipakai dulu, lalu yang terbaru. Satu baris per deskripsi
(tanpa memandang besar-kecil huruf), dan nilai yang terbawa diambil dari entri
**terakhir**, bukan gabungan — karena itu kueri memakai window function, bukan GROUP BY.

## Struktur

```
app/main.py        routes (bulan, transaksi, kantong, aset, laporan, ringkasan, setelan)
app/report.py      laporan bulanan: build_metrics() hitung angka, render_rules() susun narasi
app/suggest.py     tebakan kategori dari kata kunci deskripsi (dipakai layar perapihan)
app/users.py       pengguna + buku masing-masing (file database terpisah)
app/legal.py       isi halaman /privacy dan /terms (dipakai consent screen Google)
app/mailer.py      kirim surel lewat Resend (verifikasi email, setel ulang password)
app/backup.py      arsip semua buku + jadwal + retensi
app/s3.py          klien S3 seadanya (SigV4 ditulis sendiri, tanpa boto3)
app/csrf.py        middleware ASGI double-submit token
app/oauth.py       masuk dengan Google (OAuth2 + PKCE), daftar email yang diizinkan
app/i18n.py        dwibahasa: bahasa aktif per-permintaan, nama bulan, satuan angka
app/lang_en.py     kamus terjemahan Inggris (kunci = teks Indonesia di template/kode)
tests/            unittest, jalan tanpa server dan tanpa database asli
app/db.py          koneksi SQLite per buku, system.db, perhitungan saldo kantong
app/schema.py      skema v2 + kategori/kantong bawaan
app/auth.py        login satu user, cookie bertanda tangan
app/templates/     Jinja2 — base, month, accounts, assets, report, review, overview, settings, login
app/static/        style.css (Jakarta Sans, radius 10px, glass + shadow macOS, light/dark), app.js, vendor/tom-select, video/ (klip Jakarta, sama dengan landing), manifest PWA
scripts/import_xlsx.py   spreadsheet -> database bentuk lama
scripts/migrate_v2.py    bentuk lama -> skema aplikasi (punya mode pratinjau)
```

## Model data

- **accounts** — kantong: `cash` (kas/rekening harian), `savings` (dana darurat, tabungan),
  `credit` (kartu & paylater), `investment` (saham, crypto). Saldo tidak disimpan, selalu
  dihitung dari transaksi lewat view `account_balances`; `opening_balance` = posisi sebelum
  bulan pertama.
- **categories** — master kategori yang bisa ditambah/diubah/disembunyikan user. `is_debt`
  menandai kategori cicilan (dipakai rasio cicilan di laporan), `is_system` menandai
  kategori penampung yang tidak bisa dihapus.
- **transactions** — tiga tipe:
  - `income` — `account_id` = kantong tujuan, `category_id` wajib
  - `expense` — `account_id` = kantong sumber, `category_id` wajib
  - `transfer` — `account_id` → `to_account_id`, tanpa kategori; **tidak** masuk hitungan
    pemasukan/pengeluaran
  Plus `status` paid/planned dan `needs_review` untuk baris hasil impor yang perlu dicek.
- **asset_snapshots** — nilai pasar kantong investasi per bulan (kantong, simbol, nilai).
  Menu **Aset** memakainya untuk tren 12 bulan, komposisi antar kantong, dan untung/rugi per
  kantong = nilai pasar − modal. Modal = `opening_balance` (posisi sebelum bulan pertama)
  + semua transfer masuk − transfer keluar, jadi posisi lama tidak terhitung sebagai untung.
  Kalau bulan yang dilihat belum punya snapshot, nilai snapshot terakhir dipakai dan kantongnya
  diberi tanda "belum diperbarui".
- **recurring** — template rutin (bisa bertipe transfer juga); tombol "Isi bulan ini".
- **reports** — laporan bulanan tersimpan (satu baris per bulan per `engine`), dibuat sekali lalu
  dibaca dari sana; `?refresh=1` menghitung ulang.

### Perapihan (`/review`)

Transaksi hasil impor ditandai `needs_review`. Layar ini mengelompokkannya per bulan,
menebak kategori dari kata kunci deskripsi (`app/suggest.py` — daftar aturan biasa, bukan
model, jadi hasilnya bisa dijelaskan dan ditambah sendiri), dan menampilkan tebakan itu
sebagai pilihan yang **belum tersimpan**. Menekan Simpan memakai kategori yang tampil dan
melepas tanda untuk bulan itu. Baris yang deskripsinya berbau pemindahan uang
("pemisahan dana", "return", "backup operasional") dapat tombol **Ini transfer?** untuk
diubah jadi transfer antar kantong — nilainya langsung keluar dari hitungan pengeluaran.

### Laporan bulanan

`app/report.py` sengaja dibelah dua: `build_metrics(db, mk)` menghasilkan angka saja
(tingkat menabung, rasio cicilan dari kategori bertanda `is_debt`, cakupan dana darurat
terhadap belanja rata-rata 3 bulan, kategori yang melonjak >30%, transaksi terbesar,
template rutin yang belum tercatat, perubahan aset), lalu `render_rules(m)` menyusun
ringkasan, indikator, sorotan, dan maksimal empat saran dari angka itu.

Pembagian ini yang membuat lapis AI nanti murah dipasang: metrik yang sama dikirim ke model,
hasilnya disimpan dengan `engine='ai'`. Angka tidak pernah dihitung oleh model.
- **settings** — `first_month`, `schema_version`, password & secret cookie.

Sisa kas = Σ saldo awal kantong `cash` + pemasukan − pengeluaran − transfer keluar + transfer
masuk, sampai akhir bulan yang dilihat. Total aset = saldo kantong `savings` + nilai snapshot
investasi terakhir. Kartu kredit dicatat dengan cara "tagihannya saja": bayar tagihan =
pengeluaran kategori *Tagihan Kartu*.
