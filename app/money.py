"""Mata uang: satu tempat untuk bentuk angka, simbol, dan pembacaan input.

Semua nominal disimpan di database sebagai **bilangan bulat satuan perseratus**
(SCALE = 100), berapa pun mata uangnya. Jadi Rp 18.888.000 tersimpan sebagai
1888800000, dan $12.50 sebagai 1250. Skalanya sengaja tetap supaya berganti
mata uang tidak pernah butuh migrasi data lagi — yang berubah hanya cara
menampilkannya.

Berapa angka di belakang koma ditentukan mata uang (rupiah dan yen nol, sisanya
dua — dinar Teluk yang resminya tiga ikut dibulatkan dua karena skalanya perseratus),
sedangkan pemisah ribuan dan koma desimal ikut bahasa antarmuka —
orang Indonesia menulis 1.234,56 dan orang Inggris 1,234.56 untuk uang yang sama.
"""
from contextvars import ContextVar

from .i18n import get_lang, units

SCALE = 100                      # nilai tersimpan = nominal * 100, selalu
DEFAULT = "IDR"

# Mata uang tanpa angka di belakang koma. Rupiah sebenarnya punya sen menurut
# ISO, tapi tidak ada yang memakainya sejak lama, jadi diperlakukan nol.
ZERO_DECIMALS = {
    "BIF", "CLP", "DJF", "GNF", "IDR", "ISK", "JPY", "KMF", "KRW", "PYG", "RWF",
    "UGX", "UYI", "VND", "VUV", "XAF", "XOF", "XPF",
}

# Simbol untuk yang lazim dikenal; sisanya memakai kode ISO-nya sebagai simbol,
# yang justru lebih jelas daripada lambang yang tidak dikenali orang.
SYMBOLS = {
    "AED": "د.إ", "ARS": "$", "AUD": "A$", "BDT": "৳", "BGN": "лв", "BRL": "R$",
    "CAD": "C$", "CHF": "CHF", "CNY": "¥", "COP": "$", "CZK": "Kč", "DKK": "kr",
    "EGP": "E£", "EUR": "€", "GBP": "£", "HKD": "HK$", "HUF": "Ft", "IDR": "Rp",
    "ILS": "₪", "INR": "₹", "JPY": "¥", "KES": "KSh", "KRW": "₩", "LKR": "Rs",
    "MXN": "$", "MYR": "RM", "NGN": "₦", "NOK": "kr", "NZD": "NZ$", "PHP": "₱",
    "PKR": "₨", "PLN": "zł", "QAR": "﷼", "RON": "lei", "RUB": "₽", "SAR": "﷼",
    "SEK": "kr", "SGD": "S$", "THB": "฿", "TRY": "₺", "TWD": "NT$", "UAH": "₴",
    "USD": "$", "VND": "₫", "ZAR": "R",
}

