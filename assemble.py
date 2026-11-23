"""Builds the map's final data file from the facts of all sources.

Input:    data/belvaros_epuletek.geojson     (OSM buildings, geojson_keszites.py)
          data/tenyek/*.csv                  (tenyek_*.py scripts)
          forras/kezi_javitasok.csv          (your manual corrections, these always win)
          forras/prioritas.json              (which source wins for which field)
Output:   data/belvaros_epuletek_vegleges.geojson
          data/utkozesek.csv                 (where sources disagree, for review)

City mode:  py assemble.py varos
  Input:    data/varos/epuletek.geojson, reszek.geojson, osm_cimek.csv (city_assembly.py)
  Output:   data/varos/epuletek_vegleges.geojson, data/varos/utkozesek.csv
  (facts and manual corrections apply the same way by id; the inner-city files are not touched)
"""
import csv
import math
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from common import inner_point, building_key, point_in_ring, point_in_polygon, read_facts, area_center

OSM = "data/belvaros_epuletek.geojson"
FACTS_FOLDER = Path("data/tenyek")
MANUAL = "forras/kezi_javitasok.csv"
MANUAL_BUILDINGS = "forras/kezi_epuletek.geojson"          # manually added items that are not buildings in OSM (e.g. memorials): GeoJSON, with the usual fields
GROUPS = "forras/epulet_csoportok.csv"       # a building made of several OSM elements (e.g. bath, hospital): group;nev;osm_tipus;id;fo
OENY_EXCLUDED = "forras/oeny_kizart.csv"   # osm_tipus;id;megjegyzes - drops every E-Örökség (oeny, oeny_koord) fact for the listed OSM elements (data sheet, register number, protection, year, designer)
EXCLUDED = "forras/kizart_epuletek.csv"   # osm_tipus;id;megjegyzes - leaves the listed OSM elements (e.g. courtyard, not a building) off the map
MANUAL_ADDRESSES = "forras/kezi_cimek.csv"       # manual override of the address shown on the card (osm_tipus;id;cim;megjegyzes)
PARTITION = "forras/kezi_felosztas.csv"   # splitting one OSM outline in two along a straight line (e.g. two houses drawn as one polygon)
DUPLICATES = "forras/duplikatumok.csv"   # duplicate_finder.py + manual decision: cleaning up buildings drawn on top of each other without losing data
ALIAS = {}                                  # key of the removed (duplicate) element -> key of the kept element
PRIORITY = "forras/prioritas.json"
PARTS = "data/belvaros_reszek.geojson"           # building:part elements (geojson_keszites.py)
OUTPUT = "data/belvaros_epuletek_vegleges.geojson"
CONFLICTS = "data/utkozesek.csv"
ADDRESSES = "data/osm_cimek.csv"                      # output of download_addresses.py (OSM address points)
ESTIMATE = "data/ev_becsles.csv"                   # output of year_estimate.py (an estimate only, not data)
CITY = len(sys.argv) > 1 and sys.argv[1] == "varos"
if CITY:
    OSM = "data/varos/epuletek.geojson"
    PARTS = "data/varos/reszek.geojson"
    OUTPUT = "data/varos/epuletek_vegleges.geojson"
    CONFLICTS = "data/varos/utkozesek.csv"
    ADDRESSES = "data/varos/osm_cimek.csv"
    ESTIMATE = "data/varos/ev_becsles.csv"
ESTIMATE_ERAS = ["1867 előtt", "1867–1918", "1919–1944", "1945–1956", "1957–1989", "1990–2010", "2011-től"]

DECIDING_FIELDS = ["ev", "szintek", "tervezo", "magassag"]
DELETE = object()          # the marker of a manual '-' in the numeric fields
NUMBERED = {"ev", "szintek", "magassag", "lechner_ev_kezdet", "lechner_ev_veg", "szintek_kep",
          "eubucco_magassag_min", "eubucco_magassag_max", "eubucco_szintek"}


def number(x):
    try:
        v = float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return int(v) if v == int(v) else v


def designer_names(x):
    """Normalises names: 'Feszl Frigyes (1821–1884)' and 'Feszl Frigyes' are the same; several names are separated by ',' ';' ' és '."""
    x = re.sub(r"\u00ad\s*|\u200b", "", re.sub(r"\([^)]*\)", "", str(x)))
    parts = re.split(r",|;|\bés\b", x)
    out = set()
    for r in parts:
        r = " ".join(r.split()).lower().replace("ifj. ", "").replace("id. ", "")
        if r:
            out.add(r)
    return out


DESIGNER_NOT_NAME = re.compile(r"[-–—]+|tervező\s+nem\s+ismert", re.I)


def designer_clean(x):
    """Designer-name normalisation, step 1: delete all parenthesised content (years of life, alternative name form, remark)."""
    x = str(x or "")
    while True:
        y = re.sub(r"\([^()]*\)", "", x)
        if y == x:
            break
        x = y
    x = re.sub(r"[()]", "", x)                       # unpaired parenthesis
    x = re.sub(r"\u00ad|\u200b", "", x)
    x = re.sub(r"\s+([,;])", r"\1", " ".join(x.split()))
    x = re.sub(r"([,;])(\s*[,;])+", r"\1", x)       # separators left empty after the deletion
    x = x.strip(" ,;")
    if DESIGNER_NOT_NAME.search(x):                    # "Tervező nem ismert" ("designer unknown") and a lone "-" are not names: the item is deleted (the other names stay)
        parts = re.split(r"(\s*[;,]\s*|\s+és\s+)", x)
        out = ""
        for i in range(0, len(parts), 2):
            if DESIGNER_NOT_NAME.fullmatch(parts[i].strip()):
                continue
            out += (parts[i - 1] if out and i else "") + parts[i]
        x = out
    return x.strip(" ,;")


def clean_designer(feats):
    """The designer fields (of the building and the one inherited from the zone) without parentheses; if nothing remains, the field is removed."""
    count_ = 0
    for ft in feats:
        pr = ft["properties"]
        for m in ("tervezo", "zona_tervezo"):
            if pr.get(m):
                new = designer_clean(pr[m])
                if new != pr[m]:
                    count_ += 1
                if new:
                    pr[m] = new
                else:
                    pr.pop(m, None)
                    if m == "tervezo":
                        pr.pop("tervezo_forras", None)
    return count_


def designer_matches(a, b):
    na, nb = designer_names(a), designer_names(b)
    return bool(na and nb and (na <= nb or nb <= na))


# The parts may inherit these properties from the building if they have no data of their own
NOT_INHERITED = {"id", "osm_tipus", "resz", "szulo_id", "szulo_tipus"}
YEAR_GROUP = ("ev", "ev_forras")
LEVEL_GROUP = ("szintek", "szintek_forras", "szintek_osm", "szint_eltero")
HEIGHT_GROUP = ("magassag", "magassag_forras", "magassag_szintbol")
FURTHER_COVERED = 0.5          # for a building covered by parts to a lesser degree than this, the parts are ignored


SMALL_BUILDING_M2 = 50.0          # a data-less building with a smaller footprint than this is a small outbuilding
SMALL_BUILDING_HEIGHT = 3.5     # m
KIOSK_M2 = 15.0              # a building with a smaller footprint than this (kiosk, transformer) always gets the low height
SMALL_BUILDING_MAX_ESTIMATED = 6.0   # m: the estimated EUBUCCO height of a small building is at most this


def ring_area(rings):
    """Area in m²: the outer ring minus the holes (courtyards)."""
    return max(area_center(rings[0])[0] - sum(area_center(h)[0] for h in rings[1:]), 1e-9)


