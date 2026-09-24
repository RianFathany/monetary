"""Muara — kas, kantong, dana darurat, dan aset. Satu user, satu file SQLite.

Tiga tipe transaksi: pemasukan, pengeluaran, dan transfer antar kantong.
Transfer tidak pernah dihitung sebagai pemasukan/pengeluaran — itu yang bikin
angka bulanan jujur (menabung bukan belanja).
"""
import json
import os
import re
import secrets
from urllib.parse import quote
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse, RedirectResponse,
                               StreamingResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from . import (auth, backup, csrf, documents, i18n, legal, mailer, money, oauth, report,
               statement, suggest, users)
from .i18n import t
from .db import (ASSET_TYPES, CASH_TYPES, accounts, asset_view, balance_upto, balances, book_currency,
                 get_db, get_setting, set_book_currency,
                 init_db, set_app_setting, set_book, set_setting, upgrade_all_books)

BASE = Path(__file__).resolve().parent
def _load_env_file() -> None:
    """Baca `.env` di akar proyek kalau ada. Variabel yang sudah ada di
    environment tidak ditimpa, jadi di server (fly secrets) berkas ini tidak
    berpengaruh apa-apa. Tanpa ini, `.env` hanya terbaca lewat Docker Compose
    dan setelan lokal diam-diam terabaikan."""
    berkas = BASE.parent / ".env"
    if not berkas.exists():
        return
    for baris in berkas.read_text(errors="replace").splitlines():
        baris = baris.strip()
        if not baris or baris.startswith("#") or "=" not in baris:
            continue
        kunci, _, nilai = baris.partition("=")
        kunci = kunci.strip()
        nilai = nilai.strip().strip('"').strip("'")
        if kunci and kunci not in os.environ:
            os.environ[kunci] = nilai


_load_env_file()

app = FastAPI(title="Muara", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
app.add_middleware(csrf.CSRFMiddleware)
templates = Jinja2Templates(directory=BASE / "templates")

ACCOUNT_TYPES = {
    "cash": "Kas & rekening harian",
    "savings": "Tabungan & dana darurat",
    "credit": "Kartu kredit & paylater",
    "investment": "Investasi",
}   # label ini diterjemahkan lewat _() di template


# ---------- helpers ----------

def rupiah(n) -> str:
    """Nama filternya tetap `rupiah` — dipakai di puluhan template. Isinya
    sekarang mengikuti mata uang buku yang sedang dibuka."""
    return money.fmt(n)


def month_label(key: str) -> str:
    y, m = key.split("-")
    return f"{i18n.months(short=True)[int(m) - 1]} {y}"


def shift_month(key: str, delta: int) -> str:
    y, m = map(int, key.split("-"))
    m += delta
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}"


def this_month() -> str:
    return date.today().strftime("%Y-%m")


def parse_amount(raw: str) -> int:
    return money.parse(raw)


def clean_date(raw: Optional[str]) -> Optional[str]:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return None


def fmt_date(raw: Optional[str]) -> str:
    if not raw:
        return ""
    try:
        d = datetime.strptime(raw, "%Y-%m-%d")
        return f"{d.day} {i18n.months(short=True)[d.month - 1]}"
    except ValueError:
        return raw


def hue(name) -> int:
    h = 0
    for ch in str(name or ""):
        h = (h * 31 + ord(ch)) % 360
    return h


def short_rupiah(n) -> str:
    return money.short(n)


def stamp(raw) -> str:
    try:
        d = datetime.strptime(str(raw)[:16], "%Y-%m-%d %H:%M")
        return f"{d.day} {i18n.months(short=True)[d.month - 1]} {d.year}, {d:%H:%M}"
    except ValueError:
        return str(raw)


templates.env.filters["stamp"] = stamp
templates.env.filters["rupiah"] = rupiah
templates.env.filters["month_label"] = month_label
templates.env.filters["fmt_date"] = fmt_date
templates.env.filters["hue"] = hue
templates.env.filters["short"] = short_rupiah
templates.env.filters["plain"] = money.plain
templates.env.filters["t"] = t
templates.env.globals["_"] = t


# Domain lama tetap dilayani supaya tautan yang sudah beredar tidak putus, tapi
# dialihkan permanen ke domain utama agar tidak ada dua alamat dengan isi sama.
# Daftarnya dari environment: kosong = tidak ada pengalihan, aman untuk laptop.
LEGACY_HOSTS = {h.strip().lower() for h in os.environ.get("REDIRECT_HOSTS", "").split(",") if h.strip()}
CANONICAL_HOST = os.environ.get("CANONICAL_HOST", "").strip().lower()


@app.middleware("http")
async def _canonical_host(request: Request, call_next):
    """Domain lama dialihkan permanen ke yang baru.

    301 hanya untuk permintaan yang aman. Untuk POST dipakai 308, karena
    peramban mengubah 301 dan 302 menjadi GET tanpa membawa body — jadi setiap
    form yang dikirim dari domain lama akan mendarat sebagai GET ke rute yang
    cuma menerima POST, dan berakhir 405. Yang patah bukan satu tombol, tapi
    semua form: masuk, daftar, simpan transaksi, ganti bahasa."""
    host = (request.headers.get("host") or "").split(":")[0].lower()
    if CANONICAL_HOST and host in LEGACY_HOSTS:
        url = request.url.replace(netloc=CANONICAL_HOST, scheme="https")
        kode = 301 if request.method in ("GET", "HEAD") else 308
        return RedirectResponse(str(url), status_code=kode)
    return await call_next(request)


@app.middleware("http")
async def _book_and_language(request: Request, call_next):
    """Tentukan buku milik sesi ini lalu bahasanya, sebelum rute apa pun jalan.

    Semua query di aplikasi memakai get_db() tanpa tahu siapa penggunanya —
    pemisahan datanya ada di level file, ditentukan di sini sekali per permintaan.
    """
    set_book("")
    i18n.set_lang("id")
    money.set_currency(money.DEFAULT)
    if not request.url.path.startswith("/static"):
        try:
            u = signed_in(request)
            if u:
                set_book(users.path_for(u))
                with get_db() as db:
                    i18n.set_lang(get_setting(db, "lang", "id") or "id")
                    money.set_currency(book_currency(db))
            else:                              # tamu: cookie pilihannya, lalu bahasa peramban
                i18n.set_lang(i18n.guest_lang(request.cookies.get(i18n.COOKIE, ""),
                                              request.headers.get("accept-language", "")))
            backup.maybe_run()                 # cadangan harian menumpang lalu lintas biasa
        except Exception:                      # database belum siap (mis. saat start pertama)
            pass
    return await call_next(request)


@app.on_event("startup")
def _startup():
    init_db()
    auth.bootstrap()
    for path, before, after in upgrade_all_books():      # buku pengguna lain ikut naik versi
        print(f"[muara] skema buku diperbarui: {Path(path).name} v{before} -> v{after}")


def signed_in(request: Request):
    """Pengguna sesi ini, atau None. Sesi ditolak kalau pengguna dinonaktifkan,
    dihapus, atau password-nya diganti setelah cookie ini dibuat."""
    if not auth.is_authed(request):
        return None
    u = users.by_id(auth.user_id(request))
    if not u or not u["active"]:
        return None
    if int(u["session_epoch"]) != auth.session_epoch(request):
        return None
    return u


def me(request: Request):
    return signed_in(request)


def require_owner(request: Request):
    """Setelan yang berlaku untuk seluruh aplikasi hanya boleh disentuh pemilik."""
    if (r := require_login(request)):
        return r
    u = me(request)
    return None if (u and u["is_owner"]) else RedirectResponse("/settings", status_code=303)


def require_login(request: Request):
    if signed_in(request) is None:
        return RedirectResponse(f"/login?next={request.url.path}", status_code=303)
    return None


def asset_version() -> str:
    try:
        return str(int(max(p.stat().st_mtime for p in (BASE / "static").rglob("*") if p.is_file())))
    except (ValueError, FileNotFoundError):
        return "0"


def csrf_for(request: Request) -> str:
    """Token untuk permintaan ini: dari cookie kalau ada, kalau belum dibuatkan baru."""
    token = request.cookies.get(csrf.COOKIE) or getattr(request.state, "csrf", "")
    if not token:
        token = csrf.new_token()
        request.state.csrf = token
    return token


def _back_to(request: Request, fallback: str = "/") -> str:
    """Kembali ke halaman asal, tapi hanya bila itu halaman aplikasi ini sendiri."""
    ref = request.headers.get("referer") or ""
    base = str(request.base_url).rstrip("/")
    if ref.startswith(base + "/") or ref == base:
        return ref
    return fallback


