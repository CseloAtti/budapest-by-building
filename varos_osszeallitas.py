"""
varos_osszeallitas.py - A teljes Budapest épületeinek összeállítása a letöltött nyers adatokból.

Futtatás (a projekt mappájában, miután a budapest_pbf.py - vagy a budapest_letoltes.py - lefutott):
    py varos_osszeallitas.py

Bemenet:  data/budapest_nyers/*.json.gz     (budapest_pbf.py / budapest_letoltes.py)
Kimenet:  data/varos/epuletek.geojson       (OSM-épületek, mint a belvaros_epuletek.geojson, de az egész városra)
          data/varos/reszek.geojson         (building:part elemek)
          data/varos/osm_cimek.csv          (OSM-címek, mint az osm_cimek.csv)

A meglévő belvárosi fájlokhoz (data/belvaros_*.geojson, data/osm_cimek.csv) NEM nyúl.
Az elemek feldolgozása ugyanaz, mint a geojson_keszites.py-ban és a cimek_letoltes.py-ban (év, magasság, részek,
összetett épületek, címek). A tények és a kézi javítások azonosító szerint érvényesek: py osszeepit.py varos
"""
import csv
import gzip
import json
import re
import time
from collections import Counter
from pathlib import Path

from cimek_letoltes import CELLA, pont_epulete
from kozos import poligonok

NYERS = Path("data/budapest_nyers")
KI = Path("data/varos")


# ---- ugyanazok a szabályok, mint a geojson_keszites.py-ban ----
def szam(ertek):
    if ertek is None:
        return None
    t = re.search(r"\d+(?:[.,]\d+)?", ertek)
    return float(t.group().replace(",", ".")) if t else None


EV_CIMKEK = ["start_date", "building:start_date", "construction_date", "year_of_construction"]


def evszam(tags):
    """Csak pontos év: 1890, 1890-05, 1890-05-12. A tartomány/évtized/évszázad ("1890s", "C19") nem pontos év."""
    for cimke in EV_CIMKEK:
        ertek = tags.get(cimke)
        if ertek:
            t = re.fullmatch(r"\s*(1[0-9]{3}|20[0-2][0-9])(?:-\d{1,2}(?:-\d{1,2})?)?\s*", ertek)
            if t:
                return int(t.group(1)), cimke
    return None, None


def magassag(tags):
    h = szam(tags.get("height"))
    if h:
        return h, "height"
    sz = szam(tags.get("building:levels"))
    if sz:
        return sz * 3.0, "szintszam"
    return 15.0, "alapertelmezett"


def gyurukke_fuz(szakaszok):
    szakaszok = [list(s) for s in szakaszok if len(s) >= 2]
    gyuruk = []
    while szakaszok:
        gyuru = szakaszok.pop(0)
        while gyuru[0] != gyuru[-1]:
            for i, s in enumerate(szakaszok):
                if s[0] == gyuru[-1]:
                    gyuru.extend(s[1:])
                elif s[-1] == gyuru[-1]:
                    gyuru.extend(reversed(s[:-1]))
                elif s[-1] == gyuru[0]:
                    gyuru = s[:-1] + gyuru
                elif s[0] == gyuru[0]:
                    gyuru = list(reversed(s[1:])) + gyuru
                else:
                    continue
                szakaszok.pop(i)
                break
            else:
                break
        if gyuru[0] == gyuru[-1] and len(gyuru) >= 4:
            gyuruk.append(gyuru)
    return gyuruk


def kozeppont(gyuru):
    return [sum(p[0] for p in gyuru) / len(gyuru), sum(p[1] for p in gyuru) / len(gyuru)]


def pont_gyuruben(pont, gyuru):
    x, y = pont
    bent = False
    for (x1, y1), (x2, y2) in zip(gyuru, gyuru[1:]):
        if (y1 > y) != (y2 > y):
            if x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                bent = not bent
    return bent


def resz_e(tags):
    return "building" not in tags and "building:part" in tags


def lebego_e(tags):
    return any(szam(tags.get(c)) for c in ("min_height", "building:min_level", "min_level"))


