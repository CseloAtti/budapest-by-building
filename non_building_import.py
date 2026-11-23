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

from common import write_facts

RAW = Path("data/nem_epulet_nyers.json")
BUILDINGS = Path("data/varos/epuletek.geojson")
DISTRICTS = Path("data/kerulethatarok.json")
MANUAL = Path("forras/kezi_epuletek.geojson")
FACTS = "data/tenyek/nem_epulet.csv"      # facts about the architect / year known from the OSM tags (source: osm)
LAT0, LON0 = 47.5, 19.05
KX, KY = 111320 * math.cos(math.radians(LAT0)), 110574
QUERY = ('[out:json][timeout:240];(nwr["man_made"="tower"][!"building"](47.33,18.90,47.65,19.35);'
              'nwr["tourism"="viewpoint"][!"building"]["man_made"!="tower"](47.33,18.90,47.65,19.35);'
              'nwr["historic"="monument"][!"building"](47.33,18.90,47.65,19.35););out geom tags qt;')
FIELDS = ["name", "height", "start_date", "architect", "wikidata", "wikipedia", "man_made", "tourism", "historic", "tower:type",
         "addr:street", "addr:housenumber", "wikimedia_commons", "opening_date"]


def download():
    req = urllib.request.Request("https://overpass-api.de/api/interpreter", data=("data=" + urllib.parse.quote(QUERY)).encode(),
                                 headers={"User-Agent": "budapest-by-building/0.1 (oktatasi projekt)"})
    with urllib.request.urlopen(req, timeout=300) as r:
        data_ = json.load(r)["elements"]
    out = []
    for e in data_:
        t = {k: e["tags"][k] for k in FIELDS if k in e.get("tags", {})}
        if e["type"] == "node":
            g = [e["lat"], e["lon"]]
        elif e["type"] == "way":
            g = [[p["lat"], p["lon"]] for p in e.get("geometry", [])]
        else:
            g = [[m.get("role"), [[p["lat"], p["lon"]] for p in m["geometry"]]] for m in e.get("members", []) if m.get("geometry")]
        out.append({"t": e["type"][0], "i": e["id"], "g": g, "tags": t})
    RAW.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"  letöltve: {len(out)} elem -> {RAW}")


def point_in_ring(x, y, ring_):
    inside = False
    for (x1, y1), (x2, y2) in zip(ring_, ring_[1:]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def area_m2(ring_):
    pts = [((x - LON0) * KX, (y - LAT0) * KY) for x, y in ring_]
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))) / 2


