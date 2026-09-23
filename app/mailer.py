"""Kirim surel lewat Resend (HTTPS, tanpa dependensi baru).

Dipakai untuk dua hal saja: memverifikasi alamat email saat mendaftar, dan
mengirim tautan setel ulang password. Tidak ada surel pemasaran.

API key dan alamat pengirim disimpan di system.db (setelan aplikasi), sejalan
dengan konfigurasi Google — jadi bisa diatur dari halaman Setelan tanpa deploy.
"""
import json
import urllib.error
import urllib.request

from .db import get_app_setting, set_app_setting

API = "https://api.resend.com/emails"


def config() -> dict:
    return dict(
        api_key=(get_app_setting("resend_key") or "").strip(),
        sender=(get_app_setting("mail_from") or "").strip(),
        name=(get_app_setting("mail_name") or "Muara").strip(),
    )


def save_config(api_key: str, sender: str, name: str) -> None:
    if api_key.strip():                       # kosong = biarkan yang lama
        set_app_setting("resend_key", api_key.strip())
    set_app_setting("mail_from", sender.strip())
    set_app_setting("mail_name", name.strip()[:60])


def is_enabled() -> bool:
    c = config()
    return bool(c["api_key"] and c["sender"])


def send(to: str, subject: str, heading: str, lines: list, button: tuple = None) -> tuple:
    """Kirim satu surel. Kembalikan (berhasil, pesan kesalahan)."""
    c = config()
    if not is_enabled():
        return False, "mail not configured"
    payload = {
        "from": f"{c['name']} <{c['sender']}>",
        "to": [to],
        "subject": subject,
        "html": render(heading, lines, button),
        "text": "\n\n".join(lines + ([button[1]] if button else [])),
    }
    req = urllib.request.Request(
        API, data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {c['api_key']}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:      # noqa: S310 (URL tetap)
            return 200 <= r.status < 300, ""
    except urllib.error.HTTPError as e:
        return False, f"{e.code} {e.read()[:200].decode(errors='replace')}"
    except Exception as e:                                       # jaringan mati, DNS, dll.
        return False, str(e)


def render(heading: str, lines: list, button: tuple = None) -> str:
    """Surel polos yang terbaca di semua klien: satu kolom, tanpa gambar."""
    body = "".join(f'<p style="margin:0 0 14px;font-size:15px;line-height:1.6;color:#2a2a2e">{x}</p>'
                   for x in lines)
    cta = ""
    if button:
        label, url = button
        cta = (f'<p style="margin:22px 0"><a href="{url}" '
               f'style="display:inline-block;background:#0066cc;color:#fff;text-decoration:none;'
               f'padding:12px 22px;border-radius:10px;font-weight:600;font-size:15px">{label}</a></p>'
               f'<p style="margin:0;font-size:12px;color:#8a8a90;word-break:break-all">{url}</p>')
    return (
        '<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#f5f5f7;padding:28px">'
        '<div style="max-width:520px;margin:0 auto;background:#fff;border-radius:16px;padding:28px">'
        f'<h1 style="margin:0 0 16px;font-size:19px;color:#1a1a1c">{heading}</h1>'
        f'{body}{cta}'
        '<p style="margin:24px 0 0;padding-top:16px;border-top:1px solid #ececf0;font-size:12px;color:#8a8a90">'
        'Muara — catatan keuangan pribadi. Surel ini dikirim otomatis, tidak perlu dibalas.</p>'
        '</div></div>')
