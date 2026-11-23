"""
year_estimate.py - ESTIMATING the era of the grey buildings (those of unknown construction year).

Run (in the project folder):   py year_estimate.py

Uses only the Python standard library (no pip install).

What does it do?
  1. Reads data/belvaros_epuletek_vegleges.geojson. A building with a known year (ev) is a
     "labelled" building; the ones without one are estimated.
  2. For every grey building it computes a probability distribution over the 7 eras, from four
     pieces of evidence:
        neighbours   - nearby buildings of known age (directly attached ones count more)
        street       - buildings of known age on the same street
        shape        - number of storeys, footprint, building type (naive Bayes)
        zone         - forras/varosfejlodes.json (a sourced zone counts fully, one to be checked with weight 0.4)
  3. The weights of the evidence are measured on the known buildings: each known building is "hidden"
     in turn, and the program checks whether it would be guessed right. A report is written about the measurement.
  4. The estimate goes into a SEPARATE file (data/ev_becsles.csv); the 'ev' field is never overwritten.

For the whole city:   py year_estimate.py varos
  Input:   data/varos/epuletek_vegleges.geojson, data/varos/osm_cimek.csv, forras/varosfejlodes.json,
           forras/varosfejlodes_kerulet.json (district zones, with street lists), data/varos/ertekleltar_kozelito.csv
  Output:  data/varos/ev_becsles.csv, ev_becsles_jelentes.md, ev_becsles_munkalista.csv
  In city mode the street and the zone refer to the (district, street name) pair, the neighbour radius is larger (400 m),
  and the "1930s"-type data of the heritage inventories (if they fall into a single era) also count as labels (all data/varos/*_kozelito.csv) -
  these buildings appear in the estimate file with "high" certainty, marked with the heritage inventory as source.

In city mode (v2) the prior distribution of the grey buildings comes from building type x distance from the city core (ring)
  in forras/becsles_gyuru.json, and the weight of the neighbour/street evidence can be reduced per ring (0 in the outer ring:
  a building of known year does not affect its neighbours).
  The polygon zones of forras/zonak_poligon.geojson (from the zones.html drawing tool) are the strongest evidence:
  the grey buildings in them get weight for the given years. The "test" zones are not used by the estimator,
  it only measures itself on them (in the report).

Outputs:
  data/ev_becsles.csv            - the estimate per building
  data/ev_becsles_jelentes.md    - measurement report (accuracy, calibration, ablations)
  data/ev_becsles_munkalista.csv - which grey buildings are worth checking by hand
"""
import csv
import json
import re
import math
import sys
import unicodedata
import zlib
from collections import Counter, defaultdict
from pathlib import Path

CITY = "varos" in sys.argv[1:]
_ARGOK = [a for a in sys.argv[1:] if a != "varos"]
ROOT = Path(_ARGOK[0]) if _ARGOK else Path(__file__).resolve().parent
DATA = ROOT / "data" / "varos" if CITY else ROOT / "data"

# Identical to the KORSZAKOK array of index.html (if it changes there, change it here too).
ERAS = [
    (1, 1866, "1867 előtt"),
    (1867, 1918, "1867–1918"),
    (1919, 1944, "1919–1944"),
    (1945, 1956, "1945–1956"),
    (1957, 1989, "1957–1989"),
    (1990, 2010, "1990–2010"),
    (2011, 9999, "2011-től"),
]
K = len(ERAS)

NEIGHBOR_RADIUS = 400.0 if CITY else 150.0     # m: up to this distance a known building counts as a neighbour
NEIGHBOR_THIN_OUT = 80.0 if CITY else 40.0   # m: the weight is exp(-d/decay)
MAX_NEIGHBOR = 40          # in city mode: keep at most this many (nearest) known neighbours
CONTACT_M = 1.0         # m: if two buildings have a vertex within 1 m, they are considered attached
CONTACT_FACTOR = 3.0
BLOCK_M = 300.0            # m: grid size of the "block-exclusion" test


ZONE_FROM_BOUNDARY = True      # the drawn zone's "built from" year is a HARD lower bound for grey buildings (it does not affect a building of known year);
                           # "built until" is a bound only if the 'ig_hatar' switch is on for the zone
PZ_WEIGHT = 1.5                                  # fixed weight of a polygon zone (not tuned: the labels are distorted)
PZ_STATE_WEIGHT = {"helyismeret": 1.0, "forrasolt": 1.0, "ellenorizendo": 0.4}
PZ_LIST = []
RING_NAMES = ["belváros (0–2 km)", "belső gyűrű (2–3 km)", "középső gyűrű (3–6 km)", "külső gyűrű (6+ km)"]
FIT_KSH = True       # city mode: adjusts the final estimate to the district KSH proportions (data/KSH/budapest_ksh_keruleti_eloszlas.csv)
ENCLAVE_WEIGHT = 0.1         # multiplier of the neighbourhood and street effect of "enclave" buildings (church, chapel, synagogue, monastery, ruin etc.):
                           # an old church does not make the houses around it older in its newer surroundings (0 = no effect, 1 = like any house)
FIRST_ERA_MIN_P = 0.10  # the KSH quota may assign the "before 1867" era to a grey building only if the A model (neighbour, street, zone, shape)
                           # on its own gives it at least this probability; without evidence the quota does not "scatter" pre-1867 buildings (0 = off)
FIRST_ERA_DISTRICT_MAX = 0.10   # ...but only in districts where, according to KSH, the proportion of pre-1867 buildings is smaller than this (in the Castle District/Víziváros, where there are many old houses, there is no limit)
LOCAL_QUOTA = True         # the KSH quota is distributed within a district in patches of HELYI_CELLA_M (old houses stay where the model expects them)
LOCAL_CELL_M = 500.0
LOCAL_ONLY_OUTER = True    # the local quota only in the outer ring (6 km+, together with the drawn zones); in the inner rings the district-level distribution stays
NOISE_WEIGHT = 6.0             # the random (but deterministic) part of the ordering: larger = more scattered old houses
OUTER_OLD_FACTOR = 0.25    # outer ring: this share of the old (pre-1945) houses expected by the model remains (demolitions)
KSH_TOLERANCE = 0.5           # percentage points: by this much the district's KSH deviation may grow because of the demolition multiplier
OLD_ERAS = (1, 2)    # indices of the "old" eras (1867-1918, 1919-1944)
MAIN_WEIGHT = 1.0            # outer ring, within the local quota: a house more than 300 m from the main road ranks about one era "younger" (a rule, not measured)
ORDER_KAPPA = 2.0        # strength of the ordering in distributing the quota (0 = no ordering; larger = the ordering overrides weak evidence more)
RING_KM = [2.0, 3.0, 6.0]
NEIGHBOR_WEIGHT = [1.0, 1.0, 0.5, 0.0, 1.0, 0.5]
SHAPE_WEIGHT = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0]      # multiplier of the shape evidence (F) per ring; F also learns from buildings of known year
GLOBAL_MIXING = 0.1
GH = {"min_m2": 300.0, "suly": 0.7, "eps": 0.05, "max": 5.0, "utolso": 0.03}   # GHSL evidence (forras/becsles_gyuru.json: "ghsl")
GHSL_STAT = Counter()
CENTER = (47.4979, 19.0540)
PRIORITY_TYPES = {}
PUBLIC_BUILDING = {"school", "kindergarten", "university", "college", "hospital", "church", "chapel", "cathedral", "public",
             "civic", "government", "theatre", "museum", "train_station", "fire_station", "mosque", "synagogue",
             "temple", "monastery", "clinic", "library", "stadium", "sports_hall", "sports_centre", "gymnasium"}
SIDE = {"garage", "garages", "shed", "roof", "carport", "hut", "cabin", "service", "kiosk", "greenhouse", "barn",
          "stable", "container", "ruins", "construction", "tent", "bunker", "silo", "transformer_tower", "gatehouse"}
INDUSTRIAL = {"industrial", "warehouse", "factory", "manufacture", "storage", "hangar"}
COMMERCIAL = {"retail", "commercial", "supermarket", "mall", "office", "hotel", "kiosk_shop", "fuel_station"}
ENCLAVE_TYPES = {"church", "chapel", "cathedral", "mosque", "synagogue", "temple", "monastery", "ruins", "castle", "fort", "city_gate"}
ENCLAVE_NAME = re.compile(r"(?i)\b(templom|kápolna|székesegyház|bazilika|zsinagóga|mecset|kolostor|plébánia|rom|romok|romkert|erőd|kastély)\b")
ROW_HOUSE = {"terrace", "semidetached_house", "semi", "terraced_house"}


def era_index(year):
    for i, (from_, to, _) in enumerate(ERAS):
        if from_ <= year <= to:
            return i
    return None


def read_priority():
    """forras/becsles_gyuru.json -> the global tables. If the file is missing, the built-in defaults are used."""
    global RING_KM, NEIGHBOR_WEIGHT, SHAPE_WEIGHT, GH, GLOBAL_MIXING, CENTER, PRIORITY_TYPES
    path_ = ROOT / "forras" / "becsles_gyuru.json"
    if not path_.exists():
        print("Figyelem: nincs forras/becsles_gyuru.json - a gyűrűs prior nélkül fut.")
        return False
    d = json.load(open(path_, encoding="utf-8"))
    RING_KM = [float(x) for x in d.get("gyuruk_km", RING_KM)]
    NEIGHBOR_WEIGHT = [float(x) for x in d.get("szomszed_suly", NEIGHBOR_WEIGHT)]
    SHAPE_WEIGHT = [float(x) for x in d.get("alak_suly", SHAPE_WEIGHT)]
    GH = dict(GH, **{k: float(v) for k, v in d.get("ghsl", {}).items() if k in GH})
    for list_, base in ((NEIGHBOR_WEIGHT, [1.0, 1.0, 0.5, 0.0, 1.0, 0.5]), (SHAPE_WEIGHT, [1.0] * 6)):
        while len(list_) < len(base):
            list_.append(base[len(list_)])
    GLOBAL_MIXING = float(d.get("global_keveres", GLOBAL_MIXING))
    CENTER = tuple(d.get("kozpont", CENTER))
    PRIORITY_TYPES = {}
    for kind, cells in d["tipusok"].items():
        list_ = []
        for c in cells:
            components_ = c if isinstance(c[0], list) else [c]
            e = [0.0] * K
            total = sum((o[2] if len(o) > 2 else 1.0) for o in components_)
            for o in components_:
                w = (o[2] if len(o) > 2 else 1.0) / total
                for y, p in enumerate(zone_distribution(int(o[0]), int(o[1]))):
                    e[y] += w * p
            list_.append(e)
        PRIORITY_TYPES[kind] = list_
    return True


