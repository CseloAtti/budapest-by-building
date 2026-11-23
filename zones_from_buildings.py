"""
zones_from_buildings.py - computes a candidate boundary from the buildings for the HOUSING ESTATES not found by zones_osm_candidates.py.

Run (in the project folder, after zones_osm_candidates.py):
    py zones_from_buildings.py

Method (for every missing housing estate):
  1. From the estate's name it forms a street name ("Gyakorló utcai lakótelep" -> Gyakorló...), and finds the buildings of 4+ storeys
     (or of 'apartments' type) whose address is on such a street, in the zone's district. These are the seeds.
  2. From the seeds it grows a connected patch of large buildings (neighbours within 70 m), within a radius estimated from the number of dwellings.
  3. Around the patch it draws a convex hull (+12 m); this is the candidate boundary.
Where the estate's name is not a street name (e.g. Békásmegyeri, Újhegyi, Havanna), there is no seed: those must be drawn by hand
(or the OSM search found them).

Output:
    data/zonak_jeloltek_epuletbol.geojson   the computed hulls (match = 'epuletbol')
    data/zonak_jeloltek_epuletbol.csv       per zone: seeds, the patch's building count, area (ha), remark
    data/zonak_hianyzo_vegso.csv            what is still missing even so
The hull is a rough candidate: it may extend to neighbouring large buildings. Fix it in the zone drawer.
"""
import csv
import json
import math
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

DATA = Path("data")
CITY = DATA / "varos"
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12,
         "XIII": 13, "XIV": 14, "XV": 15, "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20, "XXI": 21,
         "XXII": 22, "XXIII": 23}
NEIGHBOR_M = 70.0
HULL_M = 12.0
MIN_LEVEL = 4


def simplify(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return "".join(c for c in s if c.isalnum())


def level_number(v):
    try:
        return int(float(str(v).replace(",", ".").split(";")[0]))
    except (TypeError, ValueError):
        return None


def project(lon, lat):
    return ((lon - 19.05) * math.cos(math.radians(47.5)) * 111320.0, (lat - 47.5) * 110574.0)


def back(x, y):
    return (x / (math.cos(math.radians(47.5)) * 111320.0) + 19.05, y / 110574.0 + 47.5)


def convex_hull(points):
    points = sorted(set(points))
    if len(points) < 3:
        return points

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower_ = []
    for p in points:
        while len(lower_) >= 2 and cross(lower_[-2], lower_[-1], p) <= 0:
            lower_.pop()
        lower_.append(p)
    upper_ = []
    for p in reversed(points):
        while len(upper_) >= 2 and cross(upper_[-2], upper_[-1], p) <= 0:
            upper_.pop()
        upper_.append(p)
    return lower_[:-1] + upper_[:-1]


def area(ring_):
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring_, ring_[1:] + ring_[:1]))) / 2


def street_name_fragments(name_):
    """'Bécsi–Bojtár utcai lakótelep' -> ['becsi', 'bojtar']; it drops the words 'lakótelep' (housing estate), 'utcai', 'úti', 'téri'."""
    name_ = re.sub(r"\(.*?\)", " ", name_)
    name_ = re.sub(r"\b\d+\.?\s*(ütem|ph)\b.*", " ", name_, flags=re.I)
    name_ = re.sub(r"(lakótelep|rekonstrukciós|kibővített|városközpont)", " ", name_, flags=re.I)
    name_ = re.sub(r"\b(utcai|úti|téri|körúti|utca|út|tér|krt|kisérleti)\b", " ", name_, flags=re.I)
    parts = [r for r in re.split(r"[–\-\s]+", name_) if r]
    out = [simplify(r) for r in parts if len(simplify(r)) >= 4]
    return out


def read_buildings():
    g = json.load(open(CITY / "epuletek_vegleges.geojson", encoding="utf-8"))
    out = []
    for f in g["features"]:
        p = f["properties"]
        if p.get("resz"):
            continue
        geo = f["geometry"]
        if geo["type"] == "Polygon":
            ring_ = geo["coordinates"][0]
        elif geo["type"] == "MultiPolygon":
            ring_ = geo["coordinates"][0][0]
        else:
            continue
        pts = [project(x, y) for x, y in ring_]
        a = area(pts)
        sz = level_number(p.get("szintek"))
        large = (sz is not None and sz >= MIN_LEVEL) or (p.get("tipus") == "apartments" and a >= 400)
        cx = sum(x for x, _ in pts) / len(pts)
        cy = sum(y for _, y in pts) / len(pts)
        district_ = p.get("kerulet")
        try:
            district_ = int(district_)
        except (TypeError, ValueError):
            district_ = None
        out.append({"kulcs": (p.get("osm_tipus") or "way", str(p["id"])), "x": cx, "y": cy, "pts": pts,
                   "nagy": large, "kerulet": district_, "terulet": a})
    return out


def read_addresses():
    out = {}
    path_ = CITY / "osm_cimek.csv"
    if path_.exists():
        for r in csv.DictReader(open(path_, encoding="utf-8-sig"), delimiter=";"):
            out.setdefault((r["osm_tipus"], str(r["id"])), simplify(r["utca"]))
    return out


def dwellings(remark):
    m = re.search(r"(\d+)\s*lakás", remark or "")
    return int(m.group(1)) if m else None


