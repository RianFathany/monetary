"""Sumber email, aturannya, dan draf transaksi dari email.

Alurnya: sinkron membaca email yang cocok dengan aturan lalu menulis draf.
Draf tidak menyentuh saldo atau laporan apa pun sampai pemilik buku
menyetujuinya satu per satu — baru saat itu satu baris `transactions` lahir.

Semua fungsi menerima koneksi buku yang sedang dibuka; jaringan lewat
argumen `api` (bawaannya app/gmail.py) supaya bisa diuji tanpa Google.
"""
import calendar
import re
import time
from datetime import datetime, timezone

from . import db as dbm, gmail, mailparse, suggest

FIRST_SYNC_DAYS = 30        # sinkron pertama mundur sebulan
OVERLAP_SECONDS = 86400     # mundur sehari dari sinkron terakhir; dobel dicegah UNIQUE(gmail_id)
PER_RULE = 50               # batas email per aturan per sinkron
STALE_SECONDS = 30 * 60     # halaman Dari Email menyinkron sendiri kalau sudah lewat setengah jam
OWN_NAMES_KEY = "email_own_names"   # nama pemilik rekening, dipisah koma; untuk mengenali transfer ke rekening sendiri
PAIR_DAYS = 1               # "dana masuk" dianggap pasangan transfer kalau tanggalnya selisih paling banyak sehari


def _epoch(stamp: str) -> int:
    try:
        return calendar.timegm(datetime.strptime(stamp[:19], "%Y-%m-%d %H:%M:%S").timetuple())
    except (TypeError, ValueError):
        return 0


