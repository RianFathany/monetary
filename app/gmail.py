"""Menyambungkan Gmail untuk membaca notifikasi transaksi bank.

Terpisah dari login Google (app/oauth.py). Login hanya meminta identitas;
di sini yang diminta izin `gmail.readonly`, dan akun Gmail yang disambungkan
boleh berbeda dari akun yang dipakai masuk — satu buku bisa menyambungkan
beberapa Gmail sekaligus.

OAuth client-nya sama dengan login, jadi tidak ada kredensial Google baru.
Yang baru hanya EMAIL_TOKEN_KEY: kunci untuk mengenkripsi refresh token
sebelum masuk ke berkas buku. Berkas buku ikut terbawa cadangan harian;
tanpa enkripsi, siapa pun yang memegang arsip itu bisa membaca Gmail pemiliknya.
Tanpa kunci itu fitur ini mati, bukan menyimpan token polos.

Yang dibaca hanya email yang cocok dengan aturan (pengirim + kata kunci
subjek). Tidak ada yang dikirim, dihapus, atau ditandai di Gmail.
"""
import base64
import hashlib
import html
import json
import os
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request

from . import oauth

SCOPE = "openid email https://www.googleapis.com/auth/gmail.readonly"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://gmail.googleapis.com/gmail/v1/users/me"
STATE_COOKIE = "monetary_gmail"
STATE_MAX_AGE = 600
TIMEOUT = 15


class Gagal(Exception):
    """Galat yang bisa ditampilkan apa adanya."""


class PerluSambungUlang(Gagal):
    """Google menolak refresh token: izinnya dicabut, kata sandi Google
    diganti, atau token tidak dipakai berbulan-bulan. Satu-satunya jalan
    adalah menyambungkan ulang akun itu."""


# ---------- konfigurasi ----------

def _key() -> str:
    return (os.environ.get("EMAIL_TOKEN_KEY") or "").strip()


def is_enabled() -> bool:
    return oauth.is_enabled() and bool(_key())


def missing() -> list:
    """Nama environment yang belum diisi — untuk halaman Setelan pemilik."""
    out = []
    c = oauth.config()
    if not c["client_id"]:
        out.append("GOOGLE_CLIENT_ID")
    if not c["client_secret"]:
        out.append("GOOGLE_CLIENT_SECRET")
    if not _key():
        out.append("EMAIL_TOKEN_KEY")
    return out


def redirect_uri(request) -> str:
    return oauth.redirect_uri(request).replace("/auth/google/callback", "/email/callback")


# ---------- enkripsi token ----------

def _fernet():
    from cryptography.fernet import Fernet
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(_key().encode()).digest()))


def seal(token: str) -> str:
    if not _key():
        raise Gagal("EMAIL_TOKEN_KEY belum diatur.")
    return _fernet().encrypt(token.encode()).decode()


def unseal(blob: str) -> str:
    from cryptography.fernet import InvalidToken
    try:
        return _fernet().decrypt(blob.encode()).decode()
    except InvalidToken:
        # Kuncinya diganti: token lama tidak bisa dibuka lagi, sama seperti dicabut.
        raise PerluSambungUlang("Token tidak bisa dibuka dengan kunci yang sekarang.")


# ---------- alur izin ----------

def start(request, login_hint: str = "") -> tuple:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    params = {
        "client_id": oauth.config()["client_id"],
        "redirect_uri": redirect_uri(request),
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        # offline + consent: Google hanya memberi refresh token kalau layar izin
        # benar-benar ditampilkan. Tanpa consent, menyambung ulang akun yang
        # pernah diizinkan berakhir tanpa token.
        "access_type": "offline",
        "prompt": "consent select_account",
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{oauth.AUTH_URL}?{urllib.parse.urlencode(params)}", dict(state=state, verifier=verifier)


def _post(url: str, fields: dict) -> dict:
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:    # noqa: S310 (URL tetap, milik Google)
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read() or b"{}")
        except ValueError:
            body = {}
        if body.get("error") == "invalid_grant":
            raise PerluSambungUlang("Izin Gmail sudah tidak berlaku.")
        raise Gagal(f"Google menolak permintaan ({e.code}).")
    except (urllib.error.URLError, TimeoutError):
        raise Gagal("Tidak bisa menghubungi Google.")


def exchange(code: str, verifier: str, request) -> dict:
    """Tukar code → {email, refresh_token}. Gagal kalau izin Gmail tidak dicentang."""
    c = oauth.config()
    body = _post(oauth.TOKEN_URL, {
        "code": code, "client_id": c["client_id"], "client_secret": c["client_secret"],
        "redirect_uri": redirect_uri(request), "grant_type": "authorization_code",
        "code_verifier": verifier,
    })
    granted = set((body.get("scope") or "").split())
    if "https://www.googleapis.com/auth/gmail.readonly" not in granted:
        # Layar izin Google membiarkan setiap scope dicentang terpisah.
        raise Gagal("Izin membaca Gmail tidak dicentang.")
    if not body.get("refresh_token"):
        raise Gagal("Google tidak memberikan token akses jangka panjang.")
    email = oauth.verified_email(oauth.claims(body.get("id_token", ""), c["client_id"]))
    if not email:
        raise Gagal("Email akun Google tidak terverifikasi.")
    return dict(email=email, refresh_token=body["refresh_token"])


