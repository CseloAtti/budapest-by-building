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
Run: py tenyek_kozepulet_nev.py          (afterwards: py osszeepit.py varos, py csempek_keszites.py varos)
The names come from OpenStreetMap (ODbL, © OpenStreetMap contributors)."""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

from kozos import kliens_nev, kulcs, pont_gyuruben, teruletu_kozeppont, tenyek_irasa
from terulet_kozos import VAROS_DOBOZ, EpuletIndex

EPULETEK = "data/varos/epuletek.geojson"
CACHE = Path("data/cache/kozepulet_osm.json")
KIMENET = "data/tenyek/kozepulet_nev.csv"
JELENTES = "data/varos/kozepulet_nev_jelentes.md"
SZERVEREK = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
             "https://overpass.private.coffee/api/interpreter"]
SHOP = ("mall|department_store|supermarket|hypermarket|wholesale|doityourself|hardware|furniture|electronics|"
        "car|car_repair|garden_centre|convenience")
AMENITY = ("marketplace|school|kindergarten|college|university|hospital|clinic|library|theatre|cinema|townhall|courthouse|police|"
           "fire_station|community_centre|arts_centre|place_of_worship|social_facility|nursing_home|public_building|"
           "research_institute|conference_centre|events_venue")
MIN_FELULET = 300.0

# function -> the building types (OSM building=*) that certainly belong to it
ILLO = {
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
TERULETI = {"landuse_retail", "landuse_commercial", "landuse_industrial"}   # named large areas: only for few buildings
MAX_TERULETI_EPULET = 6
ALTALANOS = {"yes", "public", "civic", "government", "institutional", "commercial", "office", "school", "hospital", "retail",
             "industrial", "warehouse"}
LAKO = {"apartments", "house", "residential", "detached", "terrace", "semidetached_house", "dormitory", "bungalow", "farm",
        "static_caravan", "houseboat"}
MELLEK = {"garage", "garages", "shed", "roof", "carport", "hut", "cabin", "service", "kiosk", "greenhouse", "barn",
          "stable", "container", "ruins", "construction", "tent", "bunker", "silo", "transformer_tower", "gatehouse"}
CELLA = 0.002


def lekeres():
    doboz = ",".join(str(x) for x in VAROS_DOBOZ)
    q = (f"[out:json][timeout:300];(nwr[\"amenity\"~\"^({AMENITY})$\"][\"name\"]({doboz});"
         f"nwr[\"tourism\"~\"^(museum|gallery|hotel)$\"][\"name\"]({doboz});"
         f"nwr[\"shop\"~\"^({SHOP})$\"][\"name\"]({doboz});"
         f"nwr[\"landuse\"~\"^(retail|commercial|industrial)$\"][\"name\"]({doboz});"
         f"nwr[\"man_made\"=\"works\"][\"name\"]({doboz});nwr[\"industrial\"][\"name\"]({doboz});"
         f"nwr[\"office\"~\"^(company|government|research|it|educational_institution)$\"][\"name\"]({doboz}););out tags geom;")
    hiba = None
    for szerver in SZERVEREK:
        url = szerver + "?" + urllib.parse.urlencode({"data": q})
        for proba in (1, 2):
            try:
                print(f"Overpass-lekérdezés: {szerver} ({proba}. próba)...")
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": kliens_nev()}), timeout=300) as r:
                    adat = json.load(r)
                if adat.get("elements") is not None:
                    return adat
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as h:
                hiba = h
                print(f"  nem sikerült: {h}; várok 20 mp-et")
                time.sleep(20)
    sys.exit(f"Az Overpass-lekérdezés nem sikerült ({hiba}). Próbáld később, vagy másik hálózaton.")


def adatok():
    if CACHE.exists() and "--frissit" not in sys.argv:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    adat = lekeres()
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(adat, ensure_ascii=False), encoding="utf-8")
    return adat


def funkcio(c):
    a = c.get("amenity")
    if a in ILLO:
        return a
    for kulcs_ in ("tourism", "shop"):
        if c.get(kulcs_) in ILLO:
            return c[kulcs_]
    if c.get("landuse") in ("retail", "commercial", "industrial"):
        return "landuse_" + c["landuse"]
    if c.get("man_made") == "works":
        return "works"
    if "industrial" in c:
        return "industrial"
    return "office" if "office" in c else None


def gyuru_elem(e):
    """The plot's outer ring [(lon, lat), ...]; for a relation only if it consists of a single closed outer member."""
    if e["type"] == "way":
        g = [(p["lon"], p["lat"]) for p in e.get("geometry", [])]
        return g if len(g) >= 4 and g[0] == g[-1] else None
    if e["type"] == "relation":
        kulso = [m for m in e.get("members", []) if m.get("role") == "outer" and m.get("geometry")]
        if len(kulso) == 1:
            g = [(p["lon"], p["lat"]) for p in kulso[0]["geometry"]]
            return g if len(g) >= 4 and g[0] == g[-1] else None
    return None


