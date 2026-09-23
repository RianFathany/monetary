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

from . import money
from .db import ASSET_TYPES, CASH_TYPES, asset_view, balance_upto
from .i18n import get_lang, t, units

LOOKBACK = 3          # bulan pembanding untuk rata-rata
SPIKE = 0.30          # kenaikan kategori dianggap menonjol di atas 30%
SPIKE_MIN = 500_000 * money.SCALE   # ...dan selisihnya minimal segini (berbentuk rupiah)
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
        "SELECT COALESCE(c.name,'" + t("Tanpa kategori") + "') name, SUM(t.amount) v, COUNT(*) n FROM transactions t "
        "LEFT JOIN categories c ON c.id=t.category_id WHERE t.deleted_at IS NULL AND t.month_key=? "
        "AND t.type='expense' GROUP BY t.category_id ORDER BY v DESC", (mk,)).fetchall()
    prev_avg = {r["name"]: r["v"] / LOOKBACK for r in db.execute(
        f"SELECT COALESCE(c.name,'{t('Tanpa kategori')}') name, SUM(t.amount) v FROM transactions t "
        f"LEFT JOIN categories c ON c.id=t.category_id WHERE t.deleted_at IS NULL AND t.type='expense' "
        f"AND t.month_key IN ({ph}) GROUP BY t.category_id", prev_months)}
    cats, spikes = [], []
    for r in now_rows:
        avg = prev_avg.get(r["name"], 0)
        row = dict(name=r["name"], value=int(r["v"]), count=r["n"], avg=int(avg),
                   delta=int(r["v"] - avg), share=(r["v"] / expense if expense else 0))
        cats.append(row)
        if avg and r["v"] > avg * (1 + SPIKE) and r["v"] - avg >= SPIKE_MIN:
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
    """Bentuk ringkas untuk kalimat laporan. Satu sumber dengan sisa aplikasi."""
    return money.short(n)


