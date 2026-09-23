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
from .db import DB_PATH, all_books, get_app_setting, set_app_setting, system_path

_running = threading.Lock()


def config() -> dict:
    return dict(
        endpoint=(get_app_setting("backup_endpoint") or "").strip(),
        bucket=(get_app_setting("backup_bucket") or "").strip(),
        access_key=(get_app_setting("backup_key") or "").strip(),
        secret_key=(get_app_setting("backup_secret") or "").strip(),
        region=(get_app_setting("backup_region") or "auto").strip(),
        prefix=(get_app_setting("backup_prefix") or "monetary/").strip(),
        keep=int(get_app_setting("backup_keep", "14") or 14),
        every_hours=int(get_app_setting("backup_every_hours", "24") or 24),
    )


def save_config(endpoint: str, bucket: str, access_key: str, secret_key: str, region: str,
                prefix: str, keep: str, every_hours: str) -> None:
    set_app_setting("backup_endpoint", endpoint.strip())
    set_app_setting("backup_bucket", bucket.strip())
    set_app_setting("backup_key", access_key.strip())
    if secret_key.strip():                     # kosong = biarkan yang lama
        set_app_setting("backup_secret", secret_key.strip())
    set_app_setting("backup_region", (region or "auto").strip())
    set_app_setting("backup_prefix", (prefix or "monetary/").strip())
    for key, raw, lo, hi, default in (("backup_keep", keep, 1, 365, 14),
                                      ("backup_every_hours", every_hours, 1, 24 * 30, 24)):
        try:
            set_app_setting(key, str(min(hi, max(lo, int(raw)))))
        except (TypeError, ValueError):
            set_app_setting(key, str(default))


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


def prune(cfg: dict) -> int:
    """Sisakan `keep` arsip terbaru."""
    keys = sorted(k for k in s3.list_keys(cfg, cfg["prefix"].strip("/")) if k.endswith(".tar.gz"))
    extra = keys[:-cfg["keep"]] if len(keys) > cfg["keep"] else []
    for key in extra:
        s3.delete(cfg, key)
    return len(extra)


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
        set_app_setting("backup_last_error", err)
        if ok:
            prune(cfg)
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
