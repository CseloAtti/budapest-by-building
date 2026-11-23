"""EUBUCCO (data/eubucco.geojson) -> data/tenyek/eubucco.csv
The height is mostly estimated by machine learning (a band of about ±4 m), so the source name is
"eubucco_becsles"; where it comes from the source data: "eubucco_forras"."""
import json
import sys
from collections import Counter, defaultdict

from common import (inner_point, building_key, point_in_any, polygons,
                   area_center, write_facts)

CITY = len(sys.argv) > 1 and sys.argv[1] == "varos"      # py facts_eubucco.py varos  -> the whole city
OSM = "data/varos/epuletek.geojson" if CITY else "data/belvaros_epuletek.geojson"
EUBUCCO = "data/eubucco_varos.geojson" if CITY else "data/eubucco.geojson"
OUTPUT = "data/tenyek/eubucco.csv"
CELL = 0.002  # degrees, the size of the grid used for the fast search


def cell(x, y):
    return int(x / CELL), int(y / CELL)


def main():
    try:
        f = open(EUBUCCO, encoding="utf-8")
    except FileNotFoundError:
        sys.exit(f"Nincs {EUBUCCO}. Készítsd el a QGIS-ben a HU11.parquet teljes exportjával (lásd a leírást).")
    with f:
        eub = json.load(f)["features"]
    with open(OSM, encoding="utf-8") as f:
        feats = [x for x in json.load(f)["features"] if x["properties"].get("tipus") != "roof"]
    print(f"EUBUCCO épületek: {len(eub)}, saját épületek: {len(feats)}")

    pieces, grid = [], defaultdict(list)
    for ft in eub:
        polys = polygons(ft["geometry"])
        if not polys:
            continue
        area_, cx, cy = area_center(polys[0][0])
        if not point_in_any(cx, cy, polys):
            cx, cy = inner_point(polys)
        d = {"p": ft["properties"], "polik": polys, "ter": area_, "x": cx, "y": cy}
        pieces.append(d)
        grid[cell(cx, cy)].append(d)

    rows, mode = [], Counter()
    for ft in feats:
        polys = polygons(ft["geometry"])
        if not polys:
            continue
        xs = [p[0] for p in polys[0][0]]
        ys = [p[1] for p in polys[0][0]]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        hit = []
        for i in range(int(x0 / CELL) - 1, int(x1 / CELL) + 2):
            for j in range(int(y0 / CELL) - 1, int(y1 / CELL) + 2):
                for d in grid.get((i, j), []):
                    if x0 <= d["x"] <= x1 and y0 <= d["y"] <= y1 and point_in_any(d["x"], d["y"], polys):
                        hit.append(d)
        how = "darabok_bennunk"
        if not hit:
            bx, by = inner_point(polys)
            ci, cj = cell(bx, by)
            for i in range(ci - 2, ci + 3):
                for j in range(cj - 2, cj + 3):
                    for d in grid.get((i, j), []):
                        if point_in_any(bx, by, d["polik"]):
                            hit.append(d)
            how = "mi_benne_vagyunk"
        if not hit:
            mode["nincs_par"] += 1
            continue
        mode[how] += 1
        e = max(hit, key=lambda z: z["ter"])["p"]
        t, i = building_key(ft["properties"])
        estimated = e.get("height_source") == 2
        F = "eubucco_becsles" if estimated else "eubucco_forras"
        rows += [(t, i, "eubucco_id", e.get("id"), F, f"{len(hit)} darab"),
                  (t, i, "eubucco_magassag_min", e.get("height_confidence_lower"), F, ""),
                  (t, i, "eubucco_magassag_max", e.get("height_confidence_upper"), F, ""),
                  (t, i, "eubucco_szintek", e.get("floors"), F, "becsult" if e.get("floors_source") == 2 else "forrasbol")]
        if e.get("height") is not None:
            rows.append((t, i, "magassag", round(float(e["height"]), 1), F, ""))
        if e.get("construction_year"):
            rows.append((t, i, "ev", int(e["construction_year"]), "eubucco", ""))
    write_facts(OUTPUT, [s for s in rows if s[3] not in (None, "")])
    for k, v in sorted(mode.items()):
        print(f"  {k}: {v}")
    print(f"Mentve: {OUTPUT}")


main()
