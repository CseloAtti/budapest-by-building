"""Hungarian Wikipedia articles in our area, by coordinate -> data/tenyek/wikipedia_terulet.csv

With Wikipedia's geographic search (GeoData) it lists the articles that have coordinates, and assigns them to our
building outlines: if the coordinate falls into the building, or is at most 10 m from it.
We leave out the nearby hits of streets, squares, bridges and similar articles.
The hits go into the popup; if one is not relevant, it can be removed on the Edit form.
"""
import hashlib
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

from kozos import http_json, kulcs, tenyek_irasa
from terulet_kozos import VAROS_DOBOZ, EpuletIndex, adaptiv_geokeres

VAROS = len(sys.argv) > 1 and sys.argv[1] == "varos"      # py tenyek_wikipedia_terulet.py varos  -> the whole city
OSM = "data/varos/epuletek.geojson" if VAROS else "data/belvaros_epuletek.geojson"
KIMENET = "data/tenyek/wikipedia_terulet.csv"
CACHE = Path("data/cache")
API = "https://hu.wikipedia.org/w/api.php"
DOBOZ = VAROS_DOBOZ if VAROS else (47.490, 19.040, 47.513, 19.062)     # south, west, north, east
KOZELI_METER = 10
SZUNET_MP = 2
UTCA_JELLEGU = re.compile(r"\b(utca|tér|tere|út|útja|körút|fasor|híd|rakpart|sétány|park|kerülete|"
                          r"városrész|negyed|állomás|megállóhely|metróvonal)\b|egyértelműsítő", re.I)


def geokeres(d0, w0, d1, w1):
    nev = "wpgeo_" + hashlib.sha1(f"{d0}{w0}{d1}{w1}".encode()).hexdigest()[:12] + ".json"
    ut = CACHE / nev
    if ut.exists():
        return json.loads(ut.read_text(encoding="utf-8"))
    url = API + "?" + urllib.parse.urlencode({
        "action": "query", "list": "geosearch", "gsbbox": f"{d1}|{w0}|{d0}|{w1}",
        "gslimit": 500, "gsnamespace": 0, "format": "json"})
    adat = http_json(url)
    CACHE.mkdir(parents=True, exist_ok=True)
    ut.write_text(json.dumps(adat, ensure_ascii=False), encoding="utf-8")
    time.sleep(SZUNET_MP)
    return adat


def main():
    def keres(d0, w0, d1, w1):
        return geokeres(d0, w0, d1, w1).get("query", {}).get("geosearch", [])

    cikkek = {}
    for r in adaptiv_geokeres(keres, DOBOZ):
        cikkek[r["pageid"]] = (r["title"], r["lon"], r["lat"])
    print(f"Koordinátás cikkek a területen: {len(cikkek)}")

    with open(OSM, encoding="utf-8") as f:
        feats = [x for x in json.load(f)["features"] if x["properties"].get("tipus") != "roof"]
    index = EpuletIndex(feats)
    del feats

    talalatok = {}   # building -> [(mode, title)]
    belul = kozeli = utca = nincs = 0
    for pid, (cim, x, y) in cikkek.items():
        epulet, mod = index.benne(x, y), "wikipedia_terulet"
        if epulet is None:
            if UTCA_JELLEGU.search(cim):
                utca += 1
                continue
            epulet = index.kozeli(x, y, KOZELI_METER)
            mod = "wikipedia_terulet_kozeli" if epulet else None
        if epulet is None:
            nincs += 1
            continue
        belul += mod == "wikipedia_terulet"
        kozeli += mod == "wikipedia_terulet_kozeli"
        talalatok.setdefault(kulcs(epulet["properties"]), []).append((mod, cim))

    sorok = []
    for (t, i), lista in talalatok.items():
        lista.sort(key=lambda z: (z[0] != "wikipedia_terulet", z[1]))   # the more certain hit first
        for mod, cim in lista[:3]:
            sorok.append((t, i, "wikipedia", f"hu:{cim}", mod, "földrajzi keresés"))
    tenyek_irasa(KIMENET, sorok)
    print(f"Épületbe esik: {belul}, közeli (≤{KOZELI_METER} m): {kozeli}, utca-jellegű közeli, kihagyva: {utca}, nem párosítható: {nincs}")
    print(f"Épület, amelyhez cikk került: {len(talalatok)}")
    print(f"Mentve: {KIMENET}")


if __name__ == "__main__":
    main()