def render(request: Request, name: str, **ctx):
    ctx.setdefault("request", request)
    ctx.setdefault("today", date.today().isoformat())
    ctx.setdefault("asset_v", asset_version())
    ctx.setdefault("session_left", auth.session_left(request))
    ctx.setdefault("csrf_token", csrf_for(request))
    ctx.setdefault("csrf_field", Markup(f'<input type="hidden" name="{csrf.FIELD}" value="{ctx["csrf_token"]}">'))
    ctx.setdefault("lang", i18n.get_lang())
    ctx.setdefault("langs", i18n.LANGS)
    ctx.setdefault("currency", money.get_currency())
    ctx.setdefault("cur_symbol", money.symbol())
    ctx.setdefault("cur_decimals", money.decimals())
    ctx.setdefault("cur_group", money.separators()[0])
    ctx.setdefault("cur_point", money.separators()[1])
    ctx.setdefault("months_short", i18n.months(short=True))
    ctx.setdefault("months_long", i18n.months())
    ctx.setdefault("days_short", i18n.DAYS[i18n.get_lang()])
    resp = templates.TemplateResponse(request, name, ctx)
    if not request.cookies.get(csrf.COOKIE):
        resp.set_cookie(csrf.COOKIE, ctx["csrf_token"], max_age=60 * 60 * 24 * 30, httponly=True,
                        samesite="lax", secure=request.url.scheme == "https")
    return resp


# ---------- domain ----------

REVIEW_WHERE = ("t.deleted_at IS NULL AND (t.needs_review=1 OR (t.category_id IS NULL AND t.type<>'transfer'))")

def categories(db, kind: Optional[str] = None, active_only: bool = True):
    sql = "SELECT * FROM categories WHERE deleted_at IS NULL"
    args: list = []
    if active_only:
        sql += " AND active=1"
    if kind:
        sql += " AND kind=?"
        args.append(kind)
    return db.execute(sql + " ORDER BY kind, sort, name", args).fetchall()


def default_account(db, type_="cash"):
    row = db.execute("SELECT id FROM accounts WHERE deleted_at IS NULL AND active=1 AND type=? ORDER BY sort, id LIMIT 1",
                     (type_,)).fetchone()
    return row["id"] if row else None


def invest_value(db, mk: str) -> tuple[int, Optional[str]]:
    """Nilai kantong investasi: snapshot terbaru <= mk; kantong tanpa snapshot pakai modal yang disetor."""
    v = asset_view(db, mk)
    return v["invest"], v["snap_month"]


def month_summary(db, mk: str) -> dict:
    def s(sql, *a):
        return int(db.execute(sql, a).fetchone()["v"] or 0)

    base = "SELECT COALESCE(SUM(amount),0) v FROM transactions WHERE deleted_at IS NULL AND month_key=?"
    income = s(f"{base} AND type='income'", mk)
    expense = s(f"{base} AND type='expense'", mk)
    unpaid = s(f"{base} AND type='expense' AND status='planned'", mk)

    cash_balance = balance_upto(db, mk, CASH_TYPES)
    cash_prev = balance_upto(db, shift_month(mk, -1), CASH_TYPES)
    fund_balance = balance_upto(db, mk, ("savings",))
    fund_prev = balance_upto(db, shift_month(mk, -1), ("savings",))

    ph = ",".join("?" * len(ASSET_TYPES))
    saved_in = s(f"""SELECT COALESCE(SUM(t.amount),0) v FROM transactions t
                     JOIN accounts a ON a.id=t.to_account_id WHERE t.deleted_at IS NULL AND t.month_key=?
                     AND t.type='transfer' AND a.type IN ({ph})""", mk, *ASSET_TYPES)
    saved_out = s(f"""SELECT COALESCE(SUM(t.amount),0) v FROM transactions t
                      JOIN accounts a ON a.id=t.account_id WHERE t.deleted_at IS NULL AND t.month_key=?
                      AND t.type='transfer' AND a.type IN ({ph})""", mk, *ASSET_TYPES)
    invest, snap_month = invest_value(db, mk)

    return dict(
        month=mk, income=income, expense=expense, unpaid=unpaid,
        cash_prev=cash_prev, cash_balance=cash_balance, net=income - expense,
        fund_prev=fund_prev, fund_balance=fund_balance,
        fund_in=saved_in, fund_out=saved_out, saved=saved_in - saved_out,
        invest=invest, snap_month=snap_month, total_assets=fund_balance + invest,
    )


TX_SELECT = """SELECT t.*, c.name AS category, c.is_debt,
                      a.name AS account, a.type AS account_type,
                      b.name AS to_account, b.type AS to_account_type
               FROM transactions t
               LEFT JOIN categories c ON c.id=t.category_id
               LEFT JOIN accounts a   ON a.id=t.account_id
               LEFT JOIN accounts b   ON b.id=t.to_account_id
               WHERE t.deleted_at IS NULL"""


def bills(db, mk: str, today: str = "") -> dict:
    """Tagihan bulan ini: pengeluaran yang belum ditandai dibayar.

    `due` = selisih hari ke tanggal jatuh tempo (negatif berarti sudah lewat).
    Entri tanpa tanggal dianggap belum terjadwal dan ditaruh paling akhir.
    """
    today = today or date.today().isoformat()
    rows = db.execute(f"{TX_SELECT} AND t.month_key=? AND t.type='expense' AND t.status='planned' "
                      "ORDER BY COALESCE(t.tx_date,'9999'), t.amount DESC", (mk,)).fetchall()
    out, late, soon, total = [], 0, 0, 0
    for r in rows:
        item = dict(r)
        due = None
        if r["tx_date"]:
            try:
                due = (date.fromisoformat(r["tx_date"]) - date.fromisoformat(today)).days
            except ValueError:
                due = None
        item["due"] = due
        item["state"] = ("late" if due is not None and due < 0 else
                         "today" if due == 0 else
                         "soon" if due is not None and due <= 7 else "later")
        total += r["amount"]
        late += 1 if item["state"] == "late" else 0
        soon += 1 if item["state"] in ("today", "soon") else 0
        out.append(item)
    return dict(rows=out, total=total, late=late, soon=soon, count=len(out))


def month_lists(db, mk: str) -> dict:
    rows = db.execute(f"{TX_SELECT} AND t.month_key=? ORDER BY COALESCE(t.tx_date,'9999'), t.id", (mk,)).fetchall()
    return dict(
        expenses=[r for r in rows if r["type"] == "expense"],
        incomes=[r for r in rows if r["type"] == "income"],
        transfers=[r for r in rows if r["type"] == "transfer"],
    )


def months_available(db) -> list[str]:
    rows = db.execute("SELECT month_key FROM transactions WHERE deleted_at IS NULL "
                      "UNION SELECT month_key FROM asset_snapshots").fetchall()
    return sorted({r["month_key"] for r in rows} | {this_month()})


