"""Daftar bank untuk Sumber Email.

Tiap bank: kunci (dipakai di email_rules.parser dan nama file logo), nama,
singkatan, domain situs (untuk mengunduh logo sekali lewat
scripts/fetch_bank_logos.py), dan domain pengirim email notifikasi.

Domain pengirim adalah tebakan terbaik dari domain resmi bank; kalau notifikasi
bank tertentu datang dari domain lain, pengguna bisa mengubahnya di "Atur
pengirim", dan isiannya di sini dibetulkan begitu ketahuan.

BCA, Bank Mega, dan Livin' punya label baca khusus di app/mailparse.py; bank
lain memakai label umum, yang menangkap sebagian besar format notifikasi.
"""

# (kunci, nama, singkatan, domain situs, domain pengirim)
INDONESIA = [
    ("bca", "BCA", "BCA", "bca.co.id", "bca.co.id"),
    ("livin", "Livin' by Mandiri", "Livin", "bankmandiri.co.id", "bankmandiri.co.id"),
    ("bri", "BRI", "BRI", "bri.co.id", "bri.co.id"),
    ("bni", "BNI", "BNI", "bni.co.id", "bni.co.id"),
    ("btn", "BTN", "BTN", "btn.co.id", "btn.co.id"),
    ("bsi", "Bank Syariah Indonesia", "BSI", "bankbsi.co.id", "bankbsi.co.id"),
    ("mega", "Bank Mega", "Mega", "bankmega.com", "bankmega.com"),
    ("cimb", "CIMB Niaga", "CIMB", "cimbniaga.co.id", "cimbniaga.co.id"),
    ("danamon", "Danamon", "Danamon", "danamon.co.id", "danamon.co.id"),
    ("permata", "PermataBank", "Permata", "permatabank.co.id", "permatabank.co.id"),
    ("panin", "Panin Bank", "Panin", "panin.co.id", "panin.co.id"),
    ("ocbc", "OCBC Indonesia", "OCBC", "ocbc.id", "ocbc.id"),
    ("maybank", "Maybank Indonesia", "Maybank", "maybank.co.id", "maybank.co.id"),
    ("uob", "UOB Indonesia", "UOB", "uob.co.id", "uob.co.id"),
    ("hsbc", "HSBC Indonesia", "HSBC", "hsbc.co.id", "hsbc.co.id"),
    ("dbs", "DBS Indonesia", "DBS", "dbs.com", "dbs.com"),
    ("sc", "Standard Chartered", "StanChart", "sc.com", "sc.com"),
    ("smbci", "SMBC Indonesia (BTPN)", "SMBC", "smbci.com", "btpn.com"),
    ("jenius", "Jenius", "Jenius", "jenius.com", "jenius.com"),
    ("sinarmas", "Bank Sinarmas", "Sinarmas", "banksinarmas.com", "banksinarmas.com"),
    ("muamalat", "Bank Muamalat", "Muamalat", "bankmuamalat.co.id", "bankmuamalat.co.id"),
    ("megasyariah", "Bank Mega Syariah", "Mega Syariah", "megasyariah.co.id", "megasyariah.co.id"),
    ("btpnsyariah", "BTPN Syariah", "BTPNS", "btpnsyariah.com", "btpnsyariah.com"),
    ("mnc", "MNC Bank", "MNC", "mncbank.co.id", "mncbank.co.id"),
    ("qnb", "QNB Indonesia", "QNB", "qnb.co.id", "qnb.co.id"),
    ("icbc", "ICBC Indonesia", "ICBC", "icbc.co.id", "icbc.co.id"),
    ("bjb", "Bank BJB", "BJB", "bankbjb.co.id", "bankbjb.co.id"),
    ("dki", "Bank DKI", "DKI", "bankdki.co.id", "bankdki.co.id"),
    ("jatim", "Bank Jatim", "Jatim", "bankjatim.co.id", "bankjatim.co.id"),
    ("jateng", "Bank Jateng", "Jateng", "bankjateng.co.id", "bankjateng.co.id"),
    ("bpddiy", "BPD DIY", "BPD DIY", "bpddiy.co.id", "bpddiy.co.id"),
    ("bankbali", "Bank BPD Bali", "BPD Bali", "bpdbali.co.id", "bpdbali.co.id"),
    ("banksumut", "Bank Sumut", "Sumut", "banksumut.co.id", "banksumut.co.id"),
    ("nagari", "Bank Nagari", "Nagari", "banknagari.co.id", "banknagari.co.id"),
    ("banksulselbar", "Bank Sulselbar", "Sulselbar", "banksulselbar.co.id", "banksulselbar.co.id"),
    ("jago", "Bank Jago", "Jago", "jago.com", "jago.com"),
    ("seabank", "SeaBank", "SeaBank", "seabank.co.id", "seabank.co.id"),
    ("blu", "blu by BCA Digital", "blu", "blubybcadigital.id", "bcadigital.co.id"),
    ("allo", "Allo Bank", "Allo", "allobank.com", "allobank.com"),
    ("neo", "Bank Neo Commerce", "Neo", "bankneocommerce.co.id", "bankneocommerce.co.id"),
    ("raya", "Bank Raya", "Raya", "bankraya.co.id", "bankraya.co.id"),
    ("superbank", "Superbank", "Superbank", "superbank.id", "superbank.id"),
    ("linebank", "LINE Bank", "LINE Bank", "linebank.co.id", "linebank.co.id"),
    ("hana", "KEB Hana Indonesia", "Hana", "hanabank.co.id", "hanabank.co.id"),
    ("krom", "Krom Bank", "Krom", "krom.id", "krom.id"),
]

