"""
zones_osm_candidates.py - for the zones of forras/zona_lista.csv, searches for a polygon by name in the OSM extract.

Run (in the project folder, where budapest_pbf.py is too):
    py zones_osm_candidates.py                 # only from the data/pbf/*.osm.pbf file, without network
    py zones_osm_candidates.py --nominatim     # it also asks Nominatim for the missing ones (1 request/s)

Output:
    data/zonak_jeloltek.geojson   the polygons found (WGS84, lon/lat), with the year and the source
    data/zonak_jeloltek.csv       per zone: type of match, OSM id, OSM name
    data/zonak_hianyzo.csv        what we did not find (these have to be drawn by hand)

Of the housing estates (lt_*) and rule rows (sz_*) it searches only for the housing estates, and the estates (ze_*) too.
A match is 'pontos' (exact) if the words of the OSM name equal the zone name, and 'reszleges' (partial) if the words of the zone name
are all contained in the OSM name. It does NOT check the district: review the matches on the map!
"""
import csv
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

from budapest_pbf import (blocks, block_read, fields, packed, delta, zigzag, labels,
                          into_rings_append, point, UNIT, UA)

DATA = Path("data")
PBF_FOLDER = DATA / "pbf"
CSV_BE = Path("forras") / "zona_lista.csv"
TYPE_KEYS = ("landuse", "place", "leisure", "boundary", "residential", "building:use")
POSSIBLE_LANDUSE = {"residential", "commercial", "retail", "industrial", "garages", "allotments"}
POSSIBLE_PLACE = {"quarter", "neighbourhood", "suburb", "city_block", "locality", "borough"}
STOP = {"lakotelep", "telep", "telepe", "utcai", "utca", "uti", "ut", "u", "ter", "teri", "kertvaros",
        "negyed", "i", "ii", "iii", "utem", "varoskozpont", "varos", "park", "lakopark", "tisztviselotelep"}


def norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return s


def words(s):
    return {w for w in norm(s).split() if w not in STOP and not w.isdigit()}