def render_rules(m: dict) -> dict:
    """Ringkasan, indikator kesehatan, sorotan, dan saran — semuanya dari angka di atas."""
    mk = m["month"]

    if m["net"] >= 0:
        summary = t("Masuk {inc}, keluar {exp} — sisa {net} ({rate}% dari pemasukan).",
                    inc=_rp(m["income"]), exp=_rp(m["expense"]), net=_rp(m["net"]),
                    rate=f"{m['savings_rate'] * 100:.0f}")
    else:
        summary = t("Masuk {inc}, keluar {exp} — defisit {net}, ditutup dari saldo atau dana darurat.",
                    inc=_rp(m["income"]), exp=_rp(m["expense"]), net=_rp(-m["net"]))
    if m["saved"] > 0:
        summary += " " + t("{v} dipindahkan ke tabungan/investasi.", v=_rp(m["saved"]))
    elif m["saved"] < 0:
        summary += " " + t("{v} ditarik dari tabungan/investasi.", v=_rp(-m["saved"]))

    health = []
    sr = m["savings_rate"]
    health.append(dict(label=t("Tingkat menabung"), value=f"{sr * 100:.0f}%",
                       tone="ok" if sr >= 0.2 else ("warn" if sr >= 0 else "bad"),
                       note=t("pemasukan dikurangi pengeluaran") +
                            ("" if sr >= 0.2 else t(" — patokan sehat 20%"))))
    dr = m["debt_ratio"]
    health.append(dict(label=t("Rasio cicilan"), value=f"{dr * 100:.0f}%" if m["income"] else "–",
                       tone="ok" if dr <= DEBT_WARN else "bad",
                       note=t("{v} cicilan & tagihan kartu", v=_rp(m["debt"])) +
                            ("" if dr <= DEBT_WARN else t(" — di atas batas sehat {pct}%",
                                                          pct=f"{DEBT_WARN * 100:.0f}"))))
    cm = m["cover_months"]
    health.append(dict(label=t("Cakupan dana darurat"),
                       value=(f"{cm:.1f} " + t("bln")) if cm else "–",
                       tone="ok" if cm >= COVER_TARGET else ("warn" if cm >= 3 else "bad"),
                       note=t("{fund} dibanding belanja rata-rata {avg}/bln",
                              fund=_rp(m["fund"]), avg=_rp(m["avg_expense"]))))
    health.append(dict(label=t("Total aset"), value=_rp(m["assets"]),
                       tone="ok" if m["assets_delta"] >= 0 else "warn",
                       note=(t("naik {v} dari bulan lalu", v=_rp(abs(m["assets_delta"])))
                             if m["assets_delta"] >= 0 else
                             t("turun {v} dari bulan lalu", v=_rp(abs(m["assets_delta"]))))))

    highlights = []
    for c in m["spikes"][:3]:
        highlights.append(t("{name} {value}, naik {delta} dari rata-rata {n} bulan ({avg}).",
                            name=c["name"], value=_rp(c["value"]), delta=_rp(c["delta"]),
                            n=LOOKBACK, avg=_rp(c["avg"])))
    if m["categories"]:
        big = m["categories"][0]
        if big["share"] >= 0.3 and big not in m["spikes"][:3]:
            highlights.append(t("{name} menyerap {pct}% pengeluaran bulan ini ({value}).",
                                name=big["name"], pct=f"{big['share'] * 100:.0f}", value=_rp(big["value"])))
    if m["top"] and m["expense"] and m["top"][0]["amount"] >= m["expense"] * 0.2:
        big_tx = m["top"][0]
        highlights.append(t("Pengeluaran terbesar: {desc} {value}.",
                            desc=big_tx["desc"], value=_rp(big_tx["amount"])))
    if m["unpaid"]:
        highlights.append(t("{v} masih bertanda belum dibayar.", v=_rp(m["unpaid"])))

    tips = []
    if m["review_count"]:
        tips.append(dict(text=t("{n} transaksi senilai {v} belum berkategori atau masih bertanda perlu "
                                "dicek — laporan ini ikut melenceng selama itu dibiarkan.",
                                n=m["review_count"], v=_rp(m["review_value"])),
                         label=t("Rapikan"), href=f"/review?m={mk}"))
    if m["debt_ratio"] > DEBT_WARN:
        tips.append(dict(text=t("Cicilan & tagihan kartu {pct}% dari pemasukan ({v}). Di atas 35% ruang "
                                "gerak bulanan jadi sempit.",
                                pct=f"{m['debt_ratio'] * 100:.0f}", v=_rp(m["debt"])),
                         label=t("Lihat kategori"), href="/settings#categories"))
    if m["cover_months"] and m["cover_months"] < 3:
        tips.append(dict(text=t("Dana darurat menutup {n} bulan belanja. Idealnya {target} bulan ({v}).",
                                n=f"{m['cover_months']:.1f}", target=COVER_TARGET,
                                v=_rp(m["avg_expense"] * COVER_TARGET)),
                         label=t("Kantong"), href="/accounts"))
    elif m["cover_months"] >= COVER_TARGET and m["saved"] > 0:
        tips.append(dict(text=t("Dana darurat sudah menutup {n} bulan belanja. Setoran berikutnya lebih "
                                "berguna diarahkan ke investasi.", n=f"{m['cover_months']:.1f}"),
                         label=t("Aset"), href="/assets"))
    if m["savings_rate"] < 0:
        tips.append(dict(text=t("Pengeluaran melebihi pemasukan {v} bulan ini. Tiga kategori teratas: {list}.",
                                v=_rp(-m["net"]),
                                list=", ".join(f"{c['name']} {_rp(c['value'])}" for c in m["categories"][:3])),
                         label=t("Rincian"), href=f"/overview?m={mk}"))
    if m["stale_pots"]:
        tips.append(dict(text=t("Nilai {pots} belum diperbarui untuk bulan ini, jadi total aset memakai "
                                "angka lama.", pots=" & ".join(m["stale_pots"])),
                         label=t("Perbarui"), href=f"/assets?mk={mk}"))

    plan = [dict(desc=r["desc"], amount=r["amount"], day=r["day"]) for r in m["missing_recurring"]]
    return dict(month=mk, summary=summary, health=health, highlights=highlights,
                tips=tips[:4], plan=plan, metrics=m)


def get_or_build(db, mk: str, engine: str = "rules", force: bool = False) -> dict:
    engine = f"{engine}:{get_lang()}"        # narasi disimpan terpisah per bahasa
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
    data["generated_at"] = t("baru saja")
    return data
