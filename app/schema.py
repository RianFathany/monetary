"""Skema v2: kantong, transaksi tiga tipe, kategori master, snapshot aset.

Perubahan inti dari v1: uang yang pindah antar kantong (tabungan, dana darurat,
setoran ke sekuritas, bayar antar rekening) bukan lagi pemasukan/pengeluaran,
tapi transaksi bertipe 'transfer'. Laporan bulanan jadi jujur: pengeluaran =
uang yang benar-benar keluar dari rumah tangga.

Kolom ledger_id ada sejak sekarang dan selalu 1. Multi-user nanti tinggal
mengisinya, tanpa membongkar tabel lagi.
"""

SCHEMA_VERSION = 3
MONEY_SCALE = 100        # nominal disimpan dalam satuan perseratus (app/money.py)

SCHEMA = """
CREATE TABLE IF NOT EXISTS ledgers (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    currency   TEXT NOT NULL DEFAULT 'IDR',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Tempat uang berada. Saldo tidak disimpan, selalu dihitung dari transaksi.
CREATE TABLE IF NOT EXISTS accounts (
    id              INTEGER PRIMARY KEY,
    ledger_id       INTEGER NOT NULL DEFAULT 1 REFERENCES ledgers(id),
    name            TEXT NOT NULL,
    type            TEXT NOT NULL CHECK (type IN ('cash','savings','credit','investment')),
    opening_balance INTEGER NOT NULL DEFAULT 0,   -- saldo sebelum bulan pertama
    note            TEXT,
    sort            INTEGER NOT NULL DEFAULT 100,
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    deleted_at      TEXT,
    UNIQUE(ledger_id, name)
);

-- Master kategori. Bawaan ikut ter-seed, user bebas menambah/mengubah/menonaktifkan.
-- is_system: tidak bisa dihapus (dipakai sebagai penampung saat kategori lain dihapus).
-- is_debt  : dihitung sebagai cicilan/utang di laporan (rasio cicilan terhadap pemasukan).
CREATE TABLE IF NOT EXISTS categories (
    id         INTEGER PRIMARY KEY,
    ledger_id  INTEGER NOT NULL DEFAULT 1 REFERENCES ledgers(id),
    name       TEXT NOT NULL,
    kind       TEXT NOT NULL CHECK (kind IN ('expense','income')),
    parent_id  INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    icon       TEXT,
    color      TEXT,
    is_debt    INTEGER NOT NULL DEFAULT 0,
    is_system  INTEGER NOT NULL DEFAULT 0,
    sort       INTEGER NOT NULL DEFAULT 100,
    active     INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    deleted_at TEXT,
    UNIQUE(ledger_id, name, kind)
);

-- income   : account_id = kantong tujuan, category_id wajib, to_account_id kosong
-- expense  : account_id = kantong sumber, category_id wajib, to_account_id kosong
-- transfer : account_id = sumber, to_account_id = tujuan, category_id kosong
CREATE TABLE IF NOT EXISTS transactions (
    id            INTEGER PRIMARY KEY,
    ledger_id     INTEGER NOT NULL DEFAULT 1 REFERENCES ledgers(id),
    month_key     TEXT NOT NULL,                  -- 'YYYY-MM', periode buku
    type          TEXT NOT NULL CHECK (type IN ('income','expense','transfer')),
    tx_date       TEXT,
    account_id    INTEGER REFERENCES accounts(id),
    to_account_id INTEGER REFERENCES accounts(id),
    category_id   INTEGER REFERENCES categories(id),
    description   TEXT,
    amount        INTEGER NOT NULL CHECK (amount > 0),
    status        TEXT NOT NULL DEFAULT 'paid' CHECK (status IN ('planned','paid')),
    needs_review  INTEGER NOT NULL DEFAULT 0,     -- hasil migrasi/impor yang perlu dicek user
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    deleted_at    TEXT,
    CHECK (type <> 'transfer' OR (to_account_id IS NOT NULL AND to_account_id <> account_id AND category_id IS NULL)),
    CHECK (type =  'transfer' OR to_account_id IS NULL)
);
-- Indeks mengikuti query yang benar-benar dipakai. Semuanya parsial
-- (deleted_at IS NULL) karena tidak ada satu pun halaman yang membaca baris
-- terhapus: indeksnya jadi lebih kecil sekaligus cocok dengan bentuk query.
CREATE INDEX IF NOT EXISTS idx_tx_month   ON transactions(month_key, type)     WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_tx_cat     ON transactions(category_id)         WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_tx_account ON transactions(account_id)          WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_tx_to      ON transactions(to_account_id)       WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_tx_review  ON transactions(month_key)           WHERE deleted_at IS NULL AND needs_review = 1;

-- Nilai kantong investasi/tabungan yang tidak bisa dihitung dari mutasi
-- (harga saham & crypto bergerak sendiri). Diisi manual per bulan.
CREATE TABLE IF NOT EXISTS asset_snapshots (
    id         INTEGER PRIMARY KEY,
    ledger_id  INTEGER NOT NULL DEFAULT 1 REFERENCES ledgers(id),
    month_key  TEXT NOT NULL,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    symbol     TEXT NOT NULL,
    amount     INTEGER NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(ledger_id, month_key, account_id, symbol)
);

-- Template rutin bulanan (KPR, tagihan kartu, gaji).
CREATE TABLE IF NOT EXISTS recurring (
    id            INTEGER PRIMARY KEY,
    ledger_id     INTEGER NOT NULL DEFAULT 1 REFERENCES ledgers(id),
    type          TEXT NOT NULL CHECK (type IN ('income','expense','transfer')),
    account_id    INTEGER REFERENCES accounts(id),
    to_account_id INTEGER REFERENCES accounts(id),
    category_id   INTEGER REFERENCES categories(id),
    description   TEXT,
    amount        INTEGER NOT NULL,
    day_of_month  INTEGER,
    active        INTEGER NOT NULL DEFAULT 1,
    sort          INTEGER NOT NULL DEFAULT 100
);

-- Laporan bulanan tersimpan. engine: 'rules' sekarang, 'ai' menyusul.
CREATE TABLE IF NOT EXISTS reports (
    id           INTEGER PRIMARY KEY,
    ledger_id    INTEGER NOT NULL DEFAULT 1 REFERENCES ledgers(id),
    month_key    TEXT NOT NULL,
    engine       TEXT NOT NULL DEFAULT 'rules',
    content_json TEXT NOT NULL,
    generated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(ledger_id, month_key, engine)
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE VIEW IF NOT EXISTS account_balances AS
SELECT a.id AS account_id, a.ledger_id, a.name, a.type, a.sort,
       a.opening_balance
       + COALESCE((SELECT SUM(amount) FROM transactions t
                   WHERE t.deleted_at IS NULL AND t.account_id=a.id AND t.type='income'), 0)
       - COALESCE((SELECT SUM(amount) FROM transactions t
                   WHERE t.deleted_at IS NULL AND t.account_id=a.id AND t.type IN ('expense','transfer')), 0)
       + COALESCE((SELECT SUM(amount) FROM transactions t
                   WHERE t.deleted_at IS NULL AND t.to_account_id=a.id AND t.type='transfer'), 0)
       AS balance
FROM accounts a
WHERE a.deleted_at IS NULL;
"""

