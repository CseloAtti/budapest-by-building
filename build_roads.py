"""Streets and street names for the 3D view's toggleable layer -> terkep3d/data_varos/utak.json

Run (in the project folder):   py build_roads.py
What does it do? From Overpass it downloads Budapest's named public roads and promenades (in 3x3 parts, so the server can cope),
drops those outside the city based on the district boundaries (data/kerulethatarok.json), simplifies the lines, and saves them converted
into the 3D view's local metre coordinates (the same as in build_tiles.py: LAT0/LON0).
The raw download stays in data/utak_nyers.json (a rerun does not download it again; --ujra: downloads it again).
Output: {"v":1,"utak":[[name, class, [x0,z0,x1,z1,...]], ...]}
  class: 0 main road (motorway, expressway, main road), 1 collector road, 2 residential street / pedestrian street, 3 footpath, steps, cycle path
The 3D view switches the layer with the "Streets" button; a rebuild (build_tiles.py) does not touch this file.
"""
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from common import client_name

RAW = Path("data/utak_nyers.json")
DISTRICTS = Path("data/kerulethatarok.json")
OUTPUT = Path("terkep3d/data_varos/utak.json")
SERVERS = ["https://overpass.kumi.systems/api/interpreter",
             "https://overpass.private.coffee/api/interpreter",
             "https://overpass-api.de/api/interpreter"]
DEL, WEST, NORTH, EAST = 47.33, 18.90, 47.65, 19.35
LAT0, LON0 = 47.5015, 19.0515                      # the same as in build_tiles.py and app.js
KX, KZ = 111320 * math.cos(math.radians(LAT0)), 110574
CLASS = {"motorway": 0, "motorway_link": 0, "trunk": 0, "trunk_link": 0, "primary": 0, "primary_link": 0,
           "secondary": 1, "secondary_link": 1, "tertiary": 1, "tertiary_link": 1,
           "residential": 2, "unclassified": 2, "living_street": 2, "pedestrian": 2,
           "footway": 3, "path": 3, "steps": 3, "cycleway": 3, "track": 3}
SIMPLIFY_M = 2.0


def query(d, n, e, k):
    types_ = "|".join(CLASS)
    return f'[out:json][timeout:180];way["highway"~"^({types_})$"]["name"]({d},{n},{e},{k});out geom tags;'


def download():
    elements = {}
    COUNT = 3
    for i in range(COUNT):
        for j in range(COUNT):
            d = DEL + (NORTH - DEL) * i / COUNT
            e = DEL + (NORTH - DEL) * (i + 1) / COUNT
            n = WEST + (EAST - WEST) * j / COUNT
            k = WEST + (EAST - WEST) * (j + 1) / COUNT
            q = query(round(d, 4), round(n, 4), round(e, 4), round(k, 4))
            data_ = None
            for era in range(3):
                for sz in SERVERS:
                    print(f"[{i * COUNT + j + 1}/{COUNT * COUNT}] {sz.split('/')[2]}", flush=True)
                    try:
                        req = urllib.request.Request(sz, data=urllib.parse.urlencode({"data": q}).encode(), headers={"User-Agent": client_name()})
                        with urllib.request.urlopen(req, timeout=240) as r:
                            data_ = json.load(r)
                        if data_.get("elements") is not None and not data_.get("remark"):
                            break
                    except Exception as error_:
                        print(f"  nem sikerült: {type(error_).__name__}", flush=True)
                    data_ = None
                if data_:
                    break
                time.sleep(15)
            if not data_:
                raise SystemExit("Egyik szerver sem válaszolt. Próbáld később újra.")
            for el in data_["elements"]:
                elements[el["id"]] = {"n": el["tags"]["name"], "h": el["tags"]["highway"], "g": [[p["lon"], p["lat"]] for p in el.get("geometry", [])]}
            print(f"  eddig {len(elements)} út", flush=True)
            time.sleep(5)
    return list(elements.values())


def in_ring(x, y, g):
    be = False
    j = len(g) - 1
    for i in range(len(g)):
        xi, yi = g[i]
        xj, yj = g[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            be = not be
        j = i
    return be


def in_city(rings):
    def f(x, y):
        for g, (x0, x1, y0, y1) in rings:
            if x0 <= x <= x1 and y0 <= y <= y1 and in_ring(x, y, g):
                return True
        return False
    return f


def dp(points, from_):
    """Douglas-Peucker (iterative)."""
    if len(points) < 3:
        return points
    hold = [False] * len(points)
    hold[0] = hold[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = points[a], points[b]
        dx, dy = bx - ax, by - ay
        h2 = dx * dx + dy * dy
        legt, aerial = -1.0, -1
        for i in range(a + 1, b):
            px, py = points[i]
            if h2 == 0:
                t = math.hypot(px - ax, py - ay)
            else:
                u = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / h2))
                t = math.hypot(px - (ax + u * dx), py - (ay + u * dy))
            if t > legt:
                legt, aerial = t, i
        if legt > from_:
            hold[aerial] = True
            stack.append((a, aerial))
            stack.append((aerial, b))
    return [p for p, t in zip(points, hold) if t]


def main():
    if "--ujra" in sys.argv or not RAW.exists():
        elements = download()
        RAW.parent.mkdir(exist_ok=True)
        RAW.write_text(json.dumps(elements), encoding="utf-8")
    else:
        elements = json.loads(RAW.read_text(encoding="utf-8"))
        print(f"Nyers adat: {len(elements)} út ({RAW})")
    rings = []
    for gy in json.loads(DISTRICTS.read_text(encoding="utf-8")).values():
        for g in gy:
            xs = [p[0] for p in g]
            ys = [p[1] for p in g]
            rings.append((g, (min(xs), max(xs), min(ys), max(ys))))
    inside = in_city(rings)
    out = []
    for el in elements:
        g = el["g"]
        if len(g) < 2:
            continue
        # it is within the city if its start, middle or end point is in one of the districts
        if not any(inside(*g[i]) for i in {0, len(g) // 2, len(g) - 1}):
            continue
        m = [((x - LON0) * KX, -(y - LAT0) * KZ) for x, y in g]
        m = dp(m, SIMPLIFY_M)
        flat = []
        for x, z in m:
            flat += [round(x), round(z)]
        out.append([el["n"], CLASS.get(el["h"], 2), flat])
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({"v": 1, "utak": out}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    count_ = [0, 0, 0, 0]
    for u in out:
        count_[u[1]] += 1
    print(f"Kész: {len(out)} út (főút {count_[0]}, gyűjtő {count_[1]}, utca {count_[2]}, gyalogút {count_[3]}) -> {OUTPUT} ({OUTPUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