def main():
    missing_path = DATA / "zonak_hianyzo.csv"
    if not missing_path.exists():
        sys.exit("Nincs data/zonak_hianyzo.csv - előbb futtasd a zones_osm_candidates.py-t.")
    missing = list(csv.DictReader(open(missing_path, encoding="utf-8-sig"), delimiter=";"))
    list_ = {r["id"]: r for r in csv.DictReader(open("forras/zona_lista.csv", encoding="utf-8-sig"), delimiter=";")}
    buildings = read_buildings()
    addresses = read_addresses()
    print("épület:", len(buildings), "| nagy (4+ szint):", sum(e["nagy"] for e in buildings), "| cím:", len(addresses))
    for e in buildings:
        e["utca"] = addresses.get(e["kulcs"], "")
    large_ = [e for e in buildings if e["nagy"]]
    grid = defaultdict(list)
    for i, e in enumerate(large_):
        grid[(int(e["x"] // NEIGHBOR_M), int(e["y"] // NEIGHBOR_M))].append(i)

    features, rows, left = [], [], []
    for h in missing:
        zid = h["id"]
        z = list_.get(zid)
        if not z or not zid.startswith("lt_"):
            left.append([zid, h["nev"], h["kerulet"], "nem lakótelep (kézzel)"])
            continue
        district = ROMAN.get(z["kerulet"].split("–")[0].strip())
        fragments = street_name_fragments(z["nev"])
        if not fragments:
            left.append([zid, h["nev"], h["kerulet"], "a név nem utcanév"])
            continue
        seeds = [i for i, e in enumerate(large_)
                 if (district is None or e["kerulet"] == district) and any(e["utca"].startswith(t) for t in fragments)]
        if not seeds:
            left.append([zid, h["nev"], h["kerulet"], "nincs mag (%s)" % ",".join(fragments)])
            continue
        xs = sorted(large_[i]["x"] for i in seeds)
        ys = sorted(large_[i]["y"] for i in seeds)
        kx, ky = xs[len(xs) // 2], ys[len(ys) // 2]
        count_ = dwellings(z["megjegyzes"])
        radius = 150 + 9 * math.sqrt(count_) if count_ else 400.0
        # of the seeds only those near the median (the far end of a long street should not be taken)
        seeds = [i for i in seeds if math.hypot(large_[i]["x"] - kx, large_[i]["y"] - ky) <= radius * 1.2]
        if not seeds:
            left.append([zid, h["nev"], h["kerulet"], "a magok szétszórtak"])
            continue
        seen = set(seeds)
        row = list(seeds)
        while row:
            i = row.pop()
            e = large_[i]
            cx, cy = int(e["x"] // NEIGHBOR_M), int(e["y"] // NEIGHBOR_M)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for j in grid.get((cx + dx, cy + dy), ()):
                        if j in seen:
                            continue
                        f = large_[j]
                        if (district is not None and f["kerulet"] != district):
                            continue
                        if math.hypot(f["x"] - e["x"], f["y"] - e["y"]) > NEIGHBOR_M:
                            continue
                        if math.hypot(f["x"] - kx, f["y"] - ky) > radius:
                            continue
                        seen.add(j)
                        row.append(j)
        points = []
        for i in seen:
            for (x, y) in large_[i]["pts"]:
                for k in range(8):
                    a = k * math.pi / 4
                    points.append((round(x + HULL_M * math.cos(a), 1), round(y + HULL_M * math.sin(a), 1)))
        hull = convex_hull(points)
        if len(hull) < 3:
            left.append([zid, h["nev"], h["kerulet"], "túl kevés épület"])
            continue
        ha = area(hull) / 10000
        coord = [list(back(x, y)) for x, y in hull]
        coord.append(coord[0])
        features.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [coord]}, "properties": {
            "id": zid, "nev": z["nev"], "tipus": z["tipus"], "kerulet": z["kerulet"],
            "ev_tol": int(z["ev_tol"]), "ev_ig": int(z["ev_ig"]), "allapot": z["allapot"],
            "forras": z["forras"], "egyezes": "epuletbol", "osm": "", "osm_nev": "",
            "mag_db": len(seeds), "folt_db": len(seen), "terulet_ha": round(ha, 1)}})
        rows.append([zid, z["nev"], z["kerulet"], len(seeds), len(seen), round(ha, 1), z["megjegyzes"]])

    json.dump({"type": "FeatureCollection", "features": features},
              open(DATA / "zonak_jeloltek_epuletbol.geojson", "w", encoding="utf-8"), ensure_ascii=False)
    with open(DATA / "zonak_jeloltek_epuletbol.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["id", "nev", "kerulet", "mag_db", "folt_db", "terulet_ha", "megjegyzes"])
        w.writerows(rows)
    with open(DATA / "zonak_hianyzo_vegso.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["id", "nev", "kerulet", "ok"])
        w.writerows(left)
    print("Épületből számolt burok: %d | még hiányzik: %d" % (len(features), len(left)))
    from collections import Counter
    for ok, n in Counter(m[3].split(" (")[0] for m in left).most_common():
        print("   hiány oka: %-28s %d" % (ok, n))


if __name__ == "__main__":
    main()
