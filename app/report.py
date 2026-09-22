"""Laporan bulanan.

Dua lapis yang sengaja dipisah:

  build_metrics(db, mk) -> angka mentah, deterministik, tanpa kalimat
  render_rules(m)       -> narasi & saran dari angka itu, pakai aturan tetap

Nanti kalau lapis AI dinyalakan, yang diganti hanya render-nya: metrik yang sama
dikirim ke model, hasilnya disimpan di tabel reports dengan engine='ai'. Angka
tidak pernah dihitung oleh model.
"""
import json
from datetime import date

from .db import ASSET_TYPES, CASH_TYPES, asset_view, balance_upto

LOOKBACK = 3          # bulan pembanding untuk rata-rata
SPIKE = 0.30          # kenaikan kategori dianggap menonjol di atas 30%
DEBT_WARN = 0.35      # rasio cicilan sehat: maksimal 35% dari pemasukan
COVER_TARGET = 6      # target cakupan dana darurat, dalam bulan belanja


def _shift(mk: str, d: int) -> str:
    y, m = map(int, mk.split("-"))
    m += d
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}"


def build_metrics(db, mk: str) -> dict:
    """Semua angka yang dibutuhkan laporan. Tidak ada kalimat di sini."""
    one = lambda sql, *a: int(db.execute(sql, a).fetchone()["v"] or 0)  # noqa: E731
    base = "SELECT COALESCE(SUM(amount),0) v FROM transactions WHERE deleted_at IS NULL AND month_key=?"

    income = one(f"{base} AND type='income'", mk)
    expense = one(f"{base} AND type='expense'", mk)
    unpaid = one(f"{base} AND type='expense' AND status='planned'", mk)
    prev_months = [_shift(mk, -i) for i in range(1, LOOKBACK + 1)]
    ph = ",".join("?" * len(prev_months))
    avg_expense = one(f"SELECT COALESCE(SUM(amount),0)/{LOOKBACK} v FROM transactions "
                      f"WHERE deleted_at IS NULL AND type='expense' AND month_key IN ({ph})", *prev_months)
    avg_income = one(f"SELECT COALESCE(SUM(amount),0)/{LOOKBACK} v FROM transactions "
                     f"WHERE deleted_at IS NULL AND type='income' AND month_key IN ({ph})", *prev_months)

    # cicilan: kategori bertanda is_debt
    debt = one("SELECT COALESCE(SUM(t.amount),0) v FROM transactions t JOIN categories c ON c.id=t.category_id "
               "WHERE t.deleted_at IS NULL AND t.month_key=? AND t.type='expense' AND c.is_debt=1", mk)

    # uang yang berpindah ke tabungan/investasi (bersih)
    ap = ",".join("?" * len(ASSET_TYPES))
    saved_in = one(f"SELECT COALESCE(SUM(t.amount),0) v FROM transactions t JOIN accounts a ON a.id=t.to_account_id "
                   f"WHERE t.deleted_at IS NULL AND t.month_key=? AND t.type='transfer' AND a.type IN ({ap})",
                   mk, *ASSET_TYPES)
    saved_out = one(f"SELECT COALESCE(SUM(t.amount),0) v FROM transactions t JOIN accounts a ON a.id=t.account_id "
                    f"WHERE t.deleted_at IS NULL AND t.month_key=? AND t.type='transfer' AND a.type IN ({ap})",
                    mk, *ASSET_TYPES)

    cash = balance_upto(db, mk, CASH_TYPES)
    cash_prev = balance_upto(db, _shift(mk, -1), CASH_TYPES)
    fund = balance_upto(db, mk, ("savings",))
    fund_prev = balance_upto(db, _shift(mk, -1), ("savings",))

    # kategori: bulan ini vs rata-rata 3 bulan sebelumnya
    now_rows = db.execute(
        "SELECT COALESCE(c.name,'Tanpa kategori') name, SUM(t.amount) v, COUNT(*) n FROM transactions t "
        "LEFT JOIN categories c ON c.id=t.category_id WHERE t.deleted_at IS NULL AND t.month_key=? "
        "AND t.type='expense' GROUP BY t.category_id ORDER BY v DESC", (mk,)).fetchall()
    prev_avg = {r["name"]: r["v"] / LOOKBACK for r in db.execute(
        f"SELECT COALESCE(c.name,'Tanpa kategori') name, SUM(t.amount) v FROM transactions t "
        f"LEFT JOIN categories c ON c.id=t.category_id WHERE t.deleted_at IS NULL AND t.type='expense' "
        f"AND t.month_key IN ({ph}) GROUP BY t.category_id", prev_months)}
    cats, spikes = [], []
    for r in now_rows:
        avg = prev_avg.get(r["name"], 0)
        row = dict(name=r["name"], value=int(r["v"]), count=r["n"], avg=int(avg),
                   delta=int(r["v"] - avg), share=(r["v"] / expense if expense else 0))
        cats.append(row)
        if avg and r["v"] > avg * (1 + SPIKE) and r["v"] - avg >= 500_000:
            spikes.append(row)

    top = [dict(desc=r["description"] or r["name"] or "—", amount=r["amount"], date=r["tx_date"], cat=r["name"])
           for r in db.execute(
               "SELECT t.amount, t.description, t.tx_date, c.name FROM transactions t "
               "LEFT JOIN categories c ON c.id=t.category_id WHERE t.deleted_at IS NULL AND t.month_key=? "
               "AND t.type='expense' ORDER BY t.amount DESC LIMIT 5", (mk,)).fetchall()]

    review = db.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(amount),0) v FROM transactions WHERE deleted_at IS NULL "
        "AND month_key=? AND (needs_review=1 OR category_id IS NULL) AND type<>'transfer'", (mk,)).fetchone()

    # template rutin yang belum muncul bulan ini
    missing = []
    for rr in db.execute("SELECT r.*, c.name AS category FROM recurring r LEFT JOIN categories c ON c.id=r.category_id "
                         "WHERE r.active=1 ORDER BY r.sort, r.id").fetchall():
        hit = db.execute(
            "SELECT 1 FROM transactions WHERE deleted_at IS NULL AND month_key=? AND type=? "
            "AND (description=? OR (category_id IS NOT NULL AND category_id=?)) LIMIT 1",
            (mk, rr["type"], rr["description"], rr["category_id"])).fetchone()
        if not hit:
            missing.append(dict(desc=rr["description"] or rr["category"] or "—", amount=rr["amount"],
                                day=rr["day_of_month"]))

    av = asset_view(db, mk)
    av_prev = asset_view(db, _shift(mk, -1))

    cover = (fund / avg_expense) if avg_expense else 0
    return dict(
        month=mk, income=income, expense=expense, net=income - expense, unpaid=unpaid,
        avg_income=avg_income, avg_expense=avg_expense,
        savings_rate=((income - expense) / income) if income else 0,
        saved=saved_in - saved_out, debt=debt, debt_ratio=(debt / income) if income else 0,
        cash=cash, cash_delta=cash - cash_prev, fund=fund, fund_delta=fund - fund_prev,
        cover_months=cover, categories=cats, spikes=spikes, top=top,
        review_count=review["n"], review_value=int(review["v"]), missing_recurring=missing,
        assets=av["total"], assets_delta=av["total"] - av_prev["total"], pots=av["pots"],
        stale_pots=[p["name"] for p in av["pots"] if p.get("stale")],
        generated_at=date.today().isoformat(),
    )


