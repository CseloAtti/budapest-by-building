"""The real names of public, commercial and industrial buildings from OpenStreetMap plot, area and point data
-> data/tenyek/kozepulet_nev.csv

Why is it needed? In OSM the name of a school, kindergarten, hospital, university is often not on the building's polygon, but on the plot
belonging to it (an amenity=school area) or on a separate point. The city building file contains only the building's own tags, so
these names were lost until now (about 21% of schools, 32% of kindergartens, 50% of hospitals have a name; for churches already 91%).

What does it do?
  1. With a single Overpass query it downloads Budapest's named elements: amenity/tourism (school, kindergarten, hospital, university,
     library, theatre, museum, church, office etc.), shop (shopping centre, supermarket, department store, DIY store...),
     landuse=retail/commercial/industrial plots, man_made=works and industrial=* (factories, plants), office, market. The answer goes into the data/cache/kozepulet_osm.json file (on a rerun
     it does not download again; with --frissit it does).
  2. Points (node): the building containing them gets the name.
  3. Areas (plots): of the buildings within the plot, those get the name whose type fits the function
     (building=school on a school plot, building=church on a church plot, building=industrial on a plant plot etc.). If there is none,
     then the largest building of a generic type (yes, public, civic...) on the plot, at least 300 m². It does not name sheds, garages,
     outbuildings. For named industrial/commercial/business areas (landuse) only if there are at most
     6 fitting buildings on them: the name of a large industrial park or district is not the name of a single building.
     It does not name a residential building (apartments, house, residential, terrace etc.) even by a point: the shop is on the ground floor, the house is not.
  4. A building that already has its own OSM name is not affected.
Output:   data/tenyek/kozepulet_nev.csv  (field: nev_kozepulet)   and   data/varos/kozepulet_nev_jelentes.md
Run: py facts_public_building_names.py          (afterwards: py assemble.py varos, py build_tiles.py varos)
The names come from OpenStreetMap (ODbL, © OpenStreetMap contributors)."""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

from common import client_name, building_key, point_in_ring, area_center, write_facts
from area_common import CITY_BOX, BuildingIndex

BUILDINGS = "data/varos/epuletek.geojson"
CACHE = Path("data/cache/kozepulet_osm.json")
OUTPUT = "data/tenyek/kozepulet_nev.csv"
REPORT = "data/varos/kozepulet_nev_jelentes.md"
SERVERS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
             "https://overpass.private.coffee/api/interpreter"]
SHOP = ("mall|department_store|supermarket|hypermarket|wholesale|doityourself|hardware|furniture|electronics|"
        "car|car_repair|garden_centre|convenience")
AMENITY = ("marketplace|school|kindergarten|college|university|hospital|clinic|library|theatre|cinema|townhall|courthouse|police|"
           "fire_station|community_centre|arts_centre|place_of_worship|social_facility|nursing_home|public_building|"
           "research_institute|conference_centre|events_venue")
MIN_SURFACE = 300.0

# function -> the building types (OSM building=*) that certainly belong to it
FITTING = {
    "school": {"school", "university", "college", "kindergarten"}, "kindergarten": {"kindergarten", "school"},
    "college": {"college", "university", "school"}, "university": {"university", "college", "school"},
    "hospital": {"hospital"}, "clinic": {"hospital", "clinic"}, "library": {"library", "public", "civic"},
    "theatre": {"theatre"}, "cinema": {"cinema", "theatre"}, "townhall": {"government", "civic", "public", "townhall"},
    "courthouse": {"government", "civic", "public", "courthouse"}, "police": {"government", "civic", "public"},
    "fire_station": {"fire_station"}, "community_centre": {"civic", "public"}, "arts_centre": {"civic", "public"},
    "place_of_worship": {"church", "chapel", "cathedral", "synagogue", "mosque", "temple", "monastery", "shrine"},
    "social_facility": {"civic", "public", "dormitory"}, "nursing_home": {"civic", "public", "residential"},
    "public_building": {"public", "civic", "government"}, "research_institute": {"university", "public", "civic", "office"},
    "conference_centre": {"public", "civic", "commercial"}, "events_venue": {"public", "civic", "commercial"},
    "museum": {"museum", "civic", "public"}, "gallery": {"civic", "public"}, "hotel": {"hotel"},
    "marketplace": {"retail", "commercial", "marketplace", "civic", "public"},
    # kereskedelem
    "mall": {"retail", "commercial", "mall", "supermarket"}, "department_store": {"retail", "commercial", "supermarket"},
    "supermarket": {"supermarket", "retail", "commercial"}, "hypermarket": {"supermarket", "retail", "commercial", "warehouse"},
    "wholesale": {"retail", "commercial", "warehouse", "industrial"},
    "doityourself": {"retail", "commercial", "warehouse"}, "hardware": {"retail", "commercial"},
    "furniture": {"retail", "commercial", "warehouse"}, "electronics": {"retail", "commercial"},
    "car": {"retail", "commercial"}, "car_repair": {"industrial", "commercial", "retail"},
    "garden_centre": {"retail", "commercial", "greenhouse"}, "convenience": {"retail", "commercial"},
    # area-like (landuse) and industry
    "landuse_retail": {"retail", "commercial", "supermarket", "mall"}, "landuse_commercial": {"commercial", "office", "retail"},
    "landuse_industrial": {"industrial", "warehouse", "factory", "manufacture"},
    "works": {"industrial", "factory", "manufacture", "warehouse"}, "industrial": {"industrial", "factory", "manufacture", "warehouse"},
    "office": {"office", "commercial"},
}
AREA = {"landuse_retail", "landuse_commercial", "landuse_industrial"}   # named large areas: only for few buildings
MAX_AREA_BUILDING = 6
GENERAL = {"yes", "public", "civic", "government", "institutional", "commercial", "office", "school", "hospital", "retail",
             "industrial", "warehouse"}