# ---------- auth ----------

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/", error: str = "", bye: str = "", verified: str = ""):
    with get_db() as db:
        google = oauth.is_enabled(db)
    wait = auth.locked_for(request)
    return render(request, "login.html", next=next, error=error, configured=auth.is_configured(),
                  google=google, wait=(wait + 59) // 60, bye=bool(bye), verified=bool(verified), signup=users.signup_open())


@app.post("/login")
def login(request: Request, password: str = Form(...), email: str = Form(""), next: str = Form("/")):
    """Masuk dengan email + password. Pemilik boleh mengosongkan email (pintu lama)."""
    if auth.locked_for(request):
        return RedirectResponse(f"/login?next={next}&error=locked", status_code=303)

    email = (email or "").strip().lower()
    u = users.by_email(email) if email else users.owner()
    ok = False
    if u and u["active"]:
        if u["password_hash"]:
            ok = auth.check_hash(password, u["password_hash"])
        elif u["is_owner"]:
            ok = auth.check_password(password)          # password pemilik dari setelan aplikasi
    if not ok:
        auth.note_failure(request)
        return RedirectResponse(f"/login?next={next}&error=1", status_code=303)

    auth.note_success(request)
    users.touch_login(u["id"])
    resp = RedirectResponse(next or "/", status_code=303)
    resp.set_cookie(auth.COOKIE, auth.make_token(u["id"], u["email"] or "password", u["session_epoch"]),
                    max_age=auth.MAX_AGE, httponly=True, samesite="lax",
                    secure=request.url.scheme == "https")
    return resp


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    """Peramban lama meminta /favicon.ico di akar, bukan yang di <link rel=icon>."""
    return FileResponse(BASE / "static" / "favicon.ico", media_type="image/x-icon",
                        headers={"Cache-Control": "public, max-age=604800"})


@app.get("/privacy", response_class=HTMLResponse)
def privacy_page(request: Request):
    """Terbuka tanpa login — dipakai consent screen Google."""
    return render(request, "legal.html", title=t("Kebijakan Privasi"), updated=legal.UPDATED,
                  body=legal.privacy(str(request.base_url)), page="legal")


@app.get("/terms", response_class=HTMLResponse)
def terms_page(request: Request):
    return render(request, "legal.html", title=t("Persyaratan Layanan"), updated=legal.UPDATED,
                  body=legal.terms(str(request.base_url)), page="legal")


VERIFY_MAX_AGE = 60 * 60 * 24 * 3        # tautan verifikasi berlaku 3 hari
RESET_MAX_AGE = 60 * 60                  # tautan setel ulang password berlaku 1 jam


def base_url(request: Request) -> str:
    url = str(request.base_url).rstrip("/")
    if url.startswith("http://") and request.headers.get("x-forwarded-proto") == "https":
        url = "https://" + url[len("http://"):]
    return url


def send_verification(request: Request, u) -> bool:
    """Kirim tautan verifikasi. Diam-diam dilewati kalau surel belum dikonfigurasi."""
    if not mailer.is_enabled() or not u["email"] or u["email_verified"]:
        return False
    token = auth.make_link("verify", {"i": u["id"], "e": u["email"]})
    link = f"{base_url(request)}/verify?token={token}"
    ok, _err = mailer.send(
        u["email"], t("Konfirmasi alamat email Anda"), t("Satu langkah lagi"),
        [t("Ketuk tombol di bawah untuk memastikan alamat ini benar milik Anda. "
           "Tautan berlaku 3 hari."),
         t("Kalau Anda tidak merasa mendaftar di Muara, abaikan saja surel ini.")],
        (t("Konfirmasi email"), link))
    return ok


@app.get("/verify", response_class=HTMLResponse)
def verify_email(request: Request, token: str = ""):
    data = auth.read_link("verify", token, VERIFY_MAX_AGE)
    u = users.by_id(data.get("i")) if data else None
    if not u or u["email"] != data.get("e"):
        return RedirectResponse("/login?error=badlink", status_code=303)
    users.mark_verified(u["id"])
    return RedirectResponse("/settings?verified=1#account" if auth.is_authed(request)
                            else "/login?verified=1", status_code=303)


@app.post("/verify/resend")
def verify_resend(request: Request):
    if (r := require_login(request)):
        return r
    u = me(request)
    sent = send_verification(request, u)
    return RedirectResponse(f"/settings?verify={'sent' if sent else 'off'}#account", status_code=303)


@app.get("/forgot", response_class=HTMLResponse)
def forgot_page(request: Request, sent: str = "", error: str = ""):
    return render(request, "forgot.html", sent=bool(sent), error=error, mail=mailer.is_enabled(),
                  page="forgot")


@app.post("/forgot")
def forgot(request: Request, email: str = Form("")):
    """Selalu menjawab sama, terkirim atau tidak — supaya alamat yang terdaftar
    tidak bisa ditebak dari halaman ini."""
    if auth.locked_for(request):
        return RedirectResponse("/forgot?error=locked", status_code=303)
    auth.note_failure(request)                      # batasi percobaan beruntun
    u = users.by_email((email or "").strip().lower())
    if u and u["active"] and mailer.is_enabled():
        token = auth.make_link("reset", {"i": u["id"], "e": u["session_epoch"],
                                         "p": (u["password_hash"] or "")[:16]})
        link = f"{base_url(request)}/reset?token={token}"
        mailer.send(u["email"], t("Setel ulang password Muara"), t("Setel ulang password"),
                    [t("Ada permintaan untuk mengatur ulang password akun ini. "
                       "Tautan di bawah berlaku satu jam dan hanya bisa dipakai sekali."),
                     t("Kalau bukan Anda yang meminta, abaikan saja — password lama tetap berlaku.")],
                    (t("Setel password baru"), link))
    return RedirectResponse("/forgot?sent=1", status_code=303)


@app.get("/reset", response_class=HTMLResponse)
def reset_page(request: Request, token: str = "", error: str = ""):
    if not _reset_user(token):
        return RedirectResponse("/login?error=badlink", status_code=303)
    return render(request, "reset.html", token=token, error=error, page="reset")


def _reset_user(token: str):
    """Pengguna dari tautan, selama password & sesinya belum berubah sejak tautan dibuat."""
    data = auth.read_link("reset", token, RESET_MAX_AGE)
    u = users.by_id(data.get("i")) if data else None
    if not u or not u["active"]:
        return None
    if int(data.get("e", -1)) != int(u["session_epoch"]):
        return None
    if data.get("p") != (u["password_hash"] or "")[:16]:
        return None
    return u


@app.post("/reset")
def reset(request: Request, token: str = Form(""), new: str = Form(""), confirm: str = Form("")):
    u = _reset_user(token)
    if not u:
        return RedirectResponse("/login?error=badlink", status_code=303)
    if len(new) < users.MIN_PASSWORD or new != confirm:
        return RedirectResponse(f"/reset?token={quote(token)}&error=password", status_code=303)
    users.set_password(u["id"], auth.make_hash(new))         # sesi lama ikut dicabut
    users.mark_verified(u["id"])                             # tautan sampai = email terbukti
    u = users.by_id(u["id"])
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(auth.COOKIE, auth.make_token(u["id"], u["email"], u["session_epoch"]),
                    max_age=auth.MAX_AGE, httponly=True, samesite="lax",
                    secure=request.url.scheme == "https")
    return resp


@app.post("/settings/backup/run")
def settings_backup_run(request: Request):
    """Jalankan cadangan sekarang, tunggu hasilnya supaya pesannya jujur."""
    if (r := require_owner(request)):
        return r
    ok, err = backup.run()
    return RedirectResponse(f"/settings?bk={'done' if ok else 'fail'}#backup", status_code=303)


@app.post("/settings/mail/test")
def settings_mail_test(request: Request):
    """Kirim surel uji ke alamat superadmin supaya konfigurasi terbukti jalan."""
    if (r := require_owner(request)):
        return r
    u = me(request)
    to = u["email"] if "@" in (u["email"] or "") else users.owner_email()
    if not to or not mailer.is_enabled():
        return RedirectResponse("/settings?mail=off#account", status_code=303)
    ok, err = mailer.send(to, t("Surel uji dari Muara"), t("Konfigurasi surel berhasil"),
                          [t("Kalau Anda menerima surel ini, pengiriman dari Muara sudah jalan.")])
    return RedirectResponse(f"/settings?mail={'sent' if ok else 'fail'}#account", status_code=303)


@app.get("/auth/ping")
def auth_ping(request: Request):
    """Dipakai layar kunci: apakah sesi masih hidup?"""
    left = auth.session_left(request)
    return JSONResponse({"ok": bool(left), "left": left}, status_code=200 if left else 401)


@app.post("/auth/unlock")
def auth_unlock(request: Request, password: str = Form(...)):
    """Buka kunci tanpa meninggalkan halaman: cukup password, cookie diperbarui."""
    if (wait := auth.locked_for(request)):
        return JSONResponse({"error": "locked", "wait": (wait + 59) // 60}, status_code=429)
    if not auth.check_password(password):
        auth.note_failure(request)
        return JSONResponse({"error": "wrong"}, status_code=401)
    auth.note_success(request)
    resp = JSONResponse({"ok": True, "left": auth.MAX_AGE})
    resp.set_cookie(auth.COOKIE,
                    auth.make_token(auth.user_id(request), auth.whoami(request) or "password",
                                    users.epoch(auth.user_id(request))),
                    max_age=auth.MAX_AGE, httponly=True, samesite="lax",
                    secure=request.url.scheme == "https")
    return resp


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request, error: str = "", email: str = ""):
    with get_db() as db:
        google = oauth.is_enabled(db)
    if not users.signup_open():
        return RedirectResponse("/login?error=closed", status_code=303)
    return render(request, "register.html", error=error, email=email, google=google, page="register")


@app.post("/register")
def register(request: Request, email: str = Form(""), password: str = Form(""), confirm: str = Form(""),
             name: str = Form("")):
    """Buat akun baru + buku kosongnya. Tanpa Google, tetapi email belum terbukti
    milik pendaftar — itu sebabnya email yang sama kalau kelak masuk lewat Google
    akan mengambil alih akunnya dan membuang password ini."""
    if not users.signup_open():
        return RedirectResponse("/login?error=closed", status_code=303)
    if (wait := auth.locked_for(request)):
        return RedirectResponse("/login?error=locked", status_code=303)

    email = (email or "").strip().lower()
    back = f"/register?email={quote(email)}&error="
    if not users.valid_email(email):
        return RedirectResponse(back + "email", status_code=303)
    if len(password) < users.MIN_PASSWORD or password != confirm:
        return RedirectResponse(back + "password", status_code=303)
    if users.by_email(email):
        return RedirectResponse(back + "exists", status_code=303)

    u = users.create(email, name, password_hash=auth.make_hash(password))
    send_verification(request, u)
    users.touch_login(u["id"])
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(auth.COOKIE, auth.make_token(u["id"], u["email"], u["session_epoch"]), max_age=auth.MAX_AGE,
                    httponly=True, samesite="lax", secure=request.url.scheme == "https")
    return resp


@app.get("/auth/google")
def google_start(request: Request, next: str = "/"):
    """Antar ke halaman pilih akun Google; titipkan state + PKCE di cookie singkat."""
    with get_db() as db:
        if not oauth.is_enabled(db):
            return RedirectResponse("/login?error=google", status_code=303)
        url, blob = oauth.start(db, request, next)
    resp = RedirectResponse(url, status_code=303)
    resp.set_cookie(oauth.STATE_COOKIE, auth.sign(blob), max_age=oauth.STATE_MAX_AGE, httponly=True,
                    samesite="lax", secure=request.url.scheme == "https")
    return resp


@app.get("/auth/google/callback")
def google_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    """Google kembali ke sini. Semua yang gagal berakhir di /login dengan pesan."""
    blob = auth.unsign(request.cookies.get(oauth.STATE_COOKIE, ""), max_age=oauth.STATE_MAX_AGE)
    fail = RedirectResponse("/login?error=google", status_code=303)
    fail.delete_cookie(oauth.STATE_COOKIE)
    if error or not code or not blob or not secrets.compare_digest(state or "", blob.get("state", "")):
        return fail
    try:
        data = oauth.exchange(None, code, blob["verifier"], request)
        email = oauth.verified_email(data)
    except Exception:                               # jaringan, token cacat, konfigurasi salah
        return fail
    if not email:
        return fail

    u = users.by_email(email)
    if u and not u["active"]:
        resp = RedirectResponse("/login?error=disabled", status_code=303)
        resp.delete_cookie(oauth.STATE_COOKIE)
        return resp
    if not u:
        name = data.get("name") or data.get("given_name") or ""
        if oauth.in_allowlist(email):               # email yang Anda izinkan -> buku pemilik
            u = users.claim_owner(email, name)
        elif users.signup_open():                   # pendaftar baru -> buku kosong sendiri
            u = users.create(email, name)
        else:
            resp = RedirectResponse("/login?error=closed", status_code=303)
            resp.delete_cookie(oauth.STATE_COOKIE)
            return resp
    if not u["email_verified"]:
        # Google membuktikan email ini memang miliknya. Kalau akunnya dulu dibuat
        # lewat pendaftaran email+password (yang tidak terbukti), password itu
        # dibuang agar pendaftar lama tidak bisa ikut masuk.
        users.mark_verified(u["id"], clear_password=bool(u["password_hash"]))
        u = users.by_id(u["id"])
    users.touch_login(u["id"])

    resp = RedirectResponse(blob.get("next") or "/", status_code=303)
    resp.delete_cookie(oauth.STATE_COOKIE)
    resp.set_cookie(auth.COOKIE, auth.make_token(u["id"], email, u["session_epoch"]), max_age=auth.MAX_AGE,
                    httponly=True, samesite="lax", secure=request.url.scheme == "https")
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(auth.COOKIE)
    return resp


# ---------- halaman bulan ----------

@app.get("/")
def home(request: Request):
    """Halaman depan publik untuk tamu — juga homepage yang diminta Google saat
    consent screen diverifikasi. Yang sudah masuk langsung ke bulan berjalan."""
    if not signed_in(request):
        return render(request, "landing.html", page="landing", signup=users.signup_open())
    return RedirectResponse(f"/m/{this_month()}", status_code=303)


@app.get("/m/{mk}", response_class=HTMLResponse)
def month_page(request: Request, mk: str):
    if (r := require_login(request)):
        return r
    try:
        datetime.strptime(mk, "%Y-%m")
    except ValueError:
        return RedirectResponse("/", status_code=303)
    with get_db() as db:
        s = month_summary(db, mk)
        lists = month_lists(db, mk)
        accs = accounts(db)
        bal = balances(db)
        cats_exp = categories(db, "expense")
        cats_inc = categories(db, "income")
        has_recurring = db.execute("SELECT COUNT(*) c FROM recurring WHERE active=1").fetchone()["c"] > 0
        months = months_available(db)
        trend = [month_summary(db, shift_month(mk, -i)) for i in range(5, -1, -1)]
        trend_max = max([max(t["income"], t["expense"]) for t in trend] + [1])
        review = db.execute("SELECT COUNT(*) c FROM transactions WHERE deleted_at IS NULL AND needs_review=1 "
                            "AND month_key=?", (mk,)).fetchone()["c"]
        bill = bills(db, mk)
        cash_id = default_account(db, "cash")
    strip = sorted(set(months) | {mk, shift_month(mk, 1), shift_month(months[-1], 1)})
    return render(
        request, "month.html", s=s, bill=bill, **lists, cats_exp=cats_exp, cats_inc=cats_inc, accounts=accs, bal=bal,
        prev=shift_month(mk, -1), next=shift_month(mk, 1), months=months, strip=strip, has_recurring=has_recurring,
        is_empty=not (lists["expenses"] or lists["incomes"] or lists["transfers"]), page="month",
        trend=trend, trend_max=trend_max, review=review, cash_id=cash_id,
    )


def recent_entries(db, type_: str, q: str, limit: int = 8) -> list:
    """Deskripsi yang pernah dipakai, beserta kategori/kantong/nominal terakhirnya.

    Diurut menurut seberapa sering dipakai, lalu yang paling baru. Satu baris per
    deskripsi (tanpa memandang besar-kecil huruf) — window function, bukan GROUP BY,
    supaya nilai yang ikut terbawa benar-benar dari entri terakhirnya.
    """
    like = f"%{q.strip()}%"
    rows = db.execute("""
        SELECT description, category_id, account_id, amount, n FROM (
            SELECT t.description, t.category_id, t.account_id, t.amount, t.id,
                   COUNT(*)     OVER (PARTITION BY lower(t.description)) n,
                   ROW_NUMBER() OVER (PARTITION BY lower(t.description)
                                      ORDER BY COALESCE(t.tx_date,'0000') DESC, t.id DESC) rn
            FROM transactions t
            WHERE t.deleted_at IS NULL AND t.type=? AND t.description IS NOT NULL
              AND TRIM(t.description) <> '' AND t.description LIKE ?
        ) WHERE rn=1 ORDER BY n DESC, id DESC LIMIT ?""", (type_, like, limit)).fetchall()
    return [dict(r) for r in rows]


@app.get("/suggest")
def suggest_entries(request: Request, q: str = "", kind: str = "expense"):
    """Usulan untuk kolom deskripsi. Hanya membaca buku milik sesi ini."""
    if (r := require_login(request)):
        return JSONResponse([], status_code=401)
    kind = kind if kind in ("expense", "income", "transfer") else "expense"
    q = (q or "").strip()[:40]
    if len(q) < 2:
        return JSONResponse([])
    with get_db() as db:
        rows = recent_entries(db, kind, q)
        names = {c["id"]: c["name"] for c in categories(db, active_only=False)}
    return JSONResponse([
        dict(text=r["description"], category_id=r["category_id"] or "",
             category=names.get(r["category_id"], ""), amount=r["amount"],
             account_id=r["account_id"] or "", n=r["n"])
        for r in rows])


# ---------- transaksi ----------

def _account_or_default(db, raw: str, type_="cash"):
    return int(raw) if str(raw).isdigit() else default_account(db, type_)


@app.post("/m/{mk}/tx")
def tx_add(
    request: Request, mk: str, type: str = Form(...), amount: str = Form(...),
    account_id: str = Form(""), to_account_id: str = Form(""), category_id: str = Form(""),
    description: str = Form(""), tx_date: str = Form(""), status: str = Form("paid"),
):
    if (r := require_login(request)):
        return r
    amt = parse_amount(amount)
    if amt <= 0 or type not in ("expense", "income", "transfer"):
        return RedirectResponse(f"/m/{mk}", status_code=303)
    with get_db() as db:
        acc = _account_or_default(db, account_id)
        if type == "transfer":
            to = int(to_account_id) if to_account_id.isdigit() else None
            if not to or to == acc:
                return RedirectResponse(f"/m/{mk}#transfer", status_code=303)
            db.execute(
                "INSERT INTO transactions(month_key,type,tx_date,account_id,to_account_id,description,amount)"
                " VALUES (?,'transfer',?,?,?,?,?)",
                (mk, clean_date(tx_date), acc, to, description.strip() or None, amt))
        else:
            db.execute(
                "INSERT INTO transactions(month_key,type,tx_date,account_id,category_id,description,amount,status)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (mk, type, clean_date(tx_date), acc, int(category_id) if category_id.isdigit() else None,
                 description.strip() or None, amt, status if status in ("planned", "paid") else "paid"))
    return RedirectResponse(f"/m/{mk}#{type}", status_code=303)


@app.post("/tx/{tx_id}/edit")
def tx_edit(
    request: Request, tx_id: int, amount: str = Form(...), category_id: str = Form(""),
    account_id: str = Form(""), to_account_id: str = Form(""), description: str = Form(""),
    tx_date: str = Form(""), status: str = Form("paid"), month_key: str = Form(...),
):
    if (r := require_login(request)):
        return r
    amt = parse_amount(amount)
    with get_db() as db:
        row = db.execute("SELECT type FROM transactions WHERE id=? AND deleted_at IS NULL", (tx_id,)).fetchone()
        if not row or amt <= 0:
            return RedirectResponse(f"/m/{month_key}", status_code=303)
        acc = _account_or_default(db, account_id)
        if row["type"] == "transfer":
            to = int(to_account_id) if to_account_id.isdigit() else None
            if not to or to == acc:
                return RedirectResponse(f"/m/{month_key}#transfer", status_code=303)
            db.execute("UPDATE transactions SET amount=?, account_id=?, to_account_id=?, description=?, tx_date=?,"
                       " month_key=?, needs_review=0, updated_at=datetime('now') WHERE id=?",
                       (amt, acc, to, description.strip() or None, clean_date(tx_date), month_key, tx_id))
        else:
            db.execute("UPDATE transactions SET amount=?, account_id=?, category_id=?, description=?, tx_date=?,"
                       " status=?, month_key=?, needs_review=0, updated_at=datetime('now') WHERE id=?",
                       (amt, acc, int(category_id) if category_id.isdigit() else None, description.strip() or None,
                        clean_date(tx_date), status if status in ("planned", "paid") else "paid", month_key, tx_id))
    return RedirectResponse(f"/m/{month_key}", status_code=303)


@app.post("/tx/{tx_id}/toggle")
def tx_toggle(request: Request, tx_id: int, month_key: str = Form(...)):
    if (r := require_login(request)):
        return r
    with get_db() as db:
        db.execute("UPDATE transactions SET status = CASE status WHEN 'paid' THEN 'planned' ELSE 'paid' END,"
                   " updated_at=datetime('now') WHERE id=?", (tx_id,))
    return RedirectResponse(f"/m/{month_key}#expense", status_code=303)


@app.post("/tx/{tx_id}/delete")
def tx_delete(request: Request, tx_id: int, month_key: str = Form(...)):
    if (r := require_login(request)):
        return r
    with get_db() as db:
        db.execute("UPDATE transactions SET deleted_at=datetime('now') WHERE id=?", (tx_id,))
    return RedirectResponse(f"/m/{month_key}", status_code=303)


@app.post("/m/{mk}/apply-recurring")
def apply_recurring(request: Request, mk: str):
    if (r := require_login(request)):
        return r
    y, m = map(int, mk.split("-"))
    with get_db() as db:
        for rr in db.execute("SELECT * FROM recurring WHERE active=1 ORDER BY sort, id").fetchall():
            d = None
            if rr["day_of_month"]:
                try:
                    d = date(y, m, min(int(rr["day_of_month"]), 28)).isoformat()
                except ValueError:
                    d = None
            db.execute(
                "INSERT INTO transactions(month_key,type,tx_date,account_id,to_account_id,category_id,description,amount,status)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (mk, rr["type"], d, rr["account_id"] or default_account(db), rr["to_account_id"], rr["category_id"],
                 rr["description"], rr["amount"], "planned" if rr["type"] == "expense" else "paid"))
    return RedirectResponse(f"/m/{mk}", status_code=303)