# ---------- narasi berbasis aturan ----------

def _rp(n) -> str:
    n = int(n or 0)
    a = abs(n)
    if a >= 1_000_000_000:
        s = f"{a/1_000_000_000:.1f}".rstrip("0").rstrip(".") + " M"
    elif a >= 1_000_000:
        s = f"{a/1_000_000:.1f}".rstrip("0").rstrip(".") + " jt"
    elif a >= 1_000:
        s = f"{a/1_000:.0f} rb"
    else:
        s = str(a)
    return ("−" if n < 0 else "") + "Rp " + s


def render_rules(m: dict) -> dict:
    """Ringkasan, indikator kesehatan, sorotan, dan saran — semuanya dari angka di atas."""
    mk = m["month"]

    if m["net"] >= 0:
        summary = (f"Masuk {_rp(m['income'])}, keluar {_rp(m['expense'])} — sisa {_rp(m['net'])} "
                   f"({m['savings_rate'] * 100:.0f}% dari pemasukan).")
    else:
        summary = (f"Masuk {_rp(m['income'])}, keluar {_rp(m['expense'])} — defisit {_rp(-m['net'])}, "
                   f"ditutup dari saldo atau dana darurat.")
    if m["saved"] > 0:
        summary += f" {_rp(m['saved'])} dipindahkan ke tabungan/investasi."
    elif m["saved"] < 0:
        summary += f" {_rp(-m['saved'])} ditarik dari tabungan/investasi."

    health = []
    sr = m["savings_rate"]
    health.append(dict(label="Tingkat menabung", value=f"{sr * 100:.0f}%",
                       tone="ok" if sr >= 0.2 else ("warn" if sr >= 0 else "bad"),
                       note="pemasukan dikurangi pengeluaran" +
                            ("" if sr >= 0.2 else " — patokan sehat 20%")))
    dr = m["debt_ratio"]
    health.append(dict(label="Rasio cicilan", value=f"{dr * 100:.0f}%" if m["income"] else "–",
                       tone="ok" if dr <= DEBT_WARN else "bad",
                       note=f"{_rp(m['debt'])} cicilan & tagihan kartu" +
                            ("" if dr <= DEBT_WARN else f" — di atas batas sehat {DEBT_WARN * 100:.0f}%")))
    cm = m["cover_months"]
    health.append(dict(label="Cakupan dana darurat", value=f"{cm:.1f} bln" if cm else "–",
                       tone="ok" if cm >= COVER_TARGET else ("warn" if cm >= 3 else "bad"),
                       note=f"{_rp(m['fund'])} dibanding belanja rata-rata {_rp(m['avg_expense'])}/bln"))
    health.append(dict(label="Total aset", value=_rp(m["assets"]),
                       tone="ok" if m["assets_delta"] >= 0 else "warn",
                       note=("naik " if m["assets_delta"] >= 0 else "turun ") + _rp(abs(m["assets_delta"])) +
                            " dari bulan lalu"))

    highlights = []
    for c in m["spikes"][:3]:
        highlights.append(f"{c['name']} {_rp(c['value'])}, naik {_rp(c['delta'])} dari rata-rata "
                          f"{LOOKBACK} bulan ({_rp(c['avg'])}).")
    if m["categories"]:
        big = m["categories"][0]
        if big["share"] >= 0.3 and big not in m["spikes"][:3]:
            highlights.append(f"{big['name']} menyerap {big['share'] * 100:.0f}% pengeluaran bulan ini "
                              f"({_rp(big['value'])}).")
    if m["top"] and m["expense"] and m["top"][0]["amount"] >= m["expense"] * 0.2:
        t = m["top"][0]
        highlights.append(f"Pengeluaran terbesar: {t['desc']} {_rp(t['amount'])}.")
    if m["unpaid"]:
        highlights.append(f"{_rp(m['unpaid'])} masih bertanda belum dibayar.")

    tips = []
    if m["review_count"]:
        tips.append(dict(text=f"{m['review_count']} transaksi senilai {_rp(m['review_value'])} belum berkategori "
                              f"atau masih bertanda perlu dicek — laporan ini ikut melenceng selama itu dibiarkan.",
                         label="Rapikan", href=f"/review?m={mk}"))
    if m["debt_ratio"] > DEBT_WARN:
        tips.append(dict(text=f"Cicilan & tagihan kartu {m['debt_ratio'] * 100:.0f}% dari pemasukan "
                              f"({_rp(m['debt'])}). Di atas 35% ruang gerak bulanan jadi sempit.",
                         label="Lihat kategori", href="/settings#categories"))
    if m["cover_months"] and m["cover_months"] < 3:
        tips.append(dict(text=f"Dana darurat menutup {m['cover_months']:.1f} bulan belanja. "
                              f"Idealnya {COVER_TARGET} bulan ({_rp(m['avg_expense'] * COVER_TARGET)}).",
                         label="Kantong", href="/accounts"))
    elif m["cover_months"] >= COVER_TARGET and m["saved"] > 0:
        tips.append(dict(text=f"Dana darurat sudah menutup {m['cover_months']:.1f} bulan belanja. "
                              f"Setoran berikutnya lebih berguna diarahkan ke investasi.",
                         label="Aset", href="/assets"))
    if m["savings_rate"] < 0:
        tips.append(dict(text=f"Pengeluaran melebihi pemasukan {_rp(-m['net'])} bulan ini. "
                              f"Tiga kategori teratas: " +
                              ", ".join(f"{c['name']} {_rp(c['value'])}" for c in m["categories"][:3]) + ".",
                         label="Rincian", href=f"/overview?m={mk}"))
    if m["stale_pots"]:
        tips.append(dict(text="Nilai " + " & ".join(m["stale_pots"]) + " belum diperbarui untuk bulan ini, "
                              "jadi total aset memakai angka lama.",
                         label="Perbarui", href=f"/assets?mk={mk}"))

    plan = [dict(desc=r["desc"], amount=r["amount"], day=r["day"]) for r in m["missing_recurring"]]
    return dict(month=mk, summary=summary, health=health, highlights=highlights,
                tips=tips[:4], plan=plan, metrics=m)


def get_or_build(db, mk: str, engine: str = "rules", force: bool = False) -> dict:
    row = None if force else db.execute(
        "SELECT content_json, generated_at FROM reports WHERE month_key=? AND engine=?", (mk, engine)).fetchone()
    if row:
        data = json.loads(row["content_json"])
        data["generated_at"] = row["generated_at"]
        return data
    data = render_rules(build_metrics(db, mk))
    db.execute("INSERT INTO reports(month_key, engine, content_json, generated_at) VALUES (?,?,?,datetime('now')) "
               "ON CONFLICT(ledger_id, month_key, engine) DO UPDATE SET content_json=excluded.content_json,"
               " generated_at=excluded.generated_at", (mk, engine, json.dumps(data, ensure_ascii=False)))
    data["generated_at"] = "baru saja"
    return data