# Kantong bawaan untuk buku baru. (name, type, sort)
DEFAULT_ACCOUNTS = [
    ("Kas Utama", "cash", 10),
    ("Dana Darurat", "savings", 20),
]

# Kategori bawaan. (name, kind, sort, is_debt, is_system)
DEFAULT_CATEGORIES = [
    ("Makan & Minum", "expense", 10, 0, 0),
    ("Transport", "expense", 20, 0, 0),
    ("Belanja", "expense", 30, 0, 0),
    ("Tagihan & Utilitas", "expense", 40, 0, 0),
    ("Cicilan Rumah", "expense", 50, 1, 0),
    ("Tagihan Kartu", "expense", 60, 1, 0),
    ("Cicilan Lain", "expense", 70, 1, 0),
    ("Kesehatan", "expense", 80, 0, 0),
    ("Pendidikan", "expense", 90, 0, 0),
    ("Keluarga & Rumah", "expense", 100, 0, 0),
    ("Hiburan", "expense", 110, 0, 0),
    ("Perawatan Diri", "expense", 120, 0, 0),
    ("Donasi & Sosial", "expense", 130, 0, 0),
    ("Pajak & Admin", "expense", 140, 0, 0),
    ("Lainnya", "expense", 999, 0, 1),
    ("Gaji", "income", 10, 0, 0),
    ("Bonus & THR", "income", 20, 0, 0),
    ("Project", "income", 30, 0, 0),
    ("Hasil Investasi", "income", 40, 0, 0),
    ("Hadiah", "income", 50, 0, 0),
    ("Lainnya", "income", 999, 0, 1),
]

DEFAULT_SETTINGS = {
    "schema_version": str(SCHEMA_VERSION),
    "first_month": "",        # 'YYYY-MM'; kosong = ambil bulan transaksi paling awal
    "ledger_name": "Pribadi",
}


