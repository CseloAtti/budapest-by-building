"""
download_water.py - polygons of the Danube, the lakes and the parks from OpenStreetMap (for the 3D view's ground).

Run (in the project folder):   py download_water.py
Output:   data/viz_zold.json   (then run: py build_tiles.py)

Uses only the Python standard library. It tries the Overpass servers in turn.
The polygons are clipped to the displayed area, so the Danube does not get too large either.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

OVERPASS_URLS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

# the displayed area: slightly larger than the examined building area (south, west, north, east)
DEL, WEST, NORTH, EAST = 47.480, 19.025, 47.523, 19.075
BBOX = f"{DEL},{WEST},{NORTH},{EAST}"

QUERY = f"""
[out:json][timeout:180];
(
  way["natural"="water"]({BBOX});
  relation["natural"="water"]({BBOX});
  way["waterway"="riverbank"]({BBOX});
  relation["waterway"="riverbank"]({BBOX});
);
out geom;
(
  way["leisure"~"^(park|garden)$"]({BBOX});
  relation["leisure"~"^(park|garden)$"]({BBOX});
  way["landuse"~"^(grass|recreation_ground)$"]({BBOX});
  relation["landuse"~"^(grass|recreation_ground)$"]({BBOX});
);
out geom;
"""


def download():
    data_ = urllib.parse.urlencode({"data": QUERY}).encode("utf-8")
    for era in range(3):
        for url in OVERPASS_URLS:
            print(f"Próbálkozás: {url}")
            search_ = urllib.request.Request(url, data=data_, headers={"User-Agent": "budapest-by-building-tanulas/0.1"})
            try:
                with urllib.request.urlopen(search_, timeout=200) as answer:
                    result_ = json.load(answer)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error_:
                print(f"  Nem sikerült: {error_}")
                continue
            if result_.get("remark"):
                print("  A szerver figyelmeztet:", result_["remark"])
                continue
            print("  Letöltött elemek:", dict(Counter(e["type"] for e in result_["elements"])))
            return result_["elements"]
        print("Minden szerver hibázott, 20 másodperc várakozás...")
        time.sleep(20)
    raise SystemExit("Nem sikerült letölteni. Próbáld meg később.")


def into_rings_append(sections):
    """Joins fragmented outline segments into closed rings (like geojson_keszites.py)."""
    sections = [list(s) for s in sections if len(s) >= 2]
    rings = []
    while sections:
        ring_ = sections.pop(0)
        while ring_[0] != ring_[-1]:
            for i, s in enumerate(sections):
                if s[0] == ring_[-1]:
                    ring_.extend(s[1:])
                elif s[-1] == ring_[-1]:
                    ring_.extend(reversed(s[:-1]))
                elif s[-1] == ring_[0]:
                    ring_ = s[:-1] + ring_
                elif s[0] == ring_[0]:
                    ring_ = list(reversed(s[1:])) + ring_
                else:
                    continue
                sections.pop(i)
                break
            else:
                break
        if ring_[0] == ring_[-1] and len(ring_) >= 4:
            rings.append(ring_)
    return rings


def clip(ring_):
    """Sutherland-Hodgman: clips the polygon to the displayed rectangle. gyuru: [(lon, lat), ...] closed."""
    points = ring_[:-1] if ring_[0] == ring_[-1] else list(ring_)
    # (inside?, intersection point) with the four edges
    boundaries = [
        (lambda p: p[0] >= WEST, lambda a, b: (WEST, a[1] + (b[1] - a[1]) * (WEST - a[0]) / (b[0] - a[0]))),
        (lambda p: p[0] <= EAST, lambda a, b: (EAST, a[1] + (b[1] - a[1]) * (EAST - a[0]) / (b[0] - a[0]))),
        (lambda p: p[1] >= DEL, lambda a, b: (a[0] + (b[0] - a[0]) * (DEL - a[1]) / (b[1] - a[1]), DEL)),
        (lambda p: p[1] <= NORTH, lambda a, b: (a[0] + (b[0] - a[0]) * (NORTH - a[1]) / (b[1] - a[1]), NORTH)),
    ]
    for inside, cut_ in boundaries:
        if not points:
            return []
        out = []
        previous = points[-1]
        for p in points:
            if inside(p):
                if not inside(previous):
                    out.append(cut_(previous, p))
                out.append(p)
            elif inside(previous):
                out.append(cut_(previous, p))
            previous = p
        points = out
    return points if len(points) >= 3 else []


def point_in_ring(point, ring_):
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(ring_, ring_[1:] + ring_[:1]):
        if (y1 > y) != (y2 > y):
            if x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                inside = not inside
    return inside


def kind(tags):
    if tags.get("natural") == "water" or tags.get("waterway") == "riverbank":
        return "viz"
    return "park"


def main():
    elements = download()
    done = []
    out = Counter()
    for e in elements:
        tags = e.get("tags", {})
        if not tags:
            continue
        f = kind(tags)
        if e["type"] == "way":
            gy = [(p["lon"], p["lat"]) for p in e.get("geometry", [])]
            outer_ = [gy] if len(gy) >= 4 and gy[0] == gy[-1] else []
            inner_ = []
        else:
            outer_sz, inner_sz = [], []
            for m in e.get("members", []):
                if m["type"] != "way" or not m.get("geometry"):
                    continue
                sz = [(p["lon"], p["lat"]) for p in m["geometry"]]
                (inner_sz if m.get("role") == "inner" else outer_sz).append(sz)
            outer_, inner_ = into_rings_append(outer_sz), into_rings_append(inner_sz)
        if not outer_:
            out[f"{f}: nem zárható gyűrű"] += 1
            continue
        for k in outer_:
            cut = clip(k)
            if not cut:
                out[f"{f}: a területen kívül"] += 1
                continue
            rings = [cut + [cut[0]]]
            for b in inner_:
                if point_in_ring(b[0], k):
                    bv = clip(b)
                    if bv:
                        rings.append(bv + [bv[0]])
            done.append({"fajta": f, "gyuruk": [[list(p) for p in g] for g in rings]})
            out[f"{f}: kész"] += 1
    Path("data").mkdir(exist_ok=True)
    Path("data/viz_zold.json").write_text(json.dumps(done), encoding="utf-8")
    for k, v in sorted(out.items()):
        print(f"  {k}: {v}")
    print("Mentve: data/viz_zold.json  (most futtasd: py build_tiles.py)")


if __name__ == "__main__":
    main()
