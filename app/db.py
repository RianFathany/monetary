"""Akses SQLite.

Satu **file per buku**. Buku pemilik = `data/monetary.db`; setiap pengguna yang
mendaftar lewat Google mendapat filenya sendiri di `data/books/`. Pemisahan di
tingkat file dipilih supaya data antar pengguna mustahil tercampur — tidak ada
satu pun query yang perlu ingat menyaring `ledger_id`.

Hal yang berlaku untuk seluruh aplikasi (daftar pengguna, password pemilik,
secret cookie, konfigurasi Google) tinggal di `data/system.db`.
"""
import os
import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from .schema import SCHEMA_VERSION, apply_schema, seed_defaults, upgrade

DB_PATH = os.environ.get("MONETARY_DB", str(Path(__file__).resolve().parent.parent / "data" / "monetary.db"))
# Dihitung dari DB_PATH setiap kali dipakai, bukan sekali saat impor: skrip dan
# tes yang mengarahkan DB_PATH ke folder lain otomatis ikut terpisah.


def data_dir() -> Path:
    return Path(DB_PATH).parent


def books_dir() -> Path:
    return data_dir() / "books"


def system_path() -> Path:
    return data_dir() / "system.db"

# Buku yang sedang dibuka permintaan ini. Diisi middleware dari sesi; di luar
# permintaan (skrip, tes, startup) berlaku buku pemilik.
_book: ContextVar[str] = ContextVar("book", default="")


_ready: set = set()        # buku yang sudah dipastikan versinya di proses ini


def set_book(path: str) -> None:
    _book.set(path or "")
    ensure_book(path or DB_PATH)


def ensure_book(path: str) -> None:
    """Pastikan file buku ini memakai skema terbaru.

    Dipanggil sekali per buku per proses (sekali per deploy, praktisnya), jadi
    menambah kolom/tabel/indeks di versi berikutnya otomatis sampai ke buku
    semua pengguna tanpa langkah manual.
    """
    path = path or DB_PATH
    if path in _ready or not Path(path).exists():
        return
    with get_db(path) as conn:
        upgrade(conn)
    _ready.add(path)


def book_path() -> str:
    return _book.get() or DB_PATH


def book_file(name: str) -> str:
    """Nama file buku -> path lengkap. Nama berasal dari database sendiri."""
    return DB_PATH if not name or name == Path(DB_PATH).name else str(books_dir() / name)


