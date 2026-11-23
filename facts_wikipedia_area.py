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

from common import http_json, building_key, write_facts
from area_common import CITY_BOX, BuildingIndex, adaptive_geosearch

CITY = len(sys.argv) > 1 and sys.argv[1] == "varos"      # py facts_wikipedia_area.py varos  -> the whole city
OSM = "data/varos/epuletek.geojson" if CITY else "data/belvaros_epuletek.geojson"
OUTPUT = "data/tenyek/wikipedia_terulet.csv"
CACHE = Path("data/cache")
API = "https://hu.wikipedia.org/w/api.php"
BOX = CITY_BOX if CITY else (47.490, 19.040, 47.513, 19.062)     # south, west, north, east
NEARBY_METER = 10
PAUSE_MP = 2
STREET_LIKE = re.compile(r"\b(utca|tér|tere|út|útja|körút|fasor|híd|rakpart|sétány|park|kerülete|"
                          r"városrész|negyed|állomás|megállóhely|metróvonal)\b|egyértelműsítő", re.I)


def geosearch(d0, w0, d1, w1):
    name_ = "wpgeo_" + hashlib.sha1(f"{d0}{w0}{d1}{w1}".encode()).hexdigest()[:12] + ".json"
    path_ = CACHE / name_
    if path_.exists():
        return json.loads(path_.read_text(encoding="utf-8"))
    url = API + "?" + urllib.parse.urlencode({
        "action": "query", "list": "geosearch", "gsbbox": f"{d1}|{w0}|{d0}|{w1}",
        "gslimit": 500, "gsnamespace": 0, "format": "json"})
    data_ = http_json(url)
    CACHE.mkdir(parents=True, exist_ok=True)
    path_.write_text(json.dumps(data_, ensure_ascii=False), encoding="utf-8")
    time.sleep(PAUSE_MP)
    return data_


def main():
    def search_(d0, w0, d1, w1):
        return geosearch(d0, w0, d1, w1).get("query", {}).get("geosearch", [])

    articles = {}
    for r in adaptive_geosearch(search_, BOX):
        articles[r["pageid"]] = (r["title"], r["lon"], r["lat"])
    print(f"Koordinátás cikkek a területen: {len(articles)}")

    with open(OSM, encoding="utf-8") as f:
        feats = [x for x in json.load(f)["features"] if x["properties"].get("tipus") != "roof"]
    index = BuildingIndex(feats)
    del feats

    hits = {}   # building -> [(mode, title)]
    inside_ = nearby = street = none = 0
    for pid, (address, x, y) in articles.items():
        building, mode = index.in_(x, y), "wikipedia_terulet"
        if building is None:
            if STREET_LIKE.search(address):
                street += 1
                continue
            building = index.nearby(x, y, NEARBY_METER)
            mode = "wikipedia_terulet_kozeli" if building else None
        if building is None:
            none += 1
            continue
        inside_ += mode == "wikipedia_terulet"
        nearby += mode == "wikipedia_terulet_kozeli"
        hits.setdefault(building_key(building["properties"]), []).append((mode, address))

    rows = []
    for (t, i), list_ in hits.items():
        list_.sort(key=lambda z: (z[0] != "wikipedia_terulet", z[1]))   # the more certain hit first
        for mode, address in list_[:3]:
            rows.append((t, i, "wikipedia", f"hu:{address}", mode, "földrajzi keresés"))
    write_facts(OUTPUT, rows)
    print(f"Épületbe esik: {inside_}, közeli (≤{NEARBY_METER} m): {nearby}, utca-jellegű közeli, kihagyva: {street}, nem párosítható: {none}")
    print(f"Épület, amelyhez cikk került: {len(hits)}")
    print(f"Mentve: {OUTPUT}")


if __name__ == "__main__":
    main()