RESIDENTIAL = {"apartments", "house", "residential", "detached", "terrace", "semidetached_house", "dormitory", "bungalow", "farm",
        "static_caravan", "houseboat"}
SIDE = {"garage", "garages", "shed", "roof", "carport", "hut", "cabin", "service", "kiosk", "greenhouse", "barn",
          "stable", "container", "ruins", "construction", "tent", "bunker", "silo", "transformer_tower", "gatehouse"}
CELL = 0.002


def fetch():
    box = ",".join(str(x) for x in CITY_BOX)
    q = (f"[out:json][timeout:300];(nwr[\"amenity\"~\"^({AMENITY})$\"][\"name\"]({box});"
         f"nwr[\"tourism\"~\"^(museum|gallery|hotel)$\"][\"name\"]({box});"
         f"nwr[\"shop\"~\"^({SHOP})$\"][\"name\"]({box});"
         f"nwr[\"landuse\"~\"^(retail|commercial|industrial)$\"][\"name\"]({box});"
         f"nwr[\"man_made\"=\"works\"][\"name\"]({box});nwr[\"industrial\"][\"name\"]({box});"
         f"nwr[\"office\"~\"^(company|government|research|it|educational_institution)$\"][\"name\"]({box}););out tags geom;")
    error_ = None
    for server in SERVERS:
        url = server + "?" + urllib.parse.urlencode({"data": q})
        for try_ in (1, 2):
            try:
                print(f"Overpass-lekérdezés: {server} ({try_}. próba)...")
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": client_name()}), timeout=300) as r:
                    data_ = json.load(r)
                if data_.get("elements") is not None:
                    return data_
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as h:
                error_ = h
                print(f"  nem sikerült: {h}; várok 20 mp-et")
                time.sleep(20)
    sys.exit(f"Az Overpass-lekérdezés nem sikerült ({error_}). Próbáld később, vagy másik hálózaton.")


def records():
    if CACHE.exists() and "--frissit" not in sys.argv:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    data_ = fetch()
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(data_, ensure_ascii=False), encoding="utf-8")
    return data_


def function(c):
    a = c.get("amenity")
    if a in FITTING:
        return a
    for key_ in ("tourism", "shop"):
        if c.get(key_) in FITTING:
            return c[key_]
    if c.get("landuse") in ("retail", "commercial", "industrial"):
        return "landuse_" + c["landuse"]
    if c.get("man_made") == "works":
        return "works"
    if "industrial" in c:
        return "industrial"
    return "office" if "office" in c else None


def ring_element(e):
    """The plot's outer ring [(lon, lat), ...]; for a relation only if it consists of a single closed outer member."""
    if e["type"] == "way":
        g = [(p["lon"], p["lat"]) for p in e.get("geometry", [])]
        return g if len(g) >= 4 and g[0] == g[-1] else None
    if e["type"] == "relation":
        outer = [m for m in e.get("members", []) if m.get("role") == "outer" and m.get("geometry")]
        if len(outer) == 1:
            g = [(p["lon"], p["lat"]) for p in outer[0]["geometry"]]
            return g if len(g) >= 4 and g[0] == g[-1] else None
    return None


