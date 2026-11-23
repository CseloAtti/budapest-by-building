"""Adding structures tagged as non-buildings (towers, lookouts, memorials) to the map.

In OSM lookouts, towers and memorials are often tagged not 'building' but man_made=tower / tourism=viewpoint / historic=monument,
so city_assembly.py leaves them out. This script puts them into the existing manual building list
(forras/kezi_epuletek.geojson) - it does not touch the other data, and assemble.py skips the already existing keys anyway.

Run:  py non_building_import.py            (downloads the raw data from Overpass: data/nem_epulet_nyers.json, if it does not exist yet)
      py non_building_import.py --ujra     (downloads the raw data again)
Input:   data/nem_epulet_nyers.json (Overpass), data/varos/epuletek.geojson (overlap filter), data/kerulethatarok.json
Output:  forras/kezi_epuletek.geojson - the earlier, manually added items STAY; the script's own items are marked 'nem_epulet_auto': true,
         and are rebuilt on every run. Manual refinement: delete the mark and the item stays.

Rules (in practice most of the 800+ hits are transmission-tower points and bench-"lookout" points - these are not buildings):
  - a polygon element (way / relation) is needed, between 8 m² and 300 m²; larger ones are squares, rocks (e.g. Erzsébet Rock)
  - a polygon with only 'tourism=viewpoint' (without a tower) is a viewing terrace/bench: left out
  - as points we take only named 'tower:type=observation' lookouts (with an estimated 4x4 m footprint, 'pont_alapu': true)
  - where the element's centre lies within an existing building's footprint, it is left out (it is already there as a building)
  - only elements falling in the Budapest districts
Height: the 'height' tag, otherwise tower 12 m, memorial 4 m, lookout 10 m.
"""
import json
import math
import sys
import urllib.parse
import re
import urllib.request
from pathlib import Path

from common import tenyek_irasa

NYERS = Path("data/nem_epulet_nyers.json")
EPULETEK = Path("data/varos/epuletek.geojson")
KERULETEK = Path("data/kerulethatarok.json")
KEZI = Path("forras/kezi_epuletek.geojson")
TENYEK = "data/tenyek/nem_epulet.csv"      # facts about the architect / year known from the OSM tags (source: osm)
LAT0, LON0 = 47.5, 19.05
KX, KY = 111320 * math.cos(math.radians(LAT0)), 110574
LEKERDEZES = ('[out:json][timeout:240];(nwr["man_made"="tower"][!"building"](47.33,18.90,47.65,19.35);'
              'nwr["tourism"="viewpoint"][!"building"]["man_made"!="tower"](47.33,18.90,47.65,19.35);'
              'nwr["historic"="monument"][!"building"](47.33,18.90,47.65,19.35););out geom tags qt;')
MEZOK = ["name", "height", "start_date", "architect", "wikidata", "wikipedia", "man_made", "tourism", "historic", "tower:type",
         "addr:street", "addr:housenumber", "wikimedia_commons", "opening_date"]


def letoltes():
    req = urllib.request.Request("https://overpass-api.de/api/interpreter", data=("data=" + urllib.parse.quote(LEKERDEZES)).encode(),
                                 headers={"User-Agent": "budapest-by-building/0.1 (oktatasi projekt)"})
    with urllib.request.urlopen(req, timeout=300) as r:
        adat = json.load(r)["elements"]
    ki = []
    for e in adat:
        t = {k: e["tags"][k] for k in MEZOK if k in e.get("tags", {})}
        if e["type"] == "node":
            g = [e["lat"], e["lon"]]
        elif e["type"] == "way":
            g = [[p["lat"], p["lon"]] for p in e.get("geometry", [])]
        else:
            g = [[m.get("role"), [[p["lat"], p["lon"]] for p in m["geometry"]]] for m in e.get("members", []) if m.get("geometry")]
        ki.append({"t": e["type"][0], "i": e["id"], "g": g, "tags": t})
    NYERS.write_text(json.dumps(ki, ensure_ascii=False), encoding="utf-8")
    print(f"  letöltve: {len(ki)} elem -> {NYERS}")


def pont_gyuruben(x, y, gyuru):
    bent = False
    for (x1, y1), (x2, y2) in zip(gyuru, gyuru[1:]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            bent = not bent
    return bent


def terulet_m2(gyuru):
    pts = [((x - LON0) * KX, (y - LAT0) * KY) for x, y in gyuru]
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))) / 2


