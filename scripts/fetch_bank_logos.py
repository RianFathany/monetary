"""Unduh logo bank sekali dari Logo.dev ke app/static/banks/<kunci>.png.

Dijalankan manual di lokal, hasilnya ikut di-commit. Aplikasi hanya memakai
file statis itu dan tidak pernah memanggil Logo.dev saat berjalan, jadi daftar
bank pengguna tidak terkirim ke pihak ketiga.

    LOGO_DEV_TOKEN=pk_xxx python scripts/fetch_bank_logos.py          # yang belum ada saja
    LOGO_DEV_TOKEN=pk_xxx python scripts/fetch_bank_logos.py bca bri  # unduh ulang bank tertentu

Logo berlatar putih dirapikan: tepi kosong dipotong lalu ditaruh di tengah
kotak putih, supaya logo yang lebar tidak tenggelam di petak 32 px. Logo yang
sudah berupa petak berwarna (mis. BCA) dibiarkan utuh. Butuh Pillow (hanya
untuk skrip ini, bukan dependensi aplikasi). Token tidak disimpan di mana pun.
"""
import io
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageChops

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.banks import ALL  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "app" / "static" / "banks"
SIZE = 128
# Logo dua bank ini dari Logo.dev berupa lambang terpotong yang sulit dikenali, jadi diambil manual:
#   bni    : Wikimedia Commons "Bank Negara Indonesia logo (2004).svg" (domain publik)
#   jateng : lambang berwarna dari https://www.bankjateng.co.id/media/Logo_Bank_Jateng_Putih_Transparan.png
# Keduanya dilewati saat mengunduh tanpa argumen supaya tidak tertimpa.
SKIP = {"bni", "jateng"}


def _putih(px) -> bool:
    return all(c >= 235 for c in px[:3])


def rapikan(data: bytes) -> Image.Image:
    im = Image.open(io.BytesIO(data)).convert("RGB")
    if not _putih(im.getpixel((0, 0))):
        return im.resize((SIZE, SIZE), Image.LANCZOS)          # petak berwarna penuh: biarkan
    beda = ImageChops.difference(im, Image.new("RGB", im.size, (255, 255, 255))).convert("L")
    box = beda.point(lambda v: 255 if v > 24 else 0).getbbox()
    if box:
        im = im.crop(box)
    w, h = im.size
    sisi = int(max(w, h) * 1.12)                              # sedikit ruang napas
    kotak = Image.new("RGB", (sisi, sisi), (255, 255, 255))
    kotak.paste(im, ((sisi - w) // 2, (sisi - h) // 2))
    return kotak.resize((SIZE, SIZE), Image.LANCZOS)


def main(argv) -> int:
    token = os.environ.get("LOGO_DEV_TOKEN", "")
    if not token.startswith("pk_"):
        print("Isi LOGO_DEV_TOKEN dengan publishable key (pk_...).")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    pilih = set(argv)
    for b in ALL:
        path = OUT / f"{b['key']}.png"
        if pilih and b["key"] not in pilih:
            continue
        if not pilih and (path.exists() or b["key"] in SKIP):
            continue
        url = f"https://img.logo.dev/{b['domain']}?token={token}&size=512&format=png"
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                data = r.read()
        except urllib.error.HTTPError as e:
            print(f"{b['key']}: {b['domain']} gagal ({e.code})")
            continue
        rapikan(data).save(path, optimize=True)
        print(f"{b['key']}: {b['domain']} -> {path.stat().st_size} byte")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