def inherit(rp, sp):
    """The part (rp) receives the building's (sp) properties if it lacks them itself."""
    rp["szulo_id"] = sp["id"]
    rp["szulo_tipus"] = sp["osm_tipus"]
    if rp.get("tipus") in (None, "yes"):
        rp["tipus"] = sp.get("tipus")
    own_year = rp.get("ev") and sp.get("ev_forras") != "kezi"
    own_level = rp.get("szintek") and sp.get("szintek_forras") != "kezi"
    own_core = rp.get("magassag_forras") in ("height", "szintszam", "szintterkep", "kezi") \
        and sp.get("magassag_forras") != "kezi"
    for k, v in sp.items():
        if k in NOT_INHERITED or k == "tipus":
            continue
        if k in YEAR_GROUP and own_year:
            continue
        if k in LEVEL_GROUP and own_level:
            continue
        if k in HEIGHT_GROUP and own_core:
            continue
        if k in YEAR_GROUP + LEVEL_GROUP + HEIGHT_GROUP or rp.get(k) in (None, ""):
            rp[k] = v


def common_vertices(ring_a, ring_b):
    return len({tuple(p) for p in ring_a} & {tuple(p) for p in ring_b})


def handle_parts(feats):
    """Assigns the building parts (building:part) to the building containing them.

    1. If a part's interior point lies within the building's outer outline (courtyards
       also belong to the building), the part belongs to the building.
    2. If the parts cover at least half of the building's outline, the parts are drawn
       instead of the outline; if less, the parts are dropped and the outline stays.
    3. Parts outside the building but connected to it (shared vertices, or one of the
       part's vertices lies inside the building) also inherit the building's data, but appear on their own.
    Name, protection etc. are inherited; the part keeps its own year, number of storeys
    and height (given in OSM or corrected by hand)."""
    parts = [ft for ft in feats if ft["properties"].get("resz")]
    parents_ = [ft for ft in feats if not ft["properties"].get("resz")]
    stat = Counter()
    if not parts:
        return feats, stat
    records = []
    for s in parents_:
        gy = s["geometry"]["coordinates"]
        xs = [p[0] for p in gy[0]]
        ys = [p[1] for p in gy[0]]
        records.append((min(xs), max(xs), min(ys), max(ys), ring_area(gy), s))
    GRID = 0.002                                  # degrees: fast lookup among the surrounding buildings
    grid = defaultdict(list)
    for a in records:
        for ci in range(int(a[0] / GRID), int(a[1] / GRID) + 1):
            for cj in range(int(a[2] / GRID), int(a[3] / GRID) + 1):
                grid[(ci, cj)].append(a)

    def nearby(x0, x1, y0, y1):
        lat = {}
        for ci in range(int(x0 / GRID), int(x1 / GRID) + 1):
            for cj in range(int(y0 / GRID), int(y1 / GRID) + 1):
                for a in grid.get((ci, cj), ()):
                    lat[id(a)] = a
        return list(lat.values())

    groups = defaultdict(list)                 # id(parent) -> [part]
    related = []                               # (part, parent feature)
    for r in parts:
        gy = r["geometry"]["coordinates"]
        x, y = inner_point([gy])
        candidates = [a for a in nearby(x, x, y, y) if a[0] <= x <= a[1] and a[2] <= y <= a[3]
                    and point_in_ring(x, y, a[5]["geometry"]["coordinates"][0])]
        if candidates:
            parent_ = min(candidates, key=lambda a: a[4])
            groups[id(parent_[5])].append((r, parent_))
            continue
        # not in any outline: is it connected to one of them?
        rx = [p[0] for p in gy[0]]
        ry = [p[1] for p in gy[0]]
        best, point = None, 0
        for a in nearby(min(rx), max(rx), min(ry), max(ry)):
            if a[1] < min(rx) or a[0] > max(rx) or a[3] < min(ry) or a[2] > max(ry):
                continue
            outer = a[5]["geometry"]["coordinates"][0]
            common_ = common_vertices(gy[0], outer)
            inside = sum(1 for px, py in gy[0][:-1] if point_in_ring(px, py, outer))
            if common_ >= 2 or inside >= 1:
                p_ = common_ * 2 + inside
                if p_ > point:
                    best, point = a, p_
        if best:
            related.append((r, best[5]))
        else:
            stat["önálló rész (nincs épületkontúr)"] += 1
    skip = set()
    for list_ in groups.values():
        parent_ = list_[0][1][5]
        parent_area = list_[0][1][4]
        covered = sum(ring_area(r["geometry"]["coordinates"]) for r, _ in list_) / parent_area
        if covered < FURTHER_COVERED:
            for r, _ in list_:
                skip.add(id(r))
            stat["rész kihagyva (kevéssé fedi le az épületet)"] += len(list_)
            continue
        skip.add(id(parent_))
        stat["épület helyett részei"] += 1
        stat["rész az épületen belül"] += len(list_)
        for r, _ in list_:
            inherit(r["properties"], parent_["properties"])
    for r, parent_ in related:
        inherit(r["properties"], parent_["properties"])
        stat["épületen kívüli, de hozzá kapcsolódó rész (örökli az adatait)"] += 1
    return [ft for ft in feats if id(ft) not in skip], stat