# Daftar ISO 4217 yang aktif. Nama dibiarkan dalam bahasa Inggris karena itulah
# bentuk bakunya, dan dropdown-nya dicari dengan mengetik kode.
NAMES = {
    "AED": "UAE Dirham", "AFN": "Afghan Afghani", "ALL": "Albanian Lek",
    "AMD": "Armenian Dram", "ANG": "Netherlands Antillean Guilder",
    "AOA": "Angolan Kwanza", "ARS": "Argentine Peso", "AUD": "Australian Dollar",
    "AWG": "Aruban Florin", "AZN": "Azerbaijani Manat",
    "BAM": "Bosnia-Herzegovina Convertible Mark", "BBD": "Barbadian Dollar",
    "BDT": "Bangladeshi Taka", "BGN": "Bulgarian Lev", "BHD": "Bahraini Dinar",
    "BIF": "Burundian Franc", "BMD": "Bermudian Dollar", "BND": "Brunei Dollar",
    "BOB": "Bolivian Boliviano", "BRL": "Brazilian Real", "BSD": "Bahamian Dollar",
    "BTN": "Bhutanese Ngultrum", "BWP": "Botswana Pula", "BYN": "Belarusian Ruble",
    "BZD": "Belize Dollar", "CAD": "Canadian Dollar", "CDF": "Congolese Franc",
    "CHF": "Swiss Franc", "CLP": "Chilean Peso", "CNY": "Chinese Yuan",
    "COP": "Colombian Peso", "CRC": "Costa Rican Colón", "CUP": "Cuban Peso",
    "CVE": "Cape Verdean Escudo", "CZK": "Czech Koruna", "DJF": "Djiboutian Franc",
    "DKK": "Danish Krone", "DOP": "Dominican Peso", "DZD": "Algerian Dinar",
    "EGP": "Egyptian Pound", "ERN": "Eritrean Nakfa", "ETB": "Ethiopian Birr",
    "EUR": "Euro", "FJD": "Fijian Dollar", "FKP": "Falkland Islands Pound",
    "GBP": "Pound Sterling", "GEL": "Georgian Lari", "GHS": "Ghanaian Cedi",
    "GIP": "Gibraltar Pound", "GMD": "Gambian Dalasi", "GNF": "Guinean Franc",
    "GTQ": "Guatemalan Quetzal", "GYD": "Guyanese Dollar", "HKD": "Hong Kong Dollar",
    "HNL": "Honduran Lempira", "HTG": "Haitian Gourde", "HUF": "Hungarian Forint",
    "IDR": "Rupiah", "ILS": "Israeli New Shekel", "INR": "Indian Rupee",
    "IQD": "Iraqi Dinar", "IRR": "Iranian Rial", "ISK": "Icelandic Króna",
    "JMD": "Jamaican Dollar", "JOD": "Jordanian Dinar", "JPY": "Japanese Yen",
    "KES": "Kenyan Shilling", "KGS": "Kyrgyzstani Som", "KHR": "Cambodian Riel",
    "KMF": "Comorian Franc", "KPW": "North Korean Won", "KRW": "South Korean Won",
    "KWD": "Kuwaiti Dinar", "KYD": "Cayman Islands Dollar", "KZT": "Kazakhstani Tenge",
    "LAK": "Lao Kip", "LBP": "Lebanese Pound", "LKR": "Sri Lankan Rupee",
    "LRD": "Liberian Dollar", "LSL": "Lesotho Loti", "LYD": "Libyan Dinar",
    "MAD": "Moroccan Dirham", "MDL": "Moldovan Leu", "MGA": "Malagasy Ariary",
    "MKD": "Macedonian Denar", "MMK": "Myanmar Kyat", "MNT": "Mongolian Tögrög",
    "MOP": "Macanese Pataca", "MRU": "Mauritanian Ouguiya", "MUR": "Mauritian Rupee",
    "MVR": "Maldivian Rufiyaa", "MWK": "Malawian Kwacha", "MXN": "Mexican Peso",
    "MYR": "Malaysian Ringgit", "MZN": "Mozambican Metical", "NAD": "Namibian Dollar",
    "NGN": "Nigerian Naira", "NIO": "Nicaraguan Córdoba", "NOK": "Norwegian Krone",
    "NPR": "Nepalese Rupee", "NZD": "New Zealand Dollar", "OMR": "Omani Rial",
    "PAB": "Panamanian Balboa", "PEN": "Peruvian Sol", "PGK": "Papua New Guinean Kina",
    "PHP": "Philippine Peso", "PKR": "Pakistani Rupee", "PLN": "Polish Złoty",
    "PYG": "Paraguayan Guaraní", "QAR": "Qatari Riyal", "RON": "Romanian Leu",
    "RSD": "Serbian Dinar", "RUB": "Russian Ruble", "RWF": "Rwandan Franc",
    "SAR": "Saudi Riyal", "SBD": "Solomon Islands Dollar", "SCR": "Seychellois Rupee",
    "SDG": "Sudanese Pound", "SEK": "Swedish Krona", "SGD": "Singapore Dollar",
    "SHP": "Saint Helena Pound", "SLE": "Sierra Leonean Leone", "SOS": "Somali Shilling",
    "SRD": "Surinamese Dollar", "SSP": "South Sudanese Pound", "STN": "São Tomé Dobra",
    "SVC": "Salvadoran Colón", "SYP": "Syrian Pound", "SZL": "Eswatini Lilangeni",
    "THB": "Thai Baht", "TJS": "Tajikistani Somoni", "TMT": "Turkmenistani Manat",
    "TND": "Tunisian Dinar", "TOP": "Tongan Paʻanga", "TRY": "Turkish Lira",
    "TTD": "Trinidad and Tobago Dollar", "TWD": "New Taiwan Dollar",
    "TZS": "Tanzanian Shilling", "UAH": "Ukrainian Hryvnia", "UGX": "Ugandan Shilling",
    "USD": "US Dollar", "UYU": "Uruguayan Peso", "UZS": "Uzbekistani Sum",
    "VES": "Venezuelan Bolívar", "VND": "Vietnamese Đồng", "VUV": "Vanuatu Vatu",
    "WST": "Samoan Tālā", "XAF": "Central African CFA Franc", "XCD": "East Caribbean Dollar",
    "XOF": "West African CFA Franc", "XPF": "CFP Franc", "YER": "Yemeni Rial",
    "ZAR": "South African Rand", "ZMW": "Zambian Kwacha", "ZWG": "Zimbabwe Gold",
}

