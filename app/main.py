"""Monetary — catatan kas masuk/keluar, dana darurat, dan aset. Satu user, satu file SQLite."""
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import auth
from .db import get_db, get_setting, init_db, set_setting

BASE = Path(__file__).resolve().parent
app = FastAPI(title="Monetary", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")

MONTHS_ID = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]


# ---------- helpers ----------

def rupiah(n) -> str:
    if n is None:
        return "–"
    n = int(n)
    s = f"{abs(n):,}".replace(",", ".")
    return f"-Rp {s}" if n < 0 else f"Rp {s}"


def month_label(key: str) -> str:
    y, m = key.split("-")
    return f"{MONTHS_ID[int(m) - 1]} {y}"


def shift_month(key: str, delta: int) -> str:
    y, m = map(int, key.split("-"))
    m += delta
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}"


def this_month() -> str:
    return date.today().strftime("%Y-%m")


def parse_amount(raw: str) -> int:
    """'11.000.000' / '11000000' / '11,000,000' -> 11000000"""
    digits = "".join(ch for ch in raw if ch.isdigit() or ch == "-")
    return int(digits) if digits and digits != "-" else 0


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
        return f"{d.day} {MONTHS_ID[d.month - 1]}"
    except ValueError:
        return raw


templates.env.filters["rupiah"] = rupiah
templates.env.filters["month_label"] = month_label
templates.env.filters["fmt_date"] = fmt_date


@app.on_event("startup")
def _startup():
    init_db()


def require_login(request: Request):
    if not auth.is_authed(request):
        return RedirectResponse(f"/login?next={request.url.path}", status_code=303)
    return None


def render(request: Request, name: str, **ctx):
    ctx.setdefault("request", request)
    ctx.setdefault("today", date.today().isoformat())
    return templates.TemplateResponse(request, name, ctx)


# ---------- domain queries ----------

def month_summary(db, mk: str) -> dict:
    opening = int(get_setting(db, "opening_balance", "0") or 0)
    first = get_setting(db, "first_month", "") or ""
    prev = db.execute(
        "SELECT COALESCE(SUM(CASE kind WHEN 'income' THEN amount ELSE -amount END),0) AS v "
        "FROM transactions WHERE month_key < ? AND (? = '' OR month_key >= ?)", (mk, first, first)
    ).fetchone()["v"]
    prev_balance = opening + prev if (not first or mk >= first) else 0

    inc = db.execute("SELECT COALESCE(SUM(amount),0) v FROM transactions WHERE month_key=? AND kind='income'", (mk,)).fetchone()["v"]
    exp = db.execute("SELECT COALESCE(SUM(amount),0) v FROM transactions WHERE month_key=? AND kind='expense'", (mk,)).fetchone()["v"]
    unpaid = db.execute("SELECT COALESCE(SUM(amount),0) v FROM transactions WHERE month_key=? AND kind='expense' AND status='planned'", (mk,)).fetchone()["v"]

    ef_open = int(get_setting(db, "opening_emergency", "0") or 0)
    ef_prev = ef_open + db.execute("SELECT COALESCE(SUM(amount),0) v FROM emergency_fund WHERE month_key < ?", (mk,)).fetchone()["v"]
    ef_in = db.execute("SELECT COALESCE(SUM(amount),0) v FROM emergency_fund WHERE month_key=? AND amount>0", (mk,)).fetchone()["v"]
    ef_out = db.execute("SELECT COALESCE(SUM(amount),0) v FROM emergency_fund WHERE month_key=? AND amount<0", (mk,)).fetchone()["v"]
    ef_cur = ef_prev + ef_in + ef_out

    asset_month = db.execute("SELECT MAX(month_key) v FROM assets WHERE month_key <= ?", (mk,)).fetchone()["v"]
    assets_total = 0
    if asset_month:
        assets_total = db.execute("SELECT COALESCE(SUM(amount),0) v FROM assets WHERE month_key=?", (asset_month,)).fetchone()["v"]

    return dict(
        month=mk, prev_balance=prev_balance, income=inc, expense=exp, unpaid=unpaid,
        balance=prev_balance + inc - exp,
        ef_prev=ef_prev, ef_in=ef_in, ef_out=ef_out, ef_cur=ef_cur,
        assets_total=assets_total, asset_month=asset_month,
        total_assets=ef_cur + assets_total,
    )


def month_lists(db, mk: str) -> dict:
    tx = db.execute(
        "SELECT t.*, c.name AS category FROM transactions t LEFT JOIN categories c ON c.id=t.category_id "
        "WHERE month_key=? ORDER BY COALESCE(tx_date,'9999') , id", (mk,)
    ).fetchall()
    ef = db.execute("SELECT * FROM emergency_fund WHERE month_key=? ORDER BY COALESCE(tx_date,'9999'), id", (mk,)).fetchall()
    return dict(
        expenses=[r for r in tx if r["kind"] == "expense"],
        incomes=[r for r in tx if r["kind"] == "income"],
        ef_rows=ef,
    )


