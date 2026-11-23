#!/usr/bin/env python3
"""Finding building geometries drawn on top of each other (duplicates) across the whole city.

Run:  py duplicate_finder.py [varos]

What it finds is APPENDED to the end of forras/duplikatumok.csv (an existing row is never rewritten or deleted):
  mod=gyuru  - one outline of the same OSM element lies inside another outline of it (same id) -> the inner outline is deleted,
               no data is lost (same element).
  mod=elem   - two different OSM elements overlap each other: the deleted element's facts (Legenda, Wikipedia, Budapest100, OENY ...) go to the
               kept one, and whichever of its OSM properties the kept one lacks, it takes over.
  alkalmaz   - 'igen' (yes): assemble.py applies it; empty: only marked, it stays on the map (you decide, change it to 'igen').
Pure Python, nothing needs to be installed."""
import csv, json, math, sys
from collections import defaultdict
from pathlib import Path

city = sys.argv[1] if len(sys.argv) > 1 else "varos"
OSM = Path("data") / city / "epuletek.geojson"
EXCLUDED = Path("forras/kizart_epuletek.csv")
OUTPUT = Path("forras/duplikatumok.csv")
COLUMNS = ["mod", "torolt_tipus", "torolt_id", "torolt_gyuru_pontok", "megtartott_tipus", "megtartott_id", "alkalmaz", "megjegyzes"]
KX = 111000 * math.cos(math.radians(47.5)); KY = 111000
AUTO_RATIO = 0.85      # the smaller/larger area is more than this -> the same building twice
COVERAGE = 0.90         # this fraction of the smaller one's points lies within the larger one's solid part


def area_(r):
    return abs(sum(r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1] for i in range(len(r) - 1))) / 2


def in_(x, y, r):
    be = False
    j = len(r) - 1
    for i in range(len(r)):
        xi, yi = r[i]; xj, yj = r[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            be = not be
        j = i
    return be


def compressed(f, x, y):
    if not in_(x, y, f["gy"][0]):
        return False
    return not any(in_(x, y, h) for h in f["gy"][1:])


def main():
    exclude = set()
    if EXCLUDED.exists():
        for r in csv.DictReader(open(EXCLUDED, encoding="utf-8-sig", newline=""), delimiter=";"):
            if (r.get("id") or "").strip().isdigit():
                exclude.add(((r.get("osm_tipus") or "way").strip(), int(r["id"])))
    F = []
    for ft in json.load(open(OSM, encoding="utf-8"))["features"]:
        p = ft["properties"]
        if p.get("tipus") == "roof" or p.get("resz"):
            continue
        k = (p.get("osm_tipus") or "way", int(p["id"]))
        if k in exclude:
            continue
        gy = [[(x * KX, y * KY) for x, y in r] for r in ft["geometry"]["coordinates"]]
        xs = [a for a, _ in gy[0]]; ys = [b for _, b in gy[0]]
        o = area_(gy[0]) - sum(area_(h) for h in gy[1:])
        F.append(dict(i=len(F), k=k, p=p, gy=gy, ar=o, bb=(min(xs), max(xs), min(ys), max(ys))))
    print(f"{len(F)} épület-körvonal vizsgálata …")
    CELL = 60.0
    grid = defaultdict(list)
    for f in F:
        a, b, c, d = f["bb"]
        for i in range(int(a // CELL), int(b // CELL) + 1):
            for j in range(int(c // CELL), int(d // CELL) + 1):
                grid[(i, j)].append(f["i"])
    candidates = set()
    for v in grid.values():
        for x in range(len(v)):
            for y in range(x + 1, len(v)):
                candidates.add((v[x], v[y]))
    found = []
    for a, b in candidates:
        A, B = F[a], F[b]
        ba, bb = A["bb"], B["bb"]
        if min(ba[1], bb[1]) - max(ba[0], bb[0]) <= 0 or min(ba[3], bb[3]) - max(ba[2], bb[2]) <= 0:
            continue
        small, large = (A, B) if A["ar"] <= B["ar"] else (B, A)
        if small["ar"] < 4:
            continue
        sb = small["bb"]
        step = max(1.0, math.sqrt(small["ar"]) / 14)
        points = []
        x = sb[0] + step / 2
        while x < sb[1]:
            y = sb[2] + step / 2
            while y < sb[3]:
                if compressed(small, x, y):
                    points.append((x, y))
                y += step
            x += step
        if len(points) < 3:
            continue
        ratio = sum(1 for x, y in points if compressed(large, x, y)) / len(points)
        if ratio >= 0.5:
            found.append((ratio, small, large))

    def point(f):
        return len(f["gy"][0])

    def accuracy(p):
        return sum(1 for m in ("nev", "wikidata", "commons") if p.get(m)) + (0 if p.get("tipus") in (None, "yes") else 0.5)

    rows = []
    for ratio, small, large in sorted(found, key=lambda t: -t[0]):
        similar = small["ar"] / large["ar"]
        if small["k"] == large["k"]:
            if ratio >= COVERAGE:
                rows.append(dict(mod="gyuru", torolt_tipus=small["k"][0], torolt_id=small["k"][1], torolt_gyuru_pontok=point(small),
                                  megtartott_tipus=large["k"][0], megtartott_id=large["k"][1], alkalmaz="igen",
                                  megjegyzes=f"azonos elem egymásba ágyazott körvonala ({small['ar']:.0f} m² a {large['ar']:.0f} m²-ben)"))
            continue
        auto = ratio >= COVERAGE and similar >= AUTO_RATIO
        t, m = (small, large)
        if auto and accuracy(small["p"]) > accuracy(large["p"]):
            t, m = large, small       # the one with richer data stays
        rows.append(dict(mod="elem", torolt_tipus=t["k"][0], torolt_id=t["k"][1], torolt_gyuru_pontok="",
                          megtartott_tipus=m["k"][0], megtartott_id=m["k"][1], alkalmaz="igen" if auto else "",
                          megjegyzes=("azonos alakú, kétszer berajzolva" if auto else
                                      f"kisebb ({small['ar']:.0f} m²) teljesen a nagyobbon belül ({large['ar']:.0f} m²) – ellenőrizendő: ha tényleg külön épület, hagyd üresen")
                                     + f"; {t['p'].get('tipus')}→{m['p'].get('tipus')}"))
    existing = set()
    if OUTPUT.exists():
        for r in csv.DictReader(open(OUTPUT, encoding="utf-8-sig", newline=""), delimiter=";"):
            existing.add((r["mod"], r["torolt_tipus"], str(r["torolt_id"]), str(r.get("torolt_gyuru_pontok") or "")))
    new = [r for r in rows if (r["mod"], r["torolt_tipus"], str(r["torolt_id"]), str(r["torolt_gyuru_pontok"])) not in existing]
    if new:
        has = OUTPUT.exists()
        with open(OUTPUT, "a", encoding="utf-8-sig" if not has else "utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS, delimiter=";")
            if not has:
                w.writeheader()
            w.writerows(new)
    print(f"Talált átfedés: {len(rows)}; új sor a {OUTPUT}-ben: {len(new)} (ebből 'igen': {sum(1 for r in new if r['alkalmaz'] == 'igen')})")


main()