def main():
    if "--ujra" in sys.argv or not RAW.exists():
        download()
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    district_boundary = [(int(k), g) for k, rings in json.loads(DISTRICTS.read_text(encoding="utf-8")).items() for g in rings]
    # grid of the existing buildings for the overlap filter
    grid = {}
    for ft in json.loads(BUILDINGS.read_text(encoding="utf-8"))["features"]:
        g = ft["geometry"]
        for p in (g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]):
            xs = [c[0] for c in p[0]]
            ys = [c[1] for c in p[0]]
            for i in range(int(min(xs) / 0.001), int(max(xs) / 0.001) + 1):
                for j in range(int(min(ys) / 0.001), int(max(ys) / 0.001) + 1):
                    grid.setdefault((i, j), []).append(p[0])

    def existing_building_under(x, y):
        return any(point_in_ring(x, y, gy) for gy in grid.get((int(x / 0.001), int(y / 0.001)), ()))

    def district_(x, y):
        for kn, g in district_boundary:
            if point_in_ring(x, y, g):
                return kn
        return None

    old = json.loads(MANUAL.read_text(encoding="utf-8")) if MANUAL.exists() else {"type": "FeatureCollection", "features": []}
    remains = [f for f in old["features"] if not f["properties"].get("nem_epulet_auto")]
    manual_id = {(f["properties"].get("osm_tipus"), f["properties"].get("id")) for f in remains}
    new, skip, facts = [], {}, set()

    def not_(ok):
        skip[ok] = skip.get(ok, 0) + 1

    for e in raw:
        tg = e["tags"]
        type_ = {"w": "way", "r": "relation", "n": "node"}[e["t"]]
        tower = tg.get("man_made") == "tower"
        memorial = tg.get("historic") == "monument"
        lookout = tg.get("tourism") == "viewpoint"
        if (type_, e["i"]) in manual_id:
            not_("már kézzel felvett")
            continue
        if e["t"] == "n":
            if not (tower and tg.get("tower:type") == "observation" and tg.get("name")):
                not_("pont: nem megnevezett kilátó")
                continue
            la, lo = e["g"]
            dx, dy = 2 / KX, 2 / KY
            ring_ = [[lo - dx, la - dy], [lo + dx, la - dy], [lo + dx, la + dy], [lo - dx, la + dy], [lo - dx, la - dy]]
            point_based = True
        elif e["t"] == "w":
            ring_ = [[lo, la] for la, lo in e["g"]]
            if len(ring_) < 4 or ring_[0] != ring_[-1]:
                not_("nem zárt vonal")
                continue
            point_based = False
        else:
            not_("reláció (nincs egyszerű alapterület)")
            continue
        if not (tower or memorial):
            not_("csak 'viewpoint' címke (terasz, pad)")
            continue
        area_ = area_m2(ring_)
        if not point_based and not 8 <= area_ <= 300:
            not_("alapterület 8 m² alatt / 300 m² felett")
            continue
        cx = sum(p[0] for p in ring_[:-1]) / (len(ring_) - 1)
        cy = sum(p[1] for p in ring_[:-1]) / (len(ring_) - 1)
        if existing_building_under(cx, cy):
            not_("meglévő épület alapterületén belül")
            continue
        kn = district_(cx, cy)
        if not kn:
            not_("Budapesten kívül")
            continue
        try:
            height = float(str(tg.get("height", "")).replace(",", ".").split()[0])
            source = "height"
        except (ValueError, IndexError):
            height = 12.0 if tower else 4.0
            if lookout:
                height = 10.0
            source = "kezi"
        name_ = tg.get("name") or ("Kilátó" if lookout else "Torony" if tower else "Emlékmű")
        pr = {"id": e["i"], "osm_tipus": type_, "nev": name_, "tipus": "yes", "resz": False, "szintek": None, "magassag": height,
              "magassag_forras": source, "ev": None, "ev_forras": None, "wikidata": tg.get("wikidata"), "commons": tg.get("wikimedia_commons"),
              "kerulet": kn, "nem_epulet_auto": True}
        if point_based:
            pr["pont_alapu"] = True
        remark = f"OSM címke ({type_} {e['i']}: {name_})"
        if tg.get("architect"):
            facts.add((type_, e["i"], "tervezo", tg["architect"].strip(), "osm_cimke", remark))
        m = re.match(r"^(\d{4})", tg.get("start_date") or tg.get("opening_date") or "")
        if m and 1000 <= int(m.group(1)) <= 2030:
            facts.add((type_, e["i"], "ev", int(m.group(1)), "osm_cimke", remark))
        if source == "kezi":
            facts.add((type_, e["i"], "magassag", height, "kezi", f"becsült magasság ({name_}): {height:g} m"))
        new.append({"type": "Feature", "properties": pr, "geometry": {"type": "Polygon", "coordinates": [ring_]}})
    # the 'kezi' height of the earlier manually added items also only counts as a fact (assemble.py does not take over the height in the geojson)
    for f in remains:
        pr = f["properties"]
        if pr.get("magassag_forras") == "kezi" and pr.get("magassag"):
            facts.add((pr["osm_tipus"], pr["id"], "magassag", pr["magassag"], "kezi", f"kézzel megadott magasság ({pr.get('nev')})"))
    old["features"] = remains + new
    MANUAL.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    write_facts(FACTS, sorted(facts, key=lambda r: (r[0], r[1], r[2])))
    print(f"Tények (építész, év): {len(facts)} sor -> {FACTS}")
    print(f"Felvett nem-épület elem: {len(new)} (a kézzel felvettek maradtak: {len(remains)}) -> {MANUAL}")
    for k, v in sorted(skip.items(), key=lambda x: -x[1]):
        print(f"  kihagyva: {k}: {v}")


if __name__ == "__main__":
    main()
