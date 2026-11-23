"""The addresses of the OSM buildings (street, house number) -> data/osm_cimek.csv.

It collects the addresses from two sources, with a single Overpass query:
  1. the buildings themselves (way/relation) that carry addr:housenumber;
  2. standalone address points (node, addr:housenumber), which are assigned to the building's polygon
     (or to one vertex of its outline). In OSM many house numbers appear this way,
     so this significantly increases the number of buildings with an address.
The buildings' outlines need data/belvaros_epuletek.geojson (geojson_keszites.py)."""
import csv
import json
import time
import urllib.error
import urllib.parse
from pathlib import Path

from kozos import http_json, legkozelebbi_csucs_m, pont_poligonban, poligonok, teruletu_kozeppont

SZERVEREK = ["https://overpass.kumi.systems/api/interpreter",
             "https://overpass.private.coffee/api/interpreter",
             "https://overpass-api.de/api/interpreter"]
DEL, NYUGAT, ESZAK, KELET = 47.490, 19.040, 47.513, 19.062
KIMENET = "data/osm_cimek.csv"
EPULETEK = "data/belvaros_epuletek.geojson"
CELLA = 0.001
CSUCS_TAV_M = 3.0         # the entrance point is within this many metres of one of the building's vertices


def lekerdezes():
    bbox = f"{DEL},{NYUGAT},{ESZAK},{KELET}"
    q = (f'[out:json][timeout:90];(way["building"]["building"!="roof"]["addr:housenumber"]({bbox});'
         f'relation["building"]["building"!="roof"]["addr:housenumber"]({bbox}););out tags;'
         f'node["addr:housenumber"]["addr:street"]({bbox});out;')
    adat = None
    for kor in range(3):
        for szerver in SZERVEREK:
            print(f"Próbálkozás: {szerver}")
            try:
                adat = http_json(szerver + "?" + urllib.parse.urlencode({"data": q}), probak=1, timeout=120)
                if adat.get("elements") is not None and not adat.get("remark"):
                    break
            except (urllib.error.URLError, OSError, ValueError) as hiba:
                print(f"  nem sikerült: {type(hiba).__name__}")
            adat = None
        if adat:
            break
        time.sleep(10)
    if not adat:
        raise SystemExit("Egyik szerver sem válaszolt. Próbáld később újra.")
    return adat["elements"]


def epulet_index():
    """Grid for the point-building lookup: cell -> [(feature, small_area)]"""
    if not Path(EPULETEK).exists():
        print(f"Figyelem: nincs {EPULETEK}, a címpontokat nem tudom épülethez rendelni.")
        return None, []
    feats = json.load(open(EPULETEK, encoding="utf-8"))["features"]
    racs = {}
    for ft in feats:
        for p in poligonok(ft["geometry"]):
            xs = [c[0] for c in p[0]]
            ys = [c[1] for c in p[0]]
            for i in range(int(min(xs) / CELLA) - 0, int(max(xs) / CELLA) + 1):
                for j in range(int(min(ys) / CELLA) - 0, int(max(ys) / CELLA) + 1):
                    racs.setdefault((i, j), []).append(ft)
    return racs, feats


def pont_epulete(x, y, racs):
    """The building (feature) in which the point lies; if in none, the one whose vertex is nearest (<=3 m)."""
    jeloltek = {id(f): f for f in racs.get((int(x / CELLA), int(y / CELLA)), [])}
    bent = []
    for ft in jeloltek.values():
        for p in poligonok(ft["geometry"]):
            if pont_poligonban(x, y, p):
                bent.append((teruletu_kozeppont(p[0])[0], ft))
                break
    if bent:
        return min(bent, key=lambda a: a[0])[1]
    legjobb, tav = None, CSUCS_TAV_M
    szomszed = {}
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            for f in racs.get((int(x / CELLA) + di, int(y / CELLA) + dj), []):
                szomszed[id(f)] = f
    for ft in szomszed.values():
        for p in poligonok(ft["geometry"]):
            t = legkozelebbi_csucs_m(x, y, p[0])
            if t < tav:
                legjobb, tav = ft, t
    return legjobb


def main():
    elemek = lekerdezes()
    sorok = []
    for e in elemek:
        if e["type"] != "node":
            t = e.get("tags", {})
            sorok.append((e["type"], e["id"], t.get("addr:street", ""), t.get("addr:housenumber", "")))
    sajat = len(sorok)
    pontok = [e for e in elemek if e["type"] == "node"]
    racs, _ = epulet_index()
    hozzarendelt = nincs = 0
    if racs is not None:
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
    Path(KIMENET).parent.mkdir(exist_ok=True)
    with open(KIMENET, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["osm_tipus", "id", "utca", "hazszam"])
        w.writerows(sorok)
    print(f"Az épületeken maguktól szereplő címek: {sajat}")
    print(f"Címpontok: {len(pontok)}, ebből épülethez rendelve: {hozzarendelt}, épület nélkül: {nincs}")
    print(f"Címmel rendelkező épület: {len({(s[0], s[1]) for s in sorok})}")
    print(f"Mentve: {KIMENET} ({len(sorok)} sor)")


if __name__ == "__main__":
    main()
