"""Panduan: dua bahasa, isinya utuh, dan tidak ada menu yang tertinggal."""
import re
import unittest

from app import guide, i18n


class TestPanduan(unittest.TestCase):
    def tearDown(self):
        i18n.set_lang("id")

    def test_dua_bahasa_punya_menu_yang_sama(self):
        """Kalau satu bahasa ketinggalan satu menu, pembacanya tidak akan tahu
        ada yang hilang — dia cuma melihat panduan yang kurang lengkap."""
        self.assertEqual([m["slug"] for m in guide.MENU_ID],
                         [m["slug"] for m in guide.MENU_EN])

    def test_setiap_entri_lengkap(self):
        for daftar in (guide.MENU_ID, guide.MENU_EN):
            for m in daftar:
                self.assertTrue(m["judul"].strip(), m)
                self.assertTrue(m["untuk"].strip(), m)
                self.assertGreaterEqual(len(m["isi"]), 2, m)

    def test_ikut_bahasa_aktif(self):
        i18n.set_lang("en")
        self.assertEqual(guide.menus()[0]["judul"], "Month")
        i18n.set_lang("id")
        self.assertEqual(guide.menus()[0]["judul"], "Bulan")

    def test_html_di_dalamnya_seimbang(self):
        """Isinya dirender dengan |safe, jadi tag yang tidak tertutup merusak
        seluruh halaman, bukan cuma satu baris."""
        for daftar in (guide.MENU_ID, guide.MENU_EN):
            for m in daftar:
                for baris in m["isi"]:
                    buka = re.findall(r"<(\w+)>", baris)
                    tutup = re.findall(r"</(\w+)>", baris)
                    self.assertEqual(sorted(buka), sorted(tutup), baris)

    def test_tiap_menu_punya_warna_sendiri(self):
        """Warna ikon dipatok per menu, bukan diambil dari hash namanya. Menu
        baru yang lupa diberi warna akan jatuh ke biru bawaan dan menabrak
        Bulan — jadi kelupaannya harus berbunyi di sini, bukan di mata orang."""
        self.assertEqual(sorted(guide.WARNA), sorted(m["slug"] for m in guide.MENU_ID))
        hue = [w[0] for w in guide.WARNA.values()]
        self.assertEqual(len(set(hue)), len(hue), "dua menu tidak boleh sewarna")

    def test_warna_tetangga_berjauhan(self):
        """Dua kartu yang bersebelahan tidak boleh terbaca sebagai warna yang
        sama. Yang netral (Setelan) dikecualikan: dia memang nyaris tanpa warna."""
        urut = [guide.WARNA[m["slug"]] for m in guide.MENU_ID]
        for (h1, s1, _), (h2, s2, _) in zip(urut, urut[1:]):
            if s1 < 30 or s2 < 30:
                continue
            jarak = abs(h1 - h2)
            self.assertGreaterEqual(min(jarak, 360 - jarak), 40, f"{h1} dan {h2} terlalu dekat")

    def test_gaya_siap_tempel_ke_style(self):
        gaya = guide.menus()[0]["gaya"]
        for bagian in ("--h:", "--gs:", "--gb:"):
            self.assertIn(bagian, gaya)
        self.assertNotIn('"', gaya, "akan merusak atribut style")

    def test_semua_menu_navigasi_terdokumentasi(self):
        """Menu yang ada di navigasi tapi tidak ada di panduan adalah menu yang
        tidak pernah dijelaskan ke siapa pun."""
        import pathlib
        nav = pathlib.Path("app/templates/base.html").read_text()
        blok = nav[nav.index('<nav class="nav">'):nav.index("</nav>")]
        alamat = set(re.findall(r'href="/(\w*)', blok))
        alamat.discard("m")                                  # /m/<bulan> = halaman Bulan
        alamat.discard("panduan")                            # halaman ini sendiri
        peta = {"accounts": "kantong", "report": "laporan", "overview": "ringkasan",
                "assets": "aset", "settings": "setelan", "dokumen": "dokumen",
                "anggaran": "anggaran"}
        punya = {m["slug"] for m in guide.MENU_ID}
        for a in alamat:
            self.assertIn(peta.get(a, a), punya, f"menu /{a} belum ada di panduan")


if __name__ == "__main__":
    unittest.main()