LUAR_NEGERI = [
    ("chase", "Chase", "Chase", "chase.com", "chase.com"),
    ("bofa", "Bank of America", "BofA", "bankofamerica.com", "bankofamerica.com"),
    ("wellsfargo", "Wells Fargo", "Wells Fargo", "wellsfargo.com", "wellsfargo.com"),
    ("citi", "Citi", "Citi", "citi.com", "citi.com"),
    ("hsbcglobal", "HSBC", "HSBC", "hsbc.com", "hsbc.com"),
    ("barclays", "Barclays", "Barclays", "barclays.co.uk", "barclays.co.uk"),
    ("dbssg", "DBS Singapore", "DBS", "dbs.com.sg", "dbs.com"),
    ("ocbcsg", "OCBC Singapore", "OCBC", "ocbc.com", "ocbc.com"),
    ("uobsg", "UOB Singapore", "UOB", "uob.com.sg", "uob.com.sg"),
    ("maybankmy", "Maybank Malaysia", "Maybank", "maybank2u.com.my", "maybank.com"),
    ("cimbmy", "CIMB Malaysia", "CIMB", "cimb.com.my", "cimb.com"),
    ("commbank", "Commonwealth Bank", "CommBank", "commbank.com.au", "commbank.com.au"),
    ("anz", "ANZ", "ANZ", "anz.com.au", "anz.com"),
    ("mufg", "MUFG", "MUFG", "mufg.jp", "mufg.jp"),
    ("wise", "Wise", "Wise", "wise.com", "wise.com"),
    ("revolut", "Revolut", "Revolut", "revolut.com", "revolut.com"),
    ("paypal", "PayPal", "PayPal", "paypal.com", "paypal.com"),
    ("monzo", "Monzo", "Monzo", "monzo.com", "monzo.com"),
    ("n26", "N26", "N26", "n26.com", "n26.com"),
]

ALL = [dict(key=k, name=n, short=s, domain=d, sender=e, region=r)
       for r, rows in (("id", INDONESIA), ("intl", LUAR_NEGERI)) for k, n, s, d, e in rows]