def read_polygon_zones():
    """forras/zonak_poligon.geojson -> PZ_LISTA (local ring zones in metres)."""
    PZ_LIST.clear()
    path_ = ROOT / "forras" / "zonak_poligon.geojson"
    if not path_.exists():
        return
    for f in json.load(open(path_, encoding="utf-8")).get("features", []):
        try:
            p = f["properties"]
            if p.get("tipus") == "muemlek":
                continue  # OENY monument polygon: not year evidence
            gy = f["geometry"]["coordinates"][0]
            ring = [((x - 19.05) * math.cos(math.radians(47.5)) * 111320.0, (y - 47.5) * 110574.0) for x, y in gy]
            xs, ys = [q[0] for q in ring], [q[1] for q in ring]
            a2 = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(ring, ring[1:]))
            PZ_LIST.append({"id": p["id"], "nev": p.get("nev") or p["id"], "tol": int(p["ev_tol"]), "ig": int(p["ev_ig"]),
                             "mero": bool(p.get("mero")), "ig_hatar": bool(p.get("ig_hatar")), "suly": PZ_STATE_WEIGHT.get(p.get("allapot"), 0.4),
                             "ring": ring, "bbox": (min(xs), min(ys), max(xs), max(ys)), "terulet": abs(a2) / 2,
                             "eloszlas": zone_distribution(int(p["ev_tol"]), int(p["ev_ig"])), "tipus": p.get("tipus", "")})
        except (KeyError, TypeError, ValueError, IndexError):
            continue


def point_in_ring_xy(x, y, ring):
    be = False
    for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            be = not be
    return be


def polygon_zones_assign(ep):
    """For every building: e['pz'] = the smallest containing, NON-test zone (for the estimate); e['pz_tag'] = every containing zone."""
    for e in ep:
        e["pz"] = None
        e["pz_tag"] = []
    for zi, z in enumerate(PZ_LIST):
        x0, y0, x1, y1 = z["bbox"]
        for e in ep:
            if x0 <= e["x"] <= x1 and y0 <= e["y"] <= y1 and point_in_ring_xy(e["x"], e["y"], z["ring"]):
                e["pz_tag"].append(zi)
                if not z["mero"] and (e["pz"] is None or z["terulet"] < PZ_LIST[e["pz"]]["terulet"]):
                    e["pz"] = zi


def ring_index(x, y):
    kx, ky = (CENTER[1] - 19.05) * math.cos(math.radians(47.5)) * 111320.0, (CENTER[0] - 47.5) * 110574.0
    km = math.hypot(x - kx, y - ky) / 1000.0
    for i, h in enumerate(RING_KM):
        if km < h:
            return i, km
    return len(RING_KM), km


def connections_number(ep):
    """With how many other buildings does it share a vertex (roughly a shared wall)? Fast: vertices rounded to a 0.5 m grid."""
    store = defaultdict(set)
    for i, e in enumerate(ep):
        for x, y in e["pts"]:
            store[(round(x * 2), round(y * 2))].add(i)
    for i, e in enumerate(ep):
        t = set()
        for x, y in e["pts"]:
            t |= store[(round(x * 2), round(y * 2))]
        t.discard(i)
        e["kapcs"] = len(t)


def building_type(e, gy):
    t = e["tipus"]
    if t in PUBLIC_BUILDING or t in SIDE:
        return "nincs"
    if t in INDUSTRIAL:
        return "ipari"
    if t in COMMERCIAL:
        return "kereskedelmi"
    if t in ROW_HOUSE:
        return "sorhaz"
    try:
        sz = float(e["szintek"])
    except (TypeError, ValueError):
        sz = None
    a, k = e["terulet"], e["kapcs"]
    if sz is not None and sz >= 4 and a >= 450 and k == 0 and gy >= 1:
        return "panel"
    if (sz is not None and sz >= 3) or t == "apartments":
        return "berhaz"
    if sz is None and a >= 700 and k == 0:
        return "nincs"
    if sz is None and a >= 300 and k >= 1:
        return "berhaz"
    if k >= 2 and a < 350 and gy >= 2 and (sz is None or sz <= 3):
        return "sorhaz"
    if a < 400:
        return "csaladi"
    return "nincs"


ROMAN_DISTRICT = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12,
             "XIII": 13, "XIV": 14, "XV": 15, "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20, "XXI": 21, "XXII": 22,
             "XXIII": 23}


def district_number(v):
    if v in (None, ""):
        return None
    t = str(v).strip().strip(".").upper()
    if t in ROMAN_DISTRICT:
        return ROMAN_DISTRICT[t]
    try:
        n = int(float(t))
        return n if 1 <= n <= 23 else None
    except ValueError:
        return None


def read_ksh():
    """data/KSH/budapest_ksh_keruleti_eloszlas.csv -> {district: [7 proportions]} (they sum to 1). Missing file: None."""
    path_ = ROOT / "data" / "KSH" / "budapest_ksh_keruleti_eloszlas.csv"
    if not path_.exists():
        return None
    d = {}
    for r in csv.DictReader(open(path_, encoding="utf-8-sig")):
        v = [float(r[k]) for k in r if k.startswith("arany_")]
        n = district_number(r.get("kerulet"))
        if len(v) != K or not n or sum(v) <= 0:
            return None
        z = sum(v)
        d[n] = [x / z for x in v]
    return d


NOT_DWELLING = SIDE | PUBLIC_BUILDING | INDUSTRIAL | COMMERCIAL


def dwelling_weight(e):
    """Dwelling equivalent (KSH counts dwellings): footprint x number of storeys; outbuilding, public, industry, commerce: 0."""
    if e["tipus"] in NOT_DWELLING or e["terulet"] < 40.0:
        return 0.0
    sz = e.get("szintek")
    if not sz and e.get("magassag") and e.get("mforras") not in (None, "", "alapertelmezett"):
        sz = float(e["magassag"]) / 3.3
    try:
        sz = max(1.0, min(float(sz), 40.0)) if sz else 2.0
    except (TypeError, ValueError):
        sz = 2.0
    return e["terulet"] * sz


def allocate_quota(gray, res, R, Q, weights, old, banned0):
    """Quota-keeping allocation over a group of buildings. R: per-era target (dwelling equivalent) for the
    (dwelling-weighted) buildings. The weighted percentile by the order (oreg) is fitted to the era's quota band, and the mu
    shift adjusts the allocated masses to the target. tiltott0: those who may not receive the 'before 1867' era.
    Returns: {i: per-era scores}; the allocated era is the one with the highest score."""
    order = sorted(gray, key=old)
    total_w = sum(weights[i] for i in gray) or 1.0
    pct, cumulative = {}, 0.0
    for i in order:
        pct[i] = (cumulative + weights[i] / 2) / total_w
        cumulative += weights[i]
    sr = sum(R) or 1.0
    f = [r / sr for r in R]
    middle, front = [], 0.0
    for c in range(K):
        middle.append(front + f[c] / 2)
        front += f[c]
    LQ = {i: [(-1e9 if (Q[i][c] <= 0.0 or (c == 0 and i in banned0)) else math.log(Q[i][c] + 1e-9) - ORDER_KAPPA * ((pct[i] - middle[c]) / (f[c] + 0.15)) ** 2)
              for c in range(K)] for i in gray}
    mu = fit_mass(res, LQ, R, weights)
    return {i: [LQ[i][x] + mu[x] for x in range(K)] for i in gray}


def fit_mass(res, point, R, weights):
    """Per-era shift (mu) by which the dwelling-weighted sum of the best eras by score gets close to the target (R)."""
    U = sum(weights[i] for i in res)
    mu = [0.0] * K
    if res and U > 0:
        step, best = 0.6, (1e18, mu[:])
        for _ in range(60):
            mm = [0.0] * K
            for i in res:
                lq = point[i]
                c = max(range(K), key=lambda x: lq[x] + mu[x])
                mm[c] += weights[i]
            error_ = sum(abs(mm[c] - R[c]) for c in range(K))
            if error_ < best[0]:
                best = (error_, mu[:])
            if error_ < 0.005 * U:
                break
            eps = 0.01 * U / K
            mu = [mu[c] + step * math.log((R[c] + eps) / (mm[c] + eps)) for c in range(K)]
            step *= 0.97
        mu = best[1]
    return mu


