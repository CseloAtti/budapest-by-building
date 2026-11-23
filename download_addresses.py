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

from common import http_json, nearest_vertex_m, point_in_polygon, polygons, area_center

SERVERS = ["https://overpass.kumi.systems/api/interpreter",
             "https://overpass.private.coffee/api/interpreter",
             "https://overpass-api.de/api/interpreter"]
DEL, WEST, NORTH, EAST = 47.490, 19.040, 47.513, 19.062
OUTPUT = "data/osm_cimek.csv"
BUILDINGS = "data/belvaros_epuletek.geojson"
CELL = 0.001
VERTEX_DISTANCE_M = 3.0         # the entrance point is within this many metres of one of the building's vertices


def query():
    bbox = f"{DEL},{WEST},{NORTH},{EAST}"
    q = (f'[out:json][timeout:90];(way["building"]["building"!="roof"]["addr:housenumber"]({bbox});'
         f'relation["building"]["building"!="roof"]["addr:housenumber"]({bbox}););out tags;'
         f'node["addr:housenumber"]["addr:street"]({bbox});out;')
    data_ = None
    for era in range(3):
        for server in SERVERS:
            print(f"Próbálkozás: {server}")
            try:
                data_ = http_json(server + "?" + urllib.parse.urlencode({"data": q}), tries=1, timeout=120)
                if data_.get("elements") is not None and not data_.get("remark"):
                    break
            except (urllib.error.URLError, OSError, ValueError) as error_:
                print(f"  nem sikerült: {type(error_).__name__}")
            data_ = None
        if data_:
            break
        time.sleep(10)
    if not data_:
        raise SystemExit("Egyik szerver sem válaszolt. Próbáld később újra.")
    return data_["elements"]


def building_index():
    """Grid for the point-building lookup: cell -> [(feature, small_area)]"""
    if not Path(BUILDINGS).exists():
        print(f"Figyelem: nincs {BUILDINGS}, a címpontokat nem tudom épülethez rendelni.")
        return None, []
    feats = json.load(open(BUILDINGS, encoding="utf-8"))["features"]
    grid = {}
    for ft in feats:
        for p in polygons(ft["geometry"]):
            xs = [c[0] for c in p[0]]
            ys = [c[1] for c in p[0]]
            for i in range(int(min(xs) / CELL) - 0, int(max(xs) / CELL) + 1):
                for j in range(int(min(ys) / CELL) - 0, int(max(ys) / CELL) + 1):
                    grid.setdefault((i, j), []).append(ft)
    return grid, feats


def point_building(x, y, grid):
    """The building (feature) in which the point lies; if in none, the one whose vertex is nearest (<=3 m)."""
    candidates = {id(f): f for f in grid.get((int(x / CELL), int(y / CELL)), [])}
    inside = []
    for ft in candidates.values():
        for p in polygons(ft["geometry"]):
            if point_in_polygon(x, y, p):
                inside.append((area_center(p[0])[0], ft))
                break
    if inside:
        return min(inside, key=lambda a: a[0])[1]
    best, distance = None, VERTEX_DISTANCE_M
    neighbor = {}
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            for f in grid.get((int(x / CELL) + di, int(y / CELL) + dj), []):
                neighbor[id(f)] = f
    for ft in neighbor.values():
        for p in polygons(ft["geometry"]):
            t = nearest_vertex_m(x, y, p[0])
            if t < distance:
                best, distance = ft, t
    return best


def main():
    elements = query()
    rows = []
    for e in elements:
        if e["type"] != "node":
            t = e.get("tags", {})
            rows.append((e["type"], e["id"], t.get("addr:street", ""), t.get("addr:housenumber", "")))
    own = len(rows)
    points = [e for e in elements if e["type"] == "node"]
    grid, _ = building_index()
    assigned = none = 0
    if grid is not None:
        for n in points:
            t = n.get("tags", {})
            ft = point_building(n["lon"], n["lat"], grid)
            if ft is None:
                none += 1
                continue
            pr = ft["properties"]
            rows.append((pr["osm_tipus"], pr["id"], t.get("addr:street", ""), t.get("addr:housenumber", "")))
            assigned += 1
    rows = sorted(set(rows), key=lambda s: (s[0], s[1], s[2], s[3]))
    Path(OUTPUT).parent.mkdir(exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["osm_tipus", "id", "utca", "hazszam"])
        w.writerows(rows)
    print(f"Az épületeken maguktól szereplő címek: {own}")
    print(f"Címpontok: {len(points)}, ebből épülethez rendelve: {assigned}, épület nélkül: {none}")
    print(f"Címmel rendelkező épület: {len({(s[0], s[1]) for s in rows})}")
    print(f"Mentve: {OUTPUT} ({len(rows)} sor)")


if __name__ == "__main__":
    main()
