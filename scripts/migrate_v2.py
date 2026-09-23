#!/usr/bin/env python3
"""Migrasi data v1 (kas + dana darurat terpisah) ke skema v2 (kantong + transfer).

Jalankan pratinjau dulu — tidak ada yang ditulis:
    python3 scripts/migrate_v2.py

Kalau hasilnya sudah benar, tulis ke file baru (monetary.db lama tidak disentuh):
    python3 scripts/migrate_v2.py --apply

Inti perubahannya: pengeluaran yang sebenarnya memindahkan uang (TABUNGAN, SAHAM,
SETOR BCA, DANA DARURAT) dan pemasukan yang sebenarnya menarik dari dana darurat
berubah jadi transaksi 'transfer' — tidak lagi dihitung sebagai belanja/penghasilan.

Baris dana darurat di v1 sering berpasangan dengan baris kas (nominal & bulan
sama). Pasangan seperti itu digabung jadi satu transfer supaya tidak dobel.

Nominal di skrip ini tetap rupiah utuh. Aplikasi yang mengubahnya ke satuan
perseratus (app/money.py) saat buku hasilnya pertama kali dibuka.
"""
import argparse
import itertools
import re
import shutil
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.schema import apply_schema, seed_defaults  # noqa: E402

SRC = Path("data/monetary.db")
DST = Path("data/monetary-v2.db")

# Kantong yang dibuat untuk buku ini. (nama, tipe, urut)
ACCOUNTS = [
    ("Operasional", "cash", 10),
    ("Dana Darurat", "savings", 20),
    ("Saham", "investment", 30),
    ("Crypto", "investment", 40),
]
# Kategori tambahan khusus buku ini (di luar bawaan).
EXTRA_CATEGORIES = [("Operasional Harian", "expense", 45, 0, 0)]
MAIN = "Operasional"
FUND = "Dana Darurat"

# Kategori pengeluaran v1 -> kategori belanja v2 (tetap pengeluaran).
EXPENSE_MAP = {
    "KPR": "Cicilan Rumah",
    "BNI": "Tagihan Kartu",
    "MEGA": "Tagihan Kartu",
    "OCTO": "Tagihan Kartu",
    "GOPAYLATER": "Tagihan Kartu",
    "KREDIVO": "Tagihan Kartu",
    "TRAVELOKA": "Tagihan Kartu",
    "SETOR BCA": "Operasional Harian",
    "OTHER": "Lainnya",
}
# Kategori pengeluaran v1 yang sebenarnya perpindahan uang -> transfer ke kantong ini.
EXPENSE_AS_TRANSFER = {
    "TABUNGAN": FUND,
    "DANA DARURAT": FUND,
    "SAHAM": "Saham",
}
# Kategori pemasukan v1 -> kategori v2.
INCOME_MAP = {"GAJI": "Gaji", "BONUS": "Bonus & THR", "PROJECT": "Project", "LAINNYA": "Lainnya"}

# Pemasukan yang sebenarnya tarikan dana darurat (dilihat dari deskripsi).
DD_INCOME_RX = re.compile(r"dana\s*darurat|dandur|alokasi dari|return from|support operasional", re.I)
# Dipakai saat mencari pasangan baris dana darurat: sisi pemasukan harus berbau
# pemindahan kantong, bukan penghasilan betulan yang kebetulan nominalnya sama.
FUND_INCOME_RX = re.compile(
    r"dana\s*darurat|dandur|darurat|alokasi dari|return from|support operasional|backup operasional|"
    r"^operasional|operasional cc|surplus|surplis|forcash", re.I)
# Pencairan dari kantong investasi, bukan penghasilan.
IDLE_RX = re.compile(r"idle\s*(saham|crypto)", re.I)
# Baris dana darurat yang tujuannya kantong lain, bukan belanja.
POCKET_RX = re.compile(
    r"operasional|opersional|mega|bni|bca|mandiri|gopaylater|tpaylater|paylater|kredivo|octo|"
    r"\bcc\b|top\s*up|topup|forcash|dandur|backup|support|adjust|return|tarik tunai|tabungan|surplis|surplus",
    re.I,
)
INVEST_RX = re.compile(r"saham|crypto", re.I)
# Tebakan kategori untuk pemakaian dana darurat yang tidak punya pasangan di kas.
BILL_RX = re.compile(r"bni|mega|gopaylater|tpaylater|paylater|kredivo|octo|\bcc\b|tagihan", re.I)
DAILY_RX = re.compile(r"operasional|opersional|top\s*up|topup|tarik tunai|forcash|dandur|backup|support|adjust|darurat", re.I)