def append_estimate(feats):
    """From ev_becsles.csv, adds separate 'ev_becsles_*' fields to the GREY (year-less) buildings.
    The 'ev' field is not touched: an estimate never counts as data."""
    if not Path(ESTIMATE).exists():
        print(f"Becslés: nincs {ESTIMATE} (futtasd: py year_estimate.py)")
        return 0
    estimate = {}
    with open(ESTIMATE, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            estimate[(r["osm_tipus"], int(r["id"]))] = r
    count_ = 0
    for x in feats:
        pr = x["properties"]
        if pr.get("ev"):
            continue
        if pr.get("resz"):
            # a building part (building:part) inherits the estimate of its parent building if the parent has one
            # previously the part was left without an estimate, and the tiling gave it the era of the nearest building (32 parts)
            if not pr.get("szulo_id"):
                continue
            r = estimate.get((pr.get("szulo_tipus") or "way", int(pr["szulo_id"])))
        else:
            r = estimate.get(building_key(pr))
        if not r or r["becsult_korszak"] not in ESTIMATE_ERAS:
            continue
        pr["ev_becsles_korszak"] = ESTIMATE_ERAS.index(r["becsult_korszak"])
        pr["ev_becsles_valoszinuseg"] = float(r["valoszinuseg"])
        pr["ev_becsles_bizonyossag"] = r["bizonyossag"]
        pr["ev_becsles_indoklas"] = r["indoklas"]
        count_ += 1
    return count_


def append_approximate(feats):
    """From the textual era data of data/varos/*_kozelito.csv ('1920-1930-as évek', i.e. "the 1920s-30s"), 'ev_kozelito_*' fields for year-less buildings.
    This is data too (roughly when it was built, according to the source), but not an exact year: the 'ev' field is not touched. With several sources the narrowest range is output."""
    if not CITY:
        return 0
    candidate = defaultdict(list)
    for path_ in sorted(Path("data/varos").glob("*_kozelito.csv")):
        with open(path_, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                try:
                    candidate[(r["osm_tipus"], int(r["id"]))].append((int(r["ev_ig"]) - int(r["ev_tol"]), int(r["ev_tol"]), int(r["ev_ig"]), (r.get("szoveg") or "").strip(), (r.get("forras") or "").strip()))
                except (KeyError, ValueError):
                    continue
    count_ = 0
    for x in feats:
        pr = x["properties"]
        if pr.get("ev") or pr.get("resz"):
            continue
        l = candidate.get(building_key(pr))
        if not l:
            continue
        _, from_, to, text_, source = min(l)
        pr["ev_kozelito_tol"], pr["ev_kozelito_ig"] = from_, to
        if text_:
            pr["ev_kozelito_szoveg"] = text_
        if source:
            pr["ev_kozelito_forras"] = source
        count_ += 1
    return count_


def append_addresses(feats):
    """The 'cim' (first address, e.g. 'Alkotmány utca 2') and 'cim_tobb' (how many further addresses) fields for the card."""
    if not Path(ADDRESSES).exists():
        return 0
    addresses = defaultdict(list)
    with open(ADDRESSES, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r["utca"] and r["hazszam"]:
                addresses[(r["osm_tipus"], int(r["id"]))].append(f'{r["utca"]} {r["hazszam"]}')
    count_ = 0
    for x in feats:
        pr = x["properties"]
        list_ = addresses.get(building_key(pr))
        if not list_ and pr.get("szulo_id") and pr.get("szulo_tipus"):
            list_ = addresses.get((pr["szulo_tipus"], int(pr["szulo_id"])))   # building part: the parent's address
        if list_:
            list_ = list(dict.fromkeys(list_))
            pr["cim"] = list_[0]
            if len(list_) > 1:
                pr["cim_tobb"] = len(list_) - 1
            count_ += 1
    return count_


def append_zone_wikipedia(feats):
    """The Wikipedia article given in the zone editor (forras/zonak_poligon.geojson, 'wikipedia' field) is the default article of the
    buildings falling in the zone. If the building has its own article (from any source, or by hand), that stays; with several zones
    the smallest zone that has an article wins. The 'wikipedia_zona' field on the building shows which zone it came from."""
    path_ = Path("forras/zonak_poligon.geojson")
    if not path_.exists():
        return 0
    zones = []
    for f in json.load(open(path_, encoding="utf-8")).get("features", []):
        p, g = f.get("properties", {}), f.get("geometry", {})
        if not p.get("wikipedia") or g.get("type") != "Polygon":
            continue
        gy = g["coordinates"][0]
        xs, ys = [q[0] for q in gy], [q[1] for q in gy]
        area = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(gy, gy[1:]))) / 2
        zones.append((area, min(xs), min(ys), max(xs), max(ys), g["coordinates"], p["wikipedia"], p.get("nev") or p["id"]))
    if not zones:
        return 0
    zones.sort(key=lambda z: z[0])               # from small to large: the first match is the smallest
    count_ = 0
    for ft in feats:
        pr = ft["properties"]
        if pr.get("wikipedia"):          # (ruins also get the zone's article if they have none of their own)
            continue
        g = ft["geometry"]
        if g["type"] == "Polygon":
            ring_ = g["coordinates"][0]
        elif g["type"] == "MultiPolygon":
            ring_ = g["coordinates"][0][0]
        else:
            continue
        _, x, y = area_center(ring_)
        for _, x0, y0, x1, y1, coord, article, name_ in zones:
            if x0 <= x <= x1 and y0 <= y <= y1 and point_in_polygon(x, y, coord):
                pr["wikipedia"], pr["wikipedia_zona"] = article, name_
                count_ += 1
                break
    return count_


ZONE_NAME_TYPES = {"lakotelep"}   # the name of these drawn zone types goes into the building's "zona_nev" field (the card's title, if the building has no name of its own)


def zone_name_assignment(feats):
    """The names of the drawn housing-estate zones (forras/zonak_poligon.geojson, tipus: lakotelep) for the buildings falling in the zone: 'zona_nev'.
    With several zones the smallest wins. The building's own name (nev, lechner_nev, nev_kozepulet) stays regardless."""
    path_ = Path("forras/zonak_poligon.geojson")
    if not path_.exists():
        return 0
    zones = []
    for f in json.load(open(path_, encoding="utf-8")).get("features", []):
        p, g = f.get("properties", {}), f.get("geometry", {})
        name_ = (p.get("nev") or "").strip()
        sign = p.get("zona_nev_hozzaad")          # the zone editor's tick box; if not set, the zone type decides
        if sign is None:
            sign = p.get("tipus") in ZONE_NAME_TYPES
        if not sign or not name_:
            continue
        polys = [g["coordinates"]] if g.get("type") == "Polygon" else g["coordinates"] if g.get("type") == "MultiPolygon" else []
        for coord in polys:
            gy = coord[0]
            xs, ys = [q[0] for q in gy], [q[1] for q in gy]
            area = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(gy, gy[1:]))) / 2
            zones.append((area, min(xs), min(ys), max(xs), max(ys), coord, name_))
    if not zones:
        return 0
    zones.sort(key=lambda z: z[0])               # from small to large
    count_ = 0
    for ft in feats:
        pr = ft["properties"]
        pr.pop("zona_nev", None)
        if pr.get("rom"):
            continue
        g = ft["geometry"]
        if g["type"] == "Polygon":
            ring_ = g["coordinates"][0]
        elif g["type"] == "MultiPolygon":
            ring_ = g["coordinates"][0][0]
        else:
            continue
        _, x, y = area_center(ring_)
        for _, x0, y0, x1, y1, coord, name_ in zones:
            if x0 <= x <= x1 and y0 <= y <= y1 and point_in_polygon(x, y, coord):
                pr["zona_nev"] = name_
                count_ += 1
                break
    return count_


def zone_designer_assignment(feats):
    """The designer(s) given in the zone editor (forras/zonak_poligon.geojson, 'tervezo' field, e.g. of a housing estate) for the buildings
    falling in the zone: 'zona_tervezo' (the text), 'zona_azon' (the zone's id) and 'zona_tervezo_nev' (the zone's name). The building's own 'tervezo'
    field is not overwritten. With several zones the smallest wins. When an architect is highlighted, the 3D view also watches this, and counts the estate as 1 project."""
    path_ = Path("forras/zonak_poligon.geojson")
    if not path_.exists():
        return 0
    zones = []
    for f in json.load(open(path_, encoding="utf-8")).get("features", []):
        p, g = f.get("properties", {}), f.get("geometry", {})
        plan = (p.get("tervezo") or "").strip()
        if not plan:
            continue
        polys = [g["coordinates"]] if g.get("type") == "Polygon" else g["coordinates"] if g.get("type") == "MultiPolygon" else []
        for coord in polys:
            gy = coord[0]
            xs, ys = [q[0] for q in gy], [q[1] for q in gy]
            area = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(gy, gy[1:]))) / 2
            zones.append((area, min(xs), min(ys), max(xs), max(ys), coord, plan, p.get("id") or "", (p.get("nev") or "").strip()))
    for ft in feats:                                  # the result of the previous run must not remain
        for k in ("zona_tervezo", "zona_azon", "zona_tervezo_nev"):
            ft["properties"].pop(k, None)
    if not zones:
        return 0
    zones.sort(key=lambda z: z[0])
    count_ = 0
    for ft in feats:
        pr = ft["properties"]
        if pr.get("rom"):
            continue
        g = ft["geometry"]
        if g["type"] == "Polygon":
            ring_ = g["coordinates"][0]
        elif g["type"] == "MultiPolygon":
            ring_ = g["coordinates"][0][0]
        else:
            continue
        _, x, y = area_center(ring_)
        for _, x0, y0, x1, y1, coord, plan, id_, name_ in zones:
            if x0 <= x <= x1 and y0 <= y <= y1 and point_in_polygon(x, y, coord):
                pr["zona_tervezo"], pr["zona_azon"], pr["zona_tervezo_nev"] = plan, id_, name_ or id_
                count_ += 1
                break
    return count_


WEAK_YEAR_SOURCES = {"eubucco", "wikidata_kozeli"}   # the least reliable year sources
ZONE_OVERWRITES_WEAK_YEAR = True                      # a weak-source year outside the drawn zone's boundary is overridden by the zone


