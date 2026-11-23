"""
city_assembly.py - assembling the buildings of the whole of Budapest from the downloaded raw data.

Run (in the project folder, after budapest_pbf.py - or download_budapest.py - has finished):
    py city_assembly.py

Input:    data/budapest_nyers/*.json.gz     (budapest_pbf.py / download_budapest.py)
Output:   data/varos/epuletek.geojson       (OSM buildings, like belvaros_epuletek.geojson, but for the whole city)
          data/varos/reszek.geojson         (building:part elements)
          data/varos/osm_cimek.csv          (OSM addresses, like osm_cimek.csv)

It does NOT touch the existing inner-city files (data/belvaros_*.geojson, data/osm_cimek.csv).
The processing of the elements is the same as in geojson_keszites.py and download_addresses.py (year, height, parts,
composite buildings, addresses). Facts and manual corrections apply by id: py assemble.py varos
"""
import csv
import gzip
import json
import re
import time
from collections import Counter
from pathlib import Path

from download_addresses import CELL, point_building
from common import polygons

RAW = Path("data/budapest_nyers")
OUT = Path("data/varos")


# ---- the same rules as in geojson_keszites.py ----
def number(value):
    if value is None:
        return None
    t = re.search(r"\d+(?:[.,]\d+)?", value)
    return float(t.group().replace(",", ".")) if t else None


YEAR_LABELS = ["start_date", "building:start_date", "construction_date", "year_of_construction"]


def year_(tags):
    """Only an exact year: 1890, 1890-05, 1890-05-12. A range/decade/century ("1890s", "C19") is not an exact year."""
    for label in YEAR_LABELS:
        value = tags.get(label)
        if value:
            t = re.fullmatch(r"\s*(1[0-9]{3}|20[0-2][0-9])(?:-\d{1,2}(?:-\d{1,2})?)?\s*", value)
            if t:
                return int(t.group(1)), label
    return None, None


def height_(tags):
    h = number(tags.get("height"))
    if h:
        return h, "height"
    sz = number(tags.get("building:levels"))
    if sz:
        return sz * 3.0, "szintszam"
    return 15.0, "alapertelmezett"


def into_rings_append(sections):
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


def center(ring_):
    return [sum(p[0] for p in ring_) / len(ring_), sum(p[1] for p in ring_) / len(ring_)]


def point_in_ring(point, ring_):
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(ring_, ring_[1:]):
        if (y1 > y) != (y2 > y):
            if x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                inside = not inside
    return inside


def part_e(tags):
    return "building" not in tags and "building:part" in tags


def floating_e(tags):
    return any(number(tags.get(c)) for c in ("min_height", "building:min_level", "min_level"))


def feature_make(element, coordinates):
    tags = element["tags"]
    year, year_source = year_(tags)
    height, core_source = height_(tags)
    return {"type": "Feature",
            "properties": {"id": element["id"], "osm_tipus": element["type"], "nev": tags.get("name"),
                           "tipus": tags.get("building") or tags.get("building:part"), "resz": part_e(tags),
                           "szintek": number(tags.get("building:levels")), "magassag": height,
                           "magassag_forras": core_source, "ev": year, "ev_forras": year_source,
                           "wikidata": tags.get("wikidata"), "commons": tags.get("wikimedia_commons")},
            "geometry": {"type": "Polygon", "coordinates": coordinates}}


