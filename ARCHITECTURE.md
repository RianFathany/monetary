# Arsitektur Muara

Catatan keuangan pribadi. Satu pengguna, satu berkas SQLite, dirender di server,
dipakai dari ponsel. 9.400 baris kode, tanpa build step, tanpa framework frontend.

Dokumen ini menjelaskan **bentuk** aplikasinya dan **kenapa** dibentuk begitu.
Cara menjalankan dan mendeploy ada di [README](README.md).

---

## 1. Gambaran umum

```
                    ponsel / browser
                           │  HTML biasa, form POST, tanpa API client
                           ▼
              ┌────────────────────────────┐
              │  FastAPI + Jinja2          │   app/main.py     — route & rendering
              │                            │   app/report.py   — laporan bulanan
              │                            │   app/suggest.py  — tebakan kategori
              │                            │   app/auth.py     — login satu user
              └──────────────┬─────────────┘
                             │  app/db.py — koneksi & perhitungan saldo
                             ▼
                    ┌─────────────────┐
                    │  SQLite (WAL)   │   app/schema.py — skema v6
                    │  data/monetary.db│
                    └─────────────────┘
                             │
                    Fly.io volume 1 GB, region sin
```

Tidak ada lapisan API terpisah, tidak ada state di klien. Setiap halaman adalah
HTML utuh; setiap perubahan adalah `POST` + redirect. JavaScript hanya untuk
kenyamanan (bottom sheet, swipe-to-delete, format ribuan) — semua fitur tetap
jalan tanpanya.

**Alasannya:** ini aplikasi satu orang dengan ratusan baris data. Arsitektur
server-rendered membuat seluruh logika uang berada di satu tempat yang bisa diuji,
dan tidak ada kemungkinan tampilan dan server berbeda pendapat soal angka.

---

## 2. Model data

Inti keputusan desainnya satu: **uang yang berpindah tempat bukan pengeluaran.**

Spreadsheet asal mencatat setoran tabungan sebagai belanja. Akibatnya Rp 420 jt
"pengeluaran" selama 11 bulan sebenarnya uang yang masih dimiliki, dan pertanyaan
"berapa sebenarnya saya belanjakan bulan ini" tidak bisa dijawab. Skema v2
memisahkan keduanya.

### Kantong (`accounts`)

Tempat uang berada. Empat jenis:

| Jenis | Isi | Peran di laporan |
|---|---|---|
| `cash` | rekening harian, dompet | sisa kas |
| `savings` | dana darurat, tabungan tujuan | aset; yang bertanda `is_emergency` jadi ketahanan belanja |
| `credit` | kartu kredit, paylater | liabilitas, mengurangi kekayaan bersih |
| `investment` | saham, crypto | aset, dinilai lewat snapshot |

Saldo **tidak pernah disimpan**. Selalu dihitung dari transaksi lewat view
`account_balances`, dengan `opening_balance` sebagai posisi sebelum bulan pertama
yang dicatat. Tidak ada kolom saldo yang bisa jadi tidak sinkron dengan mutasinya.

### Transaksi (`transactions`)

Tiga tipe, dibedakan kolom `type`:

```
income    luar        ──▶ account_id        kategori wajib
expense   account_id  ──▶ luar              kategori wajib
transfer  account_id  ──▶ to_account_id     tanpa kategori
```

Transfer tidak pernah masuk hitungan pemasukan maupun pengeluaran. Bentuk ini
dijaga oleh `CHECK` di tingkat tabel, bukan hanya oleh kode aplikasi:

```sql
CHECK (type <> 'transfer' OR (to_account_id IS NOT NULL
       AND to_account_id <> account_id AND category_id IS NULL))
CHECK (type =  'transfer' OR to_account_id IS NULL)
```

Kolom pendukung: `status` (`paid`/`planned`) untuk tagihan yang belum dibayar,
`needs_review` untuk baris hasil impor yang kategorinya masih tebakan,
`deleted_at` untuk hapus lunak (semua query menyaring `deleted_at IS NULL`).

### Kategori (`categories`)