def main():
    adat = adatok()
    elemek = []
    for e in adat["elements"]:
        c = e.get("tags", {})
        nev = " ".join(str(c.get("name", "")).split())
        f = funkcio(c)
        if not f or len(nev) < 3 or "building" in c:       # if the element is itself the building, its name is already there
            continue
        elemek.append((e, c, nev, f))
    print(f"Névvel ellátott funkcióelem: {len(elemek)}")

    with open(EPULETEK, encoding="utf-8") as fh:
        feats = [x for x in json.load(fh)["features"] if not x["properties"].get("resz")]
    index = EpuletIndex(feats)
    epulet = {}
    racs = defaultdict(list)
    for ft, pl in index.elemek:
        p = ft["properties"]
        ter, cx, cy = teruletu_kozeppont(pl[0][0])
        b = {"k": kulcs(p), "nev": p.get("nev"), "tipus": p.get("tipus") or "yes", "ter": ter, "x": cx, "y": cy, "pl": pl}
        epulet[b["k"]] = b
        racs[(int(cx / CELLA), int(cy / CELLA))].append(b)

    legjobb = {}     # building -> (rank, plot area, name, function, mode)

    def javasol(b, rang, telek, nev, f, mod):
        if b["nev"] or b["tipus"] in MELLEK:
            return
        r = legjobb.get(b["k"])
        if r is None or (rang, telek) < (r[0], r[1]):
            legjobb[b["k"]] = (rang, telek, nev, f, mod)

    pont_db = telek_db = kihagyott_rel = 0
    for e, c, nev, f in elemek:
        if e["type"] == "node":
            ft = index.benne(e["lon"], e["lat"])
            if ft is not None:
                b = epulet[kulcs(ft["properties"])]
                if b["tipus"] not in LAKO and (b["tipus"] in ILLO[f] or b["tipus"] in ALTALANOS):
                    javasol(b, 1, 0, nev, f, "pont")
                    pont_db += 1
            continue
        g = gyuru_elem(e)
        if not g:
            kihagyott_rel += e["type"] == "relation"
            continue
        xs, ys = [p[0] for p in g], [p[1] for p in g]
        telek_ter = teruletu_kozeppont(g)[0]
        bennuk = []
        for i in range(int(min(xs) / CELLA), int(max(xs) / CELLA) + 1):
            for j in range(int(min(ys) / CELLA), int(max(ys) / CELLA) + 1):
                for b in racs.get((i, j), ()):
                    if min(xs) <= b["x"] <= max(xs) and min(ys) <= b["y"] <= max(ys) and pont_gyuruben(b["x"], b["y"], g):
                        bennuk.append(b)
        if not bennuk:
            continue
        telek_db += 1
        illo = [b for b in bennuk if b["tipus"] in ILLO[f]]
        if f in TERULETI and len(illo) > MAX_TERULETI_EPULET:
            continue          # large industrial/business area: the name belongs to the area, not to a building
        if illo:
            for b in illo:
                javasol(b, 2, telek_ter, nev, f, "telek, illő épülettípus")
        else:
            nagy = [b for b in bennuk if b["tipus"] in ALTALANOS and b["ter"] >= MIN_FELULET]
            if nagy and not (f in TERULETI and len(bennuk) > MAX_TERULETI_EPULET):
                javasol(max(nagy, key=lambda b: b["ter"]), 3, telek_ter, nev, f, "telek, legnagyobb épület")

    sorok = [(b[0], b[1], "nev_kozepulet", v[2], "osm_terulet", f"{v[3]}; {v[4]}") for k, v in legjobb.items() for b in [k]]
    tenyek_irasa(KIMENET, sorok)

    mod = Counter(v[4] for v in legjobb.values())
    fn = Counter(v[3] for v in legjobb.values())
    sor = ["# Középület-nevek az OSM telekadataiból", "",
           f"- névvel ellátott funkcióelem az OSM-ben: {len(elemek)} (pont: {pont_db} talált épületben, telek: {telek_db} épületet tartalmazó)",
           f"- új név: **{len(legjobb)}** épületnek", f"- kihagyott összetett (több részes) telek: {kihagyott_rel}", "",
           "## Mód szerint"] + [f"- {k}: {v}" for k, v in mod.most_common()] + ["", "## Funkció szerint"] + \
          [f"- {k}: {v}" for k, v in fn.most_common()] + ["", "## Minta (az első 40)"]
    for (t, i), v in list(legjobb.items())[:40]:
        sor.append(f"- {t}/{i}: {v[2]} ({v[3]}; {v[4]})")
    Path(JELENTES).write_text("\n".join(sor), encoding="utf-8")
    print(f"Új név {len(legjobb)} épületnek (pont: {mod.get('pont', 0)}, telek: {len(legjobb) - mod.get('pont', 0)}).")
    print(f"Mentve: {KIMENET}, {JELENTES}")


if __name__ == "__main__":
    main()