def feature_keszit(elem, koordinatak):
    tags = elem["tags"]
    ev, ev_forras = evszam(tags)
    mag, mag_forras = magassag(tags)
    return {"type": "Feature",
            "properties": {"id": elem["id"], "osm_tipus": elem["type"], "nev": tags.get("name"),
                           "tipus": tags.get("building") or tags.get("building:part"), "resz": resz_e(tags),
                           "szintek": szam(tags.get("building:levels")), "magassag": mag,
                           "magassag_forras": mag_forras, "ev": ev, "ev_forras": ev_forras,
                           "wikidata": tags.get("wikidata"), "commons": tags.get("wikimedia_commons")},
            "geometry": {"type": "Polygon", "coordinates": koordinatak}}


class Keruletek:
    """Melyik kerületben van egy pont (data/kerulethatarok.json, a budapest_pbf.py készíti)."""
    R = 0.002

    def __init__(self):
        ut = Path("data/kerulethatarok.json")
        self.van = ut.exists()
        self.gyuruk = []          # (kerület, gyűrű, doboz)
        self.hatar = set()
        self.cache = {}
        if not self.van:
            print("  Figyelem: nincs data/kerulethatarok.json - futtasd újra: py budapest_pbf.py  (a kerület mező kimarad)")
            return
        for kn, gyuruk in json.loads(ut.read_text(encoding="utf-8")).items():
            for g in gyuruk:
                xs = [p[0] for p in g]
                ys = [p[1] for p in g]
                self.gyuruk.append((int(kn), g, (min(xs), max(xs), min(ys), max(ys))))
                for (x1, y1), (x2, y2) in zip(g, g[1:]):
                    lepes = max(1, int(max(abs(x2 - x1), abs(y2 - y1)) / (self.R / 4)) + 1)
                    for q in range(lepes + 1):
                        cx = int((x1 + (x2 - x1) * q / lepes) // self.R)
                        cy = int((y1 + (y2 - y1) * q / lepes) // self.R)
                        for ax in (-1, 0, 1):
                            for ay in (-1, 0, 1):
                                self.hatar.add((cx + ax, cy + ay))

    def pontos(self, x, y):
        for kn, g, d in self.gyuruk:
            if d[0] <= x <= d[1] and d[2] <= y <= d[3] and pont_gyuruben((x, y), g):
                return kn
        return None

    def keres(self, x, y):
        c = (int(x // self.R), int(y // self.R))
        if c in self.hatar:
            return self.pontos(x, y)
        if c not in self.cache:
            self.cache[c] = self.pontos((c[0] + 0.5) * self.R, (c[1] + 0.5) * self.R)
        return self.cache[c]


def nyers_beolvasasa():
    """Az összes nyers cellafájl elemei, a (típus, id) szerinti duplikátumok nélkül."""
    elemek = {}
    fajlok = sorted(NYERS.glob("*.json.gz"))
    if not fajlok:
        raise SystemExit("Nincs nyers adat a data/budapest_nyers mappában. Előbb: py budapest_pbf.py")
    ossz = 0
    for ut in fajlok:
        with gzip.open(ut, "rt", encoding="utf-8") as f:
            for e in json.load(f):
                ossz += 1
                elemek.setdefault((e["type"], e["id"]), e)
    print(f"  {len(fajlok)} cellafájl, {ossz} elem, duplikátumok nélkül {len(elemek)}")
    return list(elemek.values())


def main():
    t0 = time.time()
    print("Nyers adatok beolvasása...")
    elemek = nyers_beolvasasa()

    relacio_tagok = {m["ref"] for e in elemek if e["type"] == "relation"
                     for m in e.get("members", []) if m["type"] == "way" and "ref" in m}
    features, reszek = [], []
    lebego = 0
    for e in elemek:
        if e["type"] == "node":
            continue
        tags = e.get("tags", {})
        if resz_e(tags) and lebego_e(tags):
            lebego += 1
            continue
        cel = reszek if resz_e(tags) else features
        if e["type"] == "way":
            if e["id"] in relacio_tagok:
                continue
            pontok = e.get("geometry")
            if not pontok or len(pontok) < 3:
                continue
            gyuru = [[p["lon"], p["lat"]] for p in pontok]
            if gyuru[0] != gyuru[-1]:
                gyuru.append(gyuru[0])
            cel.append(feature_keszit(e, [gyuru]))
        else:
            kulso, belso = [], []
            for m in e.get("members", []):
                if m["type"] != "way" or not m.get("geometry"):
                    continue
                vonal = [[p["lon"], p["lat"]] for p in m["geometry"]]
                (belso if m.get("role") == "inner" else kulso).append(vonal)
            kulso_gyuruk = gyurukke_fuz(kulso)
            belso_gyuruk = gyurukke_fuz(belso)
            for k in kulso_gyuruk:
                lyukak = [b for b in belso_gyuruk if pont_gyuruben(kozeppont(b), k)]
                cel.append(feature_keszit(e, [k] + lyukak))

    kerulet = Keruletek()
    if kerulet.van:
        db = Counter()
        for ft in features + reszek:
            gy = ft["geometry"]["coordinates"][0]
            x, y = kozeppont(gy[:-1] if len(gy) > 1 else gy)
            kn = kerulet.keres(x, y)
            if kn:
                ft["properties"]["kerulet"] = kn
            db[kn] += 1
        print(f"  kerülethez rendelve: {sum(v for k, v in db.items() if k)}/{len(features) + len(reszek)}")

    KI.mkdir(parents=True, exist_ok=True)
    with open(KI / "epuletek.geojson", "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, ensure_ascii=False)
    with open(KI / "reszek.geojson", "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": reszek}, f, ensure_ascii=False)
    print(f"  épületek: {len(features)}, épületrészek: {len(reszek)} (elemelt rész kihagyva: {lebego})")
    for forras in ("height", "szintszam", "alapertelmezett"):
        print(f"  magasság forrása '{forras}': {sum(1 for ft in features if ft['properties']['magassag_forras'] == forras)}")
    print(f"  építési évvel: {sum(1 for ft in features if ft['properties']['ev'])}")

    # ---- címek ----
    print("Címek hozzárendelése...")
    sorok = []
    for e in elemek:
        if e["type"] != "node":
            t = e.get("tags", {})
            if t.get("addr:housenumber"):
                sorok.append((e["type"], e["id"], t.get("addr:street", ""), t.get("addr:housenumber", "")))
    sajat = len(sorok)
    racs = {}
    for ft in features:
        for p in poligonok(ft["geometry"]):
            xs = [c[0] for c in p[0]]
            ys = [c[1] for c in p[0]]
            for i in range(int(min(xs) / CELLA), int(max(xs) / CELLA) + 1):
                for j in range(int(min(ys) / CELLA), int(max(ys) / CELLA) + 1):
                    racs.setdefault((i, j), []).append(ft)
    pontok = [e for e in elemek if e["type"] == "node"]
    hozzarendelt = nincs = 0
    for n in pontok:
        t = n.get("tags", {})
        ft = pont_epulete(n["lon"], n["lat"], racs)
        if ft is None:
            nincs += 1
            continue
        pr = ft["properties"]
        sorok.append((pr["osm_tipus"], pr["id"], t.get("addr:street", ""), t.get("addr:housenumber", "")))
        hozzarendelt += 1
    sorok = sorted(set(sorok), key=lambda s: (s[0], s[1], s[2], s[3]))
    with open(KI / "osm_cimek.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["osm_tipus", "id", "utca", "hazszam"])
        w.writerows(sorok)
    print(f"  az épületeken magukon szereplő címek: {sajat}")
    print(f"  címpontok: {len(pontok)}, épülethez rendelve: {hozzarendelt}, épület nélkül: {nincs}")
    print(f"  címmel rendelkező épület: {len({(s[0], s[1]) for s in sorok})}")
    print(f"Kész: {KI}  ({(time.time() - t0) / 60:.1f} perc)")


if __name__ == "__main__":
    main()
