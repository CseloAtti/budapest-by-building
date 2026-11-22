"""A szöveges oldalak (explore/, e/, sitemap.xml) generátorának ellenőrzése.   Futtatás: py tesztek/teszt_felfedezo.py
Megfogja: szkript-beszúrás a nevekből, rossz épületek kiválasztása (épületrész, név nélküli, telepről örökölt Wikipédia),
hiányzó oldalak a sitemapben, 'None'/'undefined' szöveg az oldalakon, és hogy a valódi adaton a fájlszám a Cloudflare-korlát (20 000) alatt marad."""
import json
import re
import sys
import tempfile
from pathlib import Path
from kozos_teszt import GYOKER, ellenoriz, figyelmeztet, vege

sys.path.insert(0, str(GYOKER))
import felfedezo_keszites as F

KORSZAKOK = [{"from": 1, "to": 1866, "label": "1866-ig – Kiegyezés előtt"}, {"from": 1867, "to": 1918, "label": "1867–1918 – Dualizmus"}]


def ep(i, **kw):
    d = {"id": i, "osm_tipus": "way", "tipus": "yes", "magassag": 10, "lat": 47.5, "lon": 19.0, "kor": 2}
    d.update(kw)
    return d


def main():
    print("[explore] szöveges oldalak generátora")
    lista = [
        ep(1, nev="Jó Ház", cim="Fő utca 1", ev=1900, tervezo="Alpár Ignác", budapest100_url="https://budapest100.hu/x/"),
        ep(2, nev='<script>alert(1)</script> & "idézet"', cim="Kis utca 2", ev=1850, tervezo="Alpár Ignác"),
        ep(3, cim="Nagy utca 3", tervezo="Alpár Ignác", oeny_azonosito="123|abc"),
        ep(4, cim="Nagy utca 4", tervezo="Alpár Ignác és Másik Mester"),
        ep(5, cim="Név nélkül", ev=1900, resz=1),                       # épületrész: nem kap oldalt
        ep(6, ev=1900),                                                  # se név, se cím: nem kap oldalt
        ep(7, nev="Csak telepi wiki", cim="X utca 7", wikipedia="hu:Valami", wikipedia_zona=True),   # nincs saját adat: nem kap oldalt
        ep(8, nev="Saját wiki", cim="Y utca 8", wikipedia="hu:Saját cikk|hu:Másik"),
        ep(9, nev="Közönséges ház", cim="Z utca 9"),                     # nincs plusz adat: nem kap oldalt
    ]
    with tempfile.TemporaryDirectory() as t:
        ki = Path(t)
        r = F.keszit(ki, lista, KORSZAKOK, "var TIPUS_HU = { yes: 'x', apartments: 'lakóház' };")
        van = lambda p: (ki / p / "index.html").exists()
        ellenoriz(r["epulet"] == 5, f"5 épületnek kellene oldalt kapnia, kapott: {r['epulet']}")
        for jo in ("w1", "w2", "w3", "w4", "w8"):
            ellenoriz(van(f"e/{jo}"), f"hiányzik az oldal: e/{jo}")
        for rossz in ("w5", "w6", "w7", "w9"):
            ellenoriz(not van(f"e/{rossz}"), f"nem kellene oldalnak lennie: e/{rossz}")
        ellenoriz(van("explore"), "hiányzik a explore/ kezdőoldal")
        ellenoriz(r["epitesz"] == 1 and van("explore/architect/alpar-ignac"), "az Alpár Ignác oldal (4 épület) hiányzik")
        ellenoriz(van("explore/era/1867-1918-dualizmus") or any((ki / "explore/era").iterdir()), "hiányoznak a korszak-oldalak")
        for f in ki.rglob("index.html"):
            s = f.read_text(encoding="utf-8")
            ellenoriz("<script>alert" not in s, f"nem escape-elt szkript a(z) {f.relative_to(ki)} oldalon")
            ellenoriz(not re.search(r"\bNone\b|undefined|nan\b", re.sub(r"<style>.*?</style>", "", s, flags=re.S)), f"'None'/'undefined' szöveg: {f.relative_to(ki)}")
            ellenoriz('rel="canonical"' in s and "<title>" in s and 'name="description"' in s, f"hiányzó cím/leírás/canonical: {f.relative_to(ki)}")
        w3 = (ki / "e/w3/index.html").read_text(encoding="utf-8")
        ellenoriz("oeny.hu/oeny/eorok/public/monument/123" in w3 and "monument/abc" not in w3, "az OENY-link csak számos azonosítóból készülhet")
        sm = (ki / "sitemap.xml").read_text(encoding="utf-8")
        ellenoriz(sm.count("<loc>") == r["oldal"], "a sitemap.xml sorainak száma nem egyezik az oldalak számával")
        ellenoriz(len(list(ki.rglob("index.html"))) == r["oldal"] - 1, "az index.html fájlok száma nem egyezik az oldalak számával (a térkép kezdőlapja a kiadás része, nem ez generálja)")
        ellenoriz("Sitemap:" in (ki / "robots.txt").read_text(encoding="utf-8"), "a robots.txt-ből hiányzik a Sitemap sor")
    # valódi adat: a fájlszám a Cloudflare-korlát alatt marad
    valodi = GYOKER / "terkep3d" / "data_varos" / "epuletek.json"
    if valodi.exists():
        db = sum(1 for p in json.loads(valodi.read_text(encoding="utf-8")) if F.kell_oldal(p))
        print(f"  a valódi adatból {db} épületoldal készülne")
        ellenoriz(db < 17000, f"túl sok épületoldal ({db}): a Cloudflare 20 000 fájlos korlátját közelíti")
        if db > 12000:
            figyelmeztet(f"{db} épületoldal: a 20 000 fájlos korlát 60%-a fölött vagyunk")
    return vege("teszt_felfedezo")


if __name__ == "__main__":
    raise SystemExit(main())
