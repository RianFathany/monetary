"""Masuk dengan Google (OAuth 2.0 + OpenID Connect).

Aplikasi ini tetap satu buku. Google hanya dipakai untuk membuktikan bahwa
pemilik email tertentu yang sedang masuk; daftar email yang boleh masuk
disimpan sendiri, jadi orang lain yang punya akun Google tidak bisa ikut masuk.

Client ID, Client Secret, dan daftar email disimpan di tabel settings —
sejalan dengan password — supaya tidak perlu mengutak-atik .env di server.
Tanpa dependensi baru: cukup urllib bawaan Python.
"""
import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse
import urllib.request

from .db import get_app_setting, set_app_setting

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
STATE_COOKIE = "monetary_oauth"
STATE_MAX_AGE = 600           # 10 menit; cukup untuk satu kali login


# ---------- konfigurasi ----------

def _pick(key: str, env: str) -> str:
    """Environment yang berlaku. Nilai di database hanya sisa dari versi lama,
    saat kredensial ini masih bisa diketik lewat halaman Setelan."""
    return ((os.environ.get(env) or "").strip() or (get_app_setting(key) or "").strip())


def config(db=None) -> dict:
    """Konfigurasi Google berlaku untuk seluruh aplikasi, jadi diambil dari
    system.db, dengan environment sebagai bawaan."""
    return dict(
        client_id=_pick("google_client_id", "GOOGLE_CLIENT_ID"),
        client_secret=_pick("google_client_secret", "GOOGLE_CLIENT_SECRET"),
        allowed=emails(_pick("google_allowed", "GOOGLE_ALLOWED")),
    )


def from_env() -> bool:
    """Benar kalau tombol Google hidup karena environment, bukan karena diketik
    di Setelan — dipakai halaman Setelan untuk menjelaskan keadaannya."""
    return bool((os.environ.get("GOOGLE_CLIENT_ID") or "").strip()
                and not (get_app_setting("google_client_id") or "").strip())


def save_config(db, client_id: str, client_secret: str, allowed: str) -> None:
    set_app_setting("google_client_id", client_id.strip())
    if client_secret.strip():                     # kosong = biarkan yang lama
        set_app_setting("google_client_secret", client_secret.strip())
    set_app_setting("google_allowed", ", ".join(emails(allowed)))


def emails(raw: str) -> list:
    """Pisah daftar email dari teks (koma, spasi, atau baris baru)."""
    parts = [p.strip().lower() for p in raw.replace("\n", ",").replace(" ", ",").split(",")]
    out = []
    for p in parts:
        if "@" in p and p not in out:
            out.append(p)
    return out


def is_enabled(db=None) -> bool:
    """Cukup client id + secret. Daftar email (`allowed`) hanya menentukan siapa
    yang mewarisi buku pemilik, jadi daftar kosong tidak boleh mematikan tombolnya."""
    c = config()
    return bool(c["client_id"] and c["client_secret"])


def redirect_uri(request) -> str:
    """URI callback yang harus didaftarkan di Google Cloud Console."""
    base = str(request.base_url).rstrip("/")
    if base.startswith("http://") and request.headers.get("x-forwarded-proto") == "https":
        base = "https://" + base[len("http://"):]
    return base + "/auth/google/callback"


# ---------- alur login ----------

def start(db, request, next_url: str) -> tuple:
    """URL Google + data rahasia yang perlu dititipkan di cookie."""
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    params = {
        "client_id": config()["client_id"],
        "redirect_uri": redirect_uri(request),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}", dict(state=state, verifier=verifier, next=next_url)


def exchange(db, code: str, verifier: str, request) -> dict:
    """Tukar code jadi id_token lalu baca klaimnya."""
    c = config()
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": c["client_id"],
        "client_secret": c["client_secret"],
        "redirect_uri": redirect_uri(request),
        "grant_type": "authorization_code",
        "code_verifier": verifier,
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=15) as r:      # noqa: S310 (URL tetap, milik Google)
        body = json.loads(r.read())
    return claims(body.get("id_token", ""), c["client_id"])


def claims(id_token: str, client_id: str) -> dict:
    """Baca payload id_token. Token datang langsung dari Google lewat TLS
    (alur code + client secret), jadi tanda tangannya tidak perlu diperiksa lagi
    — yang wajib diperiksa: penerbit, tujuan, dan masa berlaku."""
    try:
        payload = id_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError):
        raise ValueError("id_token tidak terbaca")
    if data.get("iss") not in ISSUERS:
        raise ValueError("penerbit token bukan Google")
    aud = data.get("aud")
    if aud != client_id and client_id not in (aud or []):
        raise ValueError("token bukan untuk aplikasi ini")
    if int(data.get("exp", 0)) < time.time():
        raise ValueError("token kedaluwarsa")
    return data


def verified_email(data: dict) -> str:
    """Email dari klaim token, hanya bila Google menyatakannya terverifikasi."""
    email = (data.get("email") or "").lower()
    return email if email and data.get("email_verified") else ""


def in_allowlist(email: str) -> bool:
    """Email yang dipetakan ke buku pemilik (Anda, dan siapa pun yang Anda izinkan ikut)."""
    return (email or "").lower() in config()["allowed"]
