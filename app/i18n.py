"""Dwibahasa: Indonesia (bawaan) dan Inggris.

Kunci kamus = teks bahasa Indonesia apa adanya, jadi template tetap terbaca
tanpa membuka file ini, dan bahasa Indonesia tidak pernah butuh terjemahan.
Bahasa aktif disimpan per-permintaan di ContextVar supaya filter Jinja
(month_label, short, fmt_date) ikut menyesuaikan tanpa mengoper argumen.
"""
from contextvars import ContextVar

from .lang_en import EN   # kamus besar dipisah agar file ini tetap ringkas

LANGS = {"id": "Bahasa Indonesia", "en": "English"}
COOKIE = "monetary_lang"          # pilihan tamu; pengguna yang masuk disimpan di bukunya
_lang: ContextVar[str] = ContextVar("lang", default="id")


def set_lang(code: str) -> str:
    code = code if code in LANGS else "id"
    _lang.set(code)
    return code


def get_lang() -> str:
    return _lang.get()


def from_header(accept: str) -> str:
    """Bahasa pertama di Accept-Language yang kita punya; selain itu Indonesia."""
    for part in (accept or "").split(","):
        code = part.split(";")[0].strip().lower().replace("_", "-")[:2]
        if code in LANGS:
            return code
    return "id"


def guest_lang(cookie: str, accept: str = "") -> str:
    """Bahasa untuk yang belum masuk: pilihannya sendiri dulu, baru bahasa peramban.

    Sengaja tidak membaca setelan buku siapa pun — halaman masuk dilihat orang
    yang belum punya buku, dan preferensi pemilik aplikasi bukan urusan mereka.
    """
    return cookie if cookie in LANGS else from_header(accept)


# Pencarian cadangan: spasi/baris baru dinormalkan, supaya teks template yang
# dipecah beberapa baris tetap ketemu terjemahannya.
_NORM = {" ".join(k.split()): v for k, v in EN.items()}


def t(s: str, **kw) -> str:
    """Terjemahkan bila perlu; {placeholder} diisi dari kw."""
    if _lang.get() == "en":
        out = EN.get(s) or _NORM.get(" ".join(s.split()), s)
    else:
        out = s
    return out.format(**kw) if kw else out


MONTHS = {
    "id": ["Januari", "Februari", "Maret", "April", "Mei", "Juni",
           "Juli", "Agustus", "September", "Oktober", "November", "Desember"],
    "en": ["January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"],
}
MONTHS_SHORT = {
    "id": ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"],
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
}
DAYS = {
    "id": ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"],
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
}
# satuan ringkas untuk angka rupiah: 1.000 / 1 juta / 1 miliar
UNITS = {"id": ("rb", "jt", "M"), "en": ("k", "M", "B")}


def months(short: bool = False) -> list:
    return (MONTHS_SHORT if short else MONTHS)[_lang.get()]


def units() -> tuple:
    return UNITS[_lang.get()]


