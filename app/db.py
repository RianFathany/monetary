"""SQLite access. One file, WAL mode, schema created on first run."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = os.environ.get("MONETARY_DB", str(Path(__file__).resolve().parent.parent / "data" / "monetary.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id        INTEGER PRIMARY KEY,
    name      TEXT NOT NULL,
    kind      TEXT NOT NULL CHECK (kind IN ('expense','income')),
    sort      INTEGER NOT NULL DEFAULT 100,
    active    INTEGER NOT NULL DEFAULT 1,
    UNIQUE(name, kind)
);

-- Kas operasional bulanan: pemasukan & pengeluaran.
CREATE TABLE IF NOT EXISTS transactions (
    id          INTEGER PRIMARY KEY,
    month_key   TEXT NOT NULL,                       -- 'YYYY-MM' (periode buku)
    kind        TEXT NOT NULL CHECK (kind IN ('expense','income')),
    tx_date     TEXT,                                -- 'YYYY-MM-DD', boleh kosong (seperti di spreadsheet)
    category_id INTEGER REFERENCES categories(id),
    description TEXT,
    amount      INTEGER NOT NULL,                    -- rupiah bulat
    status      TEXT NOT NULL DEFAULT 'paid' CHECK (status IN ('planned','paid')),
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tx_month ON transactions(month_key, kind);

-- Mutasi dana darurat: + setor, - tarik.
CREATE TABLE IF NOT EXISTS emergency_fund (
    id          INTEGER PRIMARY KEY,
    month_key   TEXT NOT NULL,
    tx_date     TEXT,
    description TEXT,
    amount      INTEGER NOT NULL,
    linked_tx_id INTEGER REFERENCES transactions(id) ON DELETE SET NULL,  -- pasangan di kas operasional
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ef_month ON emergency_fund(month_key);

-- Snapshot aset per bulan (SAHAM / CRYPTO ...).
CREATE TABLE IF NOT EXISTS assets (
    id          INTEGER PRIMARY KEY,
    month_key   TEXT NOT NULL,
    category    TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    amount      INTEGER NOT NULL,
    UNIQUE(month_key, category, symbol)
);

-- Template rutin bulanan (KPR, CC, gaji, ...).
CREATE TABLE IF NOT EXISTS recurring (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL CHECK (kind IN ('expense','income')),
    category_id INTEGER REFERENCES categories(id),
    description TEXT,
    amount      INTEGER NOT NULL,
    day_of_month INTEGER,
    active      INTEGER NOT NULL DEFAULT 1,
    sort        INTEGER NOT NULL DEFAULT 100
);

-- Nilai tunggal: saldo awal buku, dana darurat awal.
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

DEFAULT_CATEGORIES = [
    ("KPR", "expense", 10), ("BNI", "expense", 20), ("MEGA", "expense", 30),
    ("OCTO", "expense", 35), ("GOPAYLATER", "expense", 40), ("KREDIVO", "expense", 50),
    ("TRAVELOKA", "expense", 60), ("SETOR BCA", "expense", 70), ("TABUNGAN", "expense", 80),
    ("SAHAM", "expense", 85), ("DANA DARURAT", "expense", 90), ("OTHER", "expense", 999),
    ("GAJI", "income", 10), ("BONUS", "income", 20), ("PROJECT", "income", 30),
    ("DANA DARURAT", "income", 40), ("LAINNYA", "income", 999),
]

DEFAULT_SETTINGS = {
    "opening_balance": "0",        # saldo sebelum bulan pertama
    "opening_emergency": "0",      # dana darurat sebelum bulan pertama
    "first_month": "",             # 'YYYY-MM'; kosong = ambil bulan transaksi paling awal
}


def connect() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with get_db() as db:
        db.executescript(SCHEMA)
        for name, kind, sort in DEFAULT_CATEGORIES:
            db.execute("INSERT OR IGNORE INTO categories(name, kind, sort) VALUES (?,?,?)", (name, kind, sort))
        for k, v in DEFAULT_SETTINGS.items():
            db.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?,?)", (k, v))


@contextmanager
def get_db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_setting(db, key: str, default: str = "") -> str:
    row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row and row["value"] is not None else default


def set_setting(db, key: str, value: str) -> None:
    db.execute("INSERT INTO settings(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
