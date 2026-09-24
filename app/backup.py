"""Cadangan terjadwal ke penyimpanan S3-kompatibel (Cloudflare R2, B2, MinIO, S3).

Kenapa perlu: volume Fly hanya punya snapshot harian milik Fly sendiri. Kalau
volume itu bermasalah, tidak ada salinan di tempat lain — dan sejak aplikasi ini
dipakai orang lain, yang dipertaruhkan bukan cuma data pemilik.

Isi arsip: seluruh file buku + system.db, masing-masing disalin lewat
`VACUUM INTO` supaya konsisten meski ada yang sedang menulis (bukan sekadar
menyalin file mentah yang bisa tertangkap setengah jalan).

Penjadwalan sengaja "malas": dicek sekali per permintaan, dan kalau sudah lewat
tenggat, dijalankan di thread terpisah. Mesin Fly berhenti saat idle, jadi cron
di dalam proses tidak bisa diandalkan; cara ini menumpang lalu lintas biasa.

Konfigurasinya hanya lewat environment, sejalan dengan Resend dan Google. Selain
karena kunci penyimpanan adalah urusan penyebaran, ada alasan khusus di sini:
`system.db` ikut masuk ke dalam arsip, jadi kunci yang diketik lewat Setelan akan
terbungkus di dalam setiap cadangan yang ditulisnya sendiri. Yang tetap tinggal di
database cuma catatan hasil cadangan terakhir.
"""
import io
import os
import sqlite3
import tarfile
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import s3
from .db import all_books, get_app_setting, set_app_setting, system_path

_running = threading.Lock()


def _pick(key: str, env: str, default: str = "") -> str:
    """Environment yang berlaku. Nilai di database hanya sisa dari versi lama,
    saat cadangan masih bisa diatur lewat halaman Setelan."""
    return ((os.environ.get(env) or "").strip() or (get_app_setting(key) or "").strip() or default)


def _number(key: str, env: str, default: int, lo: int, hi: int) -> int:
    """Angka yang salah ketik di environment tidak boleh mematikan cadangan."""
    try:
        return min(hi, max(lo, int(_pick(key, env, str(default)))))
    except (TypeError, ValueError):
        return default


def config() -> dict:
    return dict(
        endpoint=_pick("backup_endpoint", "BACKUP_ENDPOINT"),
        bucket=_pick("backup_bucket", "BACKUP_BUCKET"),
        access_key=_pick("backup_key", "BACKUP_KEY"),
        secret_key=_pick("backup_secret", "BACKUP_SECRET"),
        region=_pick("backup_region", "BACKUP_REGION", "auto"),
        prefix=_pick("backup_prefix", "BACKUP_PREFIX", "monetary/"),
        keep=_number("backup_keep", "BACKUP_KEEP", 14, 1, 365),
        every_hours=_number("backup_every_hours", "BACKUP_EVERY_HOURS", 24, 1, 24 * 30),
    )


def from_env() -> bool:
    """Benar kalau cadangan hidup karena environment, bukan sisa nilai lama."""
    return bool((os.environ.get("BACKUP_ENDPOINT") or "").strip()
                and not (get_app_setting("backup_endpoint") or "").strip())


def is_enabled() -> bool:
    c = config()
    return bool(c["endpoint"] and c["bucket"] and c["access_key"] and c["secret_key"])


def status() -> dict:
    return dict(
        last_at=get_app_setting("backup_last_at", ""),
        ok=get_app_setting("backup_last_status", "") == "ok",
        error=get_app_setting("backup_last_error", ""),
        size=int(get_app_setting("backup_last_size", "0") or 0),
        books=int(get_app_setting("backup_last_books", "0") or 0),
        enabled=is_enabled(),
    )


# ---------- membuat arsip ----------

def _safe_copy(src: str, dst: str) -> bool:
    """Salinan konsisten dari satu database yang mungkin sedang dipakai."""
    try:
        conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
        try:
            conn.execute("VACUUM INTO ?", (dst,))
        finally:
            conn.close()
        return True
    except sqlite3.Error:
        return False


def archive() -> tuple:
    """(bytes tar.gz, jumlah berkas). Dipanggil dari thread cadangan."""
    files = [str(system_path())] + all_books()
    buf = io.BytesIO()
    count = 0
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for path in files:
                if not Path(path).exists():
                    continue
                copy = os.path.join(tmp, Path(path).name)
                if not _safe_copy(path, copy):
                    continue
                tar.add(copy, arcname=Path(path).name)
                count += 1
    return buf.getvalue(), count


def object_key(cfg: dict, when=None) -> str:
    when = when or datetime.now(timezone.utc)
    prefix = cfg["prefix"].strip("/")
    name = f"monetary-{when:%Y%m%d-%H%M}.tar.gz"
    return f"{prefix}/{name}" if prefix else name


def prune(cfg: dict) -> tuple:
    """Sisakan `keep` arsip terbaru. Kembalikan (terhapus, gagal).

    Kegagalan dihitung, bukan diabaikan: kalau token kehilangan izin hapus,
    arsip menumpuk lewat batas tanpa ada yang tahu — dan itu justru baru
    ketahuan saat tagihan atau kuota penyimpanan yang memberitahu."""
    keys = sorted(k for k in s3.list_keys(cfg, cfg["prefix"].strip("/")) if k.endswith(".tar.gz"))
    extra = keys[:-cfg["keep"]] if len(keys) > cfg["keep"] else []
    hapus = gagal = 0
    for key in extra:
        status, _ = s3.delete(cfg, key)
        if 200 <= status < 300:
            hapus += 1
        else:
            gagal += 1
    return hapus, gagal


def run() -> tuple:
    """Buat & unggah satu cadangan. Kembalikan (berhasil, pesan)."""
    if not is_enabled():
        return False, "backup not configured"
    if not _running.acquire(blocking=False):            # jangan menumpuk
        return False, "already running"
    try:
        cfg = config()
        blob, count = archive()
        status_code, body = s3.put(cfg, object_key(cfg), blob, "application/gzip")
        ok = 200 <= status_code < 300
        set_app_setting("backup_last_at", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"))
        set_app_setting("backup_last_status", "ok" if ok else "fail")
        set_app_setting("backup_last_size", str(len(blob)))
        set_app_setting("backup_last_books", str(count))
        err = "" if ok else f"{status_code} {body[:200].decode(errors='replace')}"
        if ok:
            _, gagal = prune(cfg)
            if gagal:                                   # unggahan berhasil, retensinya yang macet
                err = f"retensi: {gagal} arsip lama gagal dihapus"
        set_app_setting("backup_last_error", err)
        return ok, err
    finally:
        _running.release()


# ---------- penjadwalan ----------

def due() -> bool:
    if not is_enabled():
        return False
    last = get_app_setting("backup_last_at", "")
    if not last:
        return True
    try:
        when = datetime.strptime(last, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return (datetime.now(timezone.utc) - when).total_seconds() >= config()["every_hours"] * 3600


_last_check = 0.0


def maybe_run() -> None:
    """Dipanggil dari middleware. Murah: cek waktu di memori dulu, database
    hanya disentuh sekali per 10 menit, dan unggahan jalan di thread terpisah."""
    global _last_check
    now = time.time()
    if now - _last_check < 600:
        return
    _last_check = now
    try:
        if due():
            threading.Thread(target=run, name="monetary-backup", daemon=True).start()
    except Exception:                                   # cadangan tidak boleh menjatuhkan permintaan
        pass
