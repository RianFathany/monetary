"""Pengguna dan bukunya.

Satu pengguna = satu file buku. Pemilik memakai buku lama (`data/monetary.db`);
email yang ada di daftar izin ikut masuk ke buku pemilik; email lain yang
mendaftar lewat Google mendapat buku baru yang kosong berisi kategori & kantong
bawaan — jadi keuangan masing-masing orang tidak pernah bertemu.
"""
from pathlib import Path

import re

from . import db as _db
from .db import book_file, books_dir, get_app_setting, init_book, system_db

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
MIN_PASSWORD = 8

def owner_book() -> str:
    return Path(_db.DB_PATH).name


def by_email(email: str):
    with system_db() as db:
        return db.execute("SELECT * FROM users WHERE email=?", ((email or "").lower(),)).fetchone()


def by_id(uid):
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        return None
    with system_db() as db:
        return db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


def owner():
    with system_db() as db:
        return db.execute("SELECT * FROM users WHERE is_owner=1 ORDER BY id LIMIT 1").fetchone()


def all_users():
    with system_db() as db:
        return db.execute("SELECT * FROM users ORDER BY is_owner DESC, id").fetchall()


def signup_open() -> bool:
    return get_app_setting("allow_signup", "1") != "0" and count() < max_users()


def max_users() -> int:
    """Batas jumlah akun. Menjaga volume server, dan menahan pendaftaran beruntun."""
    try:
        return max(1, int(get_app_setting("max_users", "50")))
    except ValueError:
        return 50


def owner_email() -> str:
    """Email yang memegang akun superadmin. Hanya email ini yang boleh menjadi
    pemilik; email lain di daftar izin sekadar ikut membaca buku pemilik."""
    return (get_app_setting("owner_email", "") or "").strip().lower()


def is_owner_email(email: str) -> bool:
    oe = owner_email()
    return bool(oe) and (email or "").strip().lower() == oe


def claim_owner(email: str, name: str = ""):
    """Email yang berhak memakai buku pemilik.

    Baris pemilik (superadmin) hanya boleh ditempel oleh `owner_email`. Email lain
    di daftar izin tetap masuk ke buku yang sama, tapi sebagai pengguna biasa —
    mereka tidak bisa mengelola pengguna, konfigurasi Google, atau password aplikasi.
    """
    o = owner()
    take_over = is_owner_email(email) or not owner_email()
    with system_db() as db:
        if take_over and o and (not o["email"] or o["email"] == "owner"):
            db.execute("UPDATE users SET email=?, name=COALESCE(NULLIF(?,''), name) WHERE id=?",
                       (email.lower(), name, o["id"]))
            uid = o["id"]
        else:
            cur = db.execute("INSERT OR IGNORE INTO users(email, name, book, is_owner) VALUES (?,?,?,0)",
                             (email.lower(), name, owner_book()))
            uid = cur.lastrowid
    return by_id(uid) or by_email(email)


def valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match((email or "").strip().lower())) and len(email) <= 120


def create(email: str, name: str = "", password_hash: str = "", email_verified: bool = False):
    """Pengguna baru + buku kosong miliknya sendiri."""
    email = (email or "").strip().lower()
    with system_db() as db:
        cur = db.execute("INSERT INTO users(email, name, book, password_hash, email_verified) "
                         "VALUES (?,?,'',?,?)", (email, name.strip()[:60], password_hash or None,
                                                 1 if email_verified else 0))
        uid = cur.lastrowid
        book = f"book-{uid}.db"
        db.execute("UPDATE users SET book=? WHERE id=?", (book, uid))
    books_dir().mkdir(parents=True, exist_ok=True)
    init_book(book_file(book))
    return by_id(uid)


def set_password(uid, password_hash: str, revoke_sessions: bool = True) -> None:
    """Simpan hash password milik satu pengguna. Sesi lamanya dicabut."""
    with system_db() as db:
        db.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash or None, uid))
        if revoke_sessions:
            db.execute("UPDATE users SET session_epoch=session_epoch+1 WHERE id=?", (uid,))


def mark_verified(uid, clear_password: bool = False) -> None:
    """Google sudah membuktikan email ini milik yang bersangkutan.

    `clear_password` dipakai saat akun sebelumnya dibuat lewat pendaftaran
    email+password yang belum terbukti: password lama dibuang supaya orang yang
    mendaftar memakai email orang lain tidak bisa ikut masuk.
    """
    with system_db() as db:
        if clear_password:
            db.execute("UPDATE users SET email_verified=1, password_hash=NULL, "
                       "session_epoch=session_epoch+1 WHERE id=?", (uid,))
        else:
            db.execute("UPDATE users SET email_verified=1 WHERE id=?", (uid,))


def count() -> int:
    with system_db() as db:
        return db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]


def epoch(uid) -> int:
    u = by_id(uid)
    return int(u["session_epoch"]) if u else 0


def touch_login(uid) -> None:
    with system_db() as db:
        db.execute("UPDATE users SET last_login_at=datetime('now') WHERE id=?", (uid,))


def set_active(uid, active: bool) -> None:
    """Pemilik tidak bisa dinonaktifkan; bukunya tetap ada agar datanya aman."""
    with system_db() as db:
        db.execute("UPDATE users SET active=? WHERE id=? AND is_owner=0", (1 if active else 0, uid))


def delete(uid) -> bool:
    """Hapus pengguna beserta file bukunya. Pemilik dilewati."""
    u = by_id(uid)
    if not u or u["is_owner"]:
        return False
    path = Path(path_for(u))
    with system_db() as db:
        db.execute("DELETE FROM users WHERE id=? AND is_owner=0", (u["id"],))
    for suffix in ("", "-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)
    return True


def path_for(user) -> str:
    return book_file(user["book"] if user else owner_book())