def categories(db, kind: Optional[str] = None):
    if kind:
        return db.execute("SELECT * FROM categories WHERE active=1 AND kind=? ORDER BY sort, name", (kind,)).fetchall()
    return db.execute("SELECT * FROM categories WHERE active=1 ORDER BY kind, sort, name").fetchall()


def months_available(db) -> list[str]:
    rows = db.execute(
        "SELECT month_key FROM transactions UNION SELECT month_key FROM emergency_fund UNION SELECT month_key FROM assets"
    ).fetchall()
    keys = {r["month_key"] for r in rows} | {this_month()}
    return sorted(keys)


# ---------- auth ----------

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/", error: str = ""):
    return render(request, "login.html", next=next, error=error, configured=bool(auth.PASSWORD))


@app.post("/login")
def login(request: Request, password: str = Form(...), next: str = Form("/")):
    if not auth.check_password(password):
        return RedirectResponse(f"/login?next={next}&error=1", status_code=303)
    resp = RedirectResponse(next or "/", status_code=303)
    resp.set_cookie(auth.COOKIE, auth.make_token(), max_age=auth.MAX_AGE, httponly=True, samesite="lax",
                    secure=request.url.scheme == "https")
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(auth.COOKIE)
    return resp


# ---------- pages ----------

@app.get("/")
def home(request: Request):
    if (r := require_login(request)):
        return r
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
        cats_exp = categories(db, "expense")
        cats_inc = categories(db, "income")
        has_recurring = db.execute("SELECT COUNT(*) c FROM recurring WHERE active=1").fetchone()["c"] > 0
        months = months_available(db)
    return render(
        request, "month.html", s=s, **lists, cats_exp=cats_exp, cats_inc=cats_inc,
        prev=shift_month(mk, -1), next=shift_month(mk, 1), months=months, has_recurring=has_recurring,
        is_empty=not (lists["expenses"] or lists["incomes"]), page="month",
    )


# ---------- transactions ----------

@app.post("/m/{mk}/tx")
def tx_add(
    request: Request, mk: str, kind: str = Form(...), amount: str = Form(...),
    category_id: str = Form(""), description: str = Form(""), tx_date: str = Form(""), status: str = Form("paid"),
):
    if (r := require_login(request)):
        return r
    amt = parse_amount(amount)
    if amt <= 0 or kind not in ("expense", "income"):
        return RedirectResponse(f"/m/{mk}", status_code=303)
    with get_db() as db:
        db.execute(
            "INSERT INTO transactions(month_key, kind, tx_date, category_id, description, amount, status) VALUES (?,?,?,?,?,?,?)",
            (mk, kind, clean_date(tx_date), int(category_id) if category_id else None, description.strip() or None, amt,
             status if status in ("planned", "paid") else "paid"),
        )
    return RedirectResponse(f"/m/{mk}#{kind}", status_code=303)


@app.post("/tx/{tx_id}/edit")
def tx_edit(
    request: Request, tx_id: int, amount: str = Form(...), category_id: str = Form(""),
    description: str = Form(""), tx_date: str = Form(""), status: str = Form("paid"), month_key: str = Form(...),
):
    if (r := require_login(request)):
        return r
    amt = parse_amount(amount)
    with get_db() as db:
        row = db.execute("SELECT kind FROM transactions WHERE id=?", (tx_id,)).fetchone()
        if row and amt > 0:
            db.execute(
                "UPDATE transactions SET amount=?, category_id=?, description=?, tx_date=?, status=?, month_key=? WHERE id=?",
                (amt, int(category_id) if category_id else None, description.strip() or None, clean_date(tx_date),
                 status if status in ("planned", "paid") else "paid", month_key, tx_id),
            )
            # jaga pasangan dana darurat tetap sinkron
            db.execute("UPDATE emergency_fund SET amount = CASE WHEN amount<0 THEN -? ELSE ? END, month_key=? WHERE linked_tx_id=?",
                       (amt, amt, month_key, tx_id))
    return RedirectResponse(f"/m/{month_key}", status_code=303)


@app.post("/tx/{tx_id}/toggle")
def tx_toggle(request: Request, tx_id: int, month_key: str = Form(...)):
    if (r := require_login(request)):
        return r
    with get_db() as db:
        db.execute("UPDATE transactions SET status = CASE status WHEN 'paid' THEN 'planned' ELSE 'paid' END WHERE id=?", (tx_id,))
    return RedirectResponse(f"/m/{month_key}#expense", status_code=303)


