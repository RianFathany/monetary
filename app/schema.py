"""Skema v2: kantong, transaksi tiga tipe, kategori master, snapshot aset.

Perubahan inti dari v1: uang yang pindah antar kantong (tabungan, dana darurat,
setoran ke sekuritas, bayar antar rekening) bukan lagi pemasukan/pengeluaran,
tapi transaksi bertipe 'transfer'. Laporan bulanan jadi jujur: pengeluaran =
uang yang benar-benar keluar dari rumah tangga.

Kolom ledger_id ada sejak sekarang dan selalu 1. Multi-user nanti tinggal
mengisinya, tanpa membongkar tabel lagi.
"""

SCHEMA_VERSION = 6
MONEY_SCALE = 100        # nominal disimpan dalam satuan perseratus (app/money.py)

SCHEMA = """
CREATE TABLE IF NOT EXISTS ledgers (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    currency   TEXT NOT NULL DEFAULT 'IDR',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Tempat uang berada. Saldo tidak disimpan, selalu dihitung dari transaksi.
--
-- is_emergency: kantong tabungan yang benar-benar dana darurat. Tanpa penanda
-- ini "cakupan dana darurat" ikut menghitung tabungan liburan dan DP rumah,
-- lalu memberi tahu pemiliknya bahwa ia aman enam bulan padahal tidak.
CREATE TABLE IF NOT EXISTS accounts (
    id              INTEGER PRIMARY KEY,
    ledger_id       INTEGER NOT NULL DEFAULT 1 REFERENCES ledgers(id),
    name            TEXT NOT NULL,
    type            TEXT NOT NULL CHECK (type IN ('cash','savings','credit','investment')),
    opening_balance INTEGER NOT NULL DEFAULT 0,   -- saldo sebelum bulan pertama
    is_emergency    INTEGER NOT NULL DEFAULT 0,   -- hanya berarti untuk type='savings'
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
    recurring_id  INTEGER REFERENCES recurring(id),  -- asalnya dari template rutin yang mana
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
CREATE INDEX IF NOT EXISTS idx_tx_recur   ON transactions(month_key, recurring_id) WHERE deleted_at IS NULL AND recurring_id IS NOT NULL;

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
CREATE TABLE IF NOT EXISTS budgets (
    id          INTEGER PRIMARY KEY,
    ledger_id   INTEGER NOT NULL DEFAULT 1 REFERENCES ledgers(id),
    month_key   TEXT NOT NULL,                  -- 'YYYY-MM'
    category_id INTEGER NOT NULL REFERENCES categories(id),
    amount      INTEGER NOT NULL DEFAULT 0,     -- satuan perseratus, 0 = tanpa anggaran
    UNIQUE(month_key, category_id)
);
CREATE INDEX IF NOT EXISTS idx_budgets_month ON budgets(month_key);

CREATE TABLE IF NOT EXISTS documents (
    id            INTEGER PRIMARY KEY,
    ledger_id     INTEGER NOT NULL DEFAULT 1 REFERENCES ledgers(id),
    kartu         TEXT NOT NULL,              -- nama kartu/penerbit, mis. "BNI"
    month_key     TEXT NOT NULL,              -- bulan tujuan tagihannya
    filename      TEXT,
    total         INTEGER NOT NULL DEFAULT 0, -- satuan perseratus, sama seperti transactions
    rows_count    INTEGER NOT NULL DEFAULT 0,
    tx_id         INTEGER REFERENCES transactions(id),   -- pengeluaran ringkas yang dibuatnya
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS document_rows (
    id            INTEGER PRIMARY KEY,
    document_id   INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    tanggal       TEXT,
    keterangan    TEXT,
    amount        INTEGER NOT NULL DEFAULT 0, -- satuan perseratus
    masuk         INTEGER NOT NULL DEFAULT 0,
    category_id   INTEGER REFERENCES categories(id),
    sort          INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_docrows_doc ON document_rows(document_id, sort);
CREATE INDEX IF NOT EXISTS idx_documents_month ON documents(month_key);

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

# Kantong bawaan untuk buku baru. (name, type, sort, is_emergency)
DEFAULT_ACCOUNTS = [
    ("Kas Utama", "cash", 10, 0),
    ("Dana Darurat", "savings", 20, 1),
]

# Buku lama tidak punya penandanya. Kantong yang namanya sudah jelas dana
# darurat ditandai sendiri saat migrasi, supaya indikator lama tidak mendadak
# kosong hanya karena ada kolom baru. Sisanya ditentukan pemiliknya di Kantong.
TAG_EMERGENCY_SQL = (
    "UPDATE accounts SET is_emergency=1 WHERE type='savings' AND is_emergency=0 "
    "AND (LOWER(name) LIKE '%darurat%' OR LOWER(name) LIKE '%emergency%')"
)

# Kategori bawaan. (name, kind, sort, is_debt, is_system)
DEFAULT_CATEGORIES = [
    ("Makan & Minum", "expense", 10, 0, 0),
    ("Transport", "expense", 20, 0, 0),
    ("Belanja", "expense", 30, 0, 0),
    ("Tagihan & Utilitas", "expense", 40, 0, 0),
    ("Cicilan Rumah", "expense", 50, 1, 0),
    # Tagihan kartu bukan cicilan: nominalnya naik-turun mengikuti belanja bulan
    # itu, dan di buku ini top-up pun lewat sini. Ikut dijumlahkan ke rasio
    # cicilan, angkanya jadi melar dan peringatannya berhenti berarti.
    ("Tagihan Kartu", "expense", 60, 0, 0),
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

# Kolom yang lahir sesudah tabelnya. `CREATE TABLE IF NOT EXISTS` tidak menyentuh
# tabel yang sudah ada, jadi buku lama tetap kehilangan kolomnya — sementara
# indeks dan view di SCHEMA sudah menyebut kolom itu dan langsung gagal. Karena
# itu kolomnya ditambahkan lebih dulu, bukan lewat MIGRATIONS yang jalan sesudah.
ADDED_COLUMNS = {
    "accounts": [("is_emergency", "INTEGER NOT NULL DEFAULT 0")],
    "transactions": [("recurring_id", "INTEGER REFERENCES recurring(id)")],
}


def _ensure_columns(conn) -> None:
    for table, cols in ADDED_COLUMNS.items():
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            continue                                  # tabelnya lahir dari SCHEMA di bawah
        ada = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, ddl in cols:
            if name not in ada:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def apply_schema(conn) -> None:
    for name in OLD_INDEXES:
        row = conn.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name=?", (name,)).fetchone()
        if row and row[0] and "WHERE deleted_at IS NULL" not in row[0]:
            conn.execute(f"DROP INDEX IF EXISTS {name}")
    _ensure_columns(conn)
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
    # v4 — dokumen impor (rekening koran & tagihan kartu) beserta rinciannya.
    # Tidak ada perintah di sini: tabelnya lahir dari apply_schema, yang memakai
    # CREATE TABLE IF NOT EXISTS, jadi buku lama maupun baru sama-sama beres.
    4: [],
    # v5 — anggaran per kategori per bulan. Tabelnya juga lahir dari
    # apply_schema, jadi tidak ada perintah yang perlu dijalankan di sini.
    5: [],
    # v6 — tiga koreksi angka yang selama ini menyesatkan:
    #   * penanda kantong dana darurat (kolom + tebakan dari namanya),
    #   * asal-usul baris dari template rutin, supaya tidak bisa dobel,
    #   * tagihan kartu keluar dari rasio cicilan.
    # Kolomnya sendiri ditambahkan apply_schema (lihat ADDED_COLUMNS); di sini
    # tinggal isinya. Laporan tersimpan dibuang karena indikatornya sudah beda arti.
    6: [
        TAG_EMERGENCY_SQL,
        "UPDATE categories SET is_debt=0 WHERE kind='expense' AND name='Tagihan Kartu'",
        "DELETE FROM reports",
    ],
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


def _migrations_done(conn) -> set:
    """Migrasi yang benar-benar pernah dijalankan di buku ini.

    Nomor versi saja tidak cukup. Kalau `SCHEMA_VERSION` sempat naik sebelum
    isi migrasinya ditulis — pernah terjadi pada `money_scale`, dan sekali lagi
    saat kolom `is_emergency` ditambahkan — buku menyimpan nomor yang baru tanpa
    perubahannya, lalu `cur == SCHEMA_VERSION` membuat migrasi itu dilewati
    selamanya. Daftar ini yang dipercaya; nomor versi tinggal jadi label.

    Buku yang belum punya daftarnya (semua buku sebelum v6) dipercaya sekali
    lewat nomor versinya, lalu daftarnya ditulis — sesudah itu tidak ada lagi
    migrasi yang bisa hilang diam-diam.
    """
    try:
        row = conn.execute("SELECT value FROM settings WHERE key='migrations_applied'").fetchone()
    except Exception:
        return set()                     # berkas kosong: tabelnya lahir sebentar lagi di apply_schema
    if row is None or row[0] is None:
        done = {v for v in MIGRATIONS if v <= book_version(conn)}
        _mark_done(conn, done)
        return done
    out = set()
    for bit in str(row[0]).split(","):
        try:
            out.add(int(bit))
        except ValueError:
            continue
    return out


def _mark_done(conn, done: set) -> None:
    conn.execute("INSERT INTO settings(key,value) VALUES ('migrations_applied',?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (",".join(str(v) for v in sorted(done)),))


def upgrade(conn) -> int:
    """Bawa satu buku ke versi skema terbaru. Idempoten dan murah kalau sudah terbaru."""
    cur = book_version(conn)
    done = _migrations_done(conn)
    tertinggal = sorted(v for v in MIGRATIONS if v not in done)
    if cur == SCHEMA_VERSION and not tertinggal:
        _scale_money(conn)                               # murah: satu SELECT kalau sudah beres
        return cur
    apply_schema(conn)                                   # tabel/indeks baru + buang indeks usang
    for version in tertinggal:
        for stmt in MIGRATIONS[version]:
            try:
                conn.execute(stmt)
            except Exception as e:                       # kolom sudah ada dari skema baru
                if "duplicate column" not in str(e).lower():
                    raise
        done.add(version)
        _mark_done(conn, done)                           # dicatat per migrasi, bukan di akhir
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
        for name, type_, sort, emergency in DEFAULT_ACCOUNTS:
            conn.execute(
                "INSERT OR IGNORE INTO accounts(ledger_id, name, type, sort, is_emergency) VALUES (1,?,?,?,?)",
                (name, type_, sort, emergency))
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?,?)", (k, v))
