"""Pulihkan cadangan Muara dari penyimpanan S3 (Cloudflare R2).

  python scripts/restore.py --list
  python scripts/restore.py --latest --out pulih
  python scripts/restore.py --key monetary/monetary-20260924-0641.tar.gz --out pulih

Kenapa ada: cadangan yang belum pernah dipulihkan belum terbukti bisa
dipulihkan. Skrip ini membuat pembuktian itu satu perintah, bukan ingatan
seseorang tentang langkah-langkah manual.

Sengaja hanya bergantung pada `app/s3.py` dan pustaka bawaan Python — tidak
pada FastAPI, tidak pada database aplikasi. Saat kamu butuh memulihkan,
kemungkinan besar ada yang sedang rusak; alat pemulihnya tidak boleh ikut
bergantung pada bagian yang rusak itu.

Konfigurasinya sama dengan aplikasi: BACKUP_ENDPOINT, BACKUP_BUCKET,
BACKUP_KEY, BACKUP_SECRET, dan BACKUP_PREFIX (opsional, bawaan `monetary/`).
Di laptop isi `.env`; di server sudah ada sebagai fly secrets.

Skrip ini tidak pernah menimpa data yang sedang dipakai. Isinya diekstrak ke
direktori tujuan dan menolak jalan kalau di situ sudah ada berkas .db, kecuali
diberi --force. Memindahkan hasilnya ke volume adalah langkah sadar yang kamu
lakukan sendiri, dengan aplikasi dalam keadaan berhenti.
"""
import argparse
import io
import os
import sqlite3
import sys
import tarfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app import s3                                      # noqa: E402  (setelah sys.path disiapkan)

WAJIB = ("BACKUP_ENDPOINT", "BACKUP_BUCKET", "BACKUP_KEY", "BACKUP_SECRET")


def baca_env() -> None:
    """Baca `.env` di akar proyek. Environment asli tidak pernah ditimpa, jadi
    di server berkas ini tidak berpengaruh apa-apa."""
    berkas = BASE / ".env"
    if not berkas.exists():
        return
    for baris in berkas.read_text(errors="replace").splitlines():
        baris = baris.strip()
        if not baris or baris.startswith("#") or "=" not in baris:
            continue
        kunci, _, nilai = baris.partition("=")
        kunci = kunci.strip()
        if kunci and kunci not in os.environ:
            os.environ[kunci] = nilai.strip().strip('"').strip("'")


def konfigurasi() -> dict:
    baca_env()
    kurang = [k for k in WAJIB if not (os.environ.get(k) or "").strip()]
    if kurang:
        sys.exit("Belum ada di environment: " + ", ".join(kurang) +
                 "\nIsi di .env, atau ambil dari server: fly secrets list -a monetary-rianfathany")
    return dict(
        endpoint=os.environ["BACKUP_ENDPOINT"].strip(),
        bucket=os.environ["BACKUP_BUCKET"].strip(),
        access_key=os.environ["BACKUP_KEY"].strip(),
        secret_key=os.environ["BACKUP_SECRET"].strip(),
        region=(os.environ.get("BACKUP_REGION") or "auto").strip(),
        prefix=(os.environ.get("BACKUP_PREFIX") or "monetary/").strip(),
    )


def daftar(cfg: dict) -> list:
    """Nama arsip, terlama dulu. Nama memuat waktu, jadi urutan nama = urutan waktu."""
    return sorted(k for k in s3.list_keys(cfg, cfg["prefix"].strip("/")) if k.endswith(".tar.gz"))


def unduh(cfg: dict, key: str) -> bytes:
    status, body = s3.request("GET", s3.object_url(cfg, key), cfg)
    if status != 200:
        sys.exit(f"Gagal mengunduh {key}: HTTP {status} {body[:200].decode(errors='replace')}")
    return body


def pastikan_kosong(tujuan: Path, paksa: bool) -> None:
    """Diperiksa sebelum mengunduh, bukan sesudah — tidak ada gunanya menarik
    puluhan megabita untuk kemudian menolak menulisnya."""
    lama = sorted(tujuan.glob("*.db")) if tujuan.exists() else []
    if lama and not paksa:
        sys.exit(f"{tujuan} sudah berisi {len(lama)} berkas .db. Pakai direktori lain, "
                 f"atau tambahkan --force kalau memang mau ditimpa.")


def bongkar(blob: bytes, tujuan: Path) -> list:
    tujuan.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
        tar.extractall(tujuan, filter="data")
        nama = tar.getnames()
    return [tujuan / n for n in nama]


def periksa(berkas: Path) -> str:
    """Satu baris ringkasan, atau alasan kenapa berkasnya tidak sehat."""
    try:
        conn = sqlite3.connect(f"file:{berkas}?mode=ro", uri=True)
    except sqlite3.Error as e:
        return f"tidak bisa dibuka: {e}"
    try:
        hasil = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if hasil != "ok":
            return f"integrity_check: {hasil}"
        tabel = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        hitung = []
        for t in ("transactions", "accounts", "categories", "users"):
            if t in tabel:
                hitung.append(f"{conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]} {t}")
        return "ok — " + (", ".join(hitung) if hitung else f"{len(tabel)} tabel")
    except sqlite3.Error as e:
        return f"gagal dibaca: {e}"
    finally:
        conn.close()


def main() -> None:
    p = argparse.ArgumentParser(description="Pulihkan cadangan Muara dari R2.")
    p.add_argument("--list", action="store_true", help="tampilkan arsip yang ada, lalu berhenti")
    p.add_argument("--latest", action="store_true", help="ambil arsip terbaru")
    p.add_argument("--key", help="nama arsip tertentu, mis. monetary/monetary-20260924-0641.tar.gz")
    p.add_argument("--out", default="pulih", help="direktori tujuan (bawaan: pulih)")
    p.add_argument("--force", action="store_true", help="izinkan menimpa isi direktori tujuan")
    a = p.parse_args()

    cfg = konfigurasi()
    arsip = daftar(cfg)
    if not arsip:
        sys.exit(f"Tidak ada arsip di {cfg['bucket']}/{cfg['prefix']}. "
                 f"Cadangan belum pernah jalan, atau kuncinya salah.")

    if a.list or not (a.latest or a.key):
        print(f"{len(arsip)} arsip di {cfg['bucket']}:")
        for k in arsip:
            print("  " + k)
        if not (a.latest or a.key):
            print("\nTambahkan --latest untuk memulihkan yang terbaru.")
        return

    key = a.key or arsip[-1]
    if key not in arsip:
        sys.exit(f"{key} tidak ada di bucket. Jalankan --list untuk melihat yang tersedia.")

    tujuan = Path(a.out).resolve()
    pastikan_kosong(tujuan, a.force)
    print(f"Mengunduh {key} ...")
    blob = unduh(cfg, key)
    berkas = bongkar(blob, tujuan)
    print(f"{len(blob) // 1024} KB, {len(berkas)} berkas, diekstrak ke {tujuan}\n")

    sehat = True
    for b in sorted(berkas):
        hasil = periksa(b)
        sehat = sehat and hasil.startswith("ok")
        print(f"  {b.name:<20} {hasil}")

    print("\nSemua berkas sehat." if sehat else "\nADA BERKAS YANG BERMASALAH — jangan dipakai memulihkan.")
    print("Untuk benar-benar memulihkan: hentikan aplikasi, salin berkas ini ke volume "
          "(monetary.db dan system.db di data/, book-*.db di data/books/), lalu jalankan lagi.")


if __name__ == "__main__":
    main()
