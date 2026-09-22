# Arsitektur Monetary

Catatan keuangan pribadi. Satu pengguna, satu berkas SQLite, dirender di server,
dipakai dari ponsel. 4.100 baris kode, tanpa build step, tanpa framework frontend.

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
                    │  SQLite (WAL)   │   app/schema.py — skema v2
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
| `savings` | dana darurat, tabungan tujuan | aset |
| `credit` | kartu kredit, paylater | (belum dipakai — lihat §7) |
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

- **Sisa kas** = `balance_upto(mk, cash)`
- **Dana darurat** = `balance_upto(mk, savings)`
- **Total aset** = saldo `savings` + nilai snapshot `investment`
- **Kekayaan bersih** = total aset + kas (− `credit` bila nanti dipakai)
- **Ditabung bulan ini** = transfer masuk ke `savings`/`investment` − transfer keluar

---

## 4. Peta modul

| Berkas | Baris | Isi |
|---|---:|---|
| `app/schema.py` | 198 | DDL skema v2, view `account_balances`, kategori & kantong bawaan |
| `app/db.py` | 146 | koneksi SQLite, `balance_upto`, adopsi database siap-pakai saat start |
| `app/main.py` | 845 | 34 route, query domain (`month_summary`, `asset_view`), render |
| `app/report.py` | 233 | `build_metrics` (angka) + `render_rules` (narasi) + penyimpanan |
| `app/suggest.py` | 68 | aturan kata kunci → kategori, dipakai layar perapihan |
| `app/auth.py` | 78 | password tunggal PBKDF2, cookie bertanda tangan 30 hari |
| `app/templates/` | ~950 | 9 halaman Jinja, mewarisi `base.html` |
| `app/static/` | ~900 | `style.css` (glass macOS, light/dark), `app.js` (sheet, swipe, picker) |
| `scripts/migrate_v2.py` | 337 | konversi bentuk lama → skema v2, punya mode pratinjau |
| `scripts/import_xlsx.py` | 208 | spreadsheet → database bentuk lama |

### Halaman

```
/m/{bulan}   Bulan      hero sisa kas, tren 6 bulan, tab Keluar/Masuk/Transfer
/accounts    Kantong    kekayaan bersih, komposisi, saldo tiap kantong
/assets      Aset       tren 12 bulan, komposisi, nilai pasar vs modal
/report      Laporan    ringkasan, 4 indikator kesehatan, sorotan, saran
/review      Perapihan  bulk-edit kategori dengan saran, per bulan
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

Indikator yang dihitung: tingkat menabung, rasio cicilan (dari kategori `is_debt`,
ambang sehat 35%), cakupan dana darurat terhadap belanja rata-rata 3 bulan (target
6 bulan), perubahan total aset, kategori yang naik >30% dari rata-rata.

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
laporan tidak bisa menjawab "uang kartu habis untuk apa", dan rasio cicilan jadi
tinggi karena top-up ikut terhitung. Jenis kantong `credit` sudah ada di skema
kalau suatu saat mau pindah cara.

**Hapus lunak.** `deleted_at`, bukan `DELETE`. Salah hapus bisa dipulihkan dari
database, dan nanti jadi fondasi sinkronisasi offline.

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
        monetary.rianfathany.com (sertifikat Fly)
```

Mesin berhenti sendiri saat tidak dipakai, jadi kunjungan pertama setelah lama
menganggur perlu beberapa detik untuk bangun. Backup: berkas `.db` bisa diunduh
dari Setelan (`/backup.db`, memakai `VACUUM INTO` supaya salinannya konsisten)
dan ekspor Excel (`/export.xlsx`) untuk membacanya di luar aplikasi.

---

## 9. Yang belum ada

- **Tidak ada tes otomatis.** Untuk aplikasi uang, `balance_upto`, `month_summary`,
  dan pemeriksaan migrasi layak dikunci dengan beberapa assert.
- **`asset_view` tinggal di `main.py`**, padahal itu logika domain; `report.py`
  mengimpornya saat dipanggil untuk menghindari impor melingkar. Tempat yang benar
  adalah `db.py` atau modul domain sendiri.
- **`fly.toml` tanpa health check**, jadi deploy yang rusak bisa lolos smoke check.
- **Multi-user, sinkronisasi offline, aplikasi ponsel native** — belum, lihat §7.
- **Lapis AI** — kerangkanya siap (`reports.engine`), belum dinyalakan.
