"""Wikidata, by coordinate, through the normal API (not the query server)
-> data/tenyek/wikidata_terulet.csv   (the same output as that of facts_wikidata_area.py)

Steps: 1) geographic search per grid cell, 2) fetching the data of the elements,
3) keeping only the building-like elements (P31 -> P279 chain up to the 'building' class),
4) matching to our building outlines.
The content of Wikidata is CC0 (free to use).
"""
import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from common import http_json, building_key, write_facts
from area_common import CITY_BOX, BuildingIndex, adaptive_geosearch
from facts_wikidata import (API, CACHE, CLIENT, PAUSE_MP, label, in_batches, elements_id,
                             year_a_from_claims, fetch, wikipedia_article)

CITY = len(sys.argv) > 1 and sys.argv[1] == "varos"      # py facts_wikidata_api.py varos  -> the whole city
OSM = "data/varos/epuletek.geojson" if CITY else "data/belvaros_epuletek.geojson"
OUTPUT = "data/tenyek/wikidata_terulet.csv"
BOX = CITY_BOX if CITY else (47.490, 19.040, 47.513, 19.062)     # south, west, north, east
NEARBY_METER = 10
BUILDING = "Q41176"       # building
MAX_DEPTH = 7


def geosearch(d0, w0, d1, w1):
    name_ = "wdgeo_" + hashlib.sha1(f"{d0}{w0}{d1}{w1}".encode()).hexdigest()[:12] + ".json"
    path_ = CACHE / name_
    if path_.exists():
        return json.loads(path_.read_text(encoding="utf-8"))
    url = API + "?" + urllib.parse.urlencode({
        "action": "query", "list": "geosearch", "gsbbox": f"{d1}|{w0}|{d0}|{w1}",
        "gslimit": 500, "format": "json"})
    data_ = http_json(url)
    CACHE.mkdir(parents=True, exist_ok=True)
    path_.write_text(json.dumps(data_, ensure_ascii=False), encoding="utf-8")
    time.sleep(PAUSE_MP)
    return data_


def building_classes(classes):
    """Which class reaches the 'building' class along the subclass chain (P279)."""
    parents_, done = {}, set()
    ma = set(classes)
    for _ in range(MAX_DEPTH):
        new = [q for q in ma if q not in done]
        if not new:
            break
        for cs in in_batches(sorted(new), 50):
            for q, e in fetch(cs, "claims").get("entities", {}).items():
                parents_[q] = elements_id(e.get("claims", {}), "P279")
                done.add(q)
        ma = {p for q in new for p in parents_.get(q, [])}
    result_ = {}

    def reach(q, seen=()):
        if q == BUILDING:
            return True
        if q in result_:
            return result_[q]
        if q in seen:
            return False
        ok = any(reach(p, seen + (q,)) for p in parents_.get(q, []))
        result_[q] = ok
        return ok
    return {q for q in classes if reach(q)}


def main():
    # 1) geographic search
    def search_(d0, w0, d1, w1):
        return geosearch(d0, w0, d1, w1).get("query", {}).get("geosearch", [])

    hits = {}
    for r in adaptive_geosearch(search_, BOX):
        if str(r.get("title", "")).startswith("Q"):
            hits[r["title"]] = (r["lon"], r["lat"])
    print(f"Koordinátás Wikidata-elemek a területen: {len(hits)}")

    # 2) the data of the elements
    entities = {}
    for cs in in_batches(sorted(hits), 50):
        entities.update(fetch(cs, "claims|labels|sitelinks").get("entities", {}))

    # 3) only buildings, with a year of construction
    candidates = {}
    for q, e in entities.items():
        cl = e.get("claims", {})
        if year_a_from_claims(cl):
            candidates[q] = e
    classes = {c for e in candidates.values() for c in elements_id(e.get("claims", {}), "P31")}
    building_cl = building_classes(classes)
    buildings = {q: e for q, e in candidates.items()
                if any(c in building_cl for c in elements_id(e.get("claims", {}), "P31"))}
    print(f"Építési évvel: {len(candidates)}, ebből épület-jellegű: {len(buildings)}")

    secondary = set()
    for e in buildings.values():
        secondary.update(elements_id(e.get("claims", {}), "P84"))
        secondary.update(elements_id(e.get("claims", {}), "P149"))
    names = {}
    for cs in in_batches(sorted(secondary), 50):
        for q, e in fetch(cs, "labels").get("entities", {}).items():
            names[q] = label(e)

    # 4) matching
    with open(OSM, encoding="utf-8") as f:
        feats = [x for x in json.load(f)["features"] if x["properties"].get("tipus") != "roof"]
    index = BuildingIndex(feats)
    del feats
    best, inside_, nearby, none = {}, 0, 0, 0
    for q, e in buildings.items():
        x, y = hits[q]
        hit, mode = index.in_(x, y), "wikidata"
        if hit is None:
            hit = index.nearby(x, y, NEARBY_METER)
            mode = "wikidata_kozeli" if hit else None
        if hit is None:
            none += 1
            continue
        inside_ += mode == "wikidata"
        nearby += mode == "wikidata_kozeli"
        k = building_key(hit["properties"])
        previous = best.get(k)
        if previous is None or (mode == "wikidata" and previous[0] != "wikidata"):
            best[k] = (mode, q, e)

    rows = []
    for (t, i), (mode, q, e) in best.items():
        cl = e.get("claims", {})
        rows.append((t, i, "wikidata_id", q, mode, ""))
        if label(e):
            rows.append((t, i, "wikidata_nev", label(e), mode, q))
        if wikipedia_article(e):
            rows.append((t, i, "wikipedia", wikipedia_article(e), mode, q))
        rows.append((t, i, "ev", year_a_from_claims(cl), mode, f"{q}: P571"))
        architect = [names.get(x) for x in elements_id(cl, "P84") if names.get(x)]
        if architect:
            rows.append((t, i, "tervezo", ", ".join(architect), mode, q))
        style = [names.get(x) for x in elements_id(cl, "P149") if names.get(x)]
        if style:
            rows.append((t, i, "stilus", ", ".join(style), mode, q))
    write_facts(OUTPUT, rows)
    print(f"Épületbe esik: {inside_}, közeli (≤{NEARBY_METER} m): {nearby}, nem párosítható: {none}")
    print(f"Épület, amelyhez adat került: {len(best)}")
    print(f"Mentve: {OUTPUT}")


if __name__ == "__main__":
    main()
