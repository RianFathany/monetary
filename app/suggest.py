"""Tebakan kategori dari deskripsi transaksi.

Dipakai layar Perapihan: aplikasi hanya *menyarankan*, perubahan tetap butuh
klik dari pengguna. Aturannya sengaja berupa daftar kata kunci yang bisa dibaca
dan ditambah sendiri — bukan model — supaya hasilnya bisa ditebak dan dijelaskan.

Urutan penting: aturan pertama yang cocok yang dipakai, jadi yang spesifik
ditaruh di atas yang umum.
"""
import re

# (pola, nama kategori) untuk pengeluaran
EXPENSE_RULES = [
    (r"kpr|cicilan rumah", "Cicilan Rumah"),
    (r"\b(bni|mega|cimb|octo|ocbc|bca|mandiri)\b|gopaylater|tpaylater|paylater|kredivo|traveloka|"
     r"\bcc\b|kartu kredit|tagihan", "Tagihan Kartu"),
    (r"operasional|opersional|forcash|dandur|backup|adjust|top\s*up|topup|setor|tarik tunai|"
     r"emoney|e-money|gopay|dana topup|pemisahan dana", "Operasional Harian"),
    (r"apartemen|kemuning|tulip|kontrakan|sewa|listrik|pln|\bair\b|internet|wifi|ioh|telkomsel|"
     r"indihome|token", "Tagihan & Utilitas"),
    (r"gaji|adha|yoni|mpok|art\b|asisten|thr\b|pembantu|cuci", "Keluarga & Rumah"),
    (r"halodoc|dharmais|brawijaya|rumah sakit|\brs\b|klinik|apotek|century|dokter|vaksin|obat|"
     r"kaki kaki|bpjs", "Kesehatan"),
    (r"sekolah|spp|les\b|kursus|renang|daycare|kampus|buku", "Pendidikan"),
    (r"bensin|pertamina|tol\b|parkir|gojek|grab|taksi|servis|bengkel|ban\b|oli", "Transport"),
    (r"pajak|samsat|\badm\b|admin|midtrans|materai|notaris|stnk", "Pajak & Admin"),
    (r"foodhall|kintan|sushi|greyhound|anbai|kopi|cafe|resto|makan|mcd|kfc|starbucks|catering|"
     r"gsshop|bakery", "Makan & Minum"),
    (r"tiket|enhypen|\bmcr\b|tcg\b|psa\b|konser|bioskop|hotel|tjokro|skyline|liburan|wisata|game", "Hiburan"),
    (r"kiddy cuts|salon|barber|potong rambut|spa|skincare|amore|portraits", "Perawatan Diri"),
    (r"arisan|donasi|sumbangan|zakat|infaq|kado|hadiah|nikah|puncak", "Donasi & Sosial"),
    (r"uniqlo|adidas|jd sports|tokopedia|shopee|lazada|house of smith|tas\b|jersey|sepatu|baju|"
     r"laptop|\bhp\b|elektronik|kidz|mothercare|ikea|furniture", "Belanja"),
]

# (pola, nama kategori) untuk pemasukan
INCOME_RULES = [
    (r"thr\b|bonus|insentif", "Bonus & THR"),
    (r"project|proyek|freelance|invoice|kso|nfs\b", "Project"),
    (r"idle|dividen|bunga|capital gain|jual saham|jual crypto", "Hasil Investasi"),
    (r"gaji|tugu|ismaya|sci\b|nuke|rian", "Gaji"),
    (r"kado|hadiah|thr dari", "Hadiah"),
]

# Deskripsi yang biasanya bukan belanja, tapi uang pindah kantong.
TRANSFER_HINT = re.compile(
    r"pemisahan dana|return|backup|support operasional|dana darurat|dandur|tabungan|nabung|"
    r"setor(?!\s*bca)|pindah|alokasi", re.I)

_COMPILED = {
    "expense": [(re.compile(p, re.I), c) for p, c in EXPENSE_RULES],
    "income": [(re.compile(p, re.I), c) for p, c in INCOME_RULES],
}


def suggest(description: str, kind: str, available: dict):
    """Kembalikan (category_id, nama) atau (None, None). `available` = {nama: id}."""
    text = (description or "").strip()
    if not text:
        return None, None
    for rx, name in _COMPILED.get(kind, []):
        if rx.search(text) and name in available:
            return available[name], name
    return None, None


def looks_like_transfer(description: str) -> bool:
    return bool(TRANSFER_HINT.search(description or ""))