@app.post("/tx/{tx_id}/delete")
def tx_delete(request: Request, tx_id: int, month_key: str = Form(...)):
    if (r := require_login(request)):
        return r
    with get_db() as db:
        db.execute("DELETE FROM emergency_fund WHERE linked_tx_id=?", (tx_id,))
        db.execute("DELETE FROM transactions WHERE id=?", (tx_id,))
    return RedirectResponse(f"/m/{month_key}", status_code=303)


# ---------- emergency fund ----------

@app.post("/m/{mk}/ef")
def ef_add(
    request: Request, mk: str, direction: str = Form(...), amount: str = Form(...),
    description: str = Form(""), tx_date: str = Form(""), link_cash: str = Form(""),
):
    """direction: 'in' (setor) / 'out' (tarik). link_cash: buat pasangan di kas operasional."""
    if (r := require_login(request)):
        return r
    amt = parse_amount(amount)
    if amt <= 0 or direction not in ("in", "out"):
        return RedirectResponse(f"/m/{mk}#ef", status_code=303)
    desc = description.strip() or ("Setor dana darurat" if direction == "in" else "Tarik dana darurat")
    d = clean_date(tx_date)
    with get_db() as db:
        linked_id = None
        if link_cash:
            # tarik dana darurat -> pemasukan kas; setor -> pengeluaran kas
            kind = "income" if direction == "out" else "expense"
            cat = db.execute("SELECT id FROM categories WHERE name='DANA DARURAT' AND kind=?", (kind,)).fetchone()
            cur = db.execute(
                "INSERT INTO transactions(month_key, kind, tx_date, category_id, description, amount, status) VALUES (?,?,?,?,?,?, 'paid')",
                (mk, kind, d, cat["id"] if cat else None, desc, amt),
            )
            linked_id = cur.lastrowid
        db.execute(
            "INSERT INTO emergency_fund(month_key, tx_date, description, amount, linked_tx_id) VALUES (?,?,?,?,?)",
            (mk, d, desc, amt if direction == "in" else -amt, linked_id),
        )
    return RedirectResponse(f"/m/{mk}#ef", status_code=303)


@app.post("/ef/{ef_id}/delete")
def ef_delete(request: Request, ef_id: int, month_key: str = Form(...)):
    if (r := require_login(request)):
        return r
    with get_db() as db:
        row = db.execute("SELECT linked_tx_id FROM emergency_fund WHERE id=?", (ef_id,)).fetchone()
        db.execute("DELETE FROM emergency_fund WHERE id=?", (ef_id,))
        if row and row["linked_tx_id"]:
            db.execute("DELETE FROM transactions WHERE id=?", (row["linked_tx_id"],))
    return RedirectResponse(f"/m/{month_key}#ef", status_code=303)


# ---------- recurring ----------

@app.post("/m/{mk}/apply-recurring")
def apply_recurring(request: Request, mk: str):
    if (r := require_login(request)):
        return r
    y, m = map(int, mk.split("-"))
    with get_db() as db:
        rows = db.execute("SELECT * FROM recurring WHERE active=1 ORDER BY sort, id").fetchall()
        for rr in rows:
            d = None
            if rr["day_of_month"]:
                try:
                    d = date(y, m, min(int(rr["day_of_month"]), 28)).isoformat()
                except ValueError:
                    d = None
            db.execute(
                "INSERT INTO transactions(month_key, kind, tx_date, category_id, description, amount, status) VALUES (?,?,?,?,?,?,?)",
                (mk, rr["kind"], d, rr["category_id"], rr["description"], rr["amount"],
                 "planned" if rr["kind"] == "expense" else "paid"),
            )
    return RedirectResponse(f"/m/{mk}", status_code=303)


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    if (r := require_login(request)):
        return r
    with get_db() as db:
        rec = db.execute(
            "SELECT r.*, c.name AS category FROM recurring r LEFT JOIN categories c ON c.id=r.category_id ORDER BY r.kind DESC, r.sort, r.id"
        ).fetchall()
        cats = categories(db)
        opening = get_setting(db, "opening_balance", "0")
        opening_ef = get_setting(db, "opening_emergency", "0")
        first_month = get_setting(db, "first_month", "")
    return render(request, "settings.html", recurring=rec, cats=cats, opening=int(opening or 0),
                  opening_ef=int(opening_ef or 0), first_month=first_month, page="settings", mk=this_month())


