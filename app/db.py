"""Akses SQLite. Satu file, WAL, skema v2 dibuat saat pertama jalan."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .schema import SCHEMA_VERSION, apply_schema, seed_defaults

DB_PATH = os.environ.get("MONETARY_DB", str(Path(__file__).resolve().parent.parent / "data" / "monetary.db"))


def connect() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


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
        seed_defaults(db, accounts=first_run)
        db.execute("INSERT INTO settings(key,value) VALUES ('schema_version',?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(SCHEMA_VERSION),))


def get_setting(db, key: str, default: str = "") -> str:
    row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row and row["value"] is not None else default


def set_setting(db, key: str, value: str) -> None:
    db.execute("INSERT INTO settings(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               (key, value))


# ---------- kantong ----------

CASH_TYPES = ("cash",)
ASSET_TYPES = ("savings", "investment")


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