def access_token(refresh_token: str) -> str:
    c = oauth.config()
    body = _post(oauth.TOKEN_URL, {
        "client_id": c["client_id"], "client_secret": c["client_secret"],
        "refresh_token": refresh_token, "grant_type": "refresh_token",
    })
    if not body.get("access_token"):
        raise Gagal("Google tidak memberikan token akses.")
    return body["access_token"]


def revoke(refresh_token: str) -> None:
    """Cabut izin di sisi Google. Gagal jaringan tidak menghalangi pemutusan:
    tokennya tetap dihapus dari buku, dan pemilik masih bisa mencabutnya di
    myaccount.google.com/permissions."""
    try:
        _post(REVOKE_URL, {"token": refresh_token})
    except Gagal:
        pass


# ---------- membaca email ----------

def _get(token: str, path: str, params: dict) -> dict:
    url = f"{API}/{path}?{urllib.parse.urlencode(params, doseq=True)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:    # noqa: S310
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise PerluSambungUlang("Izin Gmail sudah tidak berlaku.")
        raise Gagal(f"Gmail menolak permintaan ({e.code}).")
    except (urllib.error.URLError, TimeoutError):
        raise Gagal("Tidak bisa menghubungi Gmail.")


def _bersih(nilai: str) -> str:
    """Kata kunci: hanya huruf, angka, dan spasi — tanda kurung, kutip, titik dua,
    atau minus akan mengubah arti pencarian Gmail."""
    return " ".join(re.sub(r"[^\w ]", " ", nilai or "").split())


def _pengirim(nilai: str) -> str:
    """Pengirim: satu alamat atau domain, tanpa spasi. Spasi di dalam from:( )
    berarti beberapa pengirim sekaligus, dan kata OR di sana jadi operator."""
    return re.sub(r"[^A-Za-z0-9@._+-]", "", (nilai or "").split()[0] if (nilai or "").split() else "")


def query(sender: str, keywords: str, after_epoch: int) -> str:
    """Pencarian Gmail untuk satu aturan.

    `after:` memakai detik epoch, jadi sinkron berikutnya hanya meminta email
    yang datang sesudah sinkron sebelumnya. Kata kunci dipisah koma dan
    digabung dengan OR: salah satu kata cukup.
    """
    parts = [f"from:({_pengirim(sender)})"]
    kata = [_bersih(k) for k in (keywords or "").split(",")]
    kata = [f'"{k}"' if " " in k else k for k in kata if k]
    if kata:
        parts.append(f"subject:({' OR '.join(kata)})")
    parts.append(f"after:{int(after_epoch)}")
    return " ".join(parts)


def list_ids(token: str, q: str, limit: int = 50) -> list:
    body = _get(token, "messages", {"q": q, "maxResults": limit})
    return [m["id"] for m in body.get("messages", [])]


def fetch(token: str, msg_id: str) -> dict:
    """Satu email → {id, epoch, sender, subject, text}."""
    body = _get(token, f"messages/{msg_id}", {"format": "full"})
    payload = body.get("payload") or {}
    headers = {h.get("name", "").lower(): h.get("value", "") for h in payload.get("headers", [])}
    return dict(id=body.get("id", msg_id),
                epoch=int(body.get("internalDate", "0") or 0) // 1000,
                sender=headers.get("from", ""), subject=headers.get("subject", ""),
                text=body_text(payload) or html.unescape(body.get("snippet", "")))


def _decode(data: str) -> str:
    try:
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")
    except (ValueError, TypeError):
        return ""


def html_to_text(raw: str) -> str:
    """HTML email bank → teks per baris. Sel tabel dipisah ' | ' supaya pasangan
    'Nominal | Rp 50.000' tetap bersebelahan setelah tag dibuang."""
    raw = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)</t[dh]\s*>", " | ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d|table)\s*>", "\n", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw).replace("\xa0", " ")
    lines = []
    for b in raw.splitlines():
        b = " ".join(b.split()).strip(" |")
        b = re.sub(r"(\s*\|\s*)+", " | ", b)
        if b:
            lines.append(b)
    return "\n".join(lines)


def body_text(payload: dict) -> str:
    """Teks isi email: text/plain kalau ada, kalau tidak HTML yang dibersihkan."""
    plain, rich = [], []

    def walk(part):
        mime = part.get("mimeType", "")
        data = (part.get("body") or {}).get("data")
        if data and mime == "text/plain":
            plain.append(_decode(data))
        elif data and mime == "text/html":
            rich.append(_decode(data))
        for p in part.get("parts", []) or []:
            walk(p)

    walk(payload)
    if plain and any(p.strip() for p in plain):
        return "\n".join(" ".join(b.split()) for t in plain for b in t.splitlines() if b.strip())
    if rich:
        return html_to_text("\n".join(rich))
    return ""