# ---------- kantong ----------

@app.get("/accounts", response_class=HTMLResponse)
def accounts_page(request: Request):
    if (r := require_login(request)):
        return r
    with get_db() as db:
        rows = db.execute("SELECT b.*, a.opening_balance, a.note, a.active FROM account_balances b "
                          "JOIN accounts a ON a.id=b.account_id ORDER BY b.type, b.sort, b.name").fetchall()
        groups = {}
        for r in rows:
            groups.setdefault(r["type"], []).append(r)
        cash = balance_upto(db, this_month(), CASH_TYPES)
        fund = balance_upto(db, this_month(), ("savings",))
        invest, snap = invest_value(db, this_month())
        mv = {r["account_id"]: r["v"] for r in db.execute(
            "SELECT account_id, COALESCE(SUM(amount),0) v FROM asset_snapshots "
            "WHERE month_key=(SELECT MAX(month_key) FROM asset_snapshots) GROUP BY account_id")}
    return render(request, "accounts.html", groups=groups, types=ACCOUNT_TYPES, cash=cash, fund=fund,
                  invest=invest, snap=snap, market=mv, page="accounts", mk=this_month())


@app.post("/accounts")
def account_add(request: Request, name: str = Form(...), type: str = Form(...),
                opening_balance: str = Form("0"), note: str = Form("")):
    if (r := require_login(request)):
        return r
    name = name.strip()
    if name and type in ACCOUNT_TYPES:
        with get_db() as db:
            db.execute("INSERT OR IGNORE INTO accounts(name,type,opening_balance,note,sort) VALUES (?,?,?,?,?)",
                       (name, type, parse_amount(opening_balance), note.strip() or None,
                        (db.execute("SELECT COALESCE(MAX(sort),0)+10 v FROM accounts").fetchone()["v"])))
    return RedirectResponse("/accounts", status_code=303)


