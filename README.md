# Monetary

Catatan keuangan pribadi: kas masuk/keluar bulanan, dana darurat, dan snapshot aset.
Pengganti spreadsheet `MRFNIP - Cashflow.xlsx` — satu user, satu file SQLite, mobile-first.

## Jalankan lokal (tanpa Docker)

```bash
cd monetary
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # isi MONETARY_PASSWORD dan MONETARY_SECRET
set -a; source .env; set +a
.venv/bin/uvicorn app.main:app --port 8765 --reload
```

Buka http://127.0.0.1:8765

## Jalankan dengan Docker

```bash
cp .env.example .env            # isi password + secret
docker compose up -d --build    # http://127.0.0.1:8765
```

Database ada di `./data/monetary.db` (volume). Backup = salin file itu.

## Import dari spreadsheet

```bash
.venv/bin/python scripts/import_xlsx.py "../reference/MRFNIP - Cashflow (2).xlsx" --reset
```

`--reset` mengosongkan transaksi/dana darurat/aset dulu. Saldo awal, dana darurat awal, dan bulan pertama diambil dari sheet bulan paling awal.

## Deploy ke Fly.io (monetary.rianfathany.com)

```bash
brew install flyctl && fly auth login
cd monetary
fly launch --copy-config --no-deploy        # pakai fly.toml yang ada, region sin
fly volumes create monetary_data --size 1 --region sin
fly secrets set MONETARY_PASSWORD='...' MONETARY_SECRET="$(openssl rand -hex 32)"
fly deploy
fly certs add monetary.rianfathany.com      # lalu tambah CNAME di Cloudflare (DNS only, bukan proxied, saat validasi)
```

Setelah deploy, jalankan import sekali: `fly ssh console -C "python scripts/import_xlsx.py /tmp/cashflow.xlsx --reset"` (upload file dulu dengan `fly ssh sftp shell`), atau cukup salin `data/monetary.db` lokal ke volume.

## Login

Satu password (`MONETARY_PASSWORD`), cookie 30 hari. Halaman login memakai rule yang sama dengan rianfathany.com: klip Jakarta sesuai jam (pagi/siang/senja/malam) dan otomatis klip hujan bila sedang hujan (Open-Meteo), plus jam dan nama kota dari geolocation browser (fallback Jakarta). Klip disalin dari `application/assets/video/`. Tombol keluar ada di header kanan atas.

## Struktur

```
app/main.py        routes (bulan, transaksi, dana darurat, rutin, aset, ringkasan, setelan)
app/db.py          schema SQLite + default kategori
app/auth.py        login satu user, cookie bertanda tangan
app/templates/     Jinja2 — base, month, overview, assets, settings, login
app/static/        style.css (Jakarta Sans, radius 10px, glass + shadow macOS, light/dark), app.js, vendor/tom-select, video/ (klip Jakarta, sama dengan landing), manifest PWA
scripts/import_xlsx.py
```

## Model data

- **transactions** — `month_key` (YYYY-MM), `kind` income/expense, tanggal (opsional), kategori, deskripsi, jumlah, `status` paid/planned.
- **emergency_fund** — mutasi + setor / − tarik; `linked_tx_id` menunjuk pasangan di kas (tarik → pemasukan, setor → pengeluaran). Hapus/edit salah satu ikut menyinkronkan pasangannya.
- **assets** — snapshot per bulan (kategori, simbol, nilai). Kartu "Aset" memakai snapshot terakhir ≤ bulan aktif.
- **recurring** — template rutin; tombol "Isi bulan ini" pada bulan kosong.
- **settings** — `opening_balance`, `opening_emergency`, `first_month`.

Sisa saldo = saldo awal + Σ(pemasukan − pengeluaran) semua bulan sebelumnya + bulan ini. Total assets = dana darurat + aset.
