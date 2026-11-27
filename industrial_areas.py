"""
industrial_areas.py - the OSM landuse=industrial polygons of Budapest (for the year estimate of industrial clusters).

Run (in the project folder):   py industrial_areas.py
  or with another extract:      py industrial_areas.py path\\file.osm.pbf

Reads the same OSM extract as budapest_pbf.py (data/pbf/bbbike_budapest.osm.pbf), with that script's own PBF reader
(only the Python standard library is needed). It does not touch the files of budapest_pbf.py.
Output: data/varos/ipari_teruletek.json - a list of {"gyuruk": [outer ring, hole rings...]} in [lon, lat] points;
only the areas whose first point lies inside the city boundary (data/budapest_hatar.json).
Running time: about 10 minutes, memory: 1-2 GB.
"""
import json
import sys
import time
from pathlib import Path

import budapest_pbf as B

OUT = B.DATA / "varos" / "ipari_teruletek.json"


def industrial_kind(c):
    """Replaces budapest_pbf.water_green_kind: only landuse=industrial counts as an area here."""
    return "ipari" if c.get("landuse") == "industrial" else None


def main():
    boundary = json.loads(B.BOUNDARY.read_text(encoding="utf-8"))
    hb = B.Boundary(boundary)
    d, ny, e, k = boundary["bbox"]
    box = (d - B.MARGIN, ny - B.MARGIN, e + B.MARGIN, k + B.MARGIN)
    path_ = Path(sys.argv[1]) if len(sys.argv) > 1 else B.DATA / "pbf" / "bbbike_budapest.osm.pbf"
    if not path_.exists():
        raise SystemExit(f"Hiányzik az OSM-kivonat: {path_} (előbb a budapest_pbf.py letölti).")
    fb = B.header_bbox(path_)
    if fb:
        box = (max(fb[0], d - 0.15), max(fb[1], ny - 0.15), min(fb[2], e + 0.15), min(fb[3], k + 0.15))
    B.water_green_kind = industrial_kind          # the passes of budapest_pbf look this name up in the module
    t0 = time.time()
    print("1/3 menet: kapcsolatok")
    connections, members, districts, relations = B.pass_connections(path_)
    print(f"   {len(relations)} ipari kapcsolat ({(time.time() - t0) / 60:.1f} perc)")
    print("2/3 menet: csomópontok (ez a leghosszabb)")
    points, _ = B.pass_nodes(path_, box)
    print(f"   {len(points)} csomópont ({(time.time() - t0) / 60:.1f} perc)")
    print("3/3 menet: vonalak")
    lines, waterlines = B.pass_lines(path_, points, members)
    print(f"   {len(waterlines)} ipari vonal ({(time.time() - t0) / 60:.1f} perc)")

    def ring_points(id_):
        return [[B.point(q)["lon"], B.point(q)["lat"]] for q in lines[id_][1]]

    out, open_count = [], 0
    for id_ in waterlines:
        ring = ring_points(id_)
        if len(ring) >= 4 and ring[0] == ring[-1]:
            out.append({"gyuruk": [ring]})
    for id_, (kind, tg) in relations.items():
        outer = [ring_points(m) for m, role in tg if m in lines and role != "inner"]
        inner = [ring_points(m) for m, role in tg if m in lines and role == "inner"]
        open_ = []
        outer_ = B.into_rings_append(outer, open_)
        if open_:
            open_count += 1
            continue                                     # a relation that cannot be closed is skipped (not guessed)
        inner_ = B.into_rings_append(inner)
        for ring in outer_:
            out.append({"gyuruk": [ring] + [h for h in inner_ if B.point_in_ring_lonlat(h[0], ring)]})
    inside = [a for a in out if hb.inside(a["gyuruk"][0][0][0], a["gyuruk"][0][0][1])]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(inside), encoding="utf-8")
    print(f"KÉSZ: {len(inside)} ipari terület a városhatáron belül (a kivonatban {len(out)}, nem zárható kapcsolat: {open_count}) "
          f"-> {OUT} ({(time.time() - t0) / 60:.1f} perc)")


if __name__ == "__main__":
    main()