def main_roads_distance(ep):
    """Outer ring (6 km+): the distance of the grey buildings from the nearest main road (OSM primary/secondary/tertiary/trunk) and
    from a main-road junction (a shared point of two main roads with different names). e['fout_pont'] = min(road, 600 m)/300 + min(junction, 1200 m)/1200:
    smaller = closer to the old settlement structure. Input: data/utak_nyers.json (build_roads.py). Returns the number of buildings computed."""
    path_ = ROOT / "data" / "utak_nyers.json"
    if not path_.exists():
        print("Figyelem: nincs data/utak_nyers.json - a helyi kvóta főút-sorrend nélkül fut.")
        return 0
    FO = {"primary", "secondary", "tertiary", "trunk"}
    cx_m = math.cos(math.radians(47.5)) * 111320.0
    CELL, MAX_PATH, MAX_DISTRICT = 100.0, 600.0, 1200.0
    grid, vertex = defaultdict(list), defaultdict(set)
    for u in json.load(open(path_, encoding="utf-8")):
        if u.get("h") not in FO or len(u.get("g") or []) < 2:
            continue
        pts = [((x - 19.05) * cx_m, (y - 47.5) * 110574.0) for x, y in u["g"]]
        for a, b in zip(pts, pts[1:]):
            for gx in range(int(min(a[0], b[0]) // CELL), int(max(a[0], b[0]) // CELL) + 1):
                for gy in range(int(min(a[1], b[1]) // CELL), int(max(a[1], b[1]) // CELL) + 1):
                    grid[(gx, gy)].append((a, b))
        for (x, y), p in zip(u["g"], pts):
            vertex[(round(x, 6), round(y, 6))].add(u.get("n") or str(id(u)))
    kr = defaultdict(list)
    for (x, y), names in vertex.items():
        if len(names) >= 2:
            p = ((x - 19.05) * cx_m, (y - 47.5) * 110574.0)
            kr[(int(p[0] // CELL), int(p[1] // CELL))].append(p)

    def section(p, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = dx * dx + dy * dy
        t = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L))
        return math.dist(p, (a[0] + t * dx, a[1] + t * dy))
    ru, rk = int(MAX_PATH // CELL), int(MAX_DISTRICT // CELL)
    count_ = 0
    for e in ep:
        if e["kor"] is not None or e.get("gyuru") != 3:
            continue
        p, gx, gy = (e["x"], e["y"]), int(e["x"] // CELL), int(e["y"] // CELL)
        du = MAX_PATH
        for dx in range(-ru, ru + 1):
            for dy in range(-ru, ru + 1):
                for a, b in grid.get((gx + dx, gy + dy), ()):
                    du = min(du, section(p, a, b))
        dk = MAX_DISTRICT
        for dx in range(-rk, rk + 1):
            for dy in range(-rk, rk + 1):
                for q in kr.get((gx + dx, gy + dy), ()):
                    dk = min(dk, math.dist(p, q))
        e["fout_m"] = du
        e["fout_pont"] = du / MAX_PATH * 2 + dk / MAX_DISTRICT
        count_ += 1
    return count_


def ksh_quota(ep, grey, PP, ksh):
    """District KSH fitting. PP: {i: the A model's distribution}. Returns: ({i: (top, q, lambda_top, rearranged)}, diagnostics).
    1) per district, computes how much dwelling-equivalent mass is missing for the KSH target after the buildings of known year (R);
    2) with per-era multipliers (lambda) it shifts the A probabilities so that R comes out in expectation;
    3) allocation: instead of the most probable class, log q + order term + mu: the order term fits the percentile by the building's
       expected era to the era's quota band (a building that looks older gets an older era), and mu adjusts the allocated
       masses to the quota. Strong A evidence (zone, neighbours) overrides the order, with weak evidence the order decides."""
    grey_set = set(grey)
    weights = [dwelling_weight(e) for e in ep]
    round_ = defaultdict(list)
    for i, e in enumerate(ep):
        round_[district_number(e.get("kerulet"))].append(i)
    total = sum(weights[i] for k in ksh for i in round_[k]) or 1.0
    average = [sum(ksh[k][c] * sum(weights[i] for i in round_[k]) for k in ksh) / total for c in range(K)]
    result_, diag = {}, []
    old_factor = {}
    for district, list_ in sorted(round_.items(), key=lambda kv: (kv[0] is None, kv[0] or 0)):
        T = ksh.get(district, average)
        M = sum(weights[i] for i in list_)
        Kd = [0.0] * K
        for i in list_:
            if i not in grey_set and ep[i]["kor"] is not None:
                Kd[ep[i]["kor"]] += weights[i]
        gray = [i for i in list_ if i in grey_set]
        res = [i for i in gray if weights[i] > 0]
        U = sum(weights[i] for i in res)
        lam = [1.0] * K
        R = [U * T[c] for c in range(K)]
        if M > 0 and U > 0:
            R = [max(M * T[c] - Kd[c], 0.0) for c in range(K)]
            sr = sum(R)
            R = [r * U / sr for r in R] if sr > 0 else [U * T[c] for c in range(K)]
            P = [PP[i] for i in res]
            W = [weights[i] for i in res]
            for _ in range(30):
                mm = [0.0] * K
                for p, w in zip(P, W):
                    z = sum(p[c] * lam[c] for c in range(K))
                    if z > 0:
                        for c in range(K):
                            mm[c] += w * p[c] * lam[c] / z
                for c in range(K):
                    if R[c] <= 0:
                        lam[c] = 0.02
                    elif mm[c] > 0:
                        lam[c] = min(max(lam[c] * (R[c] / mm[c]) ** 0.6, 0.02), 50.0)
        Q = {}
        for i in gray:
            q = [PP[i][c] * lam[c] for c in range(K)]
            z = sum(q) or 1.0
            Q[i] = [v / z for v in q]
        if gray:
            banned0 = {i for i in gray if T[0] < FIRST_ERA_DISTRICT_MAX and PP[i][0] < FIRST_ERA_MIN_P}

            def old(i):
                e = ep[i]
                # the A model's expected era index (from the quota-multiplied distribution) + a tiny, deterministic tie-breaker
                v = sum(c * Q[i][c] for c in range(K)) + 0.02 * ((zlib.crc32(str(e.get("id", i)).encode()) % 10000) / 10000.0)
                if LOCAL_QUOTA and e.get("fout_pont") is not None:
                    # outer ring: a house closer to the main road / junction is MORE LIKELY older, but not all of them:
                    # the deterministic noise scatters the old houses (otherwise the row of houses along the road would all be old)
                    noise = (zlib.crc32(("zaj" + str(e.get("id", i))).encode()) % 100000) / 100000.0
                    v += MAIN_WEIGHT * e["fout_pont"] + NOISE_WEIGHT * noise
                return v

            if LOCAL_QUOTA:
                # local quota: within the district, per patch of HELYI_CELLA_M, the sum of the (KSH-multiplied) probabilities is allocated,
                # so the old houses stay where the model expects them (e.g. Pesthidegkút), and the district total does not change
                patches = defaultdict(list)
                for i in gray:
                    if LOCAL_ONLY_OUTER and ep[i].get("gyuru") != 3:
                        patches["kerulet"].append(i)       # inner rings (within 6 km): the old, district-level allocation; this also takes over the demolition deficit
                    else:
                        patches[(int(ep[i]["x"] // LOCAL_CELL_M), int(ep[i]["y"] // LOCAL_CELL_M))].append(i)
                def local_point(factor):
                    point, Rd = {}, [0.0] * K
                    targets = {}
                    transfer = [0.0] * K           # the target passed from the outer patches to the rest of the district (old eras +, new ones -)
                    for building_key, members in patches.items():
                        fres = [i for i in members if weights[i] > 0]
                        Rf = [0.0] * K
                        for i in fres:
                            q = [0.0 if (c == 0 and i in banned0) else Q[i][c] for c in range(K)]
                            z = sum(q) or 1.0
                            for c in range(K):
                                Rf[c] += weights[i] * q[c] / z
                        if building_key != "kerulet" and factor < 1.0:
                            # garden suburb: most of the old houses were demolished -> fewer old, more recent houses in the patch
                            el = sum(Rf[c] * (1 - factor) for c in OLD_ERAS)
                            new = [c for c in range(K) if c not in OLD_ERAS and c > max(OLD_ERAS)]
                            new_total = sum(Rf[c] for c in new) or 1.0
                            for c in OLD_ERAS:
                                transfer[c] += Rf[c] * (1 - factor)
                                Rf[c] *= factor
                            for c in new:
                                d = el * Rf[c] / new_total
                                Rf[c] += d
                                transfer[c] -= d
                        targets[building_key] = (members, fres, Rf)
                    if "kerulet" in targets:            # the rest of the district (inner rings, zones) takes over the shortfall, so the KSH total does not change
                        members, fres, Rf = targets["kerulet"]
                        targets["kerulet"] = (members, fres, [max(a + b, 0.0) for a, b in zip(Rf, transfer)])
                    for members, fres, Rf in targets.values():
                        point.update(allocate_quota(members, fres, Rf, Q, weights, old, banned0))
                        Rd = [a + b for a, b in zip(Rd, Rf)]
                    # district equalisation: the rounding error of the small patches would add up, so a common shift sets the district total to the target
                    mu2 = fit_mass(res, point, Rd, weights)
                    point = {i: [v + m for v, m in zip(point[i], mu2)] for i in gray}
                    return point

                def deviation(point):
                    mm = [0.0] * K
                    for i in list_:
                        cc = max(range(K), key=lambda x: point[i][x]) if i in grey_set else ep[i]["kor"]
                        if cc is not None and weights[i] > 0:
                            mm[cc] += weights[i]
                    z = sum(mm) or 1.0
                    return max(abs(100 * mm[cc] / z - 100 * T[cc]) for cc in range(K))
                # the demolition multiplier is set per district to the strongest value at which the KSH deviation grows by at most KSH_TURES points
                point = local_point(1.0)
                used = 1.0
                if OUTER_OLD_FACTOR < 1.0:
                    base_e = deviation(point)
                    for sz in sorted({OUTER_OLD_FACTOR} | {s for s in (0.33, 0.5, 0.75) if s > OUTER_OLD_FACTOR}):
                        p_ = local_point(sz)
                        if deviation(p_) <= base_e + KSH_TOLERANCE:
                            point, used = p_, sz
                            break
                old_factor[district] = used
            else:
                point = allocate_quota(gray, res, R, Q, weights, old, banned0)
            for i in gray:
                top = max(range(K), key=lambda x: point[i][x])
                result_[i] = (top, Q[i], lam[top], top != max(range(K), key=lambda x: PP[i][x]))

        def ratio(choose):
            mm = [0.0] * K
            for i in list_:
                c = choose(i) if i in grey_set else ep[i]["kor"]
                if c is not None and weights[i] > 0:
                    mm[c] += weights[i]
            z = sum(mm) or 1.0
            return [100 * v / z for v in mm]
        before = ratio(lambda i: max(range(K), key=lambda x: PP[i][x]))
        after = ratio(lambda i: result_[i][0] if i in result_ else None)
        target = [100 * v for v in T]
        diag.append({"regi_szorzo": old_factor.get(district), "ker": district, "db": len(list_), "szurke": len(gray), "cel": target, "elotte": before, "utana": after,
                     "lam": max(lam), "elter_elotte": max(abs(a - b) for a, b in zip(before, target)),
                     "elter_utana": max(abs(a - b) for a, b in zip(after, target)),
                     "atrendezett": sum(1 for i in gray if i in result_ and result_[i][3])})
    return result_, diag


def ksh_report(diag):
    row = ["## KSH-illesztés kerületenként (lakás-egyenérték szerinti %, a tudott évű épületekkel együtt)\n",
           "Cellák: KSH-cél / a modell az illesztés ELŐTT / az illesztés UTÁN. Az illesztés után a legnagyobb eltérésnek 0–1 százalékpont körül kell lennie.\n",
           "| ker. | épület | szürke | " + " | ".join(k[2] for k in ERAS) + " | legnagyobb eltérés előtte → utána (százalékpont) | legnagyobb szorzó | átrendezett épület | kertvárosi régi házak megmaradó része |",
           "|---|---|---|" + "---|" * K + "---|---|---|---|"]
    for d in diag:
        if d["ker"] is None:
            continue
        cell = " | ".join(f"{d['cel'][c]:.0f} / {d['elotte'][c]:.0f} / {d['utana'][c]:.0f}" for c in range(K))
        row.append(f"| {d['ker']} | {d['db']} | {d['szurke']} | {cell} | {d['elter_elotte']:.1f} → {d['elter_utana']:.1f} | x{d['lam']:.1f} | {d['atrendezett']} | {'–' if d.get('regi_szorzo') is None else f"{100 * d['regi_szorzo']:.0f}%"} |")
    row.append("\nNagy szorzó = a tudott évű épületek vagy a KSH-tábla nem reprezentatív abban a kerületben. "
               "Az illesztés lakás-egyenértékre (alapterület x szintszám) igaz, épületszámra nem.\n")
    return "\n".join(row)


def ring_es_type(ep):

    """City mode: for every building a ring, type and prior distribution (e['prior']). The ring comes from the distance from Deák tér."""
    connections_number(ep)
    average = {}
    for gy in range(len(RING_KM) + 1):
        b, c = PRIORITY_TYPES.get("berhaz"), PRIORITY_TYPES.get("csaladi")
        if b and c:
            average[gy] = [(b[gy][y] + c[gy][y]) / 2 for y in range(K)]
    for e in ep:
        gy, km = ring_index(e["x"], e["y"])
        kind = building_type(e, gy)
        e["gyuru_km"], e["etipus"], e["gyuru"] = km, kind, gy
        e["prior"] = PRIORITY_TYPES[kind][gy] if kind in PRIORITY_TYPES else average.get(gy)


def simplify(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return "".join(c for c in s if c.isalnum())


# ---------------------------------------------------------------- reading input
def read_buildings():
    g = json.load(open(DATA / ("epuletek_vegleges.geojson" if CITY else "belvaros_epuletek_vegleges.geojson"), encoding="utf-8"))
    list_ = []
    for f in g["features"]:
        p = f["properties"]
        if p.get("resz"):
            continue  # building parts are not estimated (they inherit the parent building)
        if p.get("rom"):
            continue  # ancient/medieval ruin: a category of its own, fixed (facts_ruins.py), not estimated
        geo = f["geometry"]
        if geo["type"] == "Polygon":
            ring_ = geo["coordinates"][0]
        elif geo["type"] == "MultiPolygon":
            ring_ = geo["coordinates"][0][0]
        else:
            continue
        pts = [((x - 19.05) * math.cos(math.radians(47.5)) * 111320.0, (y - 47.5) * 110574.0)
               for x, y in ring_]
        a2 = cx = cy = 0.0
        for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
            c = x0 * y1 - x1 * y0
            a2 += c
            cx += (x0 + x1) * c
            cy += (y0 + y1) * c
        if abs(a2) < 1e-6:
            continue
        area = abs(a2) / 2
        district_ = sum(math.dist(a, b) for a, b in zip(pts, pts[1:] + pts[:1]))
        year = p.get("ev")
        try:
            year = int(year) if year not in (None, "") else None
        except (TypeError, ValueError):
            year = None
        list_.append({
            "kulcs": (p.get("osm_tipus") or "way", int(p["id"])),
            "x": cx / (3 * a2), "y": cy / (3 * a2), "pts": pts,
            "terulet": area, "kompakt": 4 * math.pi * area / (district_ ** 2),
            "szintek": p.get("szintek"), "magassag": p.get("magassag"),
            "tipus": p.get("tipus") or "yes", "ev": year,
            "kor": era_index(year) if year else None,
            "vedett": bool(p.get("vedettseg")), "nev": p.get("nev") or "",
            "zarvany": (p.get("tipus") in ENCLAVE_TYPES) or bool(ENCLAVE_NAME.search(p.get("nev") or "")) or bool(p.get("csoport")),   # a building group merged under one name (e.g. a bath) is one enclave
            "kerulet": p.get("kerulet"), "mforras": p.get("magassag_forras"),
        })
    return list_


def read_streets(buildings):
    rename = {}
    path_ = ROOT / "forras" / "utcanev_atnevezesek.csv"
    if path_.exists():
        for r in csv.DictReader(open(path_, encoding="utf-8-sig"), delimiter=";"):
            if "|" not in (r["uj"] or ""):
                rename[simplify(r["regi"])] = r["uj"]
    addresses = {}
    path_ = DATA / "osm_cimek.csv"
    if path_.exists():
        for r in csv.DictReader(open(path_, encoding="utf-8-sig"), delimiter=";"):
            k = (r["osm_tipus"], int(r["id"]))
            u = rename.get(simplify(r["utca"]), r["utca"])
            addresses.setdefault(k, simplify(u))
    for e in buildings:
        u = addresses.get(e["kulcs"])
        e["utca"] = ((e.get("kerulet") or 0, u) if u else None) if CITY else u


class ZoneStore:
    """In city mode: (district, street) -> zone; zones without a district (inner city) apply in any district."""

    def __init__(self):
        self.d = {}

    def get(self, building_key):
        if not building_key:
            return None
        return self.d.get(building_key) or self.d.get((None, building_key[1]))

    def __getitem__(self, building_key):
        return self.get(building_key)

    def __bool__(self):
        return bool(self.d)


def zone_distribution(from_, to):
    overlap = []
    for a, b, _ in ERAS:
        o = max(0, min(to, b) - max(from_, a) + 1)
        overlap.append(o / (to - from_ + 1))
    return [0.9 * x + 0.1 / K for x in overlap]


def read_zones():
    street_zone = ZoneStore() if CITY else {}
    files = ["varosfejlodes.json"] + (["varosfejlodes_kerulet.json"] if CITY else [])
    for fn in files:
        path_ = ROOT / "forras" / fn
        if not path_.exists():
            continue
        d = json.load(open(path_, encoding="utf-8"))
        weights = d.get("_sulyok", {"forrasolt": 1.0, "ellenorizendo": 0.4})
        weights = {"forrasolt": 1.0, "ellenorizendo": 0.4, **weights}
        for z in d["zonak"]:
            district_zone = fn != "varosfejlodes.json"
            if not z.get("idoszak") or not z.get("utcak"):
                continue  # there is no boundary for polygon zones and zones without a street list
            if not district_zone and z.get("tipus") != "utcak":
                continue
            from_, to = z["idoszak"]
            distribution = zone_distribution(from_, to)
            for u in z["utcak"]:
                rec = (z["id"], distribution, weights.get(z["allapot"], 0.4))
                if CITY:
                    street_zone.d[(z.get("kerulet") if district_zone else None, simplify(u))] = rec
                else:
                    street_zone[simplify(u)] = rec
    return street_zone


# ---------------------------------------------------------------- spatial relations
def neighbors_construction_city(ep):
    """City mode: only the known (labelled) buildings are kept as neighbours, the nearest MAX_SZOMSZED per building.
    Contact (shared wall) is examined only with the known buildings."""
    label = [j for j, e in enumerate(ep) if e["kor"] is not None]
    cell = defaultdict(list)
    for j in label:
        cell[(int(ep[j]["x"] // NEIGHBOR_RADIUS), int(ep[j]["y"] // NEIGHBOR_RADIUS))].append(j)
    vertex = defaultdict(set)
    for j in label:
        for x, y in ep[j]["pts"]:
            vertex[(int(x // 2), int(y // 2))].add(j)
    neighbor = []
    for i, e in enumerate(ep):
        touch = set()
        pts = e["pts"] if e.get("pts") else e["pts_fn"]()
        for x, y in pts:
            cx, cy = int(x // 2), int(y // 2)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for j in vertex.get((cx + dx, cy + dy), ()):
                        if j != i and j not in touch and any(math.dist((x, y), q) <= CONTACT_M for q in ep[j]["pts"]):
                            touch.add(j)
        cx, cy = int(e["x"] // NEIGHBOR_RADIUS), int(e["y"] // NEIGHBOR_RADIUS)
        row = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in cell.get((cx + dx, cy + dy), ()):
                    if j == i:
                        continue
                    d = math.dist((e["x"], e["y"]), (ep[j]["x"], ep[j]["y"]))
                    if d <= NEIGHBOR_RADIUS:
                        row.append((j, d, j in touch))
        if len(row) > MAX_NEIGHBOR + 1:
            row.sort(key=lambda t: t[1])
            row = row[:MAX_NEIGHBOR + 1]
        neighbor.append(row)
    return neighbor


def neighbors_construction(ep):
    if CITY:
        return neighbors_construction_city(ep)
    n = len(ep)
    cell = defaultdict(list)
    for i, e in enumerate(ep):
        cell[(int(e["x"] // NEIGHBOR_RADIUS), int(e["y"] // NEIGHBOR_RADIUS))].append(i)
    vertex = defaultdict(set)
    for i, e in enumerate(ep):
        for x, y in e["pts"]:
            vertex[(int(x // 2), int(y // 2))].add(i)
    touch = [set() for _ in range(n)]
    for i, e in enumerate(ep):
        for x, y in e["pts"]:
            cx, cy = int(x // 2), int(y // 2)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for j in vertex.get((cx + dx, cy + dy), ()):
                        if j != i and j not in touch[i]:
                            if any(math.dist((x, y), q) <= CONTACT_M for q in ep[j]["pts"]):
                                touch[i].add(j)
                                touch[j].add(i)
    neighbor = []
    for i, e in enumerate(ep):
        cx, cy = int(e["x"] // NEIGHBOR_RADIUS), int(e["y"] // NEIGHBOR_RADIUS)
        row = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in cell.get((cx + dx, cy + dy), ()):
                    if j == i:
                        continue
                    d = math.dist((e["x"], e["y"]), (ep[j]["x"], ep[j]["y"]))
                    if d <= NEIGHBOR_RADIUS:
                        row.append((j, d, j in touch[i]))
        neighbor.append(row)
    return neighbor


# ---------------------------------------------------------------- shape features
def type_group(t):
    if t == "apartments":
        return "lakoepulet"
    if t in ("yes", "residential", "house"):
        return "altalanos"
    if t in ("office", "commercial", "retail", "hotel"):
        return "kereskedelmi"
    return "kozint_egyeb"


def features(e):
    sz = e["szintek"]
    try:
        sz = float(sz)
    except (TypeError, ValueError):
        sz = None
    if sz is None:
        szs = "?"
    elif sz <= 2:
        szs = "1-2"
    elif sz <= 4:
        szs = "3-4"
    elif sz <= 5:
        szs = "5"
    elif sz <= 6:
        szs = "6"
    else:
        szs = "7+"
    t = e["terulet"]
    area_ = "<150" if t < 150 else "<300" if t < 300 else "<600" if t < 600 else "<1200" if t < 1200 else "1200+"
    comp = "kompakt" if e["kompakt"] > 0.6 else "tagolt"
    return {"szint": szs, "terulet": area_, "tipus": type_group(e["tipus"]), "forma": comp}


CONDITION_VALUES = {  # for the Laplace smoothing: how many possible values there are
    "szint": 6, "terulet": 5, "tipus": 4, "forma": 2,
}


class Model:
    """Tables computed from the labelled buildings (class frequencies, shape tables)."""

    def __init__(self, ep, training):
        self.ep = ep
        self.training = set(training)
        self.count_ = [0] * K
        self.alak = {f: [Counter() for _ in range(K)] for f in CONDITION_VALUES}
        self.jell = {}
        for i in self.training:
            self.add_(i, +1)

    def add_(self, i, sign):
        e = self.ep[i]
        y = e["kor"]
        self.count_[y] += sign
        j = self.jell.get(i) or features(e)
        self.jell[i] = j
        for f, v in j.items():
            self.alak[f][y][v] += sign

    def base_distribution(self, excluded=()):
        count_ = list(self.count_)
        for i in excluded:
            if i in self.training:
                count_[self.ep[i]["kor"]] -= 1
        total = sum(count_)
        return [(c + 1) / (total + K) for c in count_]


def components(i, ep, neighbor, m, street_index, zones, excluded):
    """Returns the four pieces of evidence of the i-th building as log-probabilities (lists of length K).
    kizart: the indices whose label it must not see (itself, or the block)."""
    e = ep[i]
    exclude = set(excluded) | {i}
    base = m.base_distribution(exclude)
    if CITY and e.get("prior"):
        b = GLOBAL_MIXING
        base = [(1 - b) * p + b * g for p, g in zip(e["prior"], base)]
    # neighbours
    N = [0.0] * K
    for j, d, touch in neighbor[i]:
        if j in exclude or j not in m.training:
            continue
        w = math.exp(-d / NEIGHBOR_THIN_OUT) * (CONTACT_FACTOR if touch else 1.0)
        if ep[j].get("zarvany"):          # church, ruin: an enclave, not a characteristic of the surroundings
            w *= ENCLAVE_WEIGHT
        N[ep[j]["kor"]] += w
    total = sum(N)
    a = 0.5
    lN = [math.log((N[y] + a * base[y]) / (total + a)) for y in range(K)]
    # street
    lS = [0.0] * K
    if e["utca"]:
        C = [0] * K
        for j in street_index.get(e["utca"], ()):
            if j not in exclude and j in m.training:
                C[ep[j]["kor"]] += ENCLAVE_WEIGHT if ep[j].get("zarvany") else 1
        n = sum(C)
        lS = [math.log((C[y] + 2 * base[y]) / (n + 2)) for y in range(K)]
    # shape (naive Bayes)
    j = features(e)
    count_ = list(m.count_)
    for t in exclude:
        if t in m.training:
            count_[ep[t]["kor"]] -= 1
    lF = [0.0] * K
    for f, v in j.items():
        for y in range(K):
            c = m.alak[f][y][v]
            for t in exclude:
                if t in m.training and ep[t]["kor"] == y and m.jell[t][f] == v:
                    c -= 1
            lF[y] += math.log((c + 1) / (count_[y] + CONDITION_VALUES[f]))
    # zone
    lZ = [0.0] * K
    zone_weight = 0.0
    z = zones.get(e["utca"]) if e["utca"] else None
    if z:
        lZ = [math.log(p) for p in z[1]]
        zone_weight = z[2]
    l0 = [math.log(p) for p in base]
    gy = NEIGHBOR_WEIGHT[min(e.get("gyuru", 0), len(NEIGHBOR_WEIGHT) - 1)] if CITY else 1.0
    gf = SHAPE_WEIGHT[min(e.get("gyuru", 0), len(SHAPE_WEIGHT) - 1)] if CITY else 1.0
    lP, weight = None, 0.0
    if CITY and e.get("pz") is not None:
        z = PZ_LIST[e["pz"]]
        lP, weight = [math.log(v) for v in z["eloszlas"]], z["suly"]
    return {"0": l0, "N": lN, "S": lS, "F": lF, "Z": lZ, "zsuly": zone_weight, "gy": gy, "gf": gf, "G": e.get("ghsl_l"), "P2": lP, "p2suly": weight}


def zone_banned(e):
    """Indices of the eras excluded by the smallest containing (non-test) drawn zone (an empty list if there is no zone)."""
    if not CITY or e.get("pz") is None:
        return []
    z = PZ_LIST[e["pz"]]
    ban = []
    for c, (a, b, _) in enumerate(ERAS):
        if (ZONE_FROM_BOUNDARY and b < z["tol"]) or (z.get("ig_hatar") and a > z["ig"]):
            ban.append(c)
    return ban if len(ban) < K else []


def distribution(k, w):
    s = []
    for y in range(K):
        g = k.get("gy", 1.0)
        s.append(w["0"] * k["0"][y] + g * (w["N"] * k["N"][y] + w["S"] * k["S"][y])
                 + k.get("gf", 1.0) * w["F"] * k["F"][y] + w["Z"] * k["zsuly"] * k["Z"][y]
                 + (PZ_WEIGHT * k["p2suly"] * k["P2"][y] if k.get("P2") else 0.0)
                 + (w.get("G", GH["suly"]) * k["G"][y] if k.get("G") else 0.0))
    mx = max(s)
    ex = [math.exp(v - mx) for v in s]
    t = sum(ex)
    return [v / t for v in ex]


# ---------------------------------------------------------------- measurement
def metrics(par):
    """par: [(true_index, distribution)] -> dictionary"""
    if not par:
        return {"n": 0}
    n = len(par)
    point = sum(1 for y, p in par if max(range(K), key=lambda q: p[q]) == y)
    top2 = sum(1 for y, p in par if y in sorted(range(K), key=lambda q: -p[q])[:2])
    ll = -sum(math.log(max(p[y], 1e-9)) for y, p in par) / n
    # a one-era error: an era adjacent to the true one
    near = sum(1 for y, p in par if abs(max(range(K), key=lambda q: p[q]) - y) <= 1)
    return {"n": n, "pontossag": point / n, "top2": top2 / n, "logloss": ll, "legfeljebb_1_korszak_tevedes": near / n}


def weights_grid():
    for wn in (0.0, 0.5, 1.0, 1.5):
        for ws in (0.0, 0.3, 0.6):
            for wf in (0.0, 0.3, 0.6, 1.0):
                for wz in (0.0, 0.5, 1.0):
                    for w0 in ((1.0,) if CITY else (0.0, 0.5, 1.0)):
                        yield {"0": w0, "N": wn, "S": ws, "F": wf, "Z": wz}


def certainty_threshold(entity, target, upper_=None, min_count=20):
    """egyed: [(probability of the most probable era, whether it hit)], in descending order.
    Returns the smallest threshold p for which the buildings falling into the band [p, felso) have an OWN hit rate of at least 'cel'
    (felso=None: no upper bound). Earlier the hits of the upper bands were included too (cumulative rate), so the
    'medium' band was reported as >=70% when it was really ~52%. If no threshold satisfies it: None."""
    list_ = [(p, ok) for p, ok in entity if upper_ is None or p < upper_]
    best = None
    found = 0
    for n, (p, ok) in enumerate(list_, 1):
        found += ok
        if n < len(list_) and list_[n][0] == p:
            continue          # guesses of equal probability can only go into a band together
        if n >= min_count and found / n >= target:
            best = p
    return best


def evaluate(sorted_, comp_, w):
    return [(ep_y, distribution(k, w)) for ep_y, k in zip(sorted_, comp_)]


def read_ghsl(ep):
    """data/varos/ghsl.csv (facts_ghsl.py): the built-up m2 of the building's 100 m cell for several years.
    Principle: the building is a random member of the cell's present (last-year) building stock. If a share f1 of the cell's built-up area already existed
    at the first year, and f2-f1 was built between the first and second, etc., then the building's construction time comes from these
    windows, weighted by the windows. Within a window the distribution is uniform; the probability of the eras comes from the overlap of the windows with the
    era (relative to the uniform distribution, clipped to [eps, max]).
    The data comes from the map, not from the buildings of known year, so it does not leak into the test either."""
    path_ = DATA / "ghsl.csv"
    if not CITY or not path_.exists():
        return 0
    idx = {e["kulcs"]: i for i, e in enumerate(ep)}
    START, END = 1800, 2026
    count_ = 0
    for r in csv.DictReader(open(path_, encoding="utf-8-sig"), delimiter=";"):
        i = idx.get((r["osm_tipus"], int(r["id"])))
        if i is None:
            continue
        years = sorted(int(k[3:]) for k in r if k and k.startswith("m2_"))
        value = [r["m2_%d" % year] for year in years]
        if not years or any(v == "" for v in value):
            continue
        run, total = [], 0.0
        for v in value:
            total = max(total, float(v))
            run.append(total)
        if total < GH["min_m2"]:
            GHSL_STAT["a cella 2020-ra sem érdemben beépített (nincs információ)"] += 1
            continue
        # windows: (start, end, mass)
        boundaries = [START] + years + [END]
        part = [run[0] / total] + [(run[k] - run[k - 1]) / total for k in range(1, len(run))] + [0.0]
        u = GH["utolso"]
        part = [(1 - u) * x + u / len(part) for x in part]
        sur = [(boundaries[k], boundaries[k + 1], part[k] / (boundaries[k + 1] - boundaries[k])) for k in range(len(part))]
        l = []
        for from_, to, _ in ERAS:
            a, b = max(from_, START), min(to, END)
            length = b - a + 1 if b >= a else 0
            if length <= 0:
                l.append(math.log(1.0))
                continue
            overlap = sum(max(0, min(b, h1) - max(a - 1, h0)) * d for h0, h1, d in sur)      # the years of the window (h0, h1]
            ratio = overlap / length * (END - START)
            l.append(math.log(min(GH["max"], max(GH["eps"], ratio))))
        ep[i]["ghsl_l"] = l
        f_first = run[0] / total
        ep[i]["ghsl_ablak"] = max(range(len(part) - 1), key=lambda k: part[k])
        ep[i]["ghsl_elso"] = f_first
        GHSL_STAT["1975-re a cella beépítettségének >75%-a megvolt" if f_first > 0.75 else
                  "1975-re 25–75%-a" if f_first >= 0.25 else "1975-re <25%-a (főleg újabb)"] += 1
        count_ += 1
    return count_


def approximate_labels(ep):
    """City mode: the approximate era data of the heritage inventories ('the 1930s') counts as a label if the range
    falls into a single era and the building has no exact year. Returns: {index: text}."""
    roads = sorted(DATA.glob("*_kozelito.csv")) if CITY else []      # ertekleltar_, osm_, wikidata_kozelito.csv...
    if not roads:
        return {}
    idx = {e["kulcs"]: i for i, e in enumerate(ep)}
    out = {}
    different = defaultdict(set)
    for path_ in roads:
        for r in csv.DictReader(open(path_, encoding="utf-8-sig"), delimiter=";"):
            i = idx.get((r["osm_tipus"], int(r["id"])))
            if i is None or ep[i]["kor"] is not None:
                continue
            a, b = era_index(int(r["ev_tol"])), era_index(int(r["ev_ig"]))
            if a is None or a != b:
                continue
            different[i].add(a)
            out[i] = (a, f"{r['szoveg']} ({r['forras']})")
    result = {}
    for i, (k, text_) in out.items():
        if len(different[i]) == 1:
            ep[i]["kor"] = k
            result[i] = text_
    return result


def approximate_ranges(ep):
    """City mode: approximate data spanning several eras ('1920-1930-as évek' i.e. 1920s-30s, 'XIX. század' i.e. 19th century) also narrows the estimate: the grey building's
    probability is restricted to the eras in the range (data falling into a single era becomes a label, see kozelito_cimkek).
    With several sources, the intersection of the ranges; if the intersection is empty, the data are ignored. Returns: {index: (eras, text)}."""
    roads = sorted(DATA.glob("*_kozelito.csv")) if CITY else []
    if not roads:
        return {}
    idx = {e["kulcs"]: i for i, e in enumerate(ep)}
    collect = defaultdict(list)
    for path_ in roads:
        for r in csv.DictReader(open(path_, encoding="utf-8-sig"), delimiter=";"):
            i = idx.get((r["osm_tipus"], int(r["id"])))
            if i is None or ep[i]["kor"] is not None:
                continue
            collect[i].append((int(r["ev_tol"]), int(r["ev_ig"]), f"{r['szoveg'] or str(r['ev_tol']) + '–' + str(r['ev_ig'])} ({r['forras']})"))
    result = {}
    for i, l in collect.items():
        from_, to = max(x[0] for x in l), min(x[1] for x in l)
        if from_ > to:
            continue
        ks = [q for q, (a, b, _) in enumerate(ERAS) if a <= to and b >= from_]
        if 1 <= len(ks) < len(ERAS):
            result[i] = (set(ks), "; ".join(x[2] for x in l[:2]))
    return result


def main():
    ep = read_buildings()
    print(f"Zárvány-épület (templom, kápolna, zsinagóga, rom stb.; a szomszédokra x{ENCLAVE_WEIGHT} súllyal hat): {sum(1 for e in ep if e.get('zarvany'))}")
    read_streets(ep)
    if CITY:
        read_polygon_zones()
        polygon_zones_assign(ep)
        print(f"Poligon-zónák: {len(PZ_LIST)} (mérőpróba: {sum(1 for z in PZ_LIST if z['mero'])}); "
              f"zónába eső épület: {sum(1 for e in ep if e['pz'] is not None)}")
    if CITY and read_priority():
        ring_es_type(ep)
        print("Épülettípusok:", dict(Counter(e["etipus"] for e in ep)))
        print("Gyűrűk:", dict(Counter(RING_NAMES[e["gyuru"]] for e in ep)))
    soft = approximate_labels(ep)
    gdb = read_ghsl(ep)
    if CITY:
        print(f"GHSL-bizonyíték: {gdb} épületnél ({dict(GHSL_STAT)})")
    if CITY:
        print(f"Címkézett épület: {sum(1 for e in ep if e['kor'] is not None)} (ebből közelítő, értékleltárból: {len(soft)})")
    zones = read_zones()
    neighbor = neighbors_construction(ep)
    labeled = [i for i, e in enumerate(ep) if e["kor"] is not None]
    grey = [i for i, e in enumerate(ep) if e["kor"] is None]
    street_index = defaultdict(list)
    for i, e in enumerate(ep):
        if e["utca"]:
            street_index[e["utca"]].append(i)
    m = Model(ep, labeled)

    # --- 1) "hide one at a time" components
    kp_loo = {i: components(i, ep, neighbor, m, street_index, zones, ()) for i in labeled}
    # --- 2) block-exclusion components (a stricter test)
    block = defaultdict(list)
    for i in labeled:
        block[(int(ep[i]["x"] // BLOCK_M), int(ep[i]["y"] // BLOCK_M))].append(i)
    kp_block = {}
    for b, members in block.items():
        for i in members:
            kp_block[i] = components(i, ep, neighbor, m, street_index, zones, members)

    # --- 3) cross-fitting the weights: tuning on one half's spatial blocks, measuring on the other
    def half(i):
        b = (int(ep[i]["x"] // BLOCK_M), int(ep[i]["y"] // BLOCK_M))
        return (b[0] * 7 + b[1] * 13) % 2

    def best_weight(indices):
        best = None
        for w in weights_grid():
            ll = metrics([(ep[i]["kor"], distribution(kp_loo[i], w)) for i in indices])["logloss"]
            if best is None or ll < best[0]:
                best = (ll, w)
        return best[1]

    A = [i for i in labeled if half(i) == 0]
    B = [i for i in labeled if half(i) == 1]
    wA, wB = best_weight(A), best_weight(B)
    cross_fitted = [(ep[i]["kor"], distribution(kp_loo[i], wA)) for i in B] + \
                        [(ep[i]["kor"], distribution(kp_loo[i], wB)) for i in A]
    w_final = best_weight(labeled)

    # --- 4) report
    empty = {"0": 0, "N": 0, "S": 0, "F": 0, "Z": 0, "G": 0}
    base_only = dict(empty, **{"0": 1.0})
    row = {}
    row["a legtöbbször előforduló korszak tippelése"] = metrics([(ep[i]["kor"], distribution(kp_loo[i], base_only)) for i in labeled])
    row["a végső modell (egyenként elrejtve)"] = metrics([(ep[i]["kor"], distribution(kp_loo[i], w_final)) for i in labeled])
    row["a végső modell (keresztillesztett súlyokkal)"] = metrics(cross_fitted)
    row["a végső modell (300 m-es blokk kizárva)"] = metrics([(ep[i]["kor"], distribution(kp_block[i], w_final)) for i in labeled])
    window = {}
    for name_, building_key in (("szomszédok nélkül", "N"), ("utca nélkül", "S"), ("alak nélkül", "F"), ("zóna nélkül", "Z"), ("alapeloszlás nélkül", "0"), ("GHSL nélkül", "G")):
        w = dict(w_final)
        w[building_key] = 0.0
        window[name_] = metrics([(ep[i]["kor"], distribution(kp_loo[i], w)) for i in labeled])
    # the drawn (polygon) zones were made with knowledge of the buildings of known year (e.g. Wekerle estate), so in the measurement they also "see" the answer:
    # this row shows the accuracy without the drawn zone's evidence
    window["rajzolt zóna nélkül"] = metrics([(ep[i]["kor"], distribution(dict(kp_loo[i], P2=None, p2suly=0.0), w_final)) for i in labeled])

    not_protected = [i for i in labeled if not ep[i]["vedett"]]
    in_zone_outside = [i for i in not_protected if ep[i].get("pz") is None]
    subgroup = {
        "védett épületek": metrics([(ep[i]["kor"], distribution(kp_loo[i], w_final)) for i in labeled if ep[i]["vedett"]]),
        "NEM védett épületek": metrics([(ep[i]["kor"], distribution(kp_loo[i], w_final)) for i in not_protected]),
        "NEM védett, rajzolt zónán kívül": metrics([(ep[i]["kor"], distribution(kp_loo[i], w_final)) for i in in_zone_outside]),
    }
    per_era = {}
    for y in range(K):
        par = [(ep[i]["kor"], distribution(kp_loo[i], w_final)) for i in labeled if ep[i]["kor"] == y]
        if par:
            found = sum(1 for yy, p in par if max(range(K), key=lambda q: p[q]) == yy)
            per_era[y] = (len(par), found / len(par))
    zone_counter = Counter()
    for i in labeled:
        zone_counter["zónával" if kp_loo[i]["zsuly"] > 0 else "zóna nélkül"] += 1
    total_grey_zone = sum(1 for i in grey if zones.get(ep[i]["utca"]))

    # confusion matrix and calibration
    zone_av = [[0] * K for _ in range(K)]
    calib = defaultdict(lambda: [0, 0])
    for i in labeled:
        p = distribution(kp_loo[i], w_final)
        top = max(range(K), key=lambda q: p[q])
        zone_av[ep[i]["kor"]][top] += 1
        band = min(int(p[top] * 10), 9) / 10
        calib[band][0] += 1
        calib[band][1] += (top == ep[i]["kor"])
    # certainty thresholds
    entity = sorted(((max(distribution(kp_loo[i], w_final)),
                     max(range(K), key=lambda q: distribution(kp_loo[i], w_final)[q]) == ep[i]["kor"])
                    for i in labeled), reverse=True)

    k_high = certainty_threshold(entity, 0.85)
    k_medium = certainty_threshold(entity, 0.70, upper_=k_high)

    not_protected_calib = [i for i in labeled if not ep[i]["vedett"]]
    # --- calibration for the probability shown on the card/in the CSV ---
    # The raw probability is overconfident (about 2/3 of the guesses called 90-100% hit). The displayed value is therefore what the
    # model actually achieved in the measurement: the hit rate belonging to the raw probability of the most probable era, with the spatial
    # 300 m block excluded (without the neighbour's year), on NON-protected known buildings, with isotonic (PAV) smoothing.
    calib_pairs = sorted(((max(pp_), max(range(K), key=lambda q: pp_[q]) == ep[i]["kor"])
                        for i in not_protected_calib for pp_ in [distribution(kp_block[i], w_final)]))
    blocks = []                                       # [hits, count, sum of raw probabilities]
    for pv, ok in calib_pairs:
        blocks.append([float(ok), 1, pv])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] >= blocks[-1][0] / blocks[-1][1]:
            b = blocks.pop()
            blocks[-1] = [blocks[-1][0] + b[0], blocks[-1][1] + b[1], blocks[-1][2] + b[2]]
    calib_points = [(b[2] / b[1], b[0] / b[1]) for b in blocks if b[1] >= 15] or [(0.0, 1.0 / K), (1.0, 1.0 / K)]

    def calibrated(pv):
        if pv <= calib_points[0][0]:
            return calib_points[0][1]
        for (x0, y0), (x1, y1) in zip(calib_points, calib_points[1:]):
            if pv <= x1:
                return y0 + (y1 - y0) * (pv - x0) / (x1 - x0 or 1.0)
        return calib_points[-1][1]

    # --- 5) estimating the grey buildings
    path_estimate = DATA / "ev_becsles.csv"
    filter_result = []
    PP = {i: distribution(components(i, ep, neighbor, m, street_index, zones, ()), w_final) for i in grey}
    zone_boundary_count = 0
    for i in grey:                                   # zone boundary: the probability of the excluded eras is 0
        ban = zone_banned(ep[i])
        if ban:
            v = [0.0 if c in ban else PP[i][c] for c in range(K)]
            s = sum(v)
            PP[i] = [x / s for x in v] if s > 0 else [1.0 / (K - len(ban)) if c not in ban else 0.0 for c in range(K)]
            zone_boundary_count += 1
    print(f"Zónahatár (építés ettől / eddig) alkalmazva {zone_boundary_count} szürke épületen")
    near_hold = approximate_ranges(ep)
    near_sign = {}
    for i in grey:                                   # approximate (multi-era) source data: only the eras within the range remain
        if i in near_hold:
            ok, text_ = near_hold[i]
            v = [PP[i][c] if c in ok else 0.0 for c in range(K)]
            s_ = sum(v)
            PP[i] = [x / s_ for x in v] if s_ > 0 else [1.0 / len(ok) if c in ok else 0.0 for c in range(K)]
            near_sign[i] = text_
    print(f"Közelítő (több korszakot átfogó) forrásadat szűkíti a becslést {len(near_sign)} szürke épületen")
    ksh_result, ksh_diag, ksh_text = {}, [], ""
    if CITY and FIT_KSH:
        ksh = read_ksh()
        if ksh:
            if LOCAL_QUOTA:
                print(f"Helyi kvóta ({LOCAL_CELL_M:.0f} m-es foltok); főút-távolság a külső gyűrű {main_roads_distance(ep)} szürke épületénél")
            ksh_result, ksh_diag = ksh_quota(ep, grey, PP, ksh)
            ksh_text = ksh_report(ksh_diag)
            print(f"KSH-illesztés: {len(ksh_result)} szürke épület; "
                  f"legnagyobb kerületi eltérés: {max(d['elter_elotte'] for d in ksh_diag if d['ker']):.1f} -> "
                  f"{max(d['elter_utana'] for d in ksh_diag if d['ker']):.1f} százalékpont")
        else:
            print("Figyelem: nincs data/KSH/budapest_ksh_keruleti_eloszlas.csv (vagy hibás) - KSH-illesztés nélkül fut.")
    for i in grey:
        p = PP[i]
        top = max(range(K), key=lambda q: p[q])
        ksh_sign = ""
        if i in ksh_result:
            top, p, lam_top, atr = ksh_result[i]
            ksh_sign = f"; KSH-kerületi illesztés (szorzó x{lam_top:.2f})" + (", a kvóta szerint átrendezve" if atr else "")
        neighbor_count = sum(1 for j, d, _ in neighbor[i] if d <= 60 and j in m.training)
        if k_high is not None and p[top] >= k_high:
            certainty = "magas"
        elif k_medium is not None and p[top] >= k_medium:
            certainty = "kozepes"
        else:
            certainty = "alacsony"
        ent = -sum(v * math.log(v) for v in p if v > 0)
        repeat_neighbor_60 = neighbor_count
        all_neighbor_60 = sum(1 for j, d, _ in neighbor[i] if d <= 60)
        reason = f"{repeat_neighbor_60} ismert korú szomszéd 60 m-en belül" + ksh_sign
        if CITY and "gyuru" in ep[i]:
            reason += f"; típus: {ep[i]['etipus']}, {RING_NAMES[ep[i]['gyuru']]}"
        if CITY and ep[i].get("pz") is not None:
            reason += f"; rajzolt zóna: {PZ_LIST[ep[i]['pz']]['nev']} ({PZ_LIST[ep[i]['pz']]['tol']}–{PZ_LIST[ep[i]['pz']]['ig']})" + (" – zónahatár érvényes" if zone_banned(ep[i]) else "")
        if ep[i]["utca"] and zones.get(ep[i]["utca"]):
            reason += f"; zóna: {zones[ep[i]['utca']][0]}"
        if i in near_sign:
            reason += f"; forrásadat (közelítő): {near_sign[i]}"
        filter_result.append((i, p, top, certainty, ent, all_neighbor_60 - repeat_neighbor_60, reason))

    with open(path_estimate, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["osm_tipus", "id", "becsult_korszak", "valoszinuseg", "bizonyossag"]
                   + [f"p_{k[2]}" for k in ERAS] + ["indoklas", "valoszinuseg_nyers"])
        for i, p, top, certainty, ent, _, reason in filter_result:
            w.writerow([ep[i]["kulcs"][0], ep[i]["kulcs"][1], ERAS[top][2], f"{calibrated(p[top]):.2f}", certainty]
                       + [f"{v:.3f}" for v in p] + [reason, f"{p[top]:.2f}"])
        for i, text_ in soft.items():      # heritage inventory: an approximate but sourced era
            k = ep[i]["kor"]
            p = [0.94 if y == k else 0.06 / (K - 1) for y in range(K)]
            w.writerow([ep[i]["kulcs"][0], ep[i]["kulcs"][1], ERAS[k][2], f"{p[k]:.2f}", "magas"]
                       + [f"{v:.3f}" for v in p] + ["értékleltár: " + text_])

    with open(DATA / "ev_becsles_munkalista.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["osm_tipus", "id", "nev", "becsult_korszak", "valoszinuseg", "bizonyossag",
                    "ismeretlen_szomszed_60m", "bizonytalansag", "terulet_m2", "miert"])
        row_w = sorted(filter_result, key=lambda r: -(r[4] * (1 + r[5]) * math.sqrt(ep[r[0]]["terulet"])))
        for i, p, top, certainty, ent, isz, reason in row_w[:300]:
            w.writerow([ep[i]["kulcs"][0], ep[i]["kulcs"][1], ep[i]["nev"], ERAS[top][2],
                        f"{calibrated(p[top]):.2f}", certainty, isz, f"{ent:.2f}", int(ep[i]["terulet"]),
                        "bizonytalan és sok ismeretlen szomszéd veszi körül: egy kézi adat sokat javít"])

    def pct(x):
        return f"{100 * x:.0f}%"

    def sort(name_, d):
        if not d.get("n"):
            return f"| {name_} | 0 | – | – | – | – |"
        return f"| {name_} | {d['n']} | {pct(d['pontossag'])} | {pct(d['top2'])} | {pct(d['legfeljebb_1_korszak_tevedes'])} | {d['logloss']:.2f} |"

    head = "| | db | találat | az első kettő között | legfeljebb 1 korszakot téved | log-veszteség (kisebb a jobb) |\n|---|---|---|---|---|---|"
    s = []
    s.append("# Építési korszak becslés: mérési jelentés\n")
    s.append(f"Címkézett (ismert évű) épület: **{len(labeled)}**; szürke, becsült: **{len(grey)}**; épületrészt nem becslünk.\n")
    s.append("A mérés úgy megy, hogy minden ismert épületet egyenként elrejtünk, és megnézzük, eltalálná-e a modell.\n")
    s.append("## Fő eredmények\n\n" + head)
    for name_, d in row.items():
        s.append(sort(name_, d))
    s.append("\n## Mit ad az egyes bizonyíték? (a végső modellből kihagyva)\n\n" + head)
    for name_, d in window.items():
        s.append(sort(name_, d))
    s.append(f"\nVégső súlyok: {w_final}\n")
    s.append("\n## Védett és nem védett épületek külön\n\nAz ismert évű épületek jelentős része védett, a szürkék többsége viszont nem az, ezért a *nem védett* sor a reálisabb. "
             "A rajzolt zónák (pl. Wekerle-telep) a tudott évű házak ismeretében készültek, ezért a zónán belüli ismert épületeken a mérés túl jó; "
             "a szürke épületek többsége zónán kívül van, ott a *NEM védett, rajzolt zónán kívül* sor a mérvadó.\n\n" + head)
    for name_, d in subgroup.items():
        s.append(sort(name_, d))
    s.append("\n## Korszakonként: hányat talál el?\n\n| korszak | ismert db | találat |\n|---|---|---|")
    for y, (n, a) in per_era.items():
        s.append(f"| {ERAS[y][2]} | {n} | {pct(a)} |")
    s.append("\nA 1945 utáni korszakoknál kevés az ismert példa, ezért ott a becslés megbízhatatlanabb.\n")
    s.append("## Kalibráció: amit a modell X%-osra mond, az valójában mennyi?\n\n| a modell biztonsága | db | tényleges találat |\n|---|---|---|")
    for band in sorted(calib):
        n, t = calib[band]
        s.append(f"| {int(band * 100)}–{int(band * 100) + 10}% | {n} | {pct(t / n)} |")
    def _threshold(k, percent):
        return f"≥ {round(k, 2)} (mért találat ≥ {percent}%)" if k is not None else f"(egyik sáv sem éri el a(z) {percent}%-os mért találatot, ezért nincs ilyen sáv)"
    s.append(f"\nBizonyossági sávok: **magas** {_threshold(k_high, 85)}, **közepes** {_threshold(k_medium, 70)}, különben **alacsony**.\n")
    band_row = []
    for name_, lo, hi in (("magas", k_high, 2), ("közepes", k_medium, k_high), ("alacsony", 0, k_medium if k_medium is not None else k_high)):
        if lo is None or hi is None:
            continue
        a = [(ep[i]["kor"], distribution(kp_loo[i], w_final)) for i in not_protected]
        a = [(y, p) for y, p in a if lo <= max(p) < hi]
        if a:
            t = sum(1 for y, p in a if max(range(K), key=lambda q: p[q]) == y)
            band_row.append(f"- {name_}: {len(a)} nem védett ismert épületből {pct(t / len(a))} találat")
    s.append("A bizonyossági sávok tényleges találata csak a NEM védett épületeken:\n\n" + "\n".join(band_row) + "\n")
    calib_table = "\n".join(f"| {pct(x)} | {pct(calibrated(x))} |" for x in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0))
    s.append("## Kalibrált valószínűség (ez jelenik meg a kártyán)\n\nA nyers valószínűség túlzottan magabiztos. A kártyán és az ev_becsles.csv `valoszinuseg` oszlopában "
             f"a *mért* találati arány áll: a 300 m-es blokk kizárásával, {len(not_protected_calib)} NEM védett ismert épületen, izotonikus illesztéssel. "
             "A nyers érték a `valoszinuseg_nyers` oszlopban marad. A bizonyossági sávok (magas/közepes/alacsony) nem változnak.\n\n"
             "| nyers valószínűség | kalibrált (mért találat) |\n|---|---|\n" + calib_table + "\n")
    s.append("## Zavaró mátrix (sor: igazi, oszlop: becsült)\n\n| | " + " | ".join(k[2] for k in ERAS) + " |\n|---|" + "---|" * K)
    for y in range(K):
        s.append(f"| {ERAS[y][2]} | " + " | ".join(str(v) for v in zone_av[y]) + " |")
    s.append("\n## A szürke épületek becslése\n")
    counter = Counter((ERAS[t][2], b) for _, _, t, b, _, _, _ in filter_result)
    s.append("| korszak | magas | közepes | alacsony |\n|---|---|---|---|")
    for _, _, name_ in ERAS:
        s.append(f"| {name_} | {counter[(name_, 'magas')]} | {counter[(name_, 'kozepes')]} | {counter[(name_, 'alacsony')]} |")
    if CITY:
        gdb = sum(1 for e in ep if e.get("ghsl_l"))
        gsz = sum(1 for e in ep if e.get("ghsl_l") and e["kor"] is None)
        s.append(f"Minimum {GH['min_m2']:.0f} m2/cella (2020), súly: {GH['suly']}. Információt ad {gdb} épületnél (szürke: {gsz}). "
                 + "; ".join(f"{k}: {v}" for k, v in GHSL_STAT.items()) + ".\n")
    s.append(f"\nZóna-támpont {total_grey_zone} szürke épületnél érvényes (utca-egyezés alapján).\n")
    if CITY and "gyuru" in ep[0]:
        s.append("\n## Gyűrűnként (városi mód)\n\n"
                 "FIGYELEM: az ismert évű épületek a külső gyűrűkben többnyire *zárványok* (védett, régi), ezért az "
                 "alábbi egyenként-elrejtős pontosság a külső gyűrűkben NEM a valódi, tipikus épületekre vonatkozik. "
                 "A szürke épületeknél a becsült eloszlás a mérvadó, ezt vesd össze a helyismereteddel.\n\n" + head)
        for gy in range(len(RING_NAMES)):
            idx = [i for i in labeled if ep[i]["gyuru"] == gy]
            s.append(sort(RING_NAMES[gy] + " (ismert)", metrics([(ep[i]["kor"], distribution(kp_loo[i], w_final)) for i in idx])))
        s.append("\n### A szürke épületek becsült korszaka gyűrűnként és típusonként (db)\n")
        s.append("| gyűrű | típus | " + " | ".join(k[2] for k in ERAS) + " |\n|---|---|" + "---|" * K)
        class_ = defaultdict(lambda: [0] * K)
        for i, p, top, certainty, ent, _, reason in filter_result:
            class_[(ep[i]["gyuru"], ep[i]["etipus"])][top] += 1
        for (gy, kind), v in sorted(class_.items()):
            s.append(f"| {RING_NAMES[gy]} | {kind} | " + " | ".join(str(x) for x in v) + " |")
    if CITY and PZ_LIST:
        def mass_years(p, from_, to):
            t = 0.0
            for y in range(K):
                lo, hi = ERAS[y][0], min(ERAS[y][1], 2026)
                t += p[y] * max(0, min(to, hi) - max(from_, lo) + 1) / (hi - lo + 1)
            return t
        filter_zone = defaultdict(list)
        for i, p, top, certainty, ent, _, reason in filter_result:
            for zi in ep[i].get("pz_tag", []):
                filter_zone[zi].append((i, p, top))
        repeat_zone = defaultdict(list)
        for i in labeled:
            for zi in ep[i].get("pz_tag", []):
                repeat_zone[zi].append(i)
        for address, measuring in (("Rajzolt zónák (a becslő használja)", False), ("Mérőpróbák (a becslő NEM használja, csak méri)", True)):
            zl = [zi for zi, z in enumerate(PZ_LIST) if z["mero"] == measuring]
            if not zl:
                continue
            s.append(f"\n## {address}\n")
            s.append("| zóna | évek | ismert épület benne | ebből a megadott években (a többi: zárvány) | szürke épület benne | a becslés tömege a megadott években | legvalószínűbb korszak a megadott években |\n|---|---|---|---|---|---|---|")
            total_t = total_n = 0
            for zi in zl:
                z = PZ_LIST[zi]
                repeat = repeat_zone.get(zi, [])
                inside = sum(1 for i in repeat if (z["tol"] <= ep[i]["ev"] <= z["ig"] if ep[i]["ev"] is not None
                                              else ERAS[ep[i]["kor"]][0] <= z["ig"] and ERAS[ep[i]["kor"]][1] >= z["tol"])) if repeat else 0
                sz = filter_zone.get(zi, [])
                mass = sum(mass_years(p, z["tol"], z["ig"]) for _, p, _ in sz)
                good = sum(1 for _, _, top in sz if ERAS[top][0] <= z["ig"] and ERAS[top][1] >= z["tol"])
                total_t += mass
                total_n += len(sz)
                s.append(f"| {z['nev']} | {z['tol']}–{z['ig']} | {len(repeat)} | {inside} | {len(sz)} | "
                         f"{pct(mass / len(sz)) if sz else '–'} | {pct(good / len(sz)) if sz else '–'} |")
            if total_n:
                s.append(f"\nÖsszesen {total_n} szürke épület: átlagos becslési tömeg a megadott években **{pct(total_t / total_n)}**.\n")
    if ksh_text:
        s.append(ksh_text)
    s.append("## Amit nem tud a modell\n\n"
             "- A tanítóadat torz: sok az 1867–1918-as és a védett épület, kevés az 1945 utáni.\n"
             "- A zónák csak az utcát nézik, a háborús pótlásokat és későbbi beépítéseket nem.\n"
             "- A kortárs és modernista épületek listái (később) fogják javítani a 1945 utáni korszakokat.\n"
             "- A becslés soha nem kerül az `ev` mezőbe, és a térképen külön, halványabb rétegként látszik.\n")
    (DATA / "ev_becsles_jelentes.md").write_text("\n".join(s), encoding="utf-8")
    print("\n".join(s))


if __name__ == "__main__":
    main()