def overwrite_zone_weak_year(feats):
    """If a building's year comes from a weak source (EUBUCCO, a nearby Wikidata match) and falls outside the hard boundary of the drawn zone
    (built from this year on; with the 'ig_hatar' switch also up to this year), the year is dropped: the building turns grey and the estimate
    decides within the zone boundary. The year of strong sources (manual, OSM, monument, OENY, heritage inventory, Budapest100 etc.) is left alone."""
    path_ = Path("forras/zonak_poligon.geojson")
    if not ZONE_OVERWRITES_WEAK_YEAR or not path_.exists():
        return 0
    zones = []
    for f in json.load(open(path_, encoding="utf-8")).get("features", []):
        p, g = f.get("properties", {}), f.get("geometry", {})
        if p.get("tipus") == "muemlek" or p.get("mero") or g.get("type") != "Polygon":
            continue
        try:
            from_, to = int(p["ev_tol"]), int(p["ev_ig"])
        except (KeyError, TypeError, ValueError):
            continue
        gy = g["coordinates"][0]
        xs, ys = [q[0] for q in gy], [q[1] for q in gy]
        area = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(gy, gy[1:]))) / 2
        zones.append((area, min(xs), min(ys), max(xs), max(ys), g["coordinates"], from_, to, bool(p.get("ig_hatar"))))
    zones.sort(key=lambda z: z[0])
    count_ = 0
    for ft in feats:
        pr = ft["properties"]
        if not pr.get("ev") or pr.get("ev_forras") not in WEAK_YEAR_SOURCES or pr.get("rom"):
            continue
        g = ft["geometry"]
        ring_ = g["coordinates"][0] if g["type"] == "Polygon" else g["coordinates"][0][0] if g["type"] == "MultiPolygon" else None
        if ring_ is None:
            continue
        _, x, y = area_center(ring_)
        for _, x0, y0, x1, y1, coord, from_, to, to_h in zones:
            if x0 <= x <= x1 and y0 <= y <= y1 and point_in_polygon(x, y, coord):
                try:
                    year = int(pr["ev"])
                except (TypeError, ValueError):
                    break
                if year < from_ or (to_h and year > to):
                    pr["ev_eldobott"] = year
                    pr["ev_eldobott_forras"] = pr.get("ev_forras")
                    pr.pop("ev", None)
                    pr.pop("ev_forras", None)
                    count_ += 1
                break
    return count_


def _zone_b100_links(feats):
    """The Budapest100 link given in the zone editor ('budapest100' field) is the default link of the buildings in the zone, if the
    building has no 'budapest100_url' of its own. With several zones the smallest zone that has a link wins."""
    path_ = Path("forras/zonak_poligon.geojson")
    if not path_.exists():
        return 0
    zones = []
    for f in json.load(open(path_, encoding="utf-8")).get("features", []):
        p, g = f.get("properties", {}), f.get("geometry", {})
        b100 = p.get("budapest100")
        if not b100:                       # for zones taken over from the zone list the URL often appears only in the remark
            m_ = re.search(r"https?://(?:www\.)?budapest100\.hu/[^\s;,)\"]+", str(p.get("megjegyzes") or ""))
            b100 = m_.group(0) if m_ else None
        if not b100 or g.get("type") != "Polygon":
            continue
        gy = g["coordinates"][0]
        xs, ys = [q[0] for q in gy], [q[1] for q in gy]
        area = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(gy, gy[1:]))) / 2
        zones.append((area, min(xs), min(ys), max(xs), max(ys), g["coordinates"], b100))
    if not zones:
        return 0
    zones.sort(key=lambda z: z[0])
    count_ = 0
    for ft in feats:
        pr = ft["properties"]
        if pr.get("budapest100_url") or pr.get("rom"):
            continue
        g = ft["geometry"]
        ring_ = g["coordinates"][0] if g["type"] == "Polygon" else g["coordinates"][0][0] if g["type"] == "MultiPolygon" else None
        if ring_ is None:
            continue
        _, x, y = area_center(ring_)
        for _, x0, y0, x1, y1, coord, url in zones:
            if x0 <= x <= x1 and y0 <= y <= y1 and point_in_polygon(x, y, coord):
                pr["budapest100_url"] = url
                count_ += 1
                break
    return count_