Master milik pengguna: bisa ditambah, diubah namanya, diurutkan, disembunyikan,
dihapus. Dua penanda punya arti di laporan:

- `is_debt` — dihitung sebagai cicilan/utang pada rasio cicilan
- `is_system` — kategori penampung ("Lainnya"), tidak bisa dihapus; transaksi
  dari kategori yang dihapus dipindahkan ke sini dan ditandai `needs_review`

Kategori adalah **jenis belanja** (Makan & Minum, Transport), bukan nama rekening.
Nama rekening adalah kantong. Pemisahan ini yang membuat laporan bisa menjawab
"uang habis ke mana", bukan sekadar "lewat rekening mana".

### Nilai investasi (`asset_snapshots`)

Harga saham dan crypto bergerak sendiri, tidak bisa diturunkan dari mutasi. Jadi
nilainya diisi manual per bulan (kantong, simbol, nilai). Selisih nilai pasar
dengan modal — `opening_balance` + transfer masuk − transfer keluar — adalah
untung/rugi. Bulan tanpa snapshot memakai snapshot terakhir dan ditandai
"belum diperbarui".

### Tabel lain

`recurring` (template bulanan, bisa bertipe transfer), `reports` (laporan
tersimpan per bulan per `engine`), `settings` (bulan pertama, versi skema, hash
password, secret cookie), `ledgers` (satu baris, lihat §7).

---

## 3. Perhitungan uang

Semua angka bermuara pada satu fungsi, `db.balance_upto(mk, types|ids)`:

```
saldo = Σ opening_balance kantong dalam kelompok
      + Σ income    yang masuk  ke kelompok
      − Σ expense   yang keluar dari kelompok
      − Σ transfer  keluar kelompok   ← sisi lawan diperiksa:
      + Σ transfer  masuk  kelompok      pindah di dalam kelompok = nol
```

Pemeriksaan sisi lawan itu yang membuat "pindah dari Operasional ke BCA" tidak
mengubah total kas, sementara "pindah dari Operasional ke Dana Darurat" mengubah
kas dan tabungan sekaligus.

Turunannya:

- **Sisa kas** = `balance_upto(mk, cash)` — sudah dikurangi tagihan `planned`,
  jadi memang tidak sama dengan saldo di m-banking; judulnya di layar menyebut itu
- **Tabungan** = `balance_upto(mk, savings)`
- **Dana darurat** = hanya kantong bertanda `is_emergency`, atau `None` kalau
  belum ada yang ditandai. Tabungan liburan yang ikut terhitung membuat
  "aman 6 bulan" jadi kalimat menenangkan tanpa dasar
- **Total aset** = saldo `savings` + nilai snapshot `investment`
- **Kekayaan bersih** = total aset + kas + saldo `credit`. Saldo kantong utang
  sudah negatif saat berutang, jadi dijumlahkan begitu saja — tanpa tanda minus buatan
- **Ditabung bulan ini** = transfer masuk ke `savings`/`investment` − transfer keluar

### Satuan simpan

Setiap kolom nominal berisi **bilangan bulat satuan perseratus**, berapa pun mata
uangnya: Rp 44.800.000 tersimpan sebagai 4480000000, $12.50 sebagai 1250. Skalanya
tetap supaya berganti mata uang tidak pernah butuh migrasi data — yang berubah hanya
`app/money.py` saat menampilkannya. Konsekuensinya, ambang berupa nominal harus ditulis
dikali `money.SCALE` (lihat `SPIKE_MIN` di `report.py`), dan apa pun yang keluar dari
aplikasi sebagai angka mentah — ekspor Excel — melewati `money.major()`.

Perkalian ke satuan ini dijalankan sekali per buku oleh `schema._scale_money()`, dijaga
penanda `settings.money_scale`, **bukan** nomor versi skema. Nomor versi pernah terlanjur
naik tanpa migrasinya ikut jalan, dan akibatnya seluruh saldo tampil seratus kali lebih
kecil; penanda tersendiri membuat keadaan itu sembuh sendiri saat buku dibuka lagi.

