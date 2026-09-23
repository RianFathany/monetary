"""Database kecil di memori untuk tes: skema asli, isi dibikin per tes.

Angka di tes ditulis dalam rupiah utuh supaya enak dibaca; `rp()` yang
mengubahnya ke satuan simpan (perseratus, lihat app/money.py).
"""
import sqlite3

from app.money import SCALE
from app.schema import apply_schema, seed_defaults


def rp(n) -> int:
    """Rupiah → satuan simpan."""
    return int(n * SCALE)


def make_db(accounts=(("Kas", "cash", 0), ("Dana Darurat", "savings", 0), ("Saham", "investment", 0))):
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    apply_schema(db)
    seed_defaults(db, accounts=False)
    for i, (name, type_, opening) in enumerate(accounts):
        db.execute("INSERT INTO accounts(name, type, opening_balance, sort) VALUES (?,?,?,?)",
                   (name, type_, rp(opening), (i + 1) * 10))
    return db


def acc(db, name):
    return db.execute("SELECT id FROM accounts WHERE name=?", (name,)).fetchone()["id"]


def cat(db, name, kind="expense"):
    return db.execute("SELECT id FROM categories WHERE name=? AND kind=?", (name, kind)).fetchone()["id"]


def add(db, month, type_, amount, account, to_account=None, category=None, status="paid", desc=None):
    db.execute(
        "INSERT INTO transactions(month_key,type,amount,account_id,to_account_id,category_id,status,description)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (month, type_, rp(amount), acc(db, account), acc(db, to_account) if to_account else None,
         cat(db, category, "income" if type_ == "income" else "expense") if category else None, status, desc))
    return db.execute("SELECT last_insert_rowid() v").fetchone()["v"]