class Districts:
    """Which district a point is in (data/kerulethatarok.json, made by budapest_pbf.py)."""
    R = 0.002

    def __init__(self):
        path_ = Path("data/kerulethatarok.json")
        self.has = path_.exists()
        self.rings = []          # (district, ring, box)
        self.boundary = set()
        self.cache = {}
        if not self.has:
            print("  Figyelem: nincs data/kerulethatarok.json - futtasd újra: py budapest_pbf.py  (a kerület mező kimarad)")
            return
        for kn, rings in json.loads(path_.read_text(encoding="utf-8")).items():
            for g in rings:
                xs = [p[0] for p in g]
                ys = [p[1] for p in g]
                self.rings.append((int(kn), g, (min(xs), max(xs), min(ys), max(ys))))
                for (x1, y1), (x2, y2) in zip(g, g[1:]):
                    step = max(1, int(max(abs(x2 - x1), abs(y2 - y1)) / (self.R / 4)) + 1)
                    for q in range(step + 1):
                        cx = int((x1 + (x2 - x1) * q / step) // self.R)
                        cy = int((y1 + (y2 - y1) * q / step) // self.R)
                        for ax in (-1, 0, 1):
                            for ay in (-1, 0, 1):
                                self.boundary.add((cx + ax, cy + ay))

    def exact(self, x, y):
        for kn, g, d in self.rings:
            if d[0] <= x <= d[1] and d[2] <= y <= d[3] and point_in_ring((x, y), g):
                return kn
        return None

    def search_(self, x, y):
        c = (int(x // self.R), int(y // self.R))
        if c in self.boundary:
            return self.exact(x, y)
        if c not in self.cache:
            self.cache[c] = self.exact((c[0] + 0.5) * self.R, (c[1] + 0.5) * self.R)
        return self.cache[c]


def read_raw():
    """The elements of all the raw cell files, without duplicates by (type, id)."""
    elements = {}
    files = sorted(RAW.glob("*.json.gz"))
    if not files:
        raise SystemExit("Nincs nyers adat a data/budapest_nyers mappában. Előbb: py budapest_pbf.py")
    total = 0
    for path_ in files:
        with gzip.open(path_, "rt", encoding="utf-8") as f:
            for e in json.load(f):
                total += 1
                elements.setdefault((e["type"], e["id"]), e)
    print(f"  {len(files)} cellafájl, {total} elem, duplikátumok nélkül {len(elements)}")
    return list(elements.values())


def main():
    t0 = time.time()
    print("Nyers adatok beolvasása...")
    elements = read_raw()

    relation_members = {m["ref"] for e in elements if e["type"] == "relation"
                     for m in e.get("members", []) if m["type"] == "way" and "ref" in m}
    features, parts = [], []
    floating = 0
    for e in elements:
        if e["type"] == "node":
            continue
        tags = e.get("tags", {})
        if part_e(tags) and floating_e(tags):
            floating += 1
            continue
        target = parts if part_e(tags) else features
        if e["type"] == "way":
            if e["id"] in relation_members:
                continue
            points = e.get("geometry")
            if not points or len(points) < 3:
                continue
            ring_ = [[p["lon"], p["lat"]] for p in points]
            if ring_[0] != ring_[-1]:
                ring_.append(ring_[0])
            target.append(feature_make(e, [ring_]))
        else:
            outer, inner = [], []
            for m in e.get("members", []):
                if m["type"] != "way" or not m.get("geometry"):
                    continue
                line = [[p["lon"], p["lat"]] for p in m["geometry"]]
                (inner if m.get("role") == "inner" else outer).append(line)
            outer_rings = into_rings_append(outer)
            inner_rings = into_rings_append(inner)
            for k in outer_rings:
                holes = [b for b in inner_rings if point_in_ring(center(b), k)]
                target.append(feature_make(e, [k] + holes))

    district_ = Districts()
    if district_.has:
        count_ = Counter()
        for ft in features + parts:
            gy = ft["geometry"]["coordinates"][0]
            x, y = center(gy[:-1] if len(gy) > 1 else gy)
            kn = district_.search_(x, y)
            if kn:
                ft["properties"]["kerulet"] = kn
            count_[kn] += 1
        print(f"  kerülethez rendelve: {sum(v for k, v in count_.items() if k)}/{len(features) + len(parts)}")

    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "epuletek.geojson", "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, ensure_ascii=False)
    with open(OUT / "reszek.geojson", "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": parts}, f, ensure_ascii=False)
    print(f"  épületek: {len(features)}, épületrészek: {len(parts)} (elemelt rész kihagyva: {floating})")
    for source in ("height", "szintszam", "alapertelmezett"):
        print(f"  magasság forrása '{source}': {sum(1 for ft in features if ft['properties']['magassag_forras'] == source)}")
    print(f"  építési évvel: {sum(1 for ft in features if ft['properties']['ev'])}")

    # ---- addresses ----
    print("Címek hozzárendelése...")
    rows = []
    for e in elements:
        if e["type"] != "node":
            t = e.get("tags", {})
            if t.get("addr:housenumber"):
                rows.append((e["type"], e["id"], t.get("addr:street", ""), t.get("addr:housenumber", "")))
    own = len(rows)
    grid = {}
    for ft in features:
        for p in polygons(ft["geometry"]):
            xs = [c[0] for c in p[0]]
            ys = [c[1] for c in p[0]]
            for i in range(int(min(xs) / CELL), int(max(xs) / CELL) + 1):
                for j in range(int(min(ys) / CELL), int(max(ys) / CELL) + 1):
                    grid.setdefault((i, j), []).append(ft)
    points = [e for e in elements if e["type"] == "node"]
    assigned = none = 0
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
    with open(OUT / "osm_cimek.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["osm_tipus", "id", "utca", "hazszam"])
        w.writerows(rows)
    print(f"  az épületeken magukon szereplő címek: {own}")
    print(f"  címpontok: {len(points)}, épülethez rendelve: {assigned}, épület nélkül: {none}")
    print(f"  címmel rendelkező épület: {len({(s[0], s[1]) for s in rows})}")
    print(f"Kész: {OUT}  ({(time.time() - t0) / 60:.1f} perc)")


if __name__ == "__main__":
    main()