---

## 4. Peta modul

| Berkas | Baris | Isi |
|---|---:|---|
| `app/schema.py` | 373 | DDL skema v6, view `account_balances`, kategori & kantong bawaan, migrasi |
| `app/db.py` | 422 | koneksi SQLite, `balance_upto`, dana darurat bertanda, adopsi database siap-pakai |
| `app/main.py` | 1611 | 69 route, query domain (`month_summary`, `asset_view`), render |
| `app/report.py` | 273 | `build_metrics` (angka) + `render_rules` (narasi) + penyimpanan |
| `app/money.py` | 213 | mata uang ISO 4217, bentuk angka, baca input, satuan simpan |
| `app/suggest.py` | 68 | aturan kata kunci → kategori, dipakai layar Rapikan |
| `app/auth.py` | 178 | password PBKDF2, cookie bertanda tangan 30 hari, pembatas percobaan |
| `app/users.py` | 167 | satu berkas buku per pengguna, pendaftaran, pemilik vs tamu |
| `app/oauth.py` | 153 | masuk lewat Google, kredensial dari Setelan atau environment |
| `app/csrf.py` | 90 | middleware ASGI double-submit cookie, semua POST tanpa kecuali |
| `app/i18n.py` | 84 | bahasa aktif per permintaan; `lang_en.py` (692) kamusnya |
| `app/legal.py` | 68 | teks Kebijakan Privasi & Persyaratan Layanan, dwibahasa |
| `app/mailer.py` | 80 | verifikasi email & setel ulang password lewat Resend |
| `app/backup.py` | 180 | cadangan harian menumpang lalu lintas; `s3.py` (102) unggah ke R2 |
| `app/templates/` | ~2070 | 24 berkas Jinja, mewarisi `base.html` |
| `app/static/` | ~1800 | `style.css` (glass macOS, light/dark), `app.js` (sheet, swipe, picker) |
| `scripts/migrate_v2.py` | 340 | konversi bentuk lama → skema v2, punya mode pratinjau |
| `scripts/import_xlsx.py` | 208 | spreadsheet → database bentuk lama |

### Halaman

```
/            Depan      halaman publik: video, alur sungai, tangkapan layar (tamu saja)
/m/{bulan}   Bulan      hero sisa kas, tren 6 bulan, tab Keluar/Masuk/Transfer
/accounts    Kantong    kekayaan bersih, komposisi, saldo tiap kantong
/assets      Aset       tren 12 bulan, komposisi, nilai pasar vs modal
/report      Laporan    ringkasan, 4 indikator kesehatan, sorotan, saran
/review      Rapikan    bulk-edit kategori dengan saran, per bulan
/overview    Ringkasan  dashboard per bulan + pencarian
/settings    Setelan    master kategori, template rutin, backup, akun
```

---

## 5. Laporan bulanan

Sengaja dibelah dua supaya lapis AI nanti murah dipasang:

```
build_metrics(db, mk)  ──▶  { savings_rate, debt_ratio, cover_months,
   angka saja                 spikes, top, missing_recurring, ... }
                                          │
                        ┌─────────────────┴─────────────────┐
                        ▼                                   ▼
                 render_rules(m)                    (nanti) model AI
                 aturan tetap, gratis               narasi & saran
                        │                                   │
                        └──────────▶ reports ◀──────────────┘
                             engine='rules'   engine='ai'
```

Angka tidak pernah dihitung oleh model — LLM buruk dalam berhitung dan hasilnya
tidak bisa diaudit. Yang dikirim nanti hanya agregat (±4 rb token), bukan
transaksi mentah. Laporan disimpan, jadi membukanya lagi tidak menghitung ulang
dan tidak memanggil API.

Indikator yang dihitung:

- **Surplus** — pemasukan dikurangi pengeluaran, patokan 20%.
- **Setoran ke tabungan** — yang benar-benar dipindahkan ke `savings`/`investment`.
  Dipisah dari surplus karena sisa yang mengendap di rekening harian biasanya
  habis juga bulan depan; satu angka yang dinamai "tingkat menabung" menutupi itu.
