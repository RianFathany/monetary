"""Anggaran per kategori per bulan.

Pencatatan saja cuma menghasilkan arsip. Yang mengubah perilaku adalah selisih
antara rencana dan kenyataan — karena itu angka yang ditampilkan bukan "kamu
sudah habis sekian", tapi "sisa jatahmu sekian".

Definisi "terpakai" sengaja dibuat sama persis dengan laporan bulanan
(`report.build_metrics`): pengeluaran di bulan itu, dikelompokkan per kategori,
tanpa membedakan sudah dibayar atau baru direncanakan. Dua tempat yang
menghitung hal sama dengan cara berbeda pada akhirnya selalu berselisih, dan
yang kena getahnya pemiliknya sendiri.
"""

def terpakai(db, mk: str) -> dict:
    """{category_id: jumlah terpakai} untuk satu bulan."""
    return {r["category_id"]: int(r["v"]) for r in db.execute(
        "SELECT t.category_id, SUM(t.amount) v FROM transactions t "
        "WHERE t.deleted_at IS NULL AND t.month_key=? AND t.type='expense' "
        "AND t.category_id IS NOT NULL GROUP BY t.category_id", (mk,)).fetchall()}


def untuk_bulan(db, mk: str) -> list:
    """Satu baris per kategori pengeluaran: anggaran, terpakai, sisa, persen.

    Kategori tanpa anggaran ikut ditampilkan dengan angka 0 — supaya yang belum
    diatur kelihatan, bukan hilang dari daftar.
    """
    pakai = terpakai(db, mk)
    anggaran = {r["category_id"]: int(r["amount"]) for r in db.execute(
        "SELECT category_id, amount FROM budgets WHERE month_key=?", (mk,)).fetchall()}
    baris = []
    for c in db.execute("SELECT id, name, is_debt FROM categories "
                        "WHERE kind='expense' AND deleted_at IS NULL ORDER BY sort, name").fetchall():
        rencana, habis = anggaran.get(c["id"], 0), pakai.get(c["id"], 0)
        baris.append(dict(
            id=c["id"], name=c["name"], is_debt=bool(c["is_debt"]),
            rencana=rencana, terpakai=habis, sisa=rencana - habis,
            persen=min(999, round(habis * 100 / rencana)) if rencana else 0,
            lewat=bool(rencana and habis > rencana),
            diatur=bool(rencana)))
    return baris


def ringkas(db, mk: str) -> dict:
    """Angka untuk dipajang: total rencana, total terpakai, berapa kategori jebol."""
    baris = untuk_bulan(db, mk)
    diatur = [b for b in baris if b["diatur"]]
    rencana = sum(b["rencana"] for b in diatur)
    habis = sum(b["terpakai"] for b in diatur)
    return dict(
        ada=bool(diatur), jumlah=len(diatur),
        rencana=rencana, terpakai=habis, sisa=rencana - habis,
        persen=min(999, round(habis * 100 / rencana)) if rencana else 0,
        lewat=[b for b in diatur if b["lewat"]],
        # Pengeluaran di luar kategori yang dianggarkan tetap uang keluar.
        # Menyembunyikannya membuat "sisa anggaran" terlihat lebih lega dari
        # kenyataan, dan itu jenis kebohongan yang paling mahal.
        di_luar=sum(b["terpakai"] for b in baris if not b["diatur"]))


def simpan(db, mk: str, nilai: dict) -> int:
    """Tulis anggaran satu bulan. Nilai 0 berarti kategori itu tidak dianggarkan."""
    ditulis = 0
    for cid, jumlah in nilai.items():
        jumlah = max(0, int(jumlah or 0))
        if jumlah:
            db.execute("INSERT INTO budgets(month_key, category_id, amount) VALUES (?,?,?) "
                       "ON CONFLICT(month_key, category_id) DO UPDATE SET amount=excluded.amount",
                       (mk, int(cid), jumlah))
            ditulis += 1
        else:
            db.execute("DELETE FROM budgets WHERE month_key=? AND category_id=?", (mk, int(cid)))
    return ditulis


def salin(db, dari: str, ke: str) -> int:
    """Tiru anggaran bulan lain. Anggaran cenderung sama tiap bulan; mengetik
    ulang dua belas kali setahun adalah cara tercepat membuat orang berhenti
    memakainya."""
    db.execute("INSERT INTO budgets(month_key, category_id, amount) "
               "SELECT ?, category_id, amount FROM budgets WHERE month_key=? "
               "ON CONFLICT(month_key, category_id) DO UPDATE SET amount=excluded.amount", (ke, dari))
    return db.execute("SELECT COUNT(*) c FROM budgets WHERE month_key=?", (ke,)).fetchone()["c"]


def bulan_terdekat(db, sebelum: str) -> str:
    """Bulan beranggaran terakhir sebelum `sebelum`, untuk tombol salin."""
    r = db.execute("SELECT month_key FROM budgets WHERE month_key < ? "
                   "ORDER BY month_key DESC LIMIT 1", (sebelum,)).fetchone()
    return r["month_key"] if r else ""