def main():
    data_ = records()
    elements = []
    for e in data_["elements"]:
        c = e.get("tags", {})
        name_ = " ".join(str(c.get("name", "")).split())
        f = function(c)
        if not f or len(name_) < 3 or "building" in c:       # if the element is itself the building, its name is already there
            continue
        elements.append((e, c, name_, f))
    print(f"Névvel ellátott funkcióelem: {len(elements)}")

    with open(BUILDINGS, encoding="utf-8") as fh:
        feats = [x for x in json.load(fh)["features"] if not x["properties"].get("resz")]
    index = BuildingIndex(feats)
    building = {}
    grid = defaultdict(list)
    for ft, pl in index.elements:
        p = ft["properties"]
        area_, cx, cy = area_center(pl[0][0])
        b = {"k": building_key(p), "nev": p.get("nev"), "tipus": p.get("tipus") or "yes", "ter": area_, "x": cx, "y": cy, "pl": pl}
        building[b["k"]] = b
        grid[(int(cx / CELL), int(cy / CELL))].append(b)

    best = {}     # building -> (rank, plot area, name, function, mode)

    def suggest(b, rank, plot, name_, f, mode):
        if b["nev"] or b["tipus"] in SIDE:
            return
        r = best.get(b["k"])
        if r is None or (rank, plot) < (r[0], r[1]):
            best[b["k"]] = (rank, plot, name_, f, mode)

    point_count = plot_count = skipped_rel = 0
    for e, c, name_, f in elements:
        if e["type"] == "node":
            ft = index.in_(e["lon"], e["lat"])
            if ft is not None:
                b = building[building_key(ft["properties"])]
                if b["tipus"] not in RESIDENTIAL and (b["tipus"] in FITTING[f] or b["tipus"] in GENERAL):
                    suggest(b, 1, 0, name_, f, "pont")
                    point_count += 1
            continue
        g = ring_element(e)
        if not g:
            skipped_rel += e["type"] == "relation"
            continue
        xs, ys = [p[0] for p in g], [p[1] for p in g]
        plot_area = area_center(g)[0]
        in_them = []
        for i in range(int(min(xs) / CELL), int(max(xs) / CELL) + 1):
            for j in range(int(min(ys) / CELL), int(max(ys) / CELL) + 1):
                for b in grid.get((i, j), ()):
                    if min(xs) <= b["x"] <= max(xs) and min(ys) <= b["y"] <= max(ys) and point_in_ring(b["x"], b["y"], g):
                        in_them.append(b)
        if not in_them:
            continue
        plot_count += 1
        fitting = [b for b in in_them if b["tipus"] in FITTING[f]]
        if f in AREA and len(fitting) > MAX_AREA_BUILDING:
            continue          # large industrial/business area: the name belongs to the area, not to a building
        if fitting:
            for b in fitting:
                suggest(b, 2, plot_area, name_, f, "telek, illő épülettípus")
        else:
            large = [b for b in in_them if b["tipus"] in GENERAL and b["ter"] >= MIN_SURFACE]
            if large and not (f in AREA and len(in_them) > MAX_AREA_BUILDING):
                suggest(max(large, key=lambda b: b["ter"]), 3, plot_area, name_, f, "telek, legnagyobb épület")

    rows = [(b[0], b[1], "nev_kozepulet", v[2], "osm_terulet", f"{v[3]}; {v[4]}") for k, v in best.items() for b in [k]]
    write_facts(OUTPUT, rows)

    mode = Counter(v[4] for v in best.values())
    fn = Counter(v[3] for v in best.values())
    row = ["# Középület-nevek az OSM telekadataiból", "",
           f"- névvel ellátott funkcióelem az OSM-ben: {len(elements)} (pont: {point_count} talált épületben, telek: {plot_count} épületet tartalmazó)",
           f"- új név: **{len(best)}** épületnek", f"- kihagyott összetett (több részes) telek: {skipped_rel}", "",
           "## Mód szerint"] + [f"- {k}: {v}" for k, v in mode.most_common()] + ["", "## Funkció szerint"] + \
          [f"- {k}: {v}" for k, v in fn.most_common()] + ["", "## Minta (az első 40)"]
    for (t, i), v in list(best.items())[:40]:
        row.append(f"- {t}/{i}: {v[2]} ({v[3]}; {v[4]})")
    Path(REPORT).write_text("\n".join(row), encoding="utf-8")
    print(f"Új név {len(best)} épületnek (pont: {mode.get('pont', 0)}, telek: {len(best) - mode.get('pont', 0)}).")
    print(f"Mentve: {OUTPUT}, {REPORT}")


if __name__ == "__main__":
    main()