def _open(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")       # pembaca tidak pernah memblokir penulis
    conn.execute("PRAGMA synchronous=NORMAL")     # aman di WAL, jauh lebih ringan saat menyimpan
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")      # tunggu, jangan langsung 'database is locked'
    conn.execute("PRAGMA cache_size=-8000")       # 8 MB per koneksi
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def connect() -> sqlite3.Connection:
    return _open(book_path())


@contextmanager
def get_db(path: str = ""):
    conn = _open(path or book_path())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _adopt_prepared_db() -> bool:
    """Pakai database hasil migrasi yang sudah ditaruh di sebelah database lama.

    Dipakai saat deploy ke server yang volumenya masih berisi skema lama dan kita
    tidak bisa menjalankan perintah di sana: cukup unggah `<nama>-v2.db`, lalu
    aplikasi menukarnya sekali waktu start. Database lama disimpan sebagai
    `<nama>-v1-backup.db`, tidak dihapus.
    """
    cur = Path(DB_PATH)
    prepared = cur.with_name(f"{cur.stem}-v2{cur.suffix}")
    if not prepared.exists():
        return False
    probe = sqlite3.connect(f"file:{prepared}?mode=ro", uri=True)
    try:
        is_v2 = probe.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='accounts'").fetchone()
    finally:
        probe.close()
    if not is_v2:
        return False
    if cur.exists():
        # rapikan WAL milik database lama dulu supaya tidak ada tulisan yang tertinggal,
        # lalu sisihkan berkasnya sebagai cadangan
        old = sqlite3.connect(str(cur))
        try:
            old.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            old.close()
        cur.replace(cur.with_name(f"{cur.stem}-v1-backup{cur.suffix}"))
        for side in ("-wal", "-shm"):
            Path(str(cur) + side).unlink(missing_ok=True)
    prepared.replace(cur)
    return True


@contextmanager
def system_db():
    """Database lintas-pengguna: daftar pengguna, password pemilik, konfigurasi Google."""
    conn = _open(str(system_path()))
    try:
        if str(system_path()) not in _system_ready:
            conn.executescript(SYSTEM_SCHEMA)
            have = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
            for col, decl in SYSTEM_COLUMNS:
                if col not in have:
                    conn.execute(f"ALTER TABLE users ADD COLUMN {col} {decl}")
            _system_ready.add(str(system_path()))
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


_system_ready: set = set()      # skema system.db cukup dipastikan sekali per proses

# Kolom yang ditambahkan setelah system.db pertama kali dibuat.
SYSTEM_COLUMNS = (
    ("password_hash", "TEXT"),
    ("email_verified", "INTEGER NOT NULL DEFAULT 0"),
    ("session_epoch", "INTEGER NOT NULL DEFAULT 0"),
)

SYSTEM_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id             INTEGER PRIMARY KEY,
    email          TEXT NOT NULL UNIQUE,
    name           TEXT,
    book           TEXT NOT NULL,              -- nama file di data/books (pemilik: monetary.db)
    is_owner       INTEGER NOT NULL DEFAULT 0,
    active         INTEGER NOT NULL DEFAULT 1,
    password_hash  TEXT,                       -- daftar dengan email+password (boleh kosong: SSO saja)
    email_verified INTEGER NOT NULL DEFAULT 0, -- 1 setelah Google membuktikan kepemilikan email
    session_epoch  INTEGER NOT NULL DEFAULT 0, -- dinaikkan untuk mencabut semua sesi pengguna ini
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    last_login_at  TEXT
);
CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def get_app_setting(key: str, default: str = "") -> str:
    with system_db() as db:
        row = db.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row and row["value"] is not None else default