- **Rasio cicilan** — kategori `is_debt` saja, dibagi pemasukan rata-rata 3 bulan,
  ambang sehat 35%. Tagihan kartu dilaporkan di sebelahnya tapi tidak ikut
  dijumlahkan: besarnya mengikuti belanja bulan itu, bukan kewajiban tetap, dan
  bulan bonus tidak boleh membuat cicilan terlihat mendadak ringan.
- **Cakupan dana darurat** — kantong bertanda `is_emergency` terhadap belanja
  rata-rata 3 bulan (target 6 bulan), atau "–" kalau belum ada yang ditandai.
- **Total aset** dan kategori yang naik >30% dari rata-rata.

---

## 6. Migrasi & impor

Spreadsheet asal berbentuk lama (kas dan dana darurat sebagai dua kolom terpisah),
jadi jalurnya dua langkah dan sengaja tidak digabung:

```
MRFNIP - Cashflow.xlsx
   │  scripts/import_xlsx.py        (menulis skema lama, apa adanya)
   ▼
data/monetary-v1.db
   │  scripts/migrate_v2.py         (pratinjau dulu; --apply untuk menulis)
   ▼
data/monetary-v2.db  ──▶  dipakai aplikasi
```

`migrate_v2.py` melakukan tiga hal yang tidak bisa diotomatiskan begitu saja:

1. **Memetakan kategori lama** — `TABUNGAN`/`SAHAM`/`DANA DARURAT` jadi transfer;
   `MEGA`/`BNI`/`GOPAYLATER` jadi pengeluaran *Tagihan Kartu*; `SETOR BCA` jadi
   *Operasional Harian* (bukan transfer, karena belanja dari BCA tidak dicatat).
2. **Menggabungkan pasangan** — satu kejadian sering tercatat dua kali, di kolom
   kas dan di kolom dana darurat. Dicocokkan 1:1 per bulan+nominal, lalu sebagai
   gabungan (satu setoran 125 jt yang di sisi dana darurat terpecah 110 jt + 15 jt).
3. **Memeriksa dirinya sendiri** — sisa kas dan saldo dana darurat hasil konversi
   harus sama persis dengan hitungan lama. Kalau meleset, dicetak sebagai MELESET.

Baris yang kategorinya hasil tebakan ditandai `needs_review` dan muncul di layar
Perapihan, bukan diam-diam dianggap benar.

---

## 7. Keputusan & konsekuensinya

**SQLite, bukan Postgres.** Satu pengguna, ratusan baris, backup = salin satu
berkas. Konsekuensi: tidak bisa multi-instance, dan pindah ke multi-user nanti
butuh migrasi. Kolom `ledger_id` sudah ada di semua tabel (selalu bernilai 1)
supaya migrasi itu tidak perlu membongkar tabel lagi.

**Server-rendered, bukan SPA.** Konsekuensi: tidak bisa langsung dibungkus jadi
aplikasi App Store/Play Store. Kalau ke sana, tampilannya dibangun ulang (Expo),
tapi seluruh perhitungan di `db.py`/`report.py` tetap terpakai.

**Kartu kredit dicatat "tagihannya saja".** Bayar tagihan = pengeluaran kategori
*Tagihan Kartu*; belanja per gesekan tidak dicatat. Lebih ringan diinput, tapi
laporan tidak bisa menjawab "uang kartu habis untuk apa". Karena itu *Tagihan
Kartu* tidak lagi bertanda `is_debt`: nominalnya mengikuti belanja bulan itu, dan
ikut dijumlahkan ke rasio cicilan membuat angkanya melompat tiap ada top-up besar.
Ia tetap dilaporkan, hanya di sebelah rasionya, bukan di dalamnya.

**Kantong `credit` dipakai, dan mengurangi kekayaan bersih.** Yang mencatat kartu
per gesekan bisa memakainya: belanja mengurangi saldo kantong itu, membayar tagihan
= transfer dari kas ke sana. Sebelumnya kantongnya bisa dibuat tapi diabaikan
seluruh halaman, jadi "kekayaan bersih" hanyalah penjumlahan aset dengan nama
yang salah.