def _utc(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ---------- sumber & aturan ----------

def sources(db) -> list:
    rows = db.execute("SELECT s.*, (SELECT COUNT(*) FROM email_drafts d WHERE d.source_id=s.id "
                      "AND d.status='pending') AS pending FROM email_sources s ORDER BY s.id").fetchall()
    out = []
    for s in rows:
        item = dict(s)
        item.pop("token_enc", None)                       # tidak pernah sampai ke template
        item["rules"] = [dict(r) for r in db.execute(
            "SELECT r.*, a.name AS account FROM email_rules r LEFT JOIN accounts a ON a.id=r.account_id "
            "WHERE r.source_id=? ORDER BY r.id", (s["id"],))]
        out.append(item)
    return out


def save_source(db, email: str, refresh_token: str) -> int:
    """Simpan atau perbarui token. Menyambung ulang akun yang sama tidak
    menghapus aturan dan draf yang sudah ada."""
    sealed = gmail.seal(refresh_token)
    db.execute("INSERT INTO email_sources(email, token_enc) VALUES (?,?) "
               "ON CONFLICT(email) DO UPDATE SET token_enc=excluded.token_enc, status='ok', last_error=NULL",
               (email.lower(), sealed))
    return db.execute("SELECT id FROM email_sources WHERE email=?", (email.lower(),)).fetchone()["id"]


def delete_source(db, source_id: int, api=gmail) -> bool:
    """Putuskan: cabut izin di Google, hapus token dan aturannya.

    Draf yang masih menunggu ikut dibuang. Draf yang sudah disetujui tetap ada
    sebagai jejak asal transaksinya."""
    row = db.execute("SELECT * FROM email_sources WHERE id=?", (source_id,)).fetchone()
    if not row:
        return False
    try:
        api.revoke(api.unseal(row["token_enc"]))
    except gmail.Gagal:
        pass
    db.execute("DELETE FROM email_drafts WHERE source_id=? AND status='pending'", (source_id,))
    db.execute("DELETE FROM email_sources WHERE id=?", (source_id,))
    return True


def add_rule(db, source_id: int, sender: str, keywords: str, parser: str, account_id) -> int:
    sender = " ".join((sender or "").split()) or mailparse.PROFILES.get(parser, {}).get("sender", "")
    if not keywords and parser in mailparse.PROFILES:
        keywords = mailparse.PROFILES[parser]["keywords"]        # tanpa JS: isian bawaan bank
    if not sender:
        raise ValueError("pengirim kosong")
    if parser not in mailparse.PROFILES:
        parser = "umum"
    if not db.execute("SELECT 1 FROM email_sources WHERE id=?", (source_id,)).fetchone():
        raise ValueError("sumber tidak ada")
    if account_id is not None and not db.execute(
            "SELECT 1 FROM accounts WHERE id=? AND deleted_at IS NULL", (account_id,)).fetchone():
        account_id = None
    kata = ", ".join(k.strip() for k in (keywords or "").split(",") if k.strip())
    cur = db.execute("INSERT INTO email_rules(source_id, sender, keywords, parser, account_id) VALUES (?,?,?,?,?)",
                     (source_id, sender, kata, parser, account_id))
    return cur.lastrowid


def preview(db, source_id: int, sender: str, keywords: str, api=gmail, now: int = 0) -> dict:
    """Berapa email 30 hari terakhir yang cocok dengan calon aturan, plus tiga
    subjek contoh — supaya pengguna tahu aturannya kena sebelum menyimpan.
    Tidak menulis apa pun."""
    row = db.execute("SELECT * FROM email_sources WHERE id=?", (source_id,)).fetchone()
    if not row:
        raise ValueError("sumber tidak ada")
    if not (sender or "").strip():
        raise ValueError("pengirim kosong")
    now = now or int(time.time())
    token = api.access_token(api.unseal(row["token_enc"]))
    ids = api.list_ids(token, api.query(sender, keywords, now - FIRST_SYNC_DAYS * 86400), PER_RULE)
    return dict(count=len(ids), more=len(ids) >= PER_RULE, subjects=api.subjects(token, ids[:3]))


def delete_rule(db, rule_id: int) -> None:
    db.execute("DELETE FROM email_rules WHERE id=?", (rule_id,))


# ---------- sinkron ----------

def is_stale(db) -> bool:
    row = db.execute("SELECT MIN(COALESCE(last_sync_at,'')) v, COUNT(*) n FROM email_sources "
                     "WHERE status='ok'").fetchone()
    if not row["n"]:
        return False
    return time.time() - _epoch(row["v"] or "") > STALE_SECONDS


def sync(db, api=gmail, now: int = 0) -> dict:
    """Baca email baru dari setiap sumber. Hanya menulis draf.

    Satu sumber yang gagal tidak menghentikan sumber lain; galatnya disimpan
    di barisnya dan ditampilkan di Setelan."""
    now = now or int(time.time())
    hasil = dict(new=0, unread=0, failed=0, reauth=0)
    for s in db.execute("SELECT * FROM email_sources WHERE status='ok' ORDER BY id").fetchall():
        rules = db.execute("SELECT * FROM email_rules WHERE source_id=? AND active=1 ORDER BY id",
                           (s["id"],)).fetchall()
        if not rules:
            continue
        try:
            token = api.access_token(api.unseal(s["token_enc"]))
            last = _epoch(s["last_sync_at"] or "")
            after = (last - OVERLAP_SECONDS) if last else (now - FIRST_SYNC_DAYS * 86400)
            for r in rules:
                for mid in api.list_ids(token, api.query(r["sender"], r["keywords"], after), PER_RULE):
                    if db.execute("SELECT 1 FROM email_drafts WHERE source_email=? AND gmail_id=?",
                                  (s["email"], mid)).fetchone():
                        continue
                    msg = api.fetch(token, mid)
                    p = mailparse.parse(msg["text"], msg["subject"], r["parser"], msg["epoch"])
                    db.execute(
                        "INSERT OR IGNORE INTO email_drafts(source_id, rule_id, gmail_id, source_email, "
                        "received_at, sender, subject, snippet, type, tx_date, amount, description, account_id) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (s["id"], r["id"], mid, s["email"], _utc(msg["epoch"]) if msg["epoch"] else None,
                         msg["sender"][:200], msg["subject"][:200], mailparse.snippet(msg["text"]),
                         p["type"], p["tx_date"], p["amount"], p["description"], r["account_id"]))
                    hasil["new"] += 1
                    hasil["unread"] += 0 if p["amount"] else 1
            db.execute("UPDATE email_sources SET last_sync_at=?, last_error=NULL WHERE id=?", (_utc(now), s["id"]))
        except gmail.PerluSambungUlang as e:
            db.execute("UPDATE email_sources SET status='reauth', last_error=? WHERE id=?", (str(e), s["id"]))
            hasil["reauth"] += 1
        except gmail.Gagal as e:
            db.execute("UPDATE email_sources SET last_error=? WHERE id=?", (str(e), s["id"]))
            hasil["failed"] += 1
    return hasil


