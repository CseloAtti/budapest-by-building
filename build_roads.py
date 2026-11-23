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

from common import kliens_nev

NYERS = Path("data/utak_nyers.json")
KERULETEK = Path("data/kerulethatarok.json")
KIMENET = Path("terkep3d/data_varos/utak.json")
SZERVEREK = ["https://overpass.kumi.systems/api/interpreter",
             "https://overpass.private.coffee/api/interpreter",
             "https://overpass-api.de/api/interpreter"]
DEL, NYUGAT, ESZAK, KELET = 47.33, 18.90, 47.65, 19.35
LAT0, LON0 = 47.5015, 19.0515                      # the same as in build_tiles.py and app.js
KX, KZ = 111320 * math.cos(math.radians(LAT0)), 110574
OSZTALY = {"motorway": 0, "motorway_link": 0, "trunk": 0, "trunk_link": 0, "primary": 0, "primary_link": 0,
           "secondary": 1, "secondary_link": 1, "tertiary": 1, "tertiary_link": 1,
           "residential": 2, "unclassified": 2, "living_street": 2, "pedestrian": 2,
           "footway": 3, "path": 3, "steps": 3, "cycleway": 3, "track": 3}
EGYSZERUSIT_M = 2.0


def lekerdezes(d, n, e, k):
    tipusok = "|".join(OSZTALY)
    return f'[out:json][timeout:180];way["highway"~"^({tipusok})$"]["name"]({d},{n},{e},{k});out geom tags;'


def letoltes():
    elemek = {}
    DB = 3
    for i in range(DB):
        for j in range(DB):
            d = DEL + (ESZAK - DEL) * i / DB
            e = DEL + (ESZAK - DEL) * (i + 1) / DB
            n = NYUGAT + (KELET - NYUGAT) * j / DB
            k = NYUGAT + (KELET - NYUGAT) * (j + 1) / DB
            q = lekerdezes(round(d, 4), round(n, 4), round(e, 4), round(k, 4))
            adat = None
            for kor in range(3):
                for sz in SZERVEREK:
                    print(f"[{i * DB + j + 1}/{DB * DB}] {sz.split('/')[2]}", flush=True)
                    try:
                        req = urllib.request.Request(sz, data=urllib.parse.urlencode({"data": q}).encode(), headers={"User-Agent": kliens_nev()})
                        with urllib.request.urlopen(req, timeout=240) as r:
                            adat = json.load(r)
                        if adat.get("elements") is not None and not adat.get("remark"):
                            break
                    except Exception as hiba:
                        print(f"  nem sikerült: {type(hiba).__name__}", flush=True)
                    adat = None
                if adat:
                    break
                time.sleep(15)
            if not adat:
                raise SystemExit("Egyik szerver sem válaszolt. Próbáld később újra.")
            for el in adat["elements"]:
                elemek[el["id"]] = {"n": el["tags"]["name"], "h": el["tags"]["highway"], "g": [[p["lon"], p["lat"]] for p in el.get("geometry", [])]}
            print(f"  eddig {len(elemek)} út", flush=True)
            time.sleep(5)
    return list(elemek.values())


def gyuruben(x, y, g):
    be = False
    j = len(g) - 1
    for i in range(len(g)):
        xi, yi = g[i]
        xj, yj = g[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            be = not be
        j = i
    return be


def varosban(gyuruk):
    def f(x, y):
        for g, (x0, x1, y0, y1) in gyuruk:
            if x0 <= x <= x1 and y0 <= y <= y1 and gyuruben(x, y, g):
                return True
        return False
    return f


def dp(pontok, tol):
    """Douglas-Peucker (iterative)."""
    if len(pontok) < 3:
        return pontok
    tart = [False] * len(pontok)
    tart[0] = tart[-1] = True
    verem = [(0, len(pontok) - 1)]
    while verem:
        a, b = verem.pop()
        (ax, ay), (bx, by) = pontok[a], pontok[b]
        dx, dy = bx - ax, by - ay
        h2 = dx * dx + dy * dy
        legt, legi = -1.0, -1
        for i in range(a + 1, b):
            px, py = pontok[i]
            if h2 == 0:
                t = math.hypot(px - ax, py - ay)
            else:
                u = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / h2))
                t = math.hypot(px - (ax + u * dx), py - (ay + u * dy))
            if t > legt:
                legt, legi = t, i
        if legt > tol:
            tart[legi] = True
            verem.append((a, legi))
            verem.append((legi, b))
    return [p for p, t in zip(pontok, tart) if t]


def main():
    if "--ujra" in sys.argv or not NYERS.exists():
        elemek = letoltes()
        NYERS.parent.mkdir(exist_ok=True)
        NYERS.write_text(json.dumps(elemek), encoding="utf-8")
    else:
        elemek = json.loads(NYERS.read_text(encoding="utf-8"))
        print(f"Nyers adat: {len(elemek)} út ({NYERS})")
    gyuruk = []
    for gy in json.loads(KERULETEK.read_text(encoding="utf-8")).values():
        for g in gy:
            xs = [p[0] for p in g]
            ys = [p[1] for p in g]
            gyuruk.append((g, (min(xs), max(xs), min(ys), max(ys))))
    bent = varosban(gyuruk)
    ki = []
    for el in elemek:
        g = el["g"]
        if len(g) < 2:
            continue
        # it is within the city if its start, middle or end point is in one of the districts
        if not any(bent(*g[i]) for i in {0, len(g) // 2, len(g) - 1}):
            continue
        m = [((x - LON0) * KX, -(y - LAT0) * KZ) for x, y in g]
        m = dp(m, EGYSZERUSIT_M)
        lapos = []
        for x, z in m:
            lapos += [round(x), round(z)]
        ki.append([el["n"], OSZTALY.get(el["h"], 2), lapos])
    KIMENET.parent.mkdir(parents=True, exist_ok=True)
    KIMENET.write_text(json.dumps({"v": 1, "utak": ki}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    db = [0, 0, 0, 0]
    for u in ki:
        db[u[1]] += 1
    print(f"Kész: {len(ki)} út (főút {db[0]}, gyűjtő {db[1]}, utca {db[2]}, gyalogút {db[3]}) -> {KIMENET} ({KIMENET.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