# Indeks versi lama yang bentuknya tidak cocok dengan query — dibuang sekali,
# lalu dibuat ulang oleh SCHEMA di atas.
OLD_INDEXES = ("idx_tx_month", "idx_tx_account", "idx_tx_to")


def apply_schema(conn) -> None:
    for name in OLD_INDEXES:
        row = conn.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name=?", (name,)).fetchone()
        if row and row[0] and "WHERE deleted_at IS NULL" not in row[0]:
            conn.execute(f"DROP INDEX IF EXISTS {name}")
    conn.executescript(SCHEMA)
    conn.execute("INSERT OR IGNORE INTO ledgers(id, name) VALUES (1, 'Pribadi')")


# Perubahan skema setelah versi 2. Satu entri = satu versi; isinya perintah yang
# aman dijalankan ulang. Dijalankan untuk SETIAP buku (pemilik maupun pengguna
# lain) saat pertama dibuka setelah aplikasi diperbarui.
#
#   MIGRATIONS = {3: ["ALTER TABLE transactions ADD COLUMN tag TEXT"]}
#
# Naikkan SCHEMA_VERSION bersamaan dengan menambah entri di sini.
MIGRATIONS: dict = {
    # v3 — nominal pindah ke satuan perseratus; lihat _scale_money() di bawah.
    # Laporan tersimpan dibuang karena angkanya sudah tidak sepadan lagi.
    3: ["DELETE FROM reports"],
}

# Skala nominal dijaga penanda sendiri, bukan nomor versi skema. Nomor versi bisa
# terlanjur naik tanpa migrasinya sempat jalan (pernah terjadi saat pengembangan),
# dan mengalikan dua kali jauh lebih merusak daripada mengecek satu baris setelan.
SCALE_STATEMENTS = (
    "UPDATE transactions SET amount = amount * {f}",
    "UPDATE accounts SET opening_balance = opening_balance * {f}",
    "UPDATE asset_snapshots SET amount = amount * {f}",
    "UPDATE recurring SET amount = amount * {f}",
)


def _scale_money(conn) -> bool:
    """Naikkan semua nominal ke satuan perseratus, sekali saja seumur buku."""
    row = conn.execute("SELECT value FROM settings WHERE key='money_scale'").fetchone()
    if row and row[0] == str(MONEY_SCALE):
        return False
    for stmt in SCALE_STATEMENTS:
        conn.execute(stmt.format(f=MONEY_SCALE))
    conn.execute("DELETE FROM reports")                  # angkanya sudah tidak sepadan
    conn.execute("INSERT INTO settings(key,value) VALUES ('money_scale',?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(MONEY_SCALE),))
    return True


def book_version(conn) -> int:
    try:
        row = conn.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()
    except Exception:
        return 0
    try:
        return int(row[0]) if row and row[0] else 0
    except (TypeError, ValueError):
        return 0


def upgrade(conn) -> int:
    """Bawa satu buku ke versi skema terbaru. Idempoten dan murah kalau sudah terbaru."""
    cur = book_version(conn)
    if cur == SCHEMA_VERSION:
        _scale_money(conn)                               # murah: satu SELECT kalau sudah beres
        return cur
    apply_schema(conn)                                   # tabel/indeks baru + buang indeks usang
    for version in sorted(v for v in MIGRATIONS if v > cur):
        for stmt in MIGRATIONS[version]:
            try:
                conn.execute(stmt)
            except Exception as e:                       # kolom sudah ada dari skema baru
                if "duplicate column" not in str(e).lower():
                    raise
    _scale_money(conn)                                   # nominal ke satuan perseratus, sekali saja
    seed_defaults(conn, accounts=False)                  # kategori bawaan yang baru ditambahkan
    conn.execute("INSERT INTO settings(key,value) VALUES ('schema_version',?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(SCHEMA_VERSION),))
    return SCHEMA_VERSION


def seed_defaults(conn, accounts=True) -> None:
    """Isi kategori (dan opsional kantong) bawaan. Aman dipanggil berulang."""
    for name, kind, sort, is_debt, is_system in DEFAULT_CATEGORIES:
        conn.execute(
            "INSERT OR IGNORE INTO categories(ledger_id, name, kind, sort, is_debt, is_system) VALUES (1,?,?,?,?,?)",
            (name, kind, sort, is_debt, is_system),
        )
    if accounts:
        for name, type_, sort in DEFAULT_ACCOUNTS:
            conn.execute("INSERT OR IGNORE INTO accounts(ledger_id, name, type, sort) VALUES (1,?,?,?)",
                         (name, type_, sort))
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?,?)", (k, v))