def rp(n):
    return f"{int(n):,}".replace(",", ".")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="tulis hasilnya ke data/monetary-v2.db")
    ap.add_argument("--src", default=str(SRC))
    ap.add_argument("--dst", default=str(DST))
    args = ap.parse_args()

    src = sqlite3.connect(f"file:{args.src}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row

    dst = sqlite3.connect(":memory:")
    dst.row_factory = sqlite3.Row
    dst.execute("PRAGMA foreign_keys=ON")
    apply_schema(dst)
    seed_defaults(dst, accounts=False)
    for name, kind, sort, is_debt, is_system in EXTRA_CATEGORIES:
        dst.execute("INSERT OR IGNORE INTO categories(ledger_id,name,kind,sort,is_debt,is_system) VALUES (1,?,?,?,?,?)",
                    (name, kind, sort, is_debt, is_system))
    for name, type_, sort in ACCOUNTS:
        dst.execute("INSERT INTO accounts(ledger_id, name, type, sort) VALUES (1,?,?,?)", (name, type_, sort))
    acc = {r["name"]: r["id"] for r in dst.execute("SELECT id, name FROM accounts")}
    cat = {(r["name"], r["kind"]): r["id"] for r in dst.execute("SELECT id, name, kind FROM categories")}

    # saldo awal
    def setting(k, d="0"):
        r = src.execute("SELECT value FROM settings WHERE key=?", (k,)).fetchone()
        return r["value"] if r and r["value"] is not None else d

    dst.execute("UPDATE accounts SET opening_balance=? WHERE id=?", (int(setting("opening_balance") or 0), acc[MAIN]))
    dst.execute("UPDATE accounts SET opening_balance=? WHERE id=?", (int(setting("opening_emergency") or 0), acc[FUND]))
    for k in ("first_month", "secret", "password_hash"):
        v = setting(k, "")
        if v:
            dst.execute("INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v))

    tx_rows = src.execute(
        "SELECT t.*, c.name AS cat FROM transactions t LEFT JOIN categories c ON c.id=t.category_id "
        "ORDER BY month_key, COALESCE(tx_date,'9999'), id"
    ).fetchall()
    ef_rows = src.execute("SELECT * FROM emergency_fund ORDER BY month_key, COALESCE(tx_date,'9999'), id").fetchall()

    # --- klasifikasi awal tiap baris kas
    plan = {}       # tx id -> dict(kind=..., ...)
    for t in tx_rows:
        c = (t["cat"] or "").strip().upper()
        d = t["description"] or ""
        if t["kind"] == "expense":
            if c in EXPENSE_AS_TRANSFER:
                plan[t["id"]] = dict(op="transfer", frm=MAIN, to=EXPENSE_AS_TRANSFER[c], why=f"pengeluaran {c}")
            else:
                plan[t["id"]] = dict(op="expense", acct=MAIN, cat=EXPENSE_MAP.get(c, "Lainnya"),
                                     review=1 if c == "OTHER" else 0)
        else:
            if (m := IDLE_RX.search(d)):
                plan[t["id"]] = dict(op="transfer", frm=m.group(1).title(), to=MAIN, why=f"pencairan {m.group(1)}")
            elif c == "DANA DARURAT" or DD_INCOME_RX.search(d):
                plan[t["id"]] = dict(op="transfer", frm=FUND, to=MAIN, why=f"pemasukan '{d[:28]}'")
            elif t["to_fund"]:
                plan[t["id"]] = dict(op="income", acct=FUND, cat=INCOME_MAP.get(c, "Lainnya"))
            else:
                plan[t["id"]] = dict(op="income", acct=MAIN, cat=INCOME_MAP.get(c, "Lainnya"))

    # --- baris dana darurat: cari pasangannya di kas, sisanya pakai aturan
    by_month_exp = defaultdict(list)   # pengeluaran yang jadi transfer ke dana darurat/saham
    by_month_inc = defaultdict(list)   # pemasukan (kandidat tarikan dana darurat)
    for t in tx_rows:
        if t["kind"] == "expense" and plan[t["id"]]["op"] == "transfer":
            by_month_exp[t["month_key"]].append(t)
        elif t["kind"] == "income":
            by_month_inc[t["month_key"]].append(t)
    used, ef_used = set(), set()
    ef_plan, merged = {}, []

    # (a) pasangan satu-lawan-satu: satu baris dana darurat, satu baris kas, nominal sama
    for e in ef_rows:
        amt, mk, d = e["amount"], e["month_key"], (e["description"] or "")
        if amt > 0:
            pair = next((t for t in by_month_exp[mk] if t["amount"] == amt and t["id"] not in used), None)
            if pair:
                used.add(pair["id"])
                ef_used.add(e["id"])
                merged.append((e, pair, "pengeluaran " + (pair["cat"] or "")))
        elif not INVEST_RX.fullmatch(d.strip()):
            pair = next((t for t in by_month_inc[mk] if t["amount"] == -amt and t["id"] not in used
                         and FUND_INCOME_RX.search(t["description"] or "")), None)
            if pair:
                used.add(pair["id"])
                ef_used.add(e["id"])
                plan[pair["id"]] = dict(op="transfer", frm=FUND, to=MAIN, why=f"pasangan dana darurat '{d[:24]}'")
                merged.append((e, pair, "pemasukan " + (pair["description"] or "")[:24]))

    # (b) satu setoran kas yang di sisi dana darurat dipecah beberapa baris (125jt = 110jt + 15jt)
    for mk, exps in by_month_exp.items():
        cands = [e for e in ef_rows if e["month_key"] == mk and e["amount"] > 0 and e["id"] not in ef_used]
        for t in exps:
            if t["id"] in used or len(cands) < 2:
                continue
            hit = next((combo for n in (2, 3) for combo in itertools.combinations(cands, n)
                        if sum(x["amount"] for x in combo) == t["amount"]), None)
            if hit:
                used.add(t["id"])
                for x in hit:
                    ef_used.add(x["id"])
                    merged.append((x, t, f"bagian dari pengeluaran {t['cat']} {rp(t['amount'])}"))
                cands = [e for e in cands if e["id"] not in ef_used]

    # (c) Sisanya tidak punya pasangan di kas. Perlakuannya sengaja dikurung di dalam
    #     Dana Darurat saja supaya sisa kas tetap sama dengan angka spreadsheet:
    #     keluar = belanja dari dana darurat, masuk = pemasukan ke dana darurat.
    #     Semua ditandai needs_review untuk ditinjau di aplikasi.
    for e in ef_rows:
        amt, d = e["amount"], (e["description"] or "")
        if e["id"] in ef_used:
            ef_plan[e["id"]] = None
        elif amt > 0:
            ef_plan[e["id"]] = dict(op="income", acct=FUND, cat="Lainnya", review=1)
        elif INVEST_RX.fullmatch(d.strip()):
            ef_plan[e["id"]] = dict(op="transfer", frm=FUND, to=d.strip().title(), review=0)
        elif BILL_RX.search(d):
            ef_plan[e["id"]] = dict(op="expense", acct=FUND, cat="Tagihan Kartu", review=1)
        elif not d.strip() or DAILY_RX.search(d):
            ef_plan[e["id"]] = dict(op="expense", acct=FUND, cat="Operasional Harian", review=1)
        else:
            ef_plan[e["id"]] = dict(op="expense", acct=FUND, cat="Lainnya", review=1)

    # --- tulis ke skema baru
    def ins(mk, op, amount, date=None, desc=None, status="paid", acct=None, frm=None, to=None, cat_name=None, review=0):
        if op == "transfer":
            dst.execute(
                "INSERT INTO transactions(ledger_id,month_key,type,tx_date,account_id,to_account_id,description,amount,status,needs_review)"
                " VALUES (1,?,'transfer',?,?,?,?,?,?,?)",
                (mk, date, acc[frm], acc[to], desc, amount, status, review))
        else:
            dst.execute(
                "INSERT INTO transactions(ledger_id,month_key,type,tx_date,account_id,category_id,description,amount,status,needs_review)"
                " VALUES (1,?,?,?,?,?,?,?,?,?)",
                (mk, op, date, acc[acct], cat[(cat_name, "income" if op == "income" else "expense")],
                 desc, amount, status, review))

    for t in tx_rows:
        p = plan[t["id"]]
        desc = t["description"] or (t["cat"] if p["op"] != "expense" or (t["cat"] or "") not in EXPENSE_MAP else None)
        ins(t["month_key"], p["op"], t["amount"], t["tx_date"], desc, t["status"],
            acct=p.get("acct"), frm=p.get("frm"), to=p.get("to"), cat_name=p.get("cat"), review=p.get("review", 0))
    for e in ef_rows:
        p = ef_plan.get(e["id"])
        if not p:
            continue
        ins(e["month_key"], p["op"], abs(e["amount"]), e["tx_date"], e["description"],
            acct=p.get("acct"), frm=p.get("frm"), to=p.get("to"), cat_name=p.get("cat"), review=p.get("review", 0))

    for a in src.execute("SELECT * FROM assets"):
        name = "Saham" if a["category"].upper() == "SAHAM" else "Crypto"
        dst.execute("INSERT OR REPLACE INTO asset_snapshots(ledger_id,month_key,account_id,symbol,amount) VALUES (1,?,?,?,?)",
                    (a["month_key"], acc[name], a["symbol"], a["amount"]))

    # Posisi saham/crypto yang sudah ada sebelum buku dimulai jadi saldo awal kantongnya,
    # supaya untung/rugi = nilai pasar - modal tidak menghitung posisi lama sebagai keuntungan.
    first_snap = dst.execute("SELECT MIN(month_key) v FROM asset_snapshots").fetchone()["v"]
    if first_snap:
        for a in dst.execute("SELECT id FROM accounts WHERE type='investment'").fetchall():
            val = dst.execute("SELECT COALESCE(SUM(amount),0) v FROM asset_snapshots WHERE account_id=? AND month_key=?",
                              (a["id"], first_snap)).fetchone()["v"]
            moved = dst.execute(
                "SELECT COALESCE(SUM(CASE WHEN to_account_id=? THEN amount ELSE -amount END),0) v FROM transactions "
                "WHERE type='transfer' AND month_key=? AND (to_account_id=? OR account_id=?)",
                (a["id"], first_snap, a["id"], a["id"])).fetchone()["v"]
            if val:
                dst.execute("UPDATE accounts SET opening_balance=? WHERE id=?", (int(val) - int(moved), a["id"]))

    dst.commit()   # wajib sebelum backup(): sumber yang masih punya transaksi terbuka bikin backup menggantung
    report(src, dst, merged, ef_plan, plan, tx_rows, ef_rows)

    if args.apply:
        out = Path(args.dst)
        if out.exists():
            bak = out.with_suffix(".db.bak")
            shutil.copy2(out, bak)
            print(f"\nFile lama dipindahkan ke {bak}")
        out.parent.mkdir(parents=True, exist_ok=True)
        disk = sqlite3.connect(out)
        dst.backup(disk)
        disk.close()
        print(f"Ditulis ke {out}.  data/monetary.db tidak disentuh.")
    else:
        print("\nPratinjau saja — belum ada yang ditulis. Tambahkan --apply kalau sudah benar.")


def report(src, dst, merged, ef_plan, plan, tx_rows, ef_rows):
    months = [r[0] for r in src.execute("SELECT DISTINCT month_key FROM transactions ORDER BY 1")]
    print("=" * 96)
    print("PERBANDINGAN PER BULAN — v1 menghitung pemindahan uang sebagai belanja/penghasilan, v2 tidak")
    print("=" * 96)
    print(f"{'bulan':8} {'masuk v1':>14} {'masuk v2':>14} {'keluar v1':>14} {'keluar v2':>14} {'transfer':>14}")
    for mk in months:
        i1 = src.execute("SELECT COALESCE(SUM(amount),0) v FROM transactions WHERE month_key=? AND kind='income'", (mk,)).fetchone()["v"]
        e1 = src.execute("SELECT COALESCE(SUM(amount),0) v FROM transactions WHERE month_key=? AND kind='expense'", (mk,)).fetchone()["v"]
        i2 = dst.execute("SELECT COALESCE(SUM(amount),0) v FROM transactions WHERE month_key=? AND type='income'", (mk,)).fetchone()["v"]
        e2 = dst.execute("SELECT COALESCE(SUM(amount),0) v FROM transactions WHERE month_key=? AND type='expense'", (mk,)).fetchone()["v"]
        t2 = dst.execute("SELECT COALESCE(SUM(amount),0) v FROM transactions WHERE month_key=? AND type='transfer'", (mk,)).fetchone()["v"]
        print(f"{mk:8} {rp(i1):>14} {rp(i2):>14} {rp(e1):>14} {rp(e2):>14} {rp(t2):>14}")

    # Pemeriksaan: tiga angka ini harus sama persis dengan hitungan v1/spreadsheet.
    def one(conn, sql, *a):
        return conn.execute(sql, a).fetchone()[0] or 0

    ob = int(one(src, "SELECT value FROM settings WHERE key='opening_balance'") or 0)
    oe = int(one(src, "SELECT value FROM settings WHERE key='opening_emergency'") or 0)
    want_cash = ob + one(src, "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE kind='income' AND to_fund=0") \
                   - one(src, "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE kind='expense'")
    want_fund = oe + one(src, "SELECT COALESCE(SUM(amount),0) FROM emergency_fund")
    got_cash = one(dst, "SELECT COALESCE(SUM(balance),0) FROM account_balances WHERE type='cash'")
    got_fund = one(dst, "SELECT COALESCE(SUM(balance),0) FROM account_balances WHERE type='savings'")
    print("\nPEMERIKSAAN (harus sama dengan hitungan lama)")
    for label, want, got in (("sisa kas", want_cash, got_cash), ("dana darurat", want_fund, got_fund)):
        mark = "COCOK" if want == got else f"MELESET {rp(got - want)}"
        print(f"  {label:14} lama {rp(want):>16}   baru {rp(got):>16}   {mark}")

    print("\nSALDO KANTONG SETELAH MIGRASI")
    for r in dst.execute("SELECT name, type, balance FROM account_balances ORDER BY sort"):
        print(f"  {r['name']:14} {r['type']:11} {rp(r['balance']):>16}")
    inv = dst.execute("SELECT COALESCE(SUM(amount),0) v FROM asset_snapshots WHERE month_key=(SELECT MAX(month_key) FROM asset_snapshots)").fetchone()["v"]
    fund = dst.execute("SELECT balance FROM account_balances WHERE name='Dana Darurat'").fetchone()["balance"]
    print(f"  {'TOTAL ASET':14} {'(dd+investasi)':11} {rp(fund + inv):>16}   <- dana darurat {rp(fund)} + snapshot investasi {rp(inv)}")

    print(f"\nPASANGAN YANG DIGABUNG ({len(merged)}) — baris dana darurat & baris kas yang ternyata kejadian yang sama")
    for e, t, why in merged:
        print(f"  {e['month_key']} {rp(abs(e['amount'])):>14}  DD '{(e['description'] or '')[:26]:26}'  +  {why[:40]}")

    review = [r for r in dst.execute(
        "SELECT t.month_key, t.type, t.description, t.amount, a.name AS acct, c.name AS cat FROM transactions t "
        "JOIN accounts a ON a.id=t.account_id LEFT JOIN categories c ON c.id=t.category_id "
        "WHERE t.needs_review=1 ORDER BY t.month_key")]
    fund_rows = [r for r in review if r["acct"] == FUND]
    print(f"\nDIPAKAI/DITERIMA LANGSUNG DI DANA DARURAT ({len(fund_rows)}) — tanpa pasangan di kas, semuanya ditandai untuk ditinjau")
    for r in fund_rows:
        print(f"  {r['month_key']} {r['type']:8} {r['cat'] or '':18} {rp(r['amount']):>14}  '{(r['description'] or '')[:34]}'")

    n_other = dst.execute("SELECT COUNT(*) c, COALESCE(SUM(amount),0) s FROM transactions t JOIN categories c2 ON c2.id=t.category_id "
                          "WHERE t.type='expense' AND c2.name='Lainnya'").fetchone()
    print(f"\nRingkasan: {len(tx_rows)} baris kas + {len(ef_rows)} baris dana darurat  ->  "
          f"{dst.execute('SELECT COUNT(*) c FROM transactions').fetchone()['c']} transaksi v2 "
          f"({len(merged)} pasangan digabung).")
    print(f"Kategori 'Lainnya': {n_other['c']} transaksi senilai {rp(n_other['s'])} — ini yang dirapikan di langkah 5.")


if __name__ == "__main__":
    main()