@app.post("/settings/opening")
def settings_opening(request: Request, opening_balance: str = Form("0"), opening_emergency: str = Form("0"), first_month: str = Form("")):
    if (r := require_login(request)):
        return r
    with get_db() as db:
        set_setting(db, "opening_balance", str(parse_amount(opening_balance)))
        set_setting(db, "opening_emergency", str(parse_amount(opening_emergency)))
        set_setting(db, "first_month", first_month.strip()[:7])
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/recurring")
def recurring_add(request: Request, kind: str = Form(...), amount: str = Form(...), category_id: str = Form(""),
                  description: str = Form(""), day_of_month: str = Form("")):
    if (r := require_login(request)):
        return r
    amt = parse_amount(amount)
    if amt > 0 and kind in ("expense", "income"):
        with get_db() as db:
            db.execute(
                "INSERT INTO recurring(kind, category_id, description, amount, day_of_month) VALUES (?,?,?,?,?)",
                (kind, int(category_id) if category_id else None, description.strip() or None, amt,
                 int(day_of_month) if day_of_month.strip().isdigit() else None),
            )
    return RedirectResponse("/settings#recurring", status_code=303)


@app.post("/settings/recurring/{rid}/delete")
def recurring_delete(request: Request, rid: int):
    if (r := require_login(request)):
        return r
    with get_db() as db:
        db.execute("DELETE FROM recurring WHERE id=?", (rid,))
    return RedirectResponse("/settings#recurring", status_code=303)


@app.post("/settings/category")
def category_add(request: Request, name: str = Form(...), kind: str = Form(...)):
    if (r := require_login(request)):
        return r
    name = name.strip().upper()
    if name and kind in ("expense", "income"):
        with get_db() as db:
            db.execute("INSERT OR IGNORE INTO categories(name, kind) VALUES (?,?)", (name, kind))
            db.execute("UPDATE categories SET active=1 WHERE name=? AND kind=?", (name, kind))
    return RedirectResponse("/settings#categories", status_code=303)


@app.post("/settings/category/{cid}/hide")
def category_hide(request: Request, cid: int):
    if (r := require_login(request)):
        return r
    with get_db() as db:
        db.execute("UPDATE categories SET active=0 WHERE id=?", (cid,))
    return RedirectResponse("/settings#categories", status_code=303)


# ---------- assets ----------

@app.get("/assets", response_class=HTMLResponse)
def assets_page(request: Request, mk: str = ""):
    if (r := require_login(request)):
        return r
    with get_db() as db:
        months = [r["month_key"] for r in db.execute("SELECT DISTINCT month_key FROM assets ORDER BY month_key DESC").fetchall()]
        mk = mk or (months[0] if months else this_month())
        rows = db.execute("SELECT * FROM assets WHERE month_key=? ORDER BY category, symbol", (mk,)).fetchall()
        total = sum(r["amount"] for r in rows)
        by_cat = {}
        for r in rows:
            by_cat[r["category"]] = by_cat.get(r["category"], 0) + r["amount"]
    return render(request, "assets.html", rows=rows, total=total, by_cat=by_cat, mk=mk, months=months, page="assets")


@app.post("/assets")
def assets_upsert(request: Request, month_key: str = Form(...), category: str = Form(...), symbol: str = Form(...), amount: str = Form(...)):
    if (r := require_login(request)):
        return r
    with get_db() as db:
        db.execute(
            "INSERT INTO assets(month_key, category, symbol, amount) VALUES (?,?,?,?) "
            "ON CONFLICT(month_key, category, symbol) DO UPDATE SET amount=excluded.amount",
            (month_key[:7], category.strip().upper(), symbol.strip().upper(), parse_amount(amount)),
        )
    return RedirectResponse(f"/assets?mk={month_key[:7]}", status_code=303)


@app.post("/assets/copy")
def assets_copy(request: Request, from_month: str = Form(...), to_month: str = Form(...)):
    """Salin snapshot bulan lalu ke bulan ini, lalu tinggal edit angkanya."""
    if (r := require_login(request)):
        return r
    with get_db() as db:
        db.execute(
            "INSERT OR IGNORE INTO assets(month_key, category, symbol, amount) "
            "SELECT ?, category, symbol, amount FROM assets WHERE month_key=?", (to_month[:7], from_month[:7]),
        )
    return RedirectResponse(f"/assets?mk={to_month[:7]}", status_code=303)


@app.post("/assets/{aid}/delete")
def assets_delete(request: Request, aid: int, month_key: str = Form(...)):
    if (r := require_login(request)):
        return r
    with get_db() as db:
        db.execute("DELETE FROM assets WHERE id=?", (aid,))
    return RedirectResponse(f"/assets?mk={month_key}", status_code=303)


# ---------- overview ----------

@app.get("/overview", response_class=HTMLResponse)
def overview(request: Request):
    if (r := require_login(request)):
        return r
    with get_db() as db:
        rows = [month_summary(db, mk) for mk in months_available(db)]
    return render(request, "overview.html", rows=rows, page="overview", mk=this_month())