# ---------- draf ----------

def pending_count(db) -> int:
    return db.execute("SELECT COUNT(*) c FROM email_drafts WHERE status='pending'").fetchone()["c"]


def drafts(db, status: str = "pending", limit: int = 200) -> list:
    return db.execute(
        "SELECT d.*, a.name AS account, r.parser FROM email_drafts d LEFT JOIN accounts a ON a.id=d.account_id "
        "LEFT JOIN email_rules r ON r.id=d.rule_id WHERE d.status=? ORDER BY COALESCE(d.tx_date, d.received_at) DESC, d.id DESC LIMIT ?",
        (status, limit)).fetchall()


def approve(db, draft_id: int, type_: str, amount: int, tx_date: str, description: str,
            account_id: int, category_id, to_account_id=None) -> int:
    """Jadikan draf satu transaksi. Tanpa kategori, transaksinya masuk antrean
    Rapikan (needs_review), bukan ditebak diam-diam.

    type_ 'transfer' = pindah antar kantong sendiri: account_id asal, to_account_id
    tujuan, tanpa kategori. Draf "dana masuk" pasangannya (nominal sama, tanggal
    berdekatan, dari rekening sendiri) ikut dibuang supaya tidak tercatat dua kali."""
    d = db.execute("SELECT * FROM email_drafts WHERE id=? AND status='pending'", (draft_id,)).fetchone()
    if not d:
        raise ValueError("draf tidak ada atau sudah diputuskan")
    if type_ not in ("income", "expense", "transfer"):
        raise ValueError("jenis tidak sah")
    if not amount or amount <= 0:
        raise ValueError("nominal kosong")
    for a in (account_id, to_account_id) if type_ == "transfer" else (account_id,):
        if not a or not db.execute("SELECT 1 FROM accounts WHERE id=? AND deleted_at IS NULL", (a,)).fetchone():
            raise ValueError("kantong tidak ada")
    if type_ == "transfer":
        if to_account_id == account_id:
            raise ValueError("kantong asal dan tujuan sama")
        category_id = None
    elif category_id is not None and not db.execute(
            "SELECT 1 FROM categories WHERE id=? AND kind=? AND deleted_at IS NULL", (category_id, type_)).fetchone():
        category_id = None
    try:
        datetime.strptime(tx_date or "", "%Y-%m-%d")
    except ValueError:
        raise ValueError("tanggal tidak sah")
    review = 0 if (category_id or type_ == "transfer") else 1
    cur = db.execute(
        "INSERT INTO transactions(month_key, type, tx_date, account_id, to_account_id, category_id, description, "
        "amount, status, needs_review) VALUES (?,?,?,?,?,?,?,?,'paid',?)",
        (tx_date[:7], type_, tx_date, account_id, to_account_id if type_ == "transfer" else None, category_id,
         (description or "").strip()[:200] or None, amount, review))
    db.execute("UPDATE email_drafts SET status='approved', tx_id=? WHERE id=?", (cur.lastrowid, draft_id))
    if type_ == "transfer":
        pasangan = _pairs(db, [dict(r) for r in db.execute(
            "SELECT * FROM email_drafts WHERE status='pending' AND type='income' AND amount=?", (amount,))],
            own_names(db), [dict(id=draft_id, amount=amount, tx_date=tx_date, type="expense")])
        for did in pasangan:
            db.execute("UPDATE email_drafts SET status='dismissed' WHERE id=? AND status='pending'", (did,))
    return cur.lastrowid