@app.post("/accounts/{aid}/edit")
def account_edit(request: Request, aid: int, name: str = Form(...), opening_balance: str = Form("0"),
                 note: str = Form(""), active: str = Form("1")):
    if (r := require_login(request)):
        return r
    with get_db() as db:
        db.execute("UPDATE accounts SET name=?, opening_balance=?, note=?, active=?, updated_at=datetime('now')"
                   " WHERE id=?", (name.strip(), parse_amount(opening_balance), note.strip() or None,
                                   1 if active == "1" else 0, aid))
    return RedirectResponse("/accounts", status_code=303)


@app.post("/accounts/{aid}/delete")
def account_delete(request: Request, aid: int):
    if (r := require_login(request)):
        return r
    with get_db() as db:
        used = db.execute("SELECT COUNT(*) c FROM transactions WHERE deleted_at IS NULL AND (account_id=? OR to_account_id=?)",
                          (aid, aid)).fetchone()["c"]
        if used:
            db.execute("UPDATE accounts SET active=0, updated_at=datetime('now') WHERE id=?", (aid,))
        else:
            db.execute("UPDATE accounts SET deleted_at=datetime('now') WHERE id=?", (aid,))
    return RedirectResponse("/accounts", status_code=303)


# ---------- setelan: kategori, rutin, akun ----------