**Hapus lunak.** `deleted_at`, bukan `DELETE`. Salah hapus bisa dipulihkan dari
database, dan nanti jadi fondasi sinkronisasi offline.

**Migrasi dicatat satu per satu, bukan disimpulkan dari nomor versi.**
`settings.migrations_applied` menyimpan daftar migrasi yang benar-benar pernah
jalan di buku itu. Nomor versi sendirian rapuh: kalau `SCHEMA_VERSION` sempat
naik sebelum isi migrasinya ditulis — pernah terjadi pada `money_scale`, dan
sekali lagi saat kolom `is_emergency` ditambahkan — buku menyimpan nomor baru
tanpa perubahannya, lalu `cur == SCHEMA_VERSION` membuat migrasi itu dilewati
selamanya tanpa jejak. Buku yang belum punya daftarnya dipercaya sekali lewat
nomor versinya, lalu daftarnya ditulis. Konsekuensinya: memundurkan nomor versi
tidak lagi menjalankan ulang migrasi — yang memang benar, karena isi migrasi v6
mengubah data dan mengulangnya berarti menimpa pilihan pemiliknya.

**Aplikasi menolak jalan di atas skema lama.** `init_db()` melempar error kalau
menemukan tabel `emergency_fund` — lebih baik mati berisik daripada diam-diam
salah baca. Jalan keluarnya: unggah `<nama>-v2.db` di sebelahnya, aplikasi
menukarnya sekali saat start dan menyimpan yang lama sebagai `-v1-backup`.

---

## 8. Penyebaran

```
GitHub  RianFathany/monetary          (push tidak memicu deploy)
   │
   │  fly deploy   — manual
   ▼
Fly.io  monetary-rianfathany, region sin
        Dockerfile → uvicorn, 1 mesin, auto_stop/auto_start
        volume monetary_data 1 GB  →  /app/data/monetary.db
        muara.rianfathany.com (sertifikat Fly)
        monetary.rianfathany.com — domain lama, masih dilayani
```

Mesin berhenti sendiri saat tidak dipakai, jadi kunjungan pertama setelah lama
menganggur perlu beberapa detik untuk bangun. Backup: berkas `.db` bisa diunduh
dari Setelan (`/backup.db`, memakai `VACUUM INTO` supaya salinannya konsisten)
dan ekspor Excel (`/export.xlsx`) untuk membacanya di luar aplikasi.

---

## 9. Tes

`tests/` berisi 291 tes `unittest`, tanpa dependensi tambahan dan tanpa menyentuh
database asli — tiap tes membangun datanya sendiri di memori.

Yang dikunci bukan detail implementasi, melainkan aturan yang kalau berubah diam-diam
akan membuat angka salah: transfer memindah dan bukan menghabiskan, transfer antar
kantong sejenis tidak mengubah total, transaksi terhapus tidak ikut dihitung, untung
investasi diukur dari modal dan bukan dari nol, rasio cicilan hanya menjumlahkan
kategori bertanda `is_debt`, utang kartu mengurangi kekayaan bersih, ketahanan
belanja hanya dari kantong yang ditandai (dan `None` kalau belum ada, bukan nol),
template rutin tidak bisa masuk dua kali ke bulan yang sama, buku lama tetap bisa
dibuka setelah kolom baru bertambah, aplikasi menolak jalan di atas skema lama,
dan — yang paling mudah salah — satu kejadian yang di spreadsheet tercatat dua
kali tidak boleh masuk dua kali setelah migrasi.

```bash
.venv/bin/python -m unittest discover -s tests -t .
```

## 10. Yang belum ada

- **Multi-user, sinkronisasi offline, aplikasi ponsel native** — belum, lihat §7.
- **Lapis AI** — kerangkanya siap (`reports.engine`), belum dinyalakan.
- **Tidak ada CI**, jadi tes hanya jalan kalau dipanggil sendiri; `fly deploy` juga
  masih manual.
