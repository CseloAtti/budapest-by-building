"""Magyar Wikipedia-cikkek a területünkön, koordináta alapján -> data/tenyek/wikipedia_terulet.csv

A Wikipedia földrajzi keresésével (GeoData) kilistázza a koordinátás cikkeket, és az épületkörvonalainkhoz
rendeli őket: ha a koordináta az épületbe esik, vagy legfeljebb 10 m-re van tőle.
Az utcák, terek, hidak és hasonló cikkek közeli találatait kihagyjuk.
A találatok bekerülnek a popupba; ha egy nem releváns, a Szerkesztés űrlapon kivehető.
"""
import hashlib
import json
import re
import time
import urllib.parse
from pathlib import Path

from kozos import (http_json, kulcs, legkozelebbi_csucs_m, pont_barmelyikben, poligonok,
                   tenyek_irasa)

OSM = "data/belvaros_epuletek.geojson"
KIMENET = "data/tenyek/wikipedia_terulet.csv"
CACHE = Path("data/cache")
API = "https://hu.wikipedia.org/w/api.php"
DEL, NYUGAT, ESZAK, KELET = 47.490, 19.040, 47.513, 19.062
RACS = 4
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
    cikkek = {}
    for i in range(RACS):
        for j in range(RACS):
            d0 = DEL + (ESZAK - DEL) * i / RACS
            d1 = DEL + (ESZAK - DEL) * (i + 1) / RACS
            w0 = NYUGAT + (KELET - NYUGAT) * j / RACS
            w1 = NYUGAT + (KELET - NYUGAT) * (j + 1) / RACS
            lista = geokeres(d0, w0, d1, w1).get("query", {}).get("geosearch", [])
            if len(lista) >= 500:
                print(f"Figyelem: a rács ({i},{j}) cellájában elérte a 500-as korlátot, adat hiányozhat.")
            for r in lista:
                cikkek[r["pageid"]] = (r["title"], r["lon"], r["lat"])
    print(f"Koordinátás cikkek a területen: {len(cikkek)}")

    with open(OSM, encoding="utf-8") as f:
        feats = [x for x in json.load(f)["features"] if x["properties"].get("tipus") != "roof"]
    polik = [(ft, poligonok(ft["geometry"])) for ft in feats]

    talalatok = {}   # épület -> [(mod, cím)]
    belul = kozeli = utca = nincs = 0
    for pid, (cim, x, y) in cikkek.items():
        epulet, mod = None, None
        for ft, pl in polik:
            if pl and pont_barmelyikben(x, y, pl):
                epulet, mod = ft, "wikipedia_terulet"
                break
        if epulet is None:
            if UTCA_JELLEGU.search(cim):
                utca += 1
                continue
            tav = KOZELI_METER
            for ft, pl in polik:
                if pl:
                    d = legkozelebbi_csucs_m(x, y, pl[0][0])
                    if d < tav:
                        epulet, tav = ft, d
            mod = "wikipedia_terulet_kozeli" if epulet else None
        if epulet is None:
            nincs += 1
            continue
        belul += mod == "wikipedia_terulet"
        kozeli += mod == "wikipedia_terulet_kozeli"
        talalatok.setdefault(kulcs(epulet["properties"]), []).append((mod, cim))

    sorok = []
    for (t, i), lista in talalatok.items():
        lista.sort(key=lambda z: (z[0] != "wikipedia_terulet", z[1]))   # a biztosabb találat elöl
        for mod, cim in lista[:3]:
            sorok.append((t, i, "wikipedia", f"hu:{cim}", mod, "földrajzi keresés"))
    tenyek_irasa(KIMENET, sorok)
    print(f"Épületbe esik: {belul}, közeli (≤{KOZELI_METER} m): {kozeli}, utca-jellegű közeli, kihagyva: {utca}, nem párosítható: {nincs}")
    print(f"Épület, amelyhez cikk került: {len(talalatok)}")
    print(f"Mentve: {KIMENET}")


if __name__ == "__main__":
    main()
