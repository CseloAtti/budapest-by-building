"""Shared helper functions for the fact-table system (this file does not need to be run)."""
import csv
import json
import math
import time
import urllib.error
import urllib.request
from pathlib import Path

HEADER = ["osm_tipus", "id", "mezo", "ertek", "forras", "megjegyzes", "lat", "lon"]


def building_key(pr):
    """The building's id: (osm_tipus, id). Old files have no osm_tipus: then it is way."""
    return (pr.get("osm_tipus") or "way", int(pr["id"]))


def write_facts(path_, rows):
    """sorok: a list of (osm_tipus, id, mezo, ertek, forras, megjegyzes). It can also be opened in Excel."""
    Path(path_).parent.mkdir(parents=True, exist_ok=True)
    with open(path_, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(HEADER)
        for s in rows:
            w.writerow(list(s) + [""] * (len(HEADER) - len(s)))


def read_facts(path_, base_source=None):
    """Returns the rows as dictionaries. A missing 'forras' field is filled in by alap_forras."""
    rows = []
    with open(path_, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if not (r.get("mezo") or "").strip():
                continue
            if not (r.get("forras") or "").strip():
                r["forras"] = base_source or Path(path_).stem
            rows.append(r)
    return rows


# ---- geometria ----
def polygons(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return geom["coordinates"]
    return []


def point_in_ring(x, y, ring_):
    inside = False
    for (x1, y1), (x2, y2) in zip(ring_, ring_[1:]):
        if (y1 > y) != (y2 > y):
            if x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                inside = not inside
    return inside


def point_in_polygon(x, y, rings):
    """gyuruk[0] is the outer outline, the others are courtyards (holes)."""
    if not point_in_ring(x, y, rings[0]):
        return False
    return not any(point_in_ring(x, y, hole) for hole in rings[1:])


def point_in_any(x, y, polys):
    return any(point_in_polygon(x, y, p) for p in polys)


def area_center(ring_):
    """(area m², x, y) from the outer outline."""
    kx = 111320 * math.cos(math.radians(ring_[0][1]))
    ky = 110540
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(ring_, ring_[1:]):
        c = x1 * y2 - x2 * y1
        a += c
        cx += (x1 + x2) * c
        cy += (y1 + y2) * c
    if abs(a) < 1e-18:
        xs = [p[0] for p in ring_]
        ys = [p[1] for p in ring_]
        return 0.0, sum(xs) / len(xs), sum(ys) / len(ys)
    return abs(a) / 2 * kx * ky, cx / (3 * a), cy / (3 * a)


def inner_point(polys):
    """A point that is certainly inside the building."""
    ring_ = polys[0][0]
    _, cx, cy = area_center(ring_)
    candidates = [(cx, cy)]
    for px, py in ring_[:-1]:
        candidates.append(((px + cx) / 2, (py + cy) / 2))
        candidates.append((px * 0.8 + cx * 0.2, py * 0.8 + cy * 0.2))
    for x, y in candidates:
        if point_in_any(x, y, polys):
            return x, y
    return cx, cy


def nearest_vertex_m(x, y, ring_):
    kx = 111320 * math.cos(math.radians(y))
    ky = 110540
    return min(math.hypot((px - x) * kx, (py - y) * ky) for px, py in ring_)


def client_name():
    """The client name given in the requests. If data/kapcsolat.txt exists (only on your machine, git does not
    upload it), its content is appended: Wikimedia then does not treat it as an anonymous bot."""
    name_ = "budapest-by-building/1.0 (tanulasi projekt)"
    path_ = Path("data/kapcsolat.txt")
    if path_.exists():
        extra = path_.read_text(encoding="utf-8").strip()
        if extra:
            name_ += " " + extra
    return name_


def http_json(url, header=None, tries=6, base_wait=60, timeout=120):
    """Fetching JSON; on a 429/5xx error it waits (as the server requests), then retries."""
    header = dict(header or {})
    header.setdefault("User-Agent", client_name())
    for p in range(1, tries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=header), timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as error_:
            if error_.code not in (429, 500, 502, 503, 504) or p == tries:
                raise
            v = base_wait
            try:
                v = max(v, int(error_.headers.get("Retry-After", 0)) + 5)
            except (TypeError, ValueError, AttributeError):
                pass
            print(f"  A szerver most lassít ({error_.code}), {p}/{tries}. próba. Várok {v} másodpercet...")
            time.sleep(v)
        except urllib.error.URLError as error_:
            if p == tries:
                raise
            print(f"  Hálózati hiba ({error_.reason}), {p}/{tries}. próba. Várok 30 másodpercet...")
            time.sleep(30)
