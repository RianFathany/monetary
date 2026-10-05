"""Sumber email, aturannya, dan draf transaksi dari email.

Alurnya: sinkron membaca email yang cocok dengan aturan lalu menulis draf.
Draf tidak menyentuh saldo atau laporan apa pun sampai pemilik buku
menyetujuinya satu per satu — baru saat itu satu baris `transactions` lahir.

Semua fungsi menerima koneksi buku yang sedang dibuka; jaringan lewat
argumen `api` (bawaannya app/gmail.py) supaya bisa diuji tanpa Google.
"""
import calendar
import time
from datetime import datetime, timezone

from . import gmail, mailparse

FIRST_SYNC_DAYS = 30        # sinkron pertama mundur sebulan
OVERLAP_SECONDS = 86400     # mundur sehari dari sinkron terakhir; dobel dicegah UNIQUE(gmail_id)
PER_RULE = 50               # batas email per aturan per sinkron
STALE_SECONDS = 30 * 60     # halaman Dari Email menyinkron sendiri kalau sudah lewat setengah jam


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
            account_id: int, category_id) -> int:
    """Jadikan draf satu transaksi. Tanpa kategori, transaksinya masuk antrean
    Rapikan (needs_review), bukan ditebak diam-diam."""
    d = db.execute("SELECT * FROM email_drafts WHERE id=? AND status='pending'", (draft_id,)).fetchone()
    if not d:
        raise ValueError("draf tidak ada atau sudah diputuskan")
    if type_ not in ("income", "expense"):
        raise ValueError("jenis tidak sah")
    if not amount or amount <= 0:
        raise ValueError("nominal kosong")
    if not db.execute("SELECT 1 FROM accounts WHERE id=? AND deleted_at IS NULL", (account_id,)).fetchone():
        raise ValueError("kantong tidak ada")
    if category_id is not None and not db.execute(
            "SELECT 1 FROM categories WHERE id=? AND kind=? AND deleted_at IS NULL", (category_id, type_)).fetchone():
        category_id = None
    try:
        datetime.strptime(tx_date or "", "%Y-%m-%d")
    except ValueError:
        raise ValueError("tanggal tidak sah")
    cur = db.execute(
        "INSERT INTO transactions(month_key, type, tx_date, account_id, category_id, description, amount, "
        "status, needs_review) VALUES (?,?,?,?,?,?,?,'paid',?)",
        (tx_date[:7], type_, tx_date, account_id, category_id, (description or "").strip()[:200] or None,
         amount, 0 if category_id else 1))
    db.execute("UPDATE email_drafts SET status='approved', tx_id=? WHERE id=?", (cur.lastrowid, draft_id))
    return cur.lastrowid


def dismiss(db, draft_id: int) -> None:
    db.execute("UPDATE email_drafts SET status='dismissed' WHERE id=? AND status='pending'", (draft_id,))
