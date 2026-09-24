"""Dokumen impor: satu rekening koran atau tagihan kartu beserta rinciannya.

Kalau dicatat, yang masuk ke catatan bulanan cuma **satu** pengeluaran —
totalnya, berkategori Tagihan Kartu dengan deskripsi nama kartunya. Rinciannya
disimpan di sini dan tidak pernah ikut dihitung.

Mencatat itu pilihan. Rekening koran yang dibuka sekadar untuk melihat ke mana
uang pergi bulan lalu disimpan tanpa transaksi apa pun.

Alasannya sederhana: yang benar-benar keluar dari kantongmu bulan itu memang
satu pembayaran tagihan, bukan empat puluh tujuh transaksi belanja. Mencatat
keduanya berarti menghitung uang yang sama dua kali.

Konsekuensinya jujur disebut di halaman: rincian kategori di laporan bulanan
tidak ikut terpecah. Analisa per kategori ada, tapi di halaman dokumen ini.
"""
import json

KATEGORI = "Tagihan Kartu"
MAKS_BARIS = 2000


def kategori_id(db) -> int:
    """Id kategori Tagihan Kartu; dibuat kalau pengguna sempat menghapusnya."""
    row = db.execute("SELECT id FROM categories WHERE name=? AND kind='expense'", (KATEGORI,)).fetchone()
    if row:
        return row["id"]
    cur = db.execute("INSERT INTO categories(name, kind, sort) VALUES (?, 'expense', 60)", (KATEGORI,))
    return cur.lastrowid


def kartu_terpakai(db) -> list:
    """Nama kartu yang sudah pernah kamu catat sendiri.

    Tidak ada daftar bank bawaan: aplikasi sudah tahu kamu memakai BNI, Mega,
    dan Kredivo karena kamu mencatat tagihannya berbulan-bulan. Daftar tebakan
    dari luar cuma akan meleset.
    """
    baris = db.execute(
        "SELECT DISTINCT TRIM(t.description) AS d FROM transactions t "
        "JOIN categories c ON c.id = t.category_id "
        "WHERE c.name = ? AND t.deleted_at IS NULL AND TRIM(COALESCE(t.description,'')) <> '' "
        "ORDER BY d", (KATEGORI,)).fetchall()
    dari_tx = [r["d"] for r in baris]
    dari_doc = [r["kartu"] for r in db.execute(
        "SELECT DISTINCT kartu FROM documents ORDER BY kartu").fetchall()]
    keluar = []
    for n in dari_tx + dari_doc:
        if n and n.lower() not in {k.lower() for k in keluar}:
            keluar.append(n)
    return keluar


def kantong(db) -> list:
    """Kantong yang bisa dipakai membayar tagihan, kas dulu."""
    return db.execute(
        "SELECT id, name, type FROM accounts WHERE deleted_at IS NULL AND active=1 "
        "ORDER BY CASE type WHEN 'cash' THEN 0 ELSE 1 END, sort, id").fetchall()


def simpan(db, kartu: str, month_key: str, filename: str, baris: list, catat: bool = True,
           account_id=None) -> int:
    """Simpan dokumen; kalau `catat`, sekalian buat pengeluaran ringkasnya.

    Tidak semua dokumen perlu masuk catatan. Rekening koran yang dibuka sekadar
    untuk melihat ke mana uang pergi bulan lalu tidak boleh menambah pengeluaran
    apa pun — kalau dipaksa masuk, angka bulananmu justru rusak. Dokumen tanpa
    transaksi tetap tersimpan lengkap dengan rinciannya, cuma tidak dihitung.
    """
    kartu = (kartu or "").strip()[:60]
    baris = [b for b in baris[:MAKS_BARIS] if int(b.get("nilai") or 0) > 0]
    if not kartu or not baris:
        raise ValueError("kartu dan minimal satu baris wajib ada")

    total = sum(int(b["nilai"]) for b in baris if not b.get("masuk"))
    total -= sum(int(b["nilai"]) for b in baris if b.get("masuk"))
    tx_id = None
    if catat:
        if total <= 0:                               # pembayaran melebihi belanja: tidak ada tagihan
            raise ValueError("total tagihannya nol atau minus, tidak ada yang perlu dicatat")
        # Tanpa account_id, pengeluarannya muncul di laporan tapi tidak
        # mengurangi kantong mana pun — tagihan yang tidak pernah dibayar dari
        # uang siapa-siapa. Kalau tidak dipilih, jatuh ke kantong kas pertama.
        if not account_id:
            kas = kantong(db)
            account_id = kas[0]["id"] if kas else None
        cur = db.execute(
            "INSERT INTO transactions(month_key, type, account_id, category_id, description, "
            "amount, status, needs_review) VALUES (?, 'expense', ?, ?, ?, ?, 'paid', 1)",
            (month_key, account_id, kategori_id(db), kartu, total))
        tx_id = cur.lastrowid

    cur = db.execute(
        "INSERT INTO documents(kartu, month_key, filename, total, rows_count, tx_id) "
        "VALUES (?,?,?,?,?,?)", (kartu, month_key, (filename or "")[:120], max(total, 0), len(baris), tx_id))
    doc_id = cur.lastrowid

    db.executemany(
        "INSERT INTO document_rows(document_id, tanggal, keterangan, amount, masuk, sort) "
        "VALUES (?,?,?,?,?,?)",
        [(doc_id, b.get("tanggal"), (b.get("keterangan") or "")[:200],
          int(b["nilai"]), 1 if b.get("masuk") else 0, i) for i, b in enumerate(baris)])
    return doc_id


def daftar(db) -> list:
    return db.execute(
        "SELECT d.*, (SELECT COUNT(*) FROM document_rows r WHERE r.document_id = d.id) AS n "
        "FROM documents d ORDER BY d.month_key DESC, d.id DESC").fetchall()


def ambil(db, doc_id: int):
    doc = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not doc:
        return None, []
    baris = db.execute("SELECT * FROM document_rows WHERE document_id=? ORDER BY sort, id",
                       (doc_id,)).fetchall()
    return doc, baris


def hapus(db, doc_id: int) -> bool:
    """Dokumen dan pengeluaran ringkasnya hilang bersamaan.

    Kalau transaksinya ditinggal, laporan bulananmu memuat tagihan yang tidak
    bisa ditelusuri lagi ke mana pun — lebih membingungkan daripada tidak ada.
    """
    doc = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not doc:
        return False
    if doc["tx_id"]:
        db.execute("UPDATE transactions SET deleted_at = datetime('now') WHERE id=?", (doc["tx_id"],))
    db.execute("DELETE FROM document_rows WHERE document_id=?", (doc_id,))
    db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    return True


def dari_json(teks: str) -> list:
    """Baris hasil pembacaan yang dititipkan lewat form. Bentuknya diperiksa
    ulang di sini: isinya datang dari peramban, jadi tidak boleh dipercaya
    apa adanya meski ini bukumu sendiri."""
    try:
        data = json.loads(teks or "[]")
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    bersih = []
    for b in data[:MAKS_BARIS]:
        if not isinstance(b, dict):
            continue
        try:
            nilai = int(b.get("nilai") or 0)
        except (TypeError, ValueError):
            continue
        if nilai <= 0:
            continue
        bersih.append(dict(tanggal=str(b.get("tanggal") or "")[:10],
                           keterangan=str(b.get("keterangan") or "")[:200],
                           nilai=nilai, masuk=bool(b.get("masuk"))))
    return bersih