@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, pw: str = "", g: str = "", adm: str = "", mail: str = "",
                  verify: str = "", verified: str = "", bk: str = ""):
    if (r := require_login(request)):
        return r
    with get_db() as db:
        rec = db.execute("SELECT r.*, c.name AS category, a.name AS account, b.name AS to_account FROM recurring r "
                         "LEFT JOIN categories c ON c.id=r.category_id LEFT JOIN accounts a ON a.id=r.account_id "
                         "LEFT JOIN accounts b ON b.id=r.to_account_id ORDER BY r.type DESC, r.sort, r.id").fetchall()
        cats = categories(db, active_only=False)
        used = {r["category_id"]: r["c"] for r in db.execute(
            "SELECT category_id, COUNT(*) c FROM transactions WHERE deleted_at IS NULL GROUP BY category_id")}
        accs = accounts(db)
        first_month = get_setting(db, "first_month", "")
        review_count = db.execute(f"SELECT COUNT(*) c FROM transactions t WHERE {REVIEW_WHERE}").fetchone()["c"]
        mc = mailer.config()
    u = me(request)
    return render(request, "settings.html", mail=mail, verify=verify, verified=bool(verified),
                  bk=bk, backup_cfg=backup.config(), backup_status=backup.status(),
                  mail_aktif=mailer.is_enabled(),
                  review_count=review_count, has_password=bool(u and (u["password_hash"] or u["is_owner"])),
                  recurring=rec, cats=cats, used=used, accounts=accs,
                  first_month=first_month, page="settings", mk=this_month(), pw=pw, g=g,
                  currencies=[(c, money.code_label(c)) for c in sorted(money.NAMES)],
                  me=u, is_owner=bool(u and u["is_owner"]),
                  users_list=users.all_users() if (u and u["is_owner"]) else [],
                  signup_open=users.signup_open(), adm=adm,
                  owner_email=users.owner_email(), max_users=users.max_users(), user_count=users.count())


@app.post("/settings/category")
def category_add(request: Request, name: str = Form(...), kind: str = Form(...), is_debt: str = Form("0")):
    if (r := require_login(request)):
        return r
    name = name.strip()
    if name and kind in ("expense", "income"):
        with get_db() as db:
            nxt = db.execute("SELECT COALESCE(MAX(sort),0)+10 v FROM categories WHERE kind=?", (kind,)).fetchone()["v"]
            db.execute("INSERT INTO categories(name,kind,sort,is_debt) VALUES (?,?,?,?) "
                       "ON CONFLICT(ledger_id,name,kind) DO UPDATE SET active=1, deleted_at=NULL",
                       (name, kind, nxt, 1 if is_debt == "1" else 0))
    return RedirectResponse("/settings#categories", status_code=303)


@app.post("/settings/category/{cid}/edit")
def category_edit(request: Request, cid: int, name: str = Form(...), sort: str = Form("100"),
                  is_debt: str = Form("0"), active: str = Form("1")):
    if (r := require_login(request)):
        return r
    with get_db() as db:
        db.execute("UPDATE categories SET name=?, sort=?, is_debt=?, active=?, updated_at=datetime('now') WHERE id=?",
                   (name.strip(), int(sort) if sort.isdigit() else 100, 1 if is_debt == "1" else 0,
                    1 if active == "1" else 0, cid))
    return RedirectResponse("/settings#categories", status_code=303)


@app.post("/settings/category/{cid}/delete")
def category_delete(request: Request, cid: int):
    """Kategori terpakai hanya dinonaktifkan; transaksinya dipindah ke 'Lainnya' kalau dihapus."""
    if (r := require_login(request)):
        return r
    with get_db() as db:
        row = db.execute("SELECT kind, is_system FROM categories WHERE id=?", (cid,)).fetchone()
        if not row or row["is_system"]:
            return RedirectResponse("/settings#categories", status_code=303)
        fallback = db.execute("SELECT id FROM categories WHERE kind=? AND is_system=1", (row["kind"],)).fetchone()
        db.execute("UPDATE transactions SET category_id=?, needs_review=1 WHERE category_id=?",
                   (fallback["id"] if fallback else None, cid))
        db.execute("UPDATE categories SET deleted_at=datetime('now'), active=0 WHERE id=?", (cid,))
    return RedirectResponse("/settings#categories", status_code=303)


@app.post("/settings/recurring")
def recurring_add(request: Request, type: str = Form(...), amount: str = Form(...), category_id: str = Form(""),
                  account_id: str = Form(""), to_account_id: str = Form(""), description: str = Form(""),
                  day_of_month: str = Form("")):
    if (r := require_login(request)):
        return r
    amt = parse_amount(amount)
    if amt > 0 and type in ("expense", "income", "transfer"):
        with get_db() as db:
            db.execute("INSERT INTO recurring(type,category_id,account_id,to_account_id,description,amount,day_of_month)"
                       " VALUES (?,?,?,?,?,?,?)",
                       (type, int(category_id) if category_id.isdigit() else None,
                        _account_or_default(db, account_id), int(to_account_id) if to_account_id.isdigit() else None,
                        description.strip() or None, amt,
                        int(day_of_month) if day_of_month.strip().isdigit() else None))
    return RedirectResponse("/settings#recurring", status_code=303)


@app.post("/settings/recurring/{rid}/delete")
def recurring_delete(request: Request, rid: int):
    if (r := require_login(request)):
        return r
    with get_db() as db:
        db.execute("DELETE FROM recurring WHERE id=?", (rid,))
    return RedirectResponse("/settings#recurring", status_code=303)


@app.post("/settings/opening")
def settings_opening(request: Request, first_month: str = Form("")):
    if (r := require_login(request)):
        return r
    with get_db() as db:
        set_setting(db, "first_month", first_month.strip()[:7])
    return RedirectResponse("/settings", status_code=303)


@app.post("/lang")
def set_language(request: Request, lang: str = Form("id")):
    """Ganti bahasa antarmuka — juga untuk yang belum masuk (halaman masuk, daftar, legal).

    Pilihannya selalu ditulis ke cookie supaya halaman publik ikut berubah, dan
    bila sedang masuk disimpan juga di bukunya supaya ikut pindah peramban.
    """
    code = lang if lang in i18n.LANGS else "id"
    resp = RedirectResponse(_back_to(request), status_code=303)
    resp.set_cookie(i18n.COOKIE, code, max_age=60 * 60 * 24 * 365, samesite="lax",
                    secure=request.url.scheme == "https")
    if signed_in(request):
        with get_db() as db:
            set_setting(db, "lang", code)
    return resp


@app.post("/settings/currency")
def settings_currency(request: Request, currency: str = Form("IDR")):
    """Ganti mata uang buku. Nominalnya tidak dikonversi — yang berubah cuma
    cara menampilkannya, karena angkanya memang disimpan tanpa mata uang."""
    if (r := require_login(request)):
        return r
    code = currency.upper()
    with get_db() as db:
        set_book_currency(db, code if code in money.NAMES else money.DEFAULT)
    return RedirectResponse("/settings#currency", status_code=303)


@app.post("/settings/account/delete")
def settings_account_delete(request: Request):
    """Pengguna menghapus akunnya sendiri: baris pengguna + file bukunya ikut hilang.
    Pemilik tidak bisa memakai ini agar data utama tidak terhapus karena salah klik."""
    if (r := require_login(request)):
        return r
    u = me(request)
    if not u or u["is_owner"]:
        return RedirectResponse("/settings", status_code=303)
    users.delete(u["id"])
    resp = RedirectResponse("/login?bye=1", status_code=303)
    resp.delete_cookie(auth.COOKIE)
    return resp


@app.post("/settings/signup")
def settings_signup(request: Request, allow: str = Form("")):
    """Buka/tutup pendaftaran pengguna baru."""
    if (r := require_owner(request)):
        return r
    set_app_setting("allow_signup", "1" if allow else "0")
    return RedirectResponse("/settings#users", status_code=303)


@app.post("/settings/admin")
def settings_admin(request: Request, owner_email: str = Form(""), max_users: str = Form("")):
    """Email pemegang akun superadmin + batas jumlah akun."""
    if (r := require_owner(request)):
        return r
    email = (owner_email or "").strip().lower()
    if email and not users.valid_email(email):
        return RedirectResponse("/settings?adm=email#users", status_code=303)
    set_app_setting("owner_email", email)
    try:
        set_app_setting("max_users", str(max(0, int(max_users))))
    except (TypeError, ValueError):
        pass
    return RedirectResponse("/settings?adm=ok#users", status_code=303)


@app.post("/settings/users/{uid}/active")
def settings_user_active(request: Request, uid: int, active: str = Form("")):
    """Nonaktifkan/aktifkan pengguna. Bukunya tidak disentuh — datanya tetap utuh."""
    if (r := require_owner(request)):
        return r
    users.set_active(uid, bool(active))
    return RedirectResponse("/settings#users", status_code=303)