def dismiss(db, draft_id: int) -> None:
    db.execute("UPDATE email_drafts SET status='dismissed' WHERE id=? AND status='pending'", (draft_id,))


# ---------- transfer & dobel ----------

def _kata(text) -> str:
    return " " + " ".join(re.findall(r"[a-z0-9]+", str(text or "").lower())) + " "


def own_names(db) -> list:
    return [n for n in (_kata(x).strip() for x in dbm.get_setting(db, OWN_NAMES_KEY, "").split(",")) if n]


def save_own_names(db, raw: str) -> None:
    names = [" ".join(x.split()) for x in (raw or "").split(",") if x.strip()]
    dbm.set_setting(db, OWN_NAMES_KEY, ", ".join(names)[:300])


def _milik_sendiri(text, names) -> bool:
    t = _kata(text)
    return any(f" {n} " in t for n in names)


def _dekat(a: str, b: str) -> bool:
    try:
        return abs((datetime.strptime(a, "%Y-%m-%d") - datetime.strptime(b, "%Y-%m-%d")).days) <= PAIR_DAYS
    except (TypeError, ValueError):
        return False


def _pairs(db, incomes: list, names: list, outs: list) -> set:
    """Id draf masuk yang merupakan sisi terima dari transfer keluar di `outs`
    (draf transfer atau transaksi transfer yang sudah dicatat)."""
    found = set()
    terpakai = set()
    for inc in incomes:
        if inc.get("type") != "income" or not inc.get("amount"):
            continue
        for o in outs:
            if o["id"] in terpakai or o["amount"] != inc["amount"] or not _dekat(o["tx_date"], inc["tx_date"]):
                continue
            found.add(inc["id"])
            terpakai.add(o["id"])
            break
    return found


def classify(db, rows: list) -> dict:
    """{draft_id: 'transfer' | 'dup' | ''} untuk draf yang menunggu.

    transfer : penerima/pengirim di keterangan adalah nama pemilik sendiri.
    dup      : "dana masuk" yang pasangannya transfer keluar (draf atau transaksi
               transfer yang sudah dicatat), jadi bukan pemasukan baru.
    Tanpa nama pemilik, tidak ada yang ditebak sebagai transfer."""
    names = own_names(db)
    rows = [dict(r) for r in rows]
    kind = {r["id"]: "" for r in rows}
    if not names:
        return kind
    for r in rows:
        if _milik_sendiri(f"{r.get('description') or ''} {r.get('subject') or ''} {r.get('snippet') or ''}", names):
            kind[r["id"]] = "transfer"
    outs = [r for r in rows if kind[r["id"]] == "transfer" and r["type"] == "expense" and r.get("amount")]
    outs += [dict(id=-t["id"], amount=t["amount"], tx_date=t["tx_date"]) for t in db.execute(
        "SELECT id, amount, tx_date FROM transactions WHERE type='transfer' AND deleted_at IS NULL "
        "AND tx_date >= date('now', '-45 day')")]
    for did in _pairs(db, [r for r in rows if r["type"] == "income"], names, outs):
        kind[did] = "dup"
    return kind


def approve_all(db, rows: list, kinds: dict, cats: dict) -> dict:
    """Setujui sekaligus draf yang sudah lengkap: nominal & kantong terisi, bukan
    transfer, bukan dobel. Kategori dari saran (sama dengan isian lembar periksa);
    yang tidak punya saran masuk Rapikan. Sisanya dibiarkan untuk diperiksa.
    cats = {"expense": {nama: id}, "income": {...}}."""
    done = skipped = 0
    for d in rows:
        if not d["amount"] or not d["account_id"] or kinds.get(d["id"]):
            skipped += 1
            continue
        cid, _ = suggest.suggest(d["description"] or d["subject"] or "", d["type"], cats.get(d["type"], {}))
        try:
            approve(db, d["id"], d["type"], d["amount"], d["tx_date"] or "", d["description"] or d["subject"] or "",
                    d["account_id"], cid)
            done += 1
        except ValueError:
            skipped += 1
    return dict(done=done, skipped=skipped)
