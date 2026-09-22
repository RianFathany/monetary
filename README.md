# Monetary

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

## Deploy ke Fly.io (monetary.rianfathany.com)

```bash
brew install flyctl && fly auth login
cd monetary
fly launch --copy-config --no-deploy        # pakai fly.toml yang ada, region sin
fly volumes create monetary_data --size 1 --region sin
fly deploy
fly certs add monetary.rianfathany.com      # lalu tambah CNAME di Cloudflare (DNS only, bukan proxied, saat validasi)
```

Setelah deploy, jalankan import sekali: `fly ssh console -C "python scripts/import_xlsx.py /tmp/cashflow.xlsx --reset"` (upload file dulu dengan `fly ssh sftp shell`), atau cukup salin `data/monetary.db` lokal ke volume.

## Login

Satu password, disimpan sebagai hash PBKDF2 di tabel `settings` bersama secret cookie (dibuat otomatis) — tidak butuh `.env`. Ganti lewat Setelan › Akun. Cookie 30 hari. Halaman login memakai rule yang sama dengan rianfathany.com: klip Jakarta sesuai jam (pagi/siang/senja/malam) dan otomatis klip hujan bila sedang hujan (Open-Meteo), plus jam dan nama kota dari geolocation browser (fallback Jakarta). Klip disalin dari `application/assets/video/`. Tombol keluar ada di header kanan atas.

## Struktur

```
app/main.py        routes (bulan, transaksi, kantong, aset, laporan, ringkasan, setelan)
app/report.py      laporan bulanan: build_metrics() hitung angka, render_rules() susun narasi
app/suggest.py     tebakan kategori dari kata kunci deskripsi (dipakai layar perapihan)
app/db.py          koneksi SQLite + perhitungan saldo kantong
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
