"""Dwibahasa: kamus lengkap, filter ikut bahasa, dan template tetap merender."""
import unittest

from app import i18n
from app.lang_en import EN


class TestKamus(unittest.TestCase):
    def tearDown(self):
        i18n.set_lang("id")

    def test_bahasa_indonesia_apa_adanya(self):
        i18n.set_lang("id")
        self.assertEqual(i18n.t("Kantong"), "Kantong")
        self.assertEqual(i18n.months(short=True)[4], "Mei")

    def test_bahasa_inggris(self):
        i18n.set_lang("en")
        self.assertEqual(i18n.t("Kantong"), "Pockets")
        self.assertEqual(i18n.months(short=True)[4], "May")
        self.assertEqual(i18n.units(), ("k", "M", "B"))

    def test_bahasa_tak_dikenal_jatuh_ke_indonesia(self):
        self.assertEqual(i18n.set_lang("de"), "id")

    def test_placeholder_diisi(self):
        i18n.set_lang("en")
        self.assertIn("3", i18n.t("{n} transaksi senilai {v} belum berkategori atau masih bertanda perlu "
                                  "dicek — laporan ini ikut melenceng selama itu dibiarkan.", n=3, v="Rp 1 k"))

    def test_terjemahan_tidak_kosong(self):
        kosong = [k for k, v in EN.items() if not v.strip()]
        self.assertEqual(kosong, [])

    def test_placeholder_cocok(self):
        """Setiap {placeholder} di kunci harus muncul juga di terjemahannya."""
        import re
        beda = []
        for k, v in EN.items():
            if set(re.findall(r"\{(\w+)\}", k)) != set(re.findall(r"\{(\w+)\}", v)):
                beda.append(k)
        self.assertEqual(beda, [])


class TestTemplateTerbungkus(unittest.TestCase):
    def test_semua_teks_template_ada_di_kamus(self):
        """Teks yang sudah dibungkus _() harus punya terjemahan Inggris."""
        import pathlib, re
        hilang = []
        for p in pathlib.Path("app/templates").glob("*.html"):
            for m in re.finditer(r"_\(\s*(['\"])(.*?)\1\s*\)", p.read_text(), re.S):
                key = " ".join(m.group(2).replace("\\n", " ").replace("\\'", "'").split())
                if key not in {" ".join(k.split()) for k in EN}:
                    hilang.append((p.name, key))
        self.assertEqual(hilang, [])


if __name__ == "__main__":
    unittest.main()
