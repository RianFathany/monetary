"""Gabungkan part-1..4 jadi design/sumber-email-20-opsi.html (satu berkas, bisa dibuka langsung)."""
from pathlib import Path

here = Path(__file__).parent
base = (here / "_base.css").read_text()
parts = "\n".join((here / f"part-{i}.html").read_text() for i in range(1, 5) if (here / f"part-{i}.html").exists())
rekom = (here / "rekomendasi.html").read_text() if (here / "rekomendasi.html").exists() else ""
nav = "".join(f'<a href="#o{i}">{i}</a>' for i in range(1, 21))

page = f"""<!doctype html>
<html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sumber Email · 20 Opsi</title>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>{base}
.top{{position:sticky;top:0;z-index:5;background:color-mix(in srgb,var(--bg) 92%,transparent);border-bottom:1px solid var(--line)}}
.top .in{{max-width:1320px;margin:0 auto;padding:14px 16px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}}
.top h1{{margin:0;font-size:17px;letter-spacing:-.01em;flex:1;min-width:200px}}
.top h1 small{{display:block;font-size:12px;font-weight:500;color:var(--muted)}}
.jump{{display:flex;gap:4px;flex-wrap:wrap}}
.jump a{{width:28px;height:28px;display:grid;place-items:center;border-radius:7px;font-size:12px;font-weight:600;color:var(--fg2);text-decoration:none;background:var(--card);box-shadow:0 0 0 1px var(--line)}}
.jump a:hover{{background:var(--fg);color:var(--bg)}}
.tog{{border:0;background:var(--fg);color:var(--bg);border-radius:8px;padding:8px 12px;font:600 12.5px "Plus Jakarta Sans",sans-serif;cursor:pointer}}
.grid{{max-width:1320px;margin:0 auto;padding:24px 16px;display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:40px 28px}}
.opt{{scroll-margin-top:90px}}
.rekom{{max-width:880px;margin:0 auto;padding:8px 16px 64px}}
</style></head><body>
<div class="top"><div class="in">
  <h1>Sumber Email · 20 opsi desain<small>Data contoh sesuai kasusmu. Logo masih tiruan; versi asli dari Logo.dev.</small></h1>
  <nav class="jump" aria-label="Lompat ke opsi">{nav}<a href="#rekom" style="width:auto;padding:0 10px">Rekomendasi</a></nav>
  <button class="tog" onclick="const r=document.documentElement;const dark=r.dataset.theme==='dark'||(!r.dataset.theme&&matchMedia('(prefers-color-scheme: dark)').matches);r.dataset.theme=dark?'light':'dark'">Terang / gelap</button>
</div></div>
<main class="grid">{parts}</main>
<section class="rekom" id="rekom">{rekom}</section>
</body></html>"""
(here.parent / "sumber-email-20-opsi.html").write_text(page)
print("ok", len(page))