def set_app_setting(key: str, value: str) -> None:
    with system_db() as db:
        db.execute("INSERT INTO app_settings(key, value) VALUES (?,?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


APP_KEYS = ("password_hash", "secret", "google_client_id", "google_client_secret",
            "google_allowed", "allow_signup")


def all_books() -> list:
    """Semua file buku yang ada: milik pemilik + milik setiap pengguna."""
    paths = [DB_PATH]
    try:
        with system_db() as db:
            rows = db.execute("SELECT book FROM users").fetchall()
    except sqlite3.OperationalError:
        rows = []
    for r in rows:
        path = book_file(r["book"])
        if path not in paths:
            paths.append(path)
    for extra in sorted(books_dir().glob("*.db")):        # file yatim (mis. sisa impor manual)
        if str(extra) not in paths:
            paths.append(str(extra))
    return [p for p in paths if Path(p).exists()]


def upgrade_all_books() -> list:
    """Bawa SEMUA buku ke skema terbaru. Dipanggil sekali saat aplikasi start,
    jadi setiap deploy langsung merapikan buku semua pengguna — bukan menunggu
    orangnya membuka aplikasi."""
    done = []
    for path in all_books():
        before = None
        with get_db(path) as conn:
            before = schema_of(conn)
            after = upgrade(conn)
        _ready.add(path)
        if before != after:
            done.append((path, before, after))
    return done


def schema_of(conn) -> int:
    from .schema import book_version
    return book_version(conn)


def init_system() -> None:
    """Siapkan system.db, dan pindahkan setelan lintas-aplikasi dari buku pemilik
    kalau aplikasi ini sebelumnya masih satu pengguna."""
    with system_db() as sysdb:
        have = {r["key"] for r in sysdb.execute("SELECT key FROM app_settings")}
        if not have and Path(DB_PATH).exists():
            with get_db(DB_PATH) as owner:
                try:
                    rows = owner.execute(
                        f"SELECT key, value FROM settings WHERE key IN ({','.join('?' * len(APP_KEYS))})",
                        APP_KEYS).fetchall()
                except sqlite3.OperationalError:
                    rows = []
            for r in rows:
                sysdb.execute("INSERT OR IGNORE INTO app_settings(key, value) VALUES (?,?)", (r["key"], r["value"]))
        owner_book = Path(DB_PATH).name
        sysdb.execute("INSERT OR IGNORE INTO users(id, email, name, book, is_owner) "
                      "VALUES (1, 'owner', 'Pemilik', ?, 1)", (owner_book,))


def init_book(path: str) -> None:
    """Buat/siapkan satu file buku: skema + kategori & kantong bawaan."""
    with get_db(path) as db:
        apply_schema(db)
        seed_defaults(db, accounts=True)
        db.execute("INSERT INTO settings(key,value) VALUES ('schema_version',?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(SCHEMA_VERSION),))
        db.execute("ANALYZE")
    _ready.add(path)


def init_db() -> None:
    with get_db() as db:
        legacy = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='emergency_fund'"
        ).fetchone()
    if legacy and _adopt_prepared_db():
        legacy = None
    with get_db() as db:
        if legacy:
            raise RuntimeError(
                f"{DB_PATH} masih memakai skema lama. Jalankan: python3 scripts/migrate_v2.py --apply"
            )
        apply_schema(db)
        first_run = db.execute("SELECT COUNT(*) c FROM categories").fetchone()["c"] == 0
        if first_run:
            seed_defaults(db, accounts=True)
        # Buku pemilik dinaikkan lewat jalur yang sama dengan buku pengguna lain.
        # Sebelumnya nomor versi ditulis langsung di sini tanpa menjalankan
        # MIGRATIONS — selama migrasinya kebetulan kosong tidak ketahuan, tapi
        # migrasi pertama yang berisi SQL akan dilewati diam-diam hanya untuk
        # buku ini. Itu keluarga bug yang sama dengan money_scale dulu: nomor
        # versi naik tanpa pekerjaannya dikerjakan.
        upgrade(db)
        db.execute("ANALYZE")                      # statistik untuk perencana query
    init_system()


def get_setting(db, key: str, default: str = "") -> str:
    row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row and row["value"] is not None else default


def set_setting(db, key: str, value: str) -> None:
    db.execute("INSERT INTO settings(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               (key, value))


def book_currency(db) -> str:
    """Mata uang buku ini. Kolomnya sudah ada di `ledgers` sejak skema awal."""
    row = db.execute("SELECT currency FROM ledgers WHERE id=1").fetchone()
    return (row["currency"] if row and row["currency"] else "IDR").upper()


def set_book_currency(db, code: str) -> None:
    db.execute("UPDATE ledgers SET currency=? WHERE id=1", (code.upper(),))


# ---------- kantong ----------

CASH_TYPES = ("cash",)
ASSET_TYPES = ("savings", "investment")
# Kantong utang. Saldonya negatif saat berutang — belanja mengurangi, membayar
# tagihan (transfer masuk) mengembalikan ke nol — jadi bisa langsung dijumlahkan
# ke kekayaan bersih tanpa tanda minus buatan.
DEBT_TYPES = ("credit",)


def accounts(db, types=None, active_only=True):
    sql = "SELECT * FROM accounts WHERE deleted_at IS NULL"
    args: list = []
    if active_only:
        sql += " AND active=1"
    if types:
        sql += f" AND type IN ({','.join('?' * len(types))})"
        args += list(types)
    return db.execute(sql + " ORDER BY sort, name", args).fetchall()


def balances(db):
    """Saldo semua kantong saat ini (lewat view account_balances)."""
    return {r["account_id"]: r["balance"] for r in db.execute("SELECT account_id, balance FROM account_balances")}


def emergency_ids(db) -> list:
    """Kantong yang ditandai pemiliknya sebagai dana darurat.

    Kosong berarti belum ditentukan — dan itu ditampilkan apa adanya, bukan
    diam-diam diganti seluruh tabungan. Tabungan liburan yang ikut terhitung
    membuat "aman 6 bulan" jadi kalimat yang menenangkan tanpa dasar.
    """
    return [r["id"] for r in db.execute(
        "SELECT id FROM accounts WHERE deleted_at IS NULL AND type='savings' AND is_emergency=1").fetchall()]


def emergency_fund(db, mk: str):
    """Saldo dana darurat sampai akhir bulan mk, atau None kalau belum ditentukan."""
    ids = emergency_ids(db)
    return balance_upto(db, mk, ids=ids) if ids else None


def balance_upto(db, mk: str, types=CASH_TYPES, ids=None) -> int:
    """Saldo gabungan kantong (menurut `types`, atau daftar `ids`) sampai akhir bulan mk.

    Transfer antar kantong di dalam kelompok yang sama tidak mengubah saldo
    kelompok, makanya sisi lawan transfer ikut diperiksa.
    """
    if ids is not None:
        if not ids:
            return 0
        rows = db.execute("SELECT id, opening_balance FROM accounts WHERE deleted_at IS NULL AND id IN "
                          f"({','.join('?' * len(ids))})", list(ids)).fetchall()
    else:
        ph = ",".join("?" * len(types))
        rows = db.execute(
            f"SELECT id, opening_balance FROM accounts WHERE deleted_at IS NULL AND type IN ({ph})", list(types)
        ).fetchall()
    if not rows:
        return 0
    ids = [r["id"] for r in rows]
    grp = ",".join(str(i) for i in ids)          # id dari database sendiri, aman dirangkai
    total = sum(r["opening_balance"] for r in rows)
    q = (f"SELECT COALESCE(SUM(CASE"
         f" WHEN type='income'   AND account_id    IN ({grp}) THEN  amount"
         f" WHEN type='expense'  AND account_id    IN ({grp}) THEN -amount"
         f" WHEN type='transfer' AND account_id    IN ({grp}) AND to_account_id NOT IN ({grp}) THEN -amount"
         f" WHEN type='transfer' AND to_account_id IN ({grp}) AND account_id    NOT IN ({grp}) THEN  amount"
         f" END),0) v FROM transactions WHERE deleted_at IS NULL AND month_key<=?")
    return int(total + (db.execute(q, (mk,)).fetchone()["v"] or 0))


def asset_view(db, mk: str) -> dict:
    """Posisi aset pada akhir bulan mk: tabungan (dihitung dari mutasi) + investasi (snapshot).

    Dipakai halaman Aset, ringkasan bulan, dan laporan — satu sumber angka.
    """
    snap_month = db.execute("SELECT MAX(month_key) v FROM asset_snapshots WHERE month_key<=?", (mk,)).fetchone()["v"]
    prev_snap = db.execute("SELECT MAX(month_key) v FROM asset_snapshots WHERE month_key<?",
                           (snap_month or mk,)).fetchone()["v"] if snap_month else None

    pots = []
    for a in accounts(db, ("savings", "investment")):
        if a["type"] == "savings":
            value = balance_upto(db, mk, ids=[a["id"]])
            pots.append(dict(id=a["id"], name=a["name"], type=a["type"], value=value, invested=value,
                             gain=0, stale=False))
        else:
            invested = balance_upto(db, mk, ids=[a["id"]])
            row = db.execute("SELECT COALESCE(SUM(amount),0) v FROM asset_snapshots WHERE account_id=? AND month_key=?",
                             (a["id"], snap_month or "")).fetchone()
            has_snap = db.execute("SELECT 1 FROM asset_snapshots WHERE account_id=? AND month_key=?",
                                  (a["id"], snap_month or "")).fetchone() is not None
            value = int(row["v"]) if has_snap else invested
            pots.append(dict(id=a["id"], name=a["name"], type=a["type"], value=value, invested=invested,
                             gain=value - invested if has_snap else 0,
                             stale=bool(snap_month and snap_month < mk) or not has_snap))
    pots = [p for p in pots if p["value"] or p["invested"]]
    total = sum(p["value"] for p in pots)
    return dict(mk=mk, pots=pots, total=total, snap_month=snap_month, prev_snap=prev_snap,
                fund=sum(p["value"] for p in pots if p["type"] == "savings"),
                invest=sum(p["value"] for p in pots if p["type"] == "investment"))