@app.post("/settings/password")
def settings_password(request: Request, new: str = Form(...), confirm: str = Form(...)):
    """Pemilik memakai password aplikasi; pengguna lain memakai password miliknya
    sendiri. Keduanya: sesi di perangkat lain otomatis keluar setelah diganti."""
    if (r := require_login(request)):
        return r
    u = me(request)
    if len(new) < users.MIN_PASSWORD or new != confirm:
        return RedirectResponse("/settings?pw=mismatch#account", status_code=303)

    # Password lama tidak diminta: pemilik biasanya masuk lewat Google dan tidak
    # hafal password aplikasinya. Pengamannya tetap ada — mengganti password
    # memutus semua sesi lain, jadi pengambilalihan diam-diam tidak mungkin.
    if u["is_owner"]:
        auth.set_password(new)                  # memutar secret aplikasi
    users.set_password(u["id"], auth.make_hash(new))

    resp = RedirectResponse("/settings?pw=ok#account", status_code=303)
    resp.set_cookie(auth.COOKIE, auth.make_token(u["id"], auth.whoami(request) or "password",
                                                 users.epoch(u["id"])),
                    max_age=auth.MAX_AGE, httponly=True, samesite="lax",
                    secure=request.url.scheme == "https")
    return resp


# ---------- aset ----------

@app.get("/assets", response_class=HTMLResponse)
def assets_page(request: Request, mk: str = ""):
    if (r := require_login(request)):
        return r
    with get_db() as db:
        months = months_available(db)
        mk = mk if re.fullmatch(r"\d{4}-\d{2}", mk or "") else months[-1]
        view = asset_view(db, mk)

        rows = db.execute(
            """SELECT s.*, a.name AS account, a.type AS account_type,
                      (SELECT amount FROM asset_snapshots p
                       WHERE p.account_id=s.account_id AND p.symbol=s.symbol AND p.month_key=?) AS prev
               FROM asset_snapshots s JOIN accounts a ON a.id=s.account_id
               WHERE s.month_key=? ORDER BY a.sort, s.amount DESC""",
            (view["prev_snap"] or "", view["snap_month"] or "")).fetchall()

        # tren 12 bulan terakhir yang ada datanya
        trend = []
        for m in months[-12:]:
            v = asset_view(db, m)
            trend.append(dict(month=m, total=v["total"], fund=v["fund"], invest=v["invest"]))
        trend_max = max([t["total"] for t in trend] + [1])
        prev_total = next((t["total"] for t in reversed(trend) if t["month"] < mk), 0)
        cash = balance_upto(db, mk, CASH_TYPES)
        invest_accounts = accounts(db, ("investment",))
    return render(request, "assets.html", v=view, rows=rows, mk=mk, months=months, trend=trend,
                  trend_max=trend_max, prev_total=prev_total, cash=cash,
                  invest_accounts=invest_accounts, page="assets")


@app.post("/assets")
def assets_upsert(request: Request, month_key: str = Form(...), account_id: str = Form(...),
                  symbol: str = Form(...), amount: str = Form(...)):
    if (r := require_login(request)):
        return r
    with get_db() as db:
        db.execute("INSERT INTO asset_snapshots(month_key,account_id,symbol,amount) VALUES (?,?,?,?) "
                   "ON CONFLICT(ledger_id,month_key,account_id,symbol) DO UPDATE SET amount=excluded.amount,"
                   " updated_at=datetime('now')",
                   (month_key[:7], int(account_id), symbol.strip().upper(), parse_amount(amount)))
    return RedirectResponse(f"/assets?mk={month_key[:7]}", status_code=303)


@app.post("/assets/copy")
def assets_copy(request: Request, from_month: str = Form(...), to_month: str = Form(...)):
    if (r := require_login(request)):
        return r
    with get_db() as db:
        db.execute("INSERT OR IGNORE INTO asset_snapshots(month_key,account_id,symbol,amount) "
                   "SELECT ?, account_id, symbol, amount FROM asset_snapshots WHERE month_key=?",
                   (to_month[:7], from_month[:7]))
    return RedirectResponse(f"/assets?mk={to_month[:7]}", status_code=303)


@app.post("/assets/{aid}/delete")
def assets_delete(request: Request, aid: int, month_key: str = Form(...)):
    if (r := require_login(request)):
        return r
    with get_db() as db:
        db.execute("DELETE FROM asset_snapshots WHERE id=?", (aid,))
    return RedirectResponse(f"/assets?mk={month_key}", status_code=303)


# ---------- perapihan kategori ----------



# ---------- impor berkas dari bank ----------

@app.get("/impor", response_class=HTMLResponse)
def import_page(request: Request):
    if (r := require_login(request)):
        return r
    return render(request, "import.html", baris=None, galat="", nama="", page="impor", tx=None, sisa=None)


@app.post("/impor", response_class=HTMLResponse)
async def import_read(request: Request, berkas: UploadFile = File(None), password: str = Form("")):
    """Baca berkas, tampilkan isinya. Belum menyimpan apa pun.

    Berkas dan passwordnya hidup di dalam fungsi ini saja: tidak ditulis ke
    volume, tidak dicatat di log, tidak dikembalikan ke halaman. Yang keluar
    hanya teks hasil bacaannya.
    """
    if (r := require_login(request)):
        return r
    nama = (berkas.filename if berkas else "") or ""
    try:
        blob = await berkas.read(statement.MAKS_BYTE + 1) if berkas else b""
        baris = statement.ekstrak(nama, blob, password)
    except statement.Gagal as e:
        return render(request, "import.html", baris=None, galat=str(e), nama=nama, page="impor", tx=None, sisa=None)
    finally:
        if berkas:
            await berkas.close()
    tx, sisa = statement.pecah(baris)
    with get_db() as db:
        kartu = documents.kartu_terpakai(db)
        kantong = documents.kantong(db)
    return render(request, "import.html", baris=baris, galat="", nama=nama, page="impor",
                  tx=tx, sisa=sisa, kartu_list=kartu, kantong=kantong, bulan=this_month(),
                  data_json=json.dumps([{k: t[k] for k in ("tanggal", "keterangan", "nilai", "masuk")}
                                        for t in tx], ensure_ascii=False),
                  total_keluar=sum(t["nilai"] for t in tx if not t["masuk"]),
                  total_masuk=sum(t["nilai"] for t in tx if t["masuk"]))


@app.post("/impor/simpan")
def import_save(request: Request, kartu: str = Form(""), month_key: str = Form(""),
                nama: str = Form(""), data: str = Form(""), catat: str = Form(""),
                account_id: str = Form("")):
    """Simpan satu dokumen: pengeluaran ringkas di bulan tujuan + rinciannya."""
    if (r := require_login(request)):
        return r
    baris = documents.dari_json(data)
    if not re.fullmatch(r"\d{4}-\d{2}", month_key or ""):
        month_key = this_month()
    with get_db() as db:
        try:
            doc_id = documents.simpan(db, kartu, month_key, nama, baris, catat=bool(catat),
                                      account_id=int(account_id) if account_id.isdigit() else None)
        except ValueError:
            return RedirectResponse("/impor?err=1", status_code=303)
    return RedirectResponse(f"/dokumen/{doc_id}?baru=1", status_code=303)


@app.get("/dokumen", response_class=HTMLResponse)
def documents_page(request: Request):
    if (r := require_login(request)):
        return r
    with get_db() as db:
        return render(request, "documents.html", docs=documents.daftar(db), page="dokumen")


@app.get("/dokumen/{doc_id}", response_class=HTMLResponse)
def document_page(request: Request, doc_id: int, baru: str = ""):
    if (r := require_login(request)):
        return r
    with get_db() as db:
        doc, baris = documents.ambil(db, doc_id)
        if not doc:
            return RedirectResponse("/dokumen", status_code=303)
        return render(request, "document.html", doc=doc, baris=baris, baru=bool(baru),
                      page="dokumen", suggest=suggest)


@app.post("/dokumen/{doc_id}/delete")
def document_delete(request: Request, doc_id: int):
    if (r := require_login(request)):
        return r
    with get_db() as db:
        documents.hapus(db, doc_id)
    return RedirectResponse("/dokumen", status_code=303)