def append_zone_budapest100(feats):
    """The link inherited from the zone + the Budapest100 page's image and photographer for every building that has a budapest100_url
    (from the zone, from manual editing or from the building pairing) but no budapest100_kep of its own yet (data/bp100/kepek.json)."""
    count_ = _zone_b100_links(feats)
    try:
        images = json.load(open("data/bp100/kepek.json", encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return count_
    image_count = 0
    for ft in feats:
        pr = ft["properties"]
        k = images.get((pr.get("budapest100_url") or "").strip())
        if k is None:
            continue
        # the image and the photographer always belong to the page whose link is on the card
        # (if several Budapest100 pages belong to the building, the link, the image and the photographer must not get mixed up)
        if k.get("kep"):
            if pr.get("budapest100_kep") != k["kep"] or pr.get("budapest100_foto", "") != k.get("foto", ""):
                image_count += 1
            pr["budapest100_kep"] = k["kep"]
            if k.get("foto"):
                pr["budapest100_foto"] = k["foto"]
            else:
                pr.pop("budapest100_foto", None)
        else:
            pr.pop("budapest100_kep", None)
            pr.pop("budapest100_foto", None)
    print(f"  Budapest100-kép a kártyán álló link oldalához igazítva: {image_count}")
    return count_


# A building group (e.g. the many OSM pieces of the Rudas bath) differs in geometry piece by piece, but is one building: one name, one card.
GROUP_PER_PART = {"wikipedia_zona", "id", "osm_tipus", "tipus", "resz", "szulo_id", "szulo_tipus", "kerulet", "lat", "lon", "csoport", "csoport_nev",
                      "csoport_reszek", "csoport_osm", "cim_tobb", "sv_lat", "sv_lon", "ev", "ev_forras", "nev", "wikidata_nev", "kep"}
GROUP_MERGED = {"wikipedia", "oeny_azonosito"}                 # the articles/data sheets of the group's pieces combined (at most 3)
GROUP_TEXT_MERGED = {"tervezo", "about"}                      # the different texts are placed side by side


# Automatic groups: parts (building:part) drawn instead of a building's outline are treated as one building,
# if no link would be lost by it (see auto_csoportok).
AUTO_GROUP = True
LINK_UNIQUE = ("budapest100_url", "budapest100_kep", "legenda_url", "legenda_kep", "epforum_url", "commons_kep")     # at most one different value per piece
LINK_MERGED = ("oeny_azonosito", "wikipedia")                                      # the merge carries over at most 3 different values


def auto_groups(feats, keys_manual, index):
    """From the parts that replace a building's outline (same szulo_id, the parent is not in the output) it forms a group, but only if
    merging the group would lose nothing: the OENY id, Wikipedia (at most 3 together), the Budapest100 and
    Legenda link (and image) have at most one different value each, and no two different years occur (the year of Építészfórum/OENY/...
    would be taken over uniformly by the group). Returns: (rows for the groups table, statistics)."""
    stat = Counter()
    grp_ = defaultdict(list)
    for ft in feats:
        p = ft["properties"]
        if p.get("resz") and p.get("szulo_id") and p.get("szulo_tipus") and building_key(p) not in keys_manual:
            if (p["szulo_tipus"], int(p["szulo_id"])) in index:
                continue                      # the parent remained: this part is only connected to it, it stays independent
            grp_[(p["szulo_tipus"], int(p["szulo_id"]))].append(ft)
    rows = {}
    for (st, sid), members in grp_.items():
        if len(members) < 2:
            continue
        pr = [ft["properties"] for ft in members]
        problem = None
        for k in LINK_UNIQUE:
            if len({p[k] for p in pr if p.get(k)}) > 1:
                problem = k
        for k in LINK_MERGED:
            total = {x for p in pr for x in str(p.get(k) or "").split("|") if x}
            if len(total) > 3:
                problem = k
        if len({p["ev"] for p in pr if p.get("ev")}) > 1:
            problem = "ev"
        if problem:
            stat["kimaradt (különböző " + problem + " menne veszendőbe)"] += 1
            continue
        fo = max(members, key=lambda ft: (bool(ft["properties"].get("ev")), ft["properties"].get("magassag") or 0))
        id_ = f"auto_{st}_{sid}"
        rows[id_] = [{"csoport": id_, "nev": "", "osm_tipus": ft["properties"]["osm_tipus"], "id": str(ft["properties"]["id"]),
                        "fo": "1" if ft is fo else "0", "auto": "1"} for ft in members]
        stat["automatikus csoport"] += 1
        stat["automatikus csoport – darab"] += len(members)
    return rows, stat


def merge_groups(feats):
    """forras/epulet_csoportok.csv: several OSM elements as one building. Every piece of the group
    - gets the same name (nev) and the year (ev) of the group's 'fo' (main) piece - so the colour and the card are uniform;
    - gets the data of all the group's pieces: what a piece lacks it takes from the others (address, protection, Wikipedia,
      Lechner, designer ...), with the Wikipedia articles and designers combined;
    - the card shows each piece's own data (csoport_reszek) and its OSM link (csoport_osm) in the 'Parts of the building' section.
    The pieces' own geometry, number of storeys and height do not change."""
    rows = defaultdict(list)
    if Path(GROUPS).exists():
        with open(GROUPS, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                if (r.get("csoport") or "").strip() and (r.get("id") or "").strip():
                    rows[r["csoport"].strip()].append(r)
    index = {building_key(ft["properties"]): ft for ft in feats}
    if AUTO_GROUP:
        manual_keys = {((r.get("osm_tipus") or "way").strip(), int(r["id"])) for l in rows.values() for r in l}
        auto, auto_stat = auto_groups(feats, manual_keys, index)
        rows.update(auto)
        for k_, count__ in auto_stat.items():
            print(f"  épületcsoport – {k_}: {count__}")
    group_count = part_count = 0
    for id_, list_ in rows.items():
        name_ = next(((r.get("nev") or "").strip() for r in list_ if (r.get("nev") or "").strip()), None)
        if name_ is None and not id_.startswith(("auto_", "kez_")):
            name_ = id_     # the name of a group created in the editor (kez_) is the pieces' shared, inherited name, not the group's id
        if name_ is None:   # automatic group: the pieces' shared, inherited name (if any)
            name_ = next((index[(r.get("osm_tipus") or "way", int(r["id"]))]["properties"].get("nev") for r in list_
                        if (r.get("osm_tipus") or "way", int(r["id"])) in index
                        and index[(r.get("osm_tipus") or "way", int(r["id"]))]["properties"].get("nev")), "")
        members = []                                   # [(feature, main?)]
        for r in list_:
            _k = ((r.get("osm_tipus") or "way").strip(), int(r["id"]))
            ft = index.get(ALIAS.get(_k, _k))
            if ft and any(ft is x for x, _ in members):
                continue
            if ft:
                members.append((ft, (r.get("fo") or "").strip() in ("1", "igen", "x")))
            else:
                print(f"  épületcsoport '{id_}': nincs ilyen épület: {r.get('osm_tipus')} {r.get('id')}")
        if len(members) < 2:
            continue
        fo = next((ft for ft, f_ in members if f_), members[0][0])
        members_order = [fo] + [ft for ft, _ in members if ft is not fo]
        fo_id = "%s:%s" % building_key(fo["properties"])
        # per-piece summary (the own data, before the year is unified)
        parts = []
        for ft in members_order:
            p = ft["properties"]
            data_ = []
            if p.get("nev") and p["nev"] != name_:
                data_.append(str(p["nev"]))
            if p.get("ev"):
                data_.append(f"{p['ev']} ({p.get('ev_forras') or '?'})")
            if p.get("tervezo"):
                data_.append("tervező: " + str(p["tervezo"]))
            if p.get("lechner_epult"):
                data_.append("Lechner: " + str(p["lechner_epult"]))
            if p.get("stilus"):
                data_.append("stílus: " + str(p["stilus"]))
            if p.get("vedettseg") or p.get("muemlek_torzsszam"):
                data_.append("védett" + (f" (törzsszám {p['muemlek_torzsszam']})" if p.get("muemlek_torzsszam") else ""))
            if p.get("wikipedia"):
                data_.append("Wikipédia: " + str(p["wikipedia"]).replace("hu:", "").replace("|", ", "))
            if p.get("cim"):
                data_.append(str(p["cim"]))
            if p.get("szintek"):
                data_.append(f"{p['szintek']:g} szint" if isinstance(p["szintek"], (int, float)) else f"{p['szintek']} szint")
            if p.get("ev_becsles_korszak") is not None and not p.get("ev"):
                data_.append("évszáma becsült")
            parts.append("%s %s: %s" % (*building_key(p), "; ".join(data_) if data_ else "nincs külön adat"))
        # collected data
        all_ = {}
        for ft in members_order:
            for k, v in ft["properties"].items():
                if k in GROUP_PER_PART or k.startswith(("eubucco_", "ev_becsles_", "ev_kozelito_", "szintek", "magassag")) or v in (None, "", False):
                    continue
                if k in GROUP_MERGED:
                    present = [x for x in str(all_.get(k, "")).split("|") if x]
                    for x in str(v).split("|"):
                        if x and x not in present:
                            present.append(x)
                    all_[k] = "|".join(present[:3])
                elif k in GROUP_TEXT_MERGED:
                    present = [x for x in str(all_.get(k, "")).split("; ") if x]
                    if str(v) not in present and not any(str(v) in j or j in str(v) for j in present):
                        present.append(str(v))
                    all_[k] = "; ".join(present)
                elif k not in all_:
                    all_[k] = v
        # The mark of a Wikipedia article inherited from a zone ('wikipedia_zona') spreads to the group only if none of the group's articles is
        # the piece's own article; otherwise a piece with its own article would look zone-derived (and drop out of the Wikipedia layer).
        zone_article = [ft["properties"] for ft in members_order if ft["properties"].get("wikipedia")]
        zone_mark = next((p["wikipedia_zona"] for p in zone_article if p.get("wikipedia_zona")), None) \
            if zone_article and all(p.get("wikipedia_zona") for p in zone_article) else None
        wd_name = fo["properties"].get("wikidata_nev") or next((ft["properties"].get("wikidata_nev") for ft in members_order if ft["properties"].get("wikidata_nev")), None)
        year = next((ft["properties"].get("ev") for ft in members_order if ft["properties"].get("ev")), None)
        year_source = next((ft["properties"].get("ev_forras") for ft in members_order if ft["properties"].get("ev")), None)
        osm = "|".join("%s:%s" % building_key(ft["properties"]) for ft in members_order)
        for ft in members_order:
            p = ft["properties"]
            for k, v in all_.items():
                if k in GROUP_MERGED or k in GROUP_TEXT_MERGED or p.get(k) in (None, "", False):
                    p[k] = v
            if name_:
                p["nev"] = name_
            if wd_name:
                p["wikidata_nev"] = wd_name
            if zone_mark and p.get("wikipedia"):
                p["wikipedia_zona"] = zone_mark
            else:
                p.pop("wikipedia_zona", None)
            p["csoport"], p["csoport_nev"] = fo_id, name_ or None
            p["csoport_reszek"], p["csoport_osm"] = "\n".join(parts), osm
            if year:
                p["ev"], p["ev_forras"] = year, year_source
                for k in [k for k in p if k.startswith("ev_becsles_")]:
                    del p[k]
            part_count += 1
        group_count += 1
    return group_count, part_count


def append_zone_monument(feats):
    """The 'muemlek' (monument) type zones drawn in the zone editor (id: oeny_<register number>[_...]) write the monument register number,
    the protection and the E-Örökség (OENY) data-sheet id onto the buildings falling in them. A building that already has its
    own monument register number (from the address-based OENY pairing or by hand) is left alone."""
    path_ = Path("forras/zonak_poligon.geojson")
    if not path_.exists():
        return 0
    try:
        id_ = json.load(open("data/oeny_azonositok.json", encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        id_ = {}
    zones = []
    for f in json.load(open(path_, encoding="utf-8")).get("features", []):
        p, g = f.get("properties", {}), f.get("geometry", {})
        if p.get("tipus") != "muemlek" or g.get("type") != "Polygon":
            continue
        m = re.match(r"oeny_(\d+)", str(p.get("lista_id") or p.get("id") or ""))
        if not m:
            continue
        gy = g["coordinates"][0]
        xs, ys = [q[0] for q in gy], [q[1] for q in gy]
        zones.append((min(xs), min(ys), max(xs), max(ys), g["coordinates"], m.group(1)))
    count_ = 0
    for ft in feats:
        pr = ft["properties"]
        if pr.get("muemlek_torzsszam") or pr.get("rom"):
            continue
        g = ft["geometry"]
        ring_ = g["coordinates"][0] if g["type"] == "Polygon" else g["coordinates"][0][0] if g["type"] == "MultiPolygon" else None
        if ring_ is None:
            continue
        _, x, y = area_center(ring_)
        for x0, y0, x1, y1, coord, serial_no in zones:
            if x0 <= x <= x1 and y0 <= y <= y1 and point_in_polygon(x, y, coord):
                pr["muemlek_torzsszam"] = serial_no
                if not pr.get("vedettseg"):
                    pr["vedettseg"] = "M"
                if id_.get(serial_no):
                    pr["oeny_azonosito"] = "|".join(id_[serial_no][:3])
                count_ += 1
                break
    return count_


def value(field, x):
    return number(x) if field in NUMBERED else x


def _clip(ring_, p1, p2, left):
    """Sutherland-Hodgman: the part of the ring (lon, lat) on one side of the line p1->p2 (bal=True: the left side of the direction of travel).
    Computed in a metric-proportional plane (a degree of longitude is shorter)."""
    kx = math.cos(math.radians(47.5))
    def page(p):
        v = ((p2[0] - p1[0]) * kx) * (p[1] - p1[1]) - (p2[1] - p1[1]) * ((p[0] - p1[0]) * kx)
        return v if left else -v
    out = []
    n = len(ring_) - 1 if ring_[0] == ring_[-1] else len(ring_)
    for i in range(n):
        a, b = ring_[i], ring_[(i + 1) % n]
        oa, ob = page(a), page(b)
        if oa >= 0:
            out.append(a)
        if (oa >= 0) != (ob >= 0):
            t = oa / (oa - ob)
            out.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
    if len(out) < 3:
        return None
    out.append(out[0])
    return [list(p) for p in out]


def partition(feats):
    """forras/kezi_felosztas.csv: cuts one outline into two buildings along the line (lat1,lon1)->(lat2,lon2).
    a_id/b_id: ids of the new elements (empty: the original id*10+1 / *10+2); a = the left, b = the right side of the line's direction of travel.
    a_cim/b_cim: addresses of the new houses. Give the new elements' facts (ev, tervezo, szintek ...) in kezi_javitasok.csv under the new id."""
    if not Path(PARTITION).exists():
        return feats
    rows = [r for r in csv.DictReader(open(PARTITION, encoding="utf-8-sig", newline=""), delimiter=";") if (r.get("id") or "").strip().isdigit()]
    if not rows:
        return feats
    out, count_ = [], 0
    for ft in feats:
        pr = ft["properties"]
        k = ((pr.get("osm_tipus") or "way"), int(pr.get("id") or 0))
        r = next((x for x in rows if ((x.get("osm_tipus") or "way").strip(), int(x["id"])) == k), None)
        gy = ft["geometry"]["coordinates"]
        if r is None or len(gy) != 1:        # an outline with a hole is not cut
            out.append(ft)
            continue
        p1, p2 = (float(r["lon1"]), float(r["lat1"])), (float(r["lon2"]), float(r["lat2"]))
        parts = []
        for page, left in (("a", True), ("b", False)):
            new = _clip([tuple(p) for p in gy[0]], p1, p2, left)
            if new is None:
                continue
            id_ = (r.get(page + "_id") or "").strip()
            id_ = int(id_) if id_.isdigit() else k[1] * 10 + (1 if left else 2)
            pr2 = dict(pr)
            pr2["id"] = id_
            pr2["felosztott_ebbol"] = f"{k[0]}:{k[1]}"
            if (r.get(page + "_cim") or "").strip():
                pr2["felosztas_cim"] = r[page + "_cim"].strip()
            parts.append({"type": "Feature", "properties": pr2, "geometry": {"type": "Polygon", "coordinates": [new]}})
        if len(parts) == 2:
            out.extend(parts)
            count_ += 1
        else:
            out.append(ft)
    if count_:
        print(f"Felosztott épületek ({PARTITION}): {count_} körvonal kettévágva")
    return out


def handle_duplicates(feats):
    """Cleans geometries drawn on top of each other from the rows of forras/duplikatumok.csv ('alkalmaz' = igen), without losing data:
    - mod=gyuru: the same element's inner, redundant outline is deleted (gyuru_pontok is the vertex count of the outer ring);
    - mod=elem: all outlines of the deleted element are deleted; its facts (ALIAS) go to the kept element, and of its OSM properties
      it hands over whatever the kept one lacks (name, Wikidata, a more precise type, the actual number of storeys/height)."""
    if not Path(DUPLICATES).exists():
        return feats
    rows = []
    with open(DUPLICATES, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if (r.get("alkalmaz") or "").strip().lower() in ("igen", "i", "x", "1") and (r.get("torolt_id") or "").strip().isdigit():
                rows.append(r)
    if not rows:
        return feats
    key_ = lambda t, i: ((t or "way").strip(), int(i))
    delete_ring = defaultdict(set)
    delete_element = {}
    for r in rows:
        t = key_(r["torolt_tipus"], r["torolt_id"])
        if r.get("mod", "").strip() == "gyuru":
            if (r.get("torolt_gyuru_pontok") or "").strip().isdigit():
                delete_ring[t].add(int(r["torolt_gyuru_pontok"]))
        elif (r.get("megtartott_id") or "").strip().isdigit():
            delete_element[t] = key_(r["megtartott_tipus"], r["megtartott_id"])
    keys = defaultdict(list)
    for ft in feats:
        keys[building_key(ft["properties"])].append(ft)
    drop = set()
    gy_count = 0
    for t, points in delete_ring.items():
        list_ = keys.get(t, [])
        to_delete = [ft for ft in list_ if len(ft["geometry"]["coordinates"][0]) in points]
        if to_delete and len(to_delete) < len(list_):      # at least one outline always remains
            drop.update(id(ft) for ft in to_delete)
            gy_count += len(to_delete)
    el_count = 0
    for t, m in delete_element.items():
        if t == m or t not in keys or m not in keys:
            print(f"  duplikátum: kihagyva {t} -> {m} (nincs meg valamelyik)")
            continue
        for ft in keys[m]:
            mp = ft["properties"]
            for d in keys[t]:
                dp = d["properties"]
                for k_, v in dp.items():
                    if k_ in ("id", "osm_tipus", "resz", "kerulet", "szintek", "magassag", "magassag_forras"):
                        continue
                    if k_ == "tipus":
                        if mp.get("tipus") in (None, "", "yes") and v not in (None, "", "yes"):
                            mp["tipus"] = v
                    elif mp.get(k_) in (None, "") and v not in (None, ""):
                        mp[k_] = v
                if mp.get("magassag_forras") in (None, "alapertelmezett") and dp.get("magassag_forras") not in (None, "alapertelmezett"):
                    for k_ in ("szintek", "magassag", "magassag_forras"):
                        mp[k_] = dp.get(k_)
                elif mp.get("szintek") in (None, "") and dp.get("szintek") not in (None, "") and mp.get("magassag_forras") == "alapertelmezett":
                    mp["szintek"] = dp["szintek"]
        for ft in keys[t]:
            drop.add(id(ft))
        ALIAS[t] = m
        el_count += 1
    for t in list(ALIAS):                                  # resolving chains
        m = ALIAS[t]
        for _ in range(5):
            if m in ALIAS:
                m = ALIAS[m]
        ALIAS[t] = m
    print(f"Duplikátumok ({DUPLICATES}): {el_count} elem és {gy_count} fölösleges körvonal törölve, a tények átirányítva")
    return [ft for ft in feats if id(ft) not in drop]


def main():
    with open(PRIORITY, encoding="utf-8") as f:
        pri = json.load(f)
    from_ = pri.get("ev_tolerancia", 2)

    with open(OSM, encoding="utf-8") as f:
        gj = json.load(f)
    previous = len(gj["features"])
    gj["features"] = [x for x in gj["features"] if x["properties"].get("tipus") != "roof"]
    if len(gj["features"]) != previous:
        print(f"Tető-elemek kihagyva: {previous - len(gj['features'])}")
    feats = gj["features"]
    if Path(PARTS).exists():
        with open(PARTS, encoding="utf-8") as f:
            parts = json.load(f)["features"]
        has = {building_key(ft["properties"]) for ft in feats}
        parts = [r for r in parts if building_key(r["properties"]) not in has]
        for r in parts:
            r["properties"]["resz"] = True
        feats.extend(parts)
        print(f"  épületrészek (building:part): {len(parts)}")
    if Path(MANUAL_BUILDINGS).exists():
        with open(MANUAL_BUILDINGS, encoding="utf-8") as f:
            manual_ep = json.load(f)["features"]
        has = {building_key(ft["properties"]) for ft in feats}
        manual_ep = [x for x in manual_ep if building_key(x["properties"]) not in has]
        feats.extend(manual_ep)
        print(f"  kézzel felvett elemek ({MANUAL_BUILDINGS}): {len(manual_ep)}")
    if Path(EXCLUDED).exists():
        excluded = set()
        with open(EXCLUDED, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                if (r.get("id") or "").strip().isdigit():
                    excluded.add(((r.get("osm_tipus") or "way").strip(), int(r["id"].strip())))
        previous = len(feats)
        feats = [ft for ft in feats if (ft["properties"].get("osm_tipus") or "way", int(ft["properties"].get("id") or 0)) not in excluded]
        gj["features"] = feats
        print(f"Kizárt épületek ({EXCLUDED}): {previous - len(feats)} elem kihagyva a listán szereplő {len(excluded)} közül")
    feats = partition(feats)
    feats = handle_duplicates(feats)
    gj["features"] = feats
    index = defaultdict(list)
    for ft in feats:
        index[building_key(ft["properties"])].append(ft)

    # ---- collecting the facts ----
    facts = []
    for path_ in sorted(FACTS_FOLDER.glob("*.csv")):
        rows = read_facts(path_)
        facts += rows
        print(f"  {path_.name}: {len(rows)} sor")
    if Path(OENY_EXCLUDED).exists():
        oeny_out, oeny_partial = set(), defaultdict(set)   # full exclusion / removal of only one register number (data sheet)
        with open(OENY_EXCLUDED, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                if (r.get("id") or "").strip().isdigit():
                    kl = ((r.get("osm_tipus") or "way").strip(), int(r["id"].strip()))
                    serial_no = (r.get("torzsszam") or "").strip()
                    if serial_no.isdigit():
                        oeny_partial[kl].add(serial_no)
                    else:
                        oeny_out.add(kl)
        previous_t = len(facts)

        def oeny_remains(r):
            if r.get("forras") not in ("oeny", "oeny_koord"):
                return True
            kl = ((r.get("osm_tipus") or "way").strip(), int(r["id"]))
            if kl in oeny_out:
                return False
            if kl in oeny_partial:
                m = re.search(r"törzsszám (\d+)", r.get("megjegyzes") or "")
                serial_no = m.group(1) if m else (str(r.get("ertek")).strip() if r.get("mezo") == "muemlek_torzsszam" else "")
                if serial_no in oeny_partial[kl]:
                    return False
            return True
        facts = [r for r in facts if oeny_remains(r)]
        print(f"  E-Örökség kizárás ({OENY_EXCLUDED}): {previous_t - len(facts)} tény eldobva a listán szereplő {len(oeny_out)} elemről + {sum(len(v) for v in oeny_partial.values())} egyedi adatlapról")
    manual_rows = read_facts(MANUAL, "kezi") if Path(MANUAL).exists() else []
    for r in manual_rows:
        r["forras"] = "kezi"
    print(f"  kézi javítások: {len(manual_rows)} sor")

    # manual row without an id: the building is found by coordinates
    not_found = 0
    for r in manual_rows:
        if (r.get("id") or "").strip():
            continue
        try:
            x, y = float(r["lon"]), float(r["lat"])
        except (TypeError, ValueError):
            not_found += 1
            r["id"] = ""
            continue
        for ft in feats:
            if point_in_polygon(x, y, ft["geometry"]["coordinates"]):
                r["osm_tipus"], r["id"] = building_key(ft["properties"])
                break
        else:
            not_found += 1
            r["id"] = ""
    facts += manual_rows

    picked = defaultdict(lambda: defaultdict(list))   # key -> field -> [(source, value, remark)]
    unknown = 0
    for r in facts:
        try:
            k = ((r.get("osm_tipus") or "way").strip(), int(r["id"]))
        except (TypeError, ValueError):
            unknown += 1
            continue
        k = ALIAS.get(k, k)
        if k not in index:
            unknown += 1
            continue
        v = value(r["mezo"], r["ertek"])
        if r["forras"] == "kezi" and r["mezo"] in NUMBERED and str(r["ertek"]).strip() == "-":
            v = DELETE           # '-' in a manual correction: deletes the numeric field (year, storeys, height); it used to be lost silently
        if v in (None, ""):
            continue
        picked[k][r["mezo"]].append((r["forras"], v, r.get("megjegyzes", "")))
    if unknown or not_found:
        print(f"Figyelem: {unknown} tény-sor olyan épületre hivatkozik, ami nincs az OSM-fájlban; "
              f"{not_found} kézi sor nem azonosítható.")

    conflicts = []
    stat = {m: Counter() for m in DECIDING_FIELDS}
    for k, list_ in index.items():
        for ft in list_:
            pr = ft["properties"]
            tn = picked.get(k, {})
            # OSM's own data count as a source too
            sign = {m: list(tn.get(m, [])) for m in DECIDING_FIELDS}
            if pr.get("ev"):
                sign["ev"].append(("osm", pr["ev"], pr.get("ev_forras") or ""))
            if pr.get("szintek"):
                sign["szintek"].append(("osm", pr["szintek"], "building:levels"))
            if pr.get("magassag_forras") == "height":
                sign["magassag"].append(("osm_height", pr["magassag"], "height"))
            osm_year_source = pr.get("ev_forras")
            for m in DECIDING_FIELDS:          # manual deletion ('-'): if the latest manual row is a deletion, every source of the field drops out
                manual_m = [x for x in sign[m] if x[0] == "kezi"]
                sign[m] = [] if manual_m and manual_m[-1][1] is DELETE else [x for x in sign[m] if x[1] is not DELETE]

            for m in ("ev", "tervezo", "szintek"):
                chosen = None
                for source in pri[m]:
                    # for the manual correction the last value entered wins
                    for f_, v, remark in (reversed(sign[m]) if source == "kezi" else sign[m]):
                        if f_ == source:
                            chosen = (f_, v, remark)
                            break
                    if chosen:
                        break
                for f_, v, remark in sign[m]:   # conflicts
                    if chosen and f_ != chosen[0] and v != chosen[1] and (
                            m != "ev" or abs(v - chosen[1]) > from_) and (
                            m != "tervezo" or not designer_matches(v, chosen[1])):
                        conflicts.append((k[0], k[1], pr.get("nev") or "", m,
                                          f"{chosen[0]}={chosen[1]}", f"{f_}={v}"))
                if chosen:
                    f_, v, _ = chosen
                    pr[m] = v
                    stat[m][f_] += 1
                    if m == "tervezo":
                        pr["tervezo_forras"] = f_
                    if m == "ev":
                        pr["ev_forras"] = osm_year_source if f_ == "osm" else f_
                    elif m == "szintek":
                        pr["szintek_forras"] = f_
                else:
                    pr.pop(m, None)
                    if m == "tervezo":
                        pr.pop("tervezo_forras", None)
                    if m == "ev":
                        pr["ev_forras"] = None
            osm_level = next((v for f_, v, _ in sign["szintek"] if f_ == "osm"), None)
            if osm_level is not None:
                pr["szintek_osm"] = osm_level
            if pr.get("szintek") and osm_level and pr["szintek"] != osm_level:
                pr["szint_eltero"] = True
            else:
                pr.pop("szint_eltero", None)
            if pr.get("szintek") is None:
                pr.pop("szintek_forras", None)

            # height: the one computed from the number of storeys and the default are also marked
            if pr.get("szintek"):
                sign["magassag"].append(("szintbol", pr["szintek"] * pri["meter_szintenkent"], ""))
                pr["magassag_szintbol"] = pr["szintek"] * pri["meter_szintenkent"]
            sign["magassag"].append(("alapertelmezett", pri["alapertelmezett_magassag"], ""))
            chosen = None
            for source in pri["magassag"]:
                for f_, v, remark in (reversed(sign["magassag"]) if source == "kezi" else sign["magassag"]):
                    if f_ == source:
                        chosen = (f_, v)
                        break
                if chosen:
                    break
            f_, v = chosen
            if f_ in ("alapertelmezett", "eubucco_becsles"):
                # no measured height data: a small outbuilding (shed, pantry, kiosk) must not get 15 m, and the estimated EUBUCCO height
                # should not be taken over either if it comes from a larger neighbouring building of EUBUCCO (the kiosk falls into the large building's footprint)
                g_ = ft.get("geometry") or {}
                if g_.get("type") == "Polygon" and g_.get("coordinates"):
                    area_ = ring_area(g_["coordinates"])
                    if area_ < SMALL_BUILDING_M2:
                        v = SMALL_BUILDING_HEIGHT if (f_ == "alapertelmezett" or area_ < KIOSK_M2) else min(v, SMALL_BUILDING_MAX_ESTIMATED)
            pr["magassag"] = v
            stat["magassag"][f_] += 1
            if f_ == "osm_height":
                pr["magassag_forras"] = "height"
            elif f_ == "szintbol":
                pr["magassag_forras"] = "szintterkep" if pr.get("szintek_forras") == "szintterkep" else "szintszam"
            else:
                pr["magassag_forras"] = f_

            # every other fact as a simple property (the last item of the list is valid)
            for field, vals in tn.items():
                if field in DECIDING_FIELDS:
                    continue
                manual = [x for x in vals if x[0] == "kezi"]
                if not manual and field == "oeny_azonosito":   # a data sheet paired by OENY coordinates is more precise than one based on register number/address
                    manual = [x for x in vals if x[0] == "oeny_koord"]
                if manual:                            # the manual correction wins for the other fields as well
                    pr[field] = manual[-1][1]
                elif field in ("wikipedia", "oeny_azonosito"):   # articles / data sheets from several sources combined (at most 3)
                    unique = list(dict.fromkeys(str(x[1]) for x in vals))
                    pr[field] = "|".join(unique[:3])
                else:
                    pr[field] = vals[-1][1]
                if pr.get(field) is DELETE or pr.get(field) in ("-", ""):       # '-' = the manual correction removes the field
                    pr.pop(field, None)

    gj["features"], part_stat = handle_parts(feats)
    zone_dropped_count = overwrite_zone_weak_year(gj["features"])
    estimate_count = append_estimate(gj["features"])
    approximate_count = append_approximate(gj["features"])
    print(f"  Közelítő korszakadat (pl. '1920-as évek') a kártyára: {approximate_count} épület")
    address_count = append_addresses(gj["features"])
    import streetview
    print(f"  Utcai pont (utcakép-link): {streetview.compute(gj['features'], ADDRESSES)} épület")
    for ft in gj["features"]:                       # manually given address of the split houses
        if ft["properties"].get("felosztas_cim"):
            ft["properties"]["cim"] = ft["properties"].pop("felosztas_cim")
            ft["properties"].pop("cim_tobb", None)
    manual_addresses = {}                                  # forras/kezi_cimek.csv: osm_tipus;id;cim;megjegyzes - manual override of the address shown on the card
    if Path(MANUAL_ADDRESSES).exists():
        with open(MANUAL_ADDRESSES, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                if (r.get("id") or "").strip().isdigit() and (r.get("cim") or "").strip():
                    manual_addresses[((r.get("osm_tipus") or "way").strip(), int(r["id"]))] = r["cim"].strip()
    for ft in gj["features"]:
        k = building_key(ft["properties"])
        if k in manual_addresses:
            ft["properties"]["cim"] = manual_addresses[k]
            ft["properties"].pop("cim_tobb", None)
    zone_wiki_count = append_zone_wikipedia(gj["features"])
    zone_name_count = zone_name_assignment(gj["features"])
    print(f"  lakótelep-zóna neve: {zone_name_count} épületen")
    zone_plan_count = zone_designer_assignment(gj["features"])
    print(f"  zónából tervezőt kapott: {zone_plan_count} épület")
    clean_designer(gj["features"])        # before the groups are merged as well: so the same name is not duplicated
    zone_monument_count = append_zone_monument(gj["features"])
    zone_bp100_count = append_zone_budapest100(gj["features"])
    for ft in gj["features"]:   # local protection = a protection type of its own (HV), if there is no higher-level (M, MJ, VK, MK, MJT) protection
        pr = ft["properties"]
        if pr.get("vedettseg_helyi") and not pr.get("vedettseg"):
            pr["vedettseg"] = "HV"
    group_count, group_part_count = merge_groups(gj["features"])
    designer_bracket_count = clean_designer(gj["features"])
    print(f"  tervező-mező zárójeles tartalma törölve: {designer_bracket_count} elemnél (az utolsó körben)")
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(gj, f, ensure_ascii=False)
    exclude_path = Path("forras/epitesz_irodak.csv")      # the names excluded (not persons) from the Architects tab as a static file for the public site
    excluded = []
    if exclude_path.exists():
        with open(exclude_path, encoding="utf-8-sig", newline="") as f:
            excluded = sorted({r["kulcs"] for r in csv.DictReader(f, delimiter=";")
                             if r.get("kulcs") and r.get("tipus") in ("iroda", "intezmeny", "tobb_szemely", "nem_nev")})
    Path("terkep3d/epitesz_kizart.json").write_text(json.dumps(excluded, ensure_ascii=False), encoding="utf-8")
    Path(CONFLICTS).parent.mkdir(exist_ok=True)
    with open(CONFLICTS, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["osm_tipus", "id", "nev", "mezo", "gyoztes", "eltero_forras"])
        w.writerows(conflicts)

    print(f"\nÉpületek: {len(feats)}")
    print(f"  műemlék-zónákból műemléki adatot kapott: {zone_monument_count}")
    print(f"  zónából Budapest100-linket kapott: {zone_bp100_count}")
    print(f"  épületcsoport (több OSM-elem egy épületként): {group_count} csoport, {group_part_count} darab")
    print(f"  zónahatáron kívüli, gyenge forrású (EUBUCCO / közeli Wikidata) évszám eldobva, szürke lett: {zone_dropped_count}")
    for key_, count_ in part_stat.items():
        print(f"  épületrészek – {key_}: {count_}")
    print(f"  kiírt elemek: {len(gj['features'])}")
    print(f"  becsült korszakkal ellátott szürke épület: {estimate_count}")
    print(f"  címmel ellátott elem: {address_count}")
    print(f"  zóna-cikket kapott épület (Wikipédia): {zone_wiki_count}")
    for m in DECIDING_FIELDS:
        print(f"  {m}: {dict(stat[m])}")
    total = Counter(u[3] for u in conflicts)
    print(f"Ütközések (források eltérnek): {dict(total)}  -> {CONFLICTS}")
    print(f"Mentve: {OUTPUT}")


if __name__ == "__main__":
    main()