def main():
    if "--ujra" in sys.argv or not NYERS.exists():
        letoltes()
    nyers = json.loads(NYERS.read_text(encoding="utf-8"))
    kerulethatar = [(int(k), g) for k, gyuruk in json.loads(KERULETEK.read_text(encoding="utf-8")).items() for g in gyuruk]
    # grid of the existing buildings for the overlap filter
    racs = {}
    for ft in json.loads(EPULETEK.read_text(encoding="utf-8"))["features"]:
        g = ft["geometry"]
        for p in (g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]):
            xs = [c[0] for c in p[0]]
            ys = [c[1] for c in p[0]]
            for i in range(int(min(xs) / 0.001), int(max(xs) / 0.001) + 1):
                for j in range(int(min(ys) / 0.001), int(max(ys) / 0.001) + 1):
                    racs.setdefault((i, j), []).append(p[0])

    def meglevo_epulet_alatt(x, y):
        return any(pont_gyuruben(x, y, gy) for gy in racs.get((int(x / 0.001), int(y / 0.001)), ()))

    def kerulet(x, y):
        for kn, g in kerulethatar:
            if pont_gyuruben(x, y, g):
                return kn
        return None

    regi = json.loads(KEZI.read_text(encoding="utf-8")) if KEZI.exists() else {"type": "FeatureCollection", "features": []}
    marad = [f for f in regi["features"] if not f["properties"].get("nem_epulet_auto")]
    kezi_azon = {(f["properties"].get("osm_tipus"), f["properties"].get("id")) for f in marad}
    uj, kihagy, tenyek = [], {}, set()

    def nem(ok):
        kihagy[ok] = kihagy.get(ok, 0) + 1

    for e in nyers:
        tg = e["tags"]
        tipus = {"w": "way", "r": "relation", "n": "node"}[e["t"]]
        torony = tg.get("man_made") == "tower"
        emlek = tg.get("historic") == "monument"
        kilato = tg.get("tourism") == "viewpoint"
        if (tipus, e["i"]) in kezi_azon:
            nem("már kézzel felvett")
            continue
        if e["t"] == "n":
            if not (torony and tg.get("tower:type") == "observation" and tg.get("name")):
                nem("pont: nem megnevezett kilátó")
                continue
            la, lo = e["g"]
            dx, dy = 2 / KX, 2 / KY
            gyuru = [[lo - dx, la - dy], [lo + dx, la - dy], [lo + dx, la + dy], [lo - dx, la + dy], [lo - dx, la - dy]]
            pont_alapu = True
        elif e["t"] == "w":
            gyuru = [[lo, la] for la, lo in e["g"]]
            if len(gyuru) < 4 or gyuru[0] != gyuru[-1]:
                nem("nem zárt vonal")
                continue
            pont_alapu = False
        else:
            nem("reláció (nincs egyszerű alapterület)")
            continue
        if not (torony or emlek):
            nem("csak 'viewpoint' címke (terasz, pad)")
            continue
        ter = terulet_m2(gyuru)
        if not pont_alapu and not 8 <= ter <= 300:
            nem("alapterület 8 m² alatt / 300 m² felett")
            continue
        cx = sum(p[0] for p in gyuru[:-1]) / (len(gyuru) - 1)
        cy = sum(p[1] for p in gyuru[:-1]) / (len(gyuru) - 1)
        if meglevo_epulet_alatt(cx, cy):
            nem("meglévő épület alapterületén belül")
            continue
        kn = kerulet(cx, cy)
        if not kn:
            nem("Budapesten kívül")
            continue
        try:
            mag = float(str(tg.get("height", "")).replace(",", ".").split()[0])
            mforras = "height"
        except (ValueError, IndexError):
            mag = 12.0 if torony else 4.0
            if kilato:
                mag = 10.0
            mforras = "kezi"
        nev = tg.get("name") or ("Kilátó" if kilato else "Torony" if torony else "Emlékmű")
        pr = {"id": e["i"], "osm_tipus": tipus, "nev": nev, "tipus": "yes", "resz": False, "szintek": None, "magassag": mag,
              "magassag_forras": mforras, "ev": None, "ev_forras": None, "wikidata": tg.get("wikidata"), "commons": tg.get("wikimedia_commons"),
              "kerulet": kn, "nem_epulet_auto": True}
        if pont_alapu:
            pr["pont_alapu"] = True
        megj = f"OSM címke ({tipus} {e['i']}: {nev})"
        if tg.get("architect"):
            tenyek.add((tipus, e["i"], "tervezo", tg["architect"].strip(), "osm_cimke", megj))
        m = re.match(r"^(\d{4})", tg.get("start_date") or tg.get("opening_date") or "")
        if m and 1000 <= int(m.group(1)) <= 2030:
            tenyek.add((tipus, e["i"], "ev", int(m.group(1)), "osm_cimke", megj))
        if mforras == "kezi":
            tenyek.add((tipus, e["i"], "magassag", mag, "kezi", f"becsült magasság ({nev}): {mag:g} m"))
        uj.append({"type": "Feature", "properties": pr, "geometry": {"type": "Polygon", "coordinates": [gyuru]}})
    # the 'kezi' height of the earlier manually added items also only counts as a fact (assemble.py does not take over the height in the geojson)
    for f in marad:
        pr = f["properties"]
        if pr.get("magassag_forras") == "kezi" and pr.get("magassag"):
            tenyek.add((pr["osm_tipus"], pr["id"], "magassag", pr["magassag"], "kezi", f"kézzel megadott magasság ({pr.get('nev')})"))
    regi["features"] = marad + uj
    KEZI.write_text(json.dumps(regi, ensure_ascii=False), encoding="utf-8")
    tenyek_irasa(TENYEK, sorted(tenyek, key=lambda r: (r[0], r[1], r[2])))
    print(f"Tények (építész, év): {len(tenyek)} sor -> {TENYEK}")
    print(f"Felvett nem-épület elem: {len(uj)} (a kézzel felvettek maradtak: {len(marad)}) -> {KEZI}")
    for k, v in sorted(kihagy.items(), key=lambda x: -x[1]):
        print(f"  kihagyva: {k}: {v}")


if __name__ == "__main__":
    main()