def read_zones():
    zones = []
    with open(CSV_BE, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r["id"].startswith("sz_"):
                continue
            name_ = re.sub(r"\(.*?\)", " ", r["nev"])
            r["_szavak"] = words(name_)
            r["_nev_norm"] = " ".join(sorted(r["_szavak"]))
            if r["_szavak"]:
                zones.append(r)
    return zones


def match(zone, osm_name):
    """pontos / reszleges / None"""
    o = words(osm_name)
    z = zone["_szavak"]
    if not o:
        return None
    if o == z:
        return "pontos"
    if z <= o and len(" ".join(z)) >= 5:
        return "reszleges"
    return None


def candidate_e(label):
    if "name" not in label:
        return False
    if label.get("place") in POSSIBLE_PLACE:
        return True
    if label.get("landuse") in POSSIBLE_LANDUSE:
        return True
    if label.get("boundary") in ("administrative", "place", "census") and label.get("admin_level", "9") in ("9", "10", "11", "12"):
        return True
    if "residential" in label or label.get("leisure") == "park":
        return False
    return False


def several_zone_matches(label, zones):
    hits = []
    for name_key in ("name", "alt_name", "old_name"):
        name_ = label.get(name_key)
        if not name_:
            continue
        for z in zones:
            e = match(z, name_)
            if e:
                hits.append((z, e, name_))
    return hits


def search_pbf():
    files = sorted(PBF_FOLDER.glob("*.pbf"))
    if not files:
        sys.exit("Nincs PBF a data/pbf mappában. Előbb futtasd: py budapest_pbf.py")
    return max(files, key=lambda p: p.stat().st_size)


def pass_connections_es_lines(path_, zones):
    """Pass 1: the named, tagged ways and relations. Pass 2: the member ways of the relations."""
    line_hit = {}      # vonal azon -> (cimke, hivatkozasok, [(zona, tipus, nev)])
    switch_hit = {}      # kapcsolat azon -> (cimke, [(tagvonal, szerep)], talalatok)
    for type_, data_ in blocks(path_):
        if type_ != "OSMData":
            continue
        dict_, grain, lat0, lon0, groups = block_read(data_)
        for cs in groups:
            for sz, t, v in fields(cs):
                if sz == 3:                                   # vonal
                    id_ = 0
                    keys = values_ = []
                    call = b""
                    for s2, t2, x in fields(v):
                        if s2 == 1:
                            id_ = x
                        elif s2 == 2:
                            keys = packed(x)
                        elif s2 == 3:
                            values_ = packed(x)
                        elif s2 == 8:
                            call = x
                    if not keys:
                        continue
                    c = labels(dict_, keys, values_)
                    if candidate_e(c):
                        tl = several_zone_matches(c, zones)
                        if tl:
                            line_hit[id_] = (c, delta(packed(call)), tl)
                elif sz == 4:                                 # kapcsolat
                    id_ = 0
                    keys = values_ = roles = ids_ = types_ = []
                    for s2, t2, x in fields(v):
                        if s2 == 1:
                            id_ = x
                        elif s2 == 2:
                            keys = packed(x)
                        elif s2 == 3:
                            values_ = packed(x)
                        elif s2 == 8:
                            roles = packed(x)
                        elif s2 == 9:
                            ids_ = delta(packed(x))
                        elif s2 == 10:
                            types_ = packed(x)
                    if not keys:
                        continue
                    c = labels(dict_, keys, values_)
                    if c.get("type") in ("multipolygon", "boundary") and candidate_e(c):
                        tl = several_zone_matches(c, zones)
                        if tl:
                            members = [(mid, dict_[sid]) for sid, mid, mt in zip(roles, ids_, types_) if mt == 1]
                            switch_hit[id_] = (c, members, tl)
    # the member ways of the relations
    needed = {mid for _, members, _ in switch_hit.values() for mid, _ in members}
    tag_lines = {}
    if needed:
        for type_, data_ in blocks(path_):
            if type_ != "OSMData":
                continue
            dict_, grain, lat0, lon0, groups = block_read(data_)
            for cs in groups:
                for sz, t, v in fields(cs):
                    if sz != 3:
                        continue
                    id_ = 0
                    call = b""
                    for s2, t2, x in fields(v):
                        if s2 == 1:
                            id_ = x
                        elif s2 == 8:
                            call = x
                    if id_ in needed:
                        tag_lines[id_] = delta(packed(call))
    return line_hit, switch_hit, tag_lines


def read_nodes(path_, needed_):
    """Coordinates of only the requested node ids: {id: (lon, lat)}."""
    out = {}
    left = set(needed_)
    for type_, data_ in blocks(path_):
        if type_ != "OSMData":
            continue
        dict_, grain, lat0, lon0, groups = block_read(data_)
        for cs in groups:
            for sz, t, v in fields(cs):
                if sz == 2:
                    ids_ = lat = lon = None
                    for s2, t2, x in fields(v):
                        if s2 == 1:
                            ids_ = delta(packed(x))
                        elif s2 == 8:
                            lat = delta(packed(x))
                        elif s2 == 9:
                            lon = delta(packed(x))
                    if ids_ is None:
                        continue
                    for a, la, lo in zip(ids_, lat, lon):
                        if a in left:
                            out[a] = ((lon0 + grain * lo) / 1e9, (lat0 + grain * la) / 1e9)
                            left.discard(a)
                elif sz == 1:
                    id_ = la = lo = 0
                    for s2, t2, x in fields(v):
                        if s2 == 1:
                            id_ = zigzag(x)
                        elif s2 == 8:
                            la = zigzag(x)
                        elif s2 == 9:
                            lo = zigzag(x)
                    if id_ in left:
                        out[id_] = ((lon0 + grain * lo) / 1e9, (lat0 + grain * la) / 1e9)
                        left.discard(id_)
    return out


def area(ring_):
    s = 0.0
    for (x1, y1), (x2, y2) in zip(ring_, ring_[1:]):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def geometry(lines, batches):
    """ways: [lists of refs] -> GeoJSON Polygon/MultiPolygon (outer rings, without holes)."""
    rings = into_rings_append([list(v) for v in lines])
    out = []
    for g in rings:
        coord = [batches[r] for r in g if r in batches]
        if len(coord) >= 4 and coord[0] == coord[-1]:
            out.append(coord)
    if not out:
        return None
    if len(out) == 1:
        return {"type": "Polygon", "coordinates": [out[0]]}
    return {"type": "MultiPolygon", "coordinates": [[g] for g in out]}


def nominatim_question(q, bounded):
    params_ = {"q": q, "format": "jsonv2", "polygon_geojson": 1, "limit": 5, "countrycodes": "hu"}
    if bounded:
        params_.update({"viewbox": "18.90,47.62,19.35,47.35", "bounded": 1})
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(params_)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def nominatim(zone):
    """Several query variants; returns the hit that gives the first polygon. It logs what it got."""
    name_ = re.sub(r"\(.*?\)", " ", zone["nev"]).strip()
    height = re.sub(r"\b(lakótelep|telep)\b", " ", name_, flags=re.I).strip()
    variants = [(name_ + ", Budapest", True), (name_ + ", Budapest", False), (height + ", Budapest", True)]
    seen = []
    for q, bounded in variants:
        time.sleep(1.1)
        data_ = nominatim_question(q, bounded)
        seen.append("%s%s: %s" % (q, "" if bounded else " [nincs doboz]",
                      ",".join((e.get("geojson") or {}).get("type", "-") + ":" + e.get("class", "?") for e in data_) or "0 találat"))
        for e in data_:
            g = e.get("geojson")
            if g and g.get("type") in ("Polygon", "MultiPolygon"):
                return g, e, seen
    return None, None, seen


def main():
    nominatim_needed = "--nominatim" in sys.argv[1:]
    zones = read_zones()
    path_ = search_pbf()
    print("PBF:", path_, "| zónák:", len(zones))
    line_t, switch_t, tag_v = pass_connections_es_lines(path_, zones)
    print("nevesített vonal-jelölt:", len(line_t), "| kapcsolat-jelölt:", len(switch_t))
    needed_ = set()
    for c, call, tl in line_t.values():
        needed_.update(call)
    for refs in tag_v.values():
        needed_.update(refs)
    batches = read_nodes(path_, needed_)

    candidates = {}   # zone id -> list (accuracy, source, geometry, osm name, osm id)
    rank = {"pontos": 0, "reszleges": 1}
    for id_, (c, call, tl) in line_t.items():
        g = geometry([call], batches)
        if not g:
            continue
        for z, e, name_ in tl:
            candidates.setdefault(z["id"], []).append((e, "way/%d" % id_, g, name_))
    for id_, (c, members, tl) in switch_t.items():
        outer = [tag_v[mid] for mid, role in members if mid in tag_v and role in ("outer", "")]
        g = geometry(outer, batches)
        if not g:
            continue
        for z, e, name_ in tl:
            candidates.setdefault(z["id"], []).append((e, "relation/%d" % id_, g, name_))

    features = []
    rows = []
    missing = []
    for z in zones:
        list_ = sorted(candidates.get(z["id"], []), key=lambda x: (rank[x[0]],
                       -max((area(r) for r in ([x[2]["coordinates"][0]] if x[2]["type"] == "Polygon" else [p[0] for p in x[2]["coordinates"]])), default=0)))
        mode = None
        if list_:
            e, osm_id, g, name_ = list_[0]
            mode = "osm_" + e
        elif nominatim_needed:
            try:
                g, ent, log = nominatim(z)
                print("Nominatim:", z["nev"], "->", "TALÁLAT" if g else "nincs poligon", "|", " || ".join(log)[:300], flush=True)
                if g:
                    osm_id = "%s/%s" % (ent.get("osm_type"), ent.get("osm_id"))
                    name_ = ent.get("display_name", "")[:80]
                    mode = "nominatim"
            except Exception as ex:
                print("Nominatim hiba:", z["nev"], ex)
        if not mode:
            missing.append([z["id"], z["nev"], z["kerulet"], z["ev_tol"], z["ev_ig"], z["allapot"]])
            continue
        features.append({"type": "Feature", "geometry": g, "properties": {
            "id": z["id"], "nev": z["nev"], "tipus": z["tipus"], "kerulet": z["kerulet"],
            "ev_tol": int(z["ev_tol"]), "ev_ig": int(z["ev_ig"]), "allapot": z["allapot"],
            "forras": z["forras"], "egyezes": mode, "osm": osm_id, "osm_nev": name_,
            "tobb_jelolt": len(list_)}})
        rows.append([z["id"], z["nev"], z["kerulet"], mode, osm_id, name_, len(list_)])

    with open(DATA / "zonak_jeloltek.geojson", "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, ensure_ascii=False)
    with open(DATA / "zonak_jeloltek.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["id", "nev", "kerulet", "egyezes", "osm", "osm_nev", "jeloltek_szama"])
        w.writerows(rows)
    with open(DATA / "zonak_hianyzo.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["id", "nev", "kerulet", "ev_tol", "ev_ig", "allapot"])
        w.writerows(missing)
    print("Megtalált: %d / %d zóna; hiányzik: %d" % (len(features), len(zones), len(missing)))
    print("-> data/zonak_jeloltek.geojson, data/zonak_jeloltek.csv, data/zonak_hianyzo.csv")


if __name__ == "__main__":
    main()