@app.get("/review", response_class=HTMLResponse)
def review_page(request: Request, m: str = ""):
    if (r := require_login(request)):
        return r
    with get_db() as db:
        counts = db.execute(f"SELECT month_key, COUNT(*) n, SUM(amount) v FROM transactions t "
                            f"WHERE {REVIEW_WHERE} GROUP BY month_key ORDER BY month_key").fetchall()
        total = sum(c["n"] for c in counts)
        mk = m if re.fullmatch(r"\d{4}-\d{2}", m or "") else (counts[0]["month_key"] if counts else this_month())
        rows = db.execute(f"{TX_SELECT} AND {REVIEW_WHERE[len('t.deleted_at IS NULL AND '):]} AND t.month_key=? "
                          "ORDER BY t.amount DESC, t.id", (mk,)).fetchall()
        cats_exp = categories(db, "expense")
        cats_inc = categories(db, "income")
        avail = {"expense": {c["name"]: c["id"] for c in cats_exp}, "income": {c["name"]: c["id"] for c in cats_inc}}
        items = []
        for t in rows:
            sid, sname = suggest.suggest(t["description"], t["type"], avail.get(t["type"], {}))
            items.append(dict(t=t, sug_id=sid, sug_name=sname if sid != t["category_id"] else None,
                              maybe_transfer=suggest.looks_like_transfer(t["description"])))
        accs = accounts(db)
    return render(request, "review.html", items=items, counts=counts, total=total, mk=mk,
                  cats_exp=cats_exp, cats_inc=cats_inc, accounts=accs, page="review")


@app.post("/review")
async def review_save(request: Request):
    """Simpan kategori untuk seluruh baris yang tampil, lalu lepas tanda 'perlu ditinjau'."""
    if (r := require_login(request)):
        return r
    form = await request.form()
    mk = str(form.get("month_key", ""))[:7]
    ids = [k[4:] for k in form if k.startswith("cat-") and k[4:].isdigit()]
    with get_db() as db:
        for tid in ids:
            raw = str(form.get(f"cat-{tid}", ""))
            db.execute("UPDATE transactions SET category_id=?, needs_review=0, updated_at=datetime('now') "
                       "WHERE id=? AND type<>'transfer'",
                       (int(raw) if raw.isdigit() else None, int(tid)))
        # transfer yang ikut tampil hanya dilepas tandanya
        for tid in [k[4:] for k in form if k.startswith("trf-") and k[4:].isdigit()]:
            db.execute("UPDATE transactions SET needs_review=0, updated_at=datetime('now') WHERE id=?", (int(tid),))
    return RedirectResponse(f"/review?m={mk}&saved={len(ids)}", status_code=303)


@app.post("/review/{tx_id}/transfer")
def review_to_transfer(request: Request, tx_id: int, account_id: str = Form(...), to_account_id: str = Form(...),
                       month_key: str = Form("")):
    """Ubah satu baris jadi transfer antar kantong (uang pindah, bukan belanja)."""
    if (r := require_login(request)):
        return r
    if not (account_id.isdigit() and to_account_id.isdigit()) or account_id == to_account_id:
        return RedirectResponse(f"/review?m={month_key}", status_code=303)
    with get_db() as db:
        db.execute("UPDATE transactions SET type='transfer', account_id=?, to_account_id=?, category_id=NULL,"
                   " status='paid', needs_review=0, updated_at=datetime('now') WHERE id=?",
                   (int(account_id), int(to_account_id), tx_id))
    return RedirectResponse(f"/review?m={month_key}", status_code=303)


# ---------- laporan bulanan ----------

@app.get("/report", response_class=HTMLResponse)
@app.get("/report/{mk}", response_class=HTMLResponse)
def report_page(request: Request, mk: str = "", refresh: str = ""):
    if (r := require_login(request)):
        return r
    with get_db() as db:
        months = months_available(db)
        if not re.fullmatch(r"\d{4}-\d{2}", mk or ""):
            # bulan berjalan kalau sudah ada isinya; awal bulan biasanya masih kosong -> pakai bulan lalu
            now = this_month()
            filled = db.execute("SELECT 1 FROM transactions WHERE deleted_at IS NULL AND month_key=? LIMIT 1",
                                (now,)).fetchone()
            mk = now if filled else shift_month(now, -1)
        data = report.get_or_build(db, mk, force=bool(refresh))
    return render(request, "report.html", r=data, m=data["metrics"], mk=mk, months=months,
                  prev=shift_month(mk, -1), next=shift_month(mk, 1), page="report")


# ---------- ringkasan ----------

@app.get("/overview", response_class=HTMLResponse)
def overview(request: Request, m: str = "", q: str = ""):
    if (r := require_login(request)):
        return r
    q = (q or "").strip()[:60]
    with get_db() as db:
        all_months = months_available(db)
        rows = [month_summary(db, mk) for mk in all_months]
        sel = m if re.fullmatch(r"\d{4}-\d{2}", m or "") else this_month()
        s = next((r for r in rows if r["month"] == sel), None) or month_summary(db, sel)
        year_rows = [r for r in rows if r["month"][:4] == sel[:4]]
        series_max = max([r["income"] for r in year_rows] + [r["expense"] for r in year_rows] + [1])

        where = ["t.deleted_at IS NULL", "t.month_key = ?"]
        args: list = [sel]
        if q:
            where.append("(t.description LIKE ? OR c.name LIKE ?)")
            args += [f"%{q}%", f"%{q}%"]
        base = f"FROM transactions t LEFT JOIN categories c ON c.id = t.category_id WHERE {' AND '.join(where)}"
        comp = db.execute(f"SELECT t.type, COALESCE(c.name,'—') name, SUM(t.amount) v, COUNT(*) n {base} "
                          "AND t.type IN ('income','expense') GROUP BY t.type, t.category_id ORDER BY v DESC",
                          args).fetchall()
        comp_exp = [c for c in comp if c["type"] == "expense"]
        comp_inc = [c for c in comp if c["type"] == "income"]
        top = db.execute(f"SELECT t.*, c.name AS category {base} ORDER BY t.amount DESC, t.id DESC LIMIT 8",
                         args).fetchall()
        qtot = db.execute(f"SELECT COALESCE(SUM(CASE t.type WHEN 'expense' THEN t.amount END),0) e, "
                          f"COALESCE(SUM(CASE t.type WHEN 'income' THEN t.amount END),0) i, COUNT(*) n {base}",
                          args).fetchone()
    return render(request, "overview.html", rows=rows, page="overview", mk=this_month(),
                  sel=sel, s=s, q=q, qtot=qtot, months=all_months, year_rows=year_rows, series_max=series_max,
                  comp_exp=comp_exp, comp_inc=comp_inc, top=top)


# ---------- backup & ekspor ----------

@app.get("/backup.db")
def backup_db(request: Request):
    if (r := require_login(request)):
        return r
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / f"muara-{date.today().isoformat()}.db"
    with get_db() as db:
        db.execute("VACUUM INTO ?", (str(tmp),))
    return FileResponse(str(tmp), media_type="application/vnd.sqlite3", filename=tmp.name)


@app.get("/export.xlsx")
def export_xlsx(request: Request):
    if (r := require_login(request)):
        return r
    import io

    import openpyxl
    from openpyxl.styles import Font
    wb = openpyxl.Workbook()
    bold = Font(bold=True)
    with get_db() as db:
        months = months_available(db)
        ws = wb.active
        ws.title = "RINGKASAN"
        ws.append(["Bulan", "Saldo awal kas", "Pemasukan", "Pengeluaran", "Sisa kas", "Ditabung",
                   "Dana darurat", "Investasi", "Total aset"])
        for c in ws[1]:
            c.font = bold
        for mk in months:
            s = month_summary(db, mk)
            ws.append([mk] + [money.major(s[k]) for k in
                               ("cash_prev", "income", "expense", "cash_balance", "saved",
                                "fund_balance", "invest", "total_assets")])
        for mk in months:
            lists = month_lists(db, mk)
            w = wb.create_sheet(month_label(mk).upper().replace(" ", "-"))
            w.append(["Tanggal", "Kategori", "Deskripsi", "Jumlah", "Kantong", "Status", "", "Tipe"])
            for c in w[1]:
                c.font = bold
            for t in lists["expenses"] + lists["incomes"]:
                w.append([t["tx_date"], t["category"], t["description"], money.major(t["amount"]),
                          t["account"], t["status"], "", t["type"]])
            for t in lists["transfers"]:
                w.append([t["tx_date"], f'{t["account"]} → {t["to_account"]}', t["description"],
                          money.major(t["amount"]), "", "", "", "transfer"])
        wa = wb.create_sheet("ASET")
        wa.append(["Bulan", "Kantong", "Simbol", "Nilai"])
        for c in wa[1]:
            c.font = bold
        for a in db.execute("SELECT s.month_key, a.name, s.symbol, s.amount FROM asset_snapshots s "
                            "JOIN accounts a ON a.id=s.account_id ORDER BY s.month_key, a.sort, s.symbol"):
            wa.append([a["month_key"], a["name"], a["symbol"], money.major(a["amount"])])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    name = f"muara-{date.today().isoformat()}.xlsx"
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})
