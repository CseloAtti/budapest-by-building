"""Checking the generator of the text pages (explore/, e/, sitemap.xml).   Run: py tests/test_explore.py
It catches: script injection from the names, selection of wrong buildings (building part, nameless, Wikipedia inherited from an estate),
missing pages in the sitemap, 'None'/'undefined' text on the pages, and that on the real data the file count stays under the Cloudflare limit (20,000)."""
import json
import re
import sys
import tempfile
from pathlib import Path
from test_common import ROOT, check, warn, end_

sys.path.insert(0, str(ROOT))
import build_explore as F

ERAS = [{"from": 1, "to": 1866, "label": "1866-ig – Kiegyezés előtt"}, {"from": 1867, "to": 1918, "label": "1867–1918 – Dualizmus"}]


def ep(i, **kw):
    d = {"id": i, "osm_tipus": "way", "tipus": "yes", "magassag": 10, "lat": 47.5, "lon": 19.0, "kor": 2}
    d.update(kw)
    return d


def main():
    print("[explore] szöveges oldalak generátora")
    list_ = [
        ep(1, nev="Jó Ház", cim="Fő utca 1", ev=1900, tervezo="Alpár Ignác", budapest100_url="https://budapest100.hu/x/"),
        ep(2, nev='<script>alert(1)</script> & "idézet"', cim="Kis utca 2", ev=1850, tervezo="Alpár Ignác"),
        ep(3, cim="Nagy utca 3", tervezo="Alpár Ignác", oeny_azonosito="123|abc"),
        ep(4, cim="Nagy utca 4", tervezo="Alpár Ignác és Másik Mester"),
        ep(5, cim="Név nélkül", ev=1900, resz=1),                       # building part: gets no page
        ep(6, ev=1900),                                                  # neither name nor address: gets no page
        ep(7, nev="Csak telepi wiki", cim="X utca 7", wikipedia="hu:Valami", wikipedia_zona=True),   # no own data: gets no page
        ep(8, nev="Saját wiki", cim="Y utca 8", wikipedia="hu:Saját cikk|hu:Másik"),
        ep(9, nev="Közönséges ház", cim="Z utca 9"),                     # no extra data: gets no page
    ]
    with tempfile.TemporaryDirectory() as t:
        out = Path(t)
        r = F.make(out, list_, ERAS, "var TIPUS_HU = { yes: 'x', apartments: 'lakóház' };")
        has = lambda p: (out / p / "index.html").exists()
        check(r["epulet"] == 5, f"5 épületnek kellene oldalt kapnia, kapott: {r['epulet']}")
        for good in ("w1", "w2", "w3", "w4", "w8"):
            check(has(f"e/{good}"), f"hiányzik az oldal: e/{good}")
        for bad in ("w5", "w6", "w7", "w9"):
            check(not has(f"e/{bad}"), f"nem kellene oldalnak lennie: e/{bad}")
        check(has("explore"), "hiányzik a explore/ kezdőoldal")
        check(r["epitesz"] == 1 and has("explore/architect/alpar-ignac"), "az Alpár Ignác oldal (4 épület) hiányzik")
        check(has("explore/era/1867-1918-dualizmus") or any((out / "explore/era").iterdir()), "hiányoznak a korszak-oldalak")
        for f in out.rglob("index.html"):
            s = f.read_text(encoding="utf-8")
            check("<script>alert" not in s, f"nem escape-elt szkript a(z) {f.relative_to(out)} oldalon")
            check(not re.search(r"\bNone\b|undefined|nan\b", re.sub(r"<style>.*?</style>", "", s, flags=re.S)), f"'None'/'undefined' szöveg: {f.relative_to(out)}")
            check('rel="canonical"' in s and "<title>" in s and 'name="description"' in s, f"hiányzó cím/leírás/canonical: {f.relative_to(out)}")
        w3 = (out / "e/w3/index.html").read_text(encoding="utf-8")
        check("oeny.hu/oeny/eorok/public/monument/123" in w3 and "monument/abc" not in w3, "az OENY-link csak számos azonosítóból készülhet")
        sm = (out / "sitemap.xml").read_text(encoding="utf-8")
        check(sm.count("<loc>") == r["oldal"], "a sitemap.xml sorainak száma nem egyezik az oldalak számával")
        check(len(list(out.rglob("index.html"))) == r["oldal"] - 1, "az index.html fájlok száma nem egyezik az oldalak számával (a térkép kezdőlapja a kiadás része, nem ez generálja)")
        check("Sitemap:" in (out / "robots.txt").read_text(encoding="utf-8"), "a robots.txt-ből hiányzik a Sitemap sor")
    # real data: the file count stays under the Cloudflare limit
    real = ROOT / "terkep3d" / "data_varos" / "epuletek.json"
    if real.exists():
        count_ = sum(1 for p in json.loads(real.read_text(encoding="utf-8")) if F.needed_page(p))
        print(f"  a valódi adatból {count_} épületoldal készülne")
        check(count_ < 17000, f"túl sok épületoldal ({count_}): a Cloudflare 20 000 fájlos korlátját közelíti")
        if count_ > 12000:
            warn(f"{count_} épületoldal: a 20 000 fájlos korlát 60%-a fölött vagyunk")
    return end_("test_explore")


if __name__ == "__main__":
    raise SystemExit(main())