_cur: ContextVar[str] = ContextVar("currency", default=DEFAULT)


def set_currency(code: str) -> str:
    code = (code or "").upper()
    code = code if code in NAMES else DEFAULT
    _cur.set(code)
    return code


def get_currency() -> str:
    return _cur.get()


def code_label(code: str) -> str:
    """'IDR · Rp — Rupiah' untuk dropdown."""
    return f"{code} · {symbol(code)} — {NAMES.get(code, code)}"


def symbol(code: str = "") -> str:
    code = code or _cur.get()
    return SYMBOLS.get(code, code)


def decimals(code: str = "") -> int:
    code = code or _cur.get()
    return 0 if code in ZERO_DECIMALS else 2


def separators() -> tuple:
    """(pemisah ribuan, pemisah desimal) menurut bahasa antarmuka."""
    return (".", ",") if get_lang() == "id" else (",", ".")


def _digits(value: int, dec: int) -> str:
    """Bagian angka saja, tanpa simbol dan tanpa tanda minus."""
    group, point = separators()
    whole, frac = divmod(abs(int(value)), SCALE)
    body = f"{whole:,}".replace(",", group)
    if dec == 0:
        return body
    return body + point + f"{frac:02d}"


def _join(sym: str, digits: str) -> str:
    """Simbol berupa huruf diberi jarak (Rp 1.000), lambang menempel ($12.50)."""
    return sym + " " + digits if sym[-1:].isalpha() else sym + digits


def fmt(value) -> str:
    """Nominal lengkap dengan simbol: 'Rp 18.888.000', '$12.50', '-€4,50'."""
    if value is None:
        return "–"
    value = int(value)
    body = _join(symbol(), _digits(value, decimals()))
    return "-" + body if value < 0 else body


def major(value):
    """Satuan simpan → nominal apa adanya, untuk ekspor spreadsheet.
    Bulat kalau mata uangnya tanpa desimal, supaya Excel tidak menampilkan ,00."""
    value = int(value or 0)
    return value // SCALE if decimals() == 0 else value / SCALE


def plain(value) -> str:
    """Tanpa simbol — untuk kolom isian dan ekspor."""
    return _digits(value or 0, decimals())


def short(value) -> str:
    """Bentuk ringkas untuk ruang sempit: '18,9 jt', '1.2 M'."""
    value = int(value or 0)
    major = abs(value) / SCALE
    rb, jt, M = units()
    if major >= 1_000_000_000:
        body = _trim(major / 1_000_000_000) + " " + M
    elif major >= 1_000_000:
        body = _trim(major / 1_000_000) + " " + jt
    elif major >= 1_000:
        body = f"{major / 1_000:.0f} " + rb
    else:
        body = _digits(abs(value), decimals())
    body = _join(symbol(), body) if major < 1_000 else body
    return "-" + body if value < 0 else body


def _trim(n: float) -> str:
    group, point = separators()
    return f"{n:.1f}".rstrip("0").rstrip(".").replace(".", point)


def parse(raw) -> int:
    """Baca apa pun yang diketik orang jadi satuan perseratus.

    '18.888.000' → 1888800000, '12,5' → 1250, 'Rp 4.500' → 450000.
    Pemisah desimal diambil dari bahasa; kalau mata uangnya tanpa desimal,
    apa pun di belakang koma diabaikan supaya '1.500' tidak jadi 1,5.
    """
    text = str(raw or "").strip()
    if not text:
        return 0
    group, point = separators()
    negative = text.lstrip().startswith("-")
    text = "".join(ch for ch in text if ch.isdigit() or ch in (group, point))
    if decimals() == 0:
        digits = "".join(ch for ch in text if ch.isdigit())
        return -int(digits) * SCALE if negative and digits else (int(digits) * SCALE if digits else 0)
    whole, _, frac = text.rpartition(point)
    if not whole:                                  # tidak ada pemisah desimal sama sekali
        whole, frac = frac, ""
    whole = "".join(ch for ch in whole if ch.isdigit()) or "0"
    frac = "".join(ch for ch in frac if ch.isdigit())[:2]
    value = int(whole) * SCALE + int((frac + "00")[:2] or 0)
    return -value if negative else value
