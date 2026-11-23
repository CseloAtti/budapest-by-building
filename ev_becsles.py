"""
ev_becsles.py - ESTIMATING the era of the grey buildings (those of unknown construction year).

Run (in the project folder):   py ev_becsles.py

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

For the whole city:   py ev_becsles.py varos
  Input:   data/varos/epuletek_vegleges.geojson, data/varos/osm_cimek.csv, forras/varosfejlodes.json,
           forras/varosfejlodes_kerulet.json (district zones, with street lists), data/varos/ertekleltar_kozelito.csv
  Output:  data/varos/ev_becsles.csv, ev_becsles_jelentes.md, ev_becsles_munkalista.csv
  In city mode the street and the zone refer to the (district, street name) pair, the neighbour radius is larger (400 m),
  and the "1930s"-type data of the heritage inventories (if they fall into a single era) also count as labels (all data/varos/*_kozelito.csv) -
  these buildings appear in the estimate file with "high" certainty, marked with the heritage inventory as source.

In city mode (v2) the prior distribution of the grey buildings comes from building type x distance from the city core (ring)
  in forras/becsles_gyuru.json, and the weight of the neighbour/street evidence can be reduced per ring (0 in the outer ring:
  a building of known year does not affect its neighbours).
  The polygon zones of forras/zonak_poligon.geojson (from the zonak.html drawing tool) are the strongest evidence:
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

VAROS = "varos" in sys.argv[1:]
_ARGOK = [a for a in sys.argv[1:] if a != "varos"]
GYOKER = Path(_ARGOK[0]) if _ARGOK else Path(__file__).resolve().parent
ADAT = GYOKER / "data" / "varos" if VAROS else GYOKER / "data"

# Identical to the KORSZAKOK array of index.html (if it changes there, change it here too).
KORSZAKOK = [
    (1, 1866, "1867 előtt"),
    (1867, 1918, "1867–1918"),
    (1919, 1944, "1919–1944"),
    (1945, 1956, "1945–1956"),
    (1957, 1989, "1957–1989"),
    (1990, 2010, "1990–2010"),
    (2011, 9999, "2011-től"),
]
K = len(KORSZAKOK)

SZOMSZED_SUGAR = 400.0 if VAROS else 150.0     # m: up to this distance a known building counts as a neighbour
SZOMSZED_LECSENGES = 80.0 if VAROS else 40.0   # m: the weight is exp(-d/decay)
MAX_SZOMSZED = 40          # in city mode: keep at most this many (nearest) known neighbours
ERINTKEZES_M = 1.0         # m: if two buildings have a vertex within 1 m, they are considered attached
ERINTKEZES_SZORZO = 3.0
BLOKK_M = 300.0            # m: grid size of the "block-exclusion" test


ZONA_TOL_HATAR = True      # the drawn zone's "built from" year is a HARD lower bound for grey buildings (it does not affect a building of known year);
                           # "built until" is a bound only if the 'ig_hatar' switch is on for the zone
PZ_SULY = 1.5                                  # fixed weight of a polygon zone (not tuned: the labels are distorted)
PZ_ALLAPOT_SULY = {"helyismeret": 1.0, "forrasolt": 1.0, "ellenorizendo": 0.4}
PZ_LISTA = []
GYURU_NEVEK = ["belváros (0–2 km)", "belső gyűrű (2–3 km)", "középső gyűrű (3–6 km)", "külső gyűrű (6+ km)"]
KSH_ILLESZTES = True       # city mode: adjusts the final estimate to the district KSH proportions (data/KSH/budapest_ksh_keruleti_eloszlas.csv)
ZARVANY_SULY = 0.1         # multiplier of the neighbourhood and street effect of "enclave" buildings (church, chapel, synagogue, monastery, ruin etc.):
                           # an old church does not make the houses around it older in its newer surroundings (0 = no effect, 1 = like any house)
ELSO_KORSZAK_MIN_P = 0.10  # the KSH quota may assign the "before 1867" era to a grey building only if the A model (neighbour, street, zone, shape)
                           # on its own gives it at least this probability; without evidence the quota does not "scatter" pre-1867 buildings (0 = off)
ELSO_KORSZAK_KERULET_MAX = 0.10   # ...but only in districts where, according to KSH, the proportion of pre-1867 buildings is smaller than this (in the Castle District/Víziváros, where there are many old houses, there is no limit)
HELYI_KVOTA = True         # the KSH quota is distributed within a district in patches of HELYI_CELLA_M (old houses stay where the model expects them)
HELYI_CELLA_M = 500.0
HELYI_CSAK_KULSO = True    # the local quota only in the outer ring (6 km+, together with the drawn zones); in the inner rings the district-level distribution stays
ZAJ_SULY = 6.0             # the random (but deterministic) part of the ordering: larger = more scattered old houses
KULSO_REGI_SZORZO = 0.25    # outer ring: this share of the old (pre-1945) houses expected by the model remains (demolitions)
KSH_TURES = 0.5           # percentage points: by this much the district's KSH deviation may grow because of the demolition multiplier
REGI_KORSZAKOK = (1, 2)    # indices of the "old" eras (1867-1918, 1919-1944)
FOUT_SULY = 1.0            # outer ring, within the local quota: a house more than 300 m from the main road ranks about one era "younger" (a rule, not measured)
SORREND_KAPPA = 2.0        # strength of the ordering in distributing the quota (0 = no ordering; larger = the ordering overrides weak evidence more)
GYURU_KM = [2.0, 3.0, 6.0]
SZOMSZED_SULY = [1.0, 1.0, 0.5, 0.0, 1.0, 0.5]
ALAK_SULY = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0]      # multiplier of the shape evidence (F) per ring; F also learns from buildings of known year
GLOBAL_KEVERES = 0.1
GH = {"min_m2": 300.0, "suly": 0.7, "eps": 0.05, "max": 5.0, "utolso": 0.03}   # GHSL evidence (forras/becsles_gyuru.json: "ghsl")
GHSL_STAT = Counter()
KOZPONT = (47.4979, 19.0540)
PRIOR_TIPUSOK = {}
KOZEPULET = {"school", "kindergarten", "university", "college", "hospital", "church", "chapel", "cathedral", "public",
             "civic", "government", "theatre", "museum", "train_station", "fire_station", "mosque", "synagogue",
             "temple", "monastery", "clinic", "library", "stadium", "sports_hall", "sports_centre", "gymnasium"}
MELLEK = {"garage", "garages", "shed", "roof", "carport", "hut", "cabin", "service", "kiosk", "greenhouse", "barn",
          "stable", "container", "ruins", "construction", "tent", "bunker", "silo", "transformer_tower", "gatehouse"}
IPARI = {"industrial", "warehouse", "factory", "manufacture", "storage", "hangar"}
KERESK = {"retail", "commercial", "supermarket", "mall", "office", "hotel", "kiosk_shop", "fuel_station"}
ZARVANY_TIPUSOK = {"church", "chapel", "cathedral", "mosque", "synagogue", "temple", "monastery", "ruins", "castle", "fort", "city_gate"}
ZARVANY_NEV = re.compile(r"(?i)\b(templom|kápolna|székesegyház|bazilika|zsinagóga|mecset|kolostor|plébánia|rom|romok|romkert|erőd|kastély)\b")
SORHAZ = {"terrace", "semidetached_house", "semi", "terraced_house"}


def korszak_index(ev):
    for i, (tol, ig, _) in enumerate(KORSZAKOK):
        if tol <= ev <= ig:
            return i
    return None


def prior_beolvasasa():
    """forras/becsles_gyuru.json -> the global tables. If the file is missing, the built-in defaults are used."""
    global GYURU_KM, SZOMSZED_SULY, ALAK_SULY, GH, GLOBAL_KEVERES, KOZPONT, PRIOR_TIPUSOK
    ut = GYOKER / "forras" / "becsles_gyuru.json"
    if not ut.exists():
        print("Figyelem: nincs forras/becsles_gyuru.json - a gyűrűs prior nélkül fut.")
        return False
    d = json.load(open(ut, encoding="utf-8"))
    GYURU_KM = [float(x) for x in d.get("gyuruk_km", GYURU_KM)]
    SZOMSZED_SULY = [float(x) for x in d.get("szomszed_suly", SZOMSZED_SULY)]
    ALAK_SULY = [float(x) for x in d.get("alak_suly", ALAK_SULY)]
    GH = dict(GH, **{k: float(v) for k, v in d.get("ghsl", {}).items() if k in GH})
    for lista, alap in ((SZOMSZED_SULY, [1.0, 1.0, 0.5, 0.0, 1.0, 0.5]), (ALAK_SULY, [1.0] * 6)):
        while len(lista) < len(alap):
            lista.append(alap[len(lista)])
    GLOBAL_KEVERES = float(d.get("global_keveres", GLOBAL_KEVERES))
    KOZPONT = tuple(d.get("kozpont", KOZPONT))
    PRIOR_TIPUSOK = {}
    for tip, cellak in d["tipusok"].items():
        lista = []
        for c in cellak:
            osszetevok = c if isinstance(c[0], list) else [c]
            e = [0.0] * K
            ossz = sum((o[2] if len(o) > 2 else 1.0) for o in osszetevok)
            for o in osszetevok:
                w = (o[2] if len(o) > 2 else 1.0) / ossz
                for y, p in enumerate(zona_eloszlas(int(o[0]), int(o[1]))):
                    e[y] += w * p
            lista.append(e)
        PRIOR_TIPUSOK[tip] = lista
    return True


def poligon_zonak_beolvasasa():
    """forras/zonak_poligon.geojson -> PZ_LISTA (local ring zones in metres)."""
    PZ_LISTA.clear()
    ut = GYOKER / "forras" / "zonak_poligon.geojson"
    if not ut.exists():
        return
    for f in json.load(open(ut, encoding="utf-8")).get("features", []):
        try:
            p = f["properties"]
            if p.get("tipus") == "muemlek":
                continue  # OENY monument polygon: not year evidence
            gy = f["geometry"]["coordinates"][0]
            ring = [((x - 19.05) * math.cos(math.radians(47.5)) * 111320.0, (y - 47.5) * 110574.0) for x, y in gy]
            xs, ys = [q[0] for q in ring], [q[1] for q in ring]
            a2 = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(ring, ring[1:]))
            PZ_LISTA.append({"id": p["id"], "nev": p.get("nev") or p["id"], "tol": int(p["ev_tol"]), "ig": int(p["ev_ig"]),
                             "mero": bool(p.get("mero")), "ig_hatar": bool(p.get("ig_hatar")), "suly": PZ_ALLAPOT_SULY.get(p.get("allapot"), 0.4),
                             "ring": ring, "bbox": (min(xs), min(ys), max(xs), max(ys)), "terulet": abs(a2) / 2,
                             "eloszlas": zona_eloszlas(int(p["ev_tol"]), int(p["ev_ig"])), "tipus": p.get("tipus", "")})
        except (KeyError, TypeError, ValueError, IndexError):
            continue


def pont_gyuruben_xy(x, y, ring):
    be = False
    for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            be = not be
    return be


def poligon_zonak_hozzarendelese(ep):
    """For every building: e['pz'] = the smallest containing, NON-test zone (for the estimate); e['pz_tag'] = every containing zone."""
    for e in ep:
        e["pz"] = None
        e["pz_tag"] = []
    for zi, z in enumerate(PZ_LISTA):
        x0, y0, x1, y1 = z["bbox"]
        for e in ep:
            if x0 <= e["x"] <= x1 and y0 <= e["y"] <= y1 and pont_gyuruben_xy(e["x"], e["y"], z["ring"]):
                e["pz_tag"].append(zi)
                if not z["mero"] and (e["pz"] is None or z["terulet"] < PZ_LISTA[e["pz"]]["terulet"]):
                    e["pz"] = zi


def gyuru_index(x, y):
    kx, ky = (KOZPONT[1] - 19.05) * math.cos(math.radians(47.5)) * 111320.0, (KOZPONT[0] - 47.5) * 110574.0
    km = math.hypot(x - kx, y - ky) / 1000.0
    for i, h in enumerate(GYURU_KM):
        if km < h:
            return i, km
    return len(GYURU_KM), km


def kapcsolatok_szama(ep):
    """With how many other buildings does it share a vertex (roughly a shared wall)? Fast: vertices rounded to a 0.5 m grid."""
    tar = defaultdict(set)
    for i, e in enumerate(ep):
        for x, y in e["pts"]:
            tar[(round(x * 2), round(y * 2))].add(i)
    for i, e in enumerate(ep):
        t = set()
        for x, y in e["pts"]:
            t |= tar[(round(x * 2), round(y * 2))]
        t.discard(i)
        e["kapcs"] = len(t)


def epulet_tipus(e, gy):
    t = e["tipus"]
    if t in KOZEPULET or t in MELLEK:
        return "nincs"
    if t in IPARI:
        return "ipari"
    if t in KERESK:
        return "kereskedelmi"
    if t in SORHAZ:
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


ROMAI_KER = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12,
             "XIII": 13, "XIV": 14, "XV": 15, "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20, "XXI": 21, "XXII": 22,
             "XXIII": 23}


def kerulet_szam(v):
    if v in (None, ""):
        return None
    t = str(v).strip().strip(".").upper()
    if t in ROMAI_KER:
        return ROMAI_KER[t]
    try:
        n = int(float(t))
        return n if 1 <= n <= 23 else None
    except ValueError:
        return None


def ksh_beolvasasa():
    """data/KSH/budapest_ksh_keruleti_eloszlas.csv -> {district: [7 proportions]} (they sum to 1). Missing file: None."""
    ut = GYOKER / "data" / "KSH" / "budapest_ksh_keruleti_eloszlas.csv"
    if not ut.exists():
        return None
    d = {}
    for r in csv.DictReader(open(ut, encoding="utf-8-sig")):
        v = [float(r[k]) for k in r if k.startswith("arany_")]
        n = kerulet_szam(r.get("kerulet"))
        if len(v) != K or not n or sum(v) <= 0:
            return None
        z = sum(v)
        d[n] = [x / z for x in v]
    return d


NEM_LAKAS = MELLEK | KOZEPULET | IPARI | KERESK


def lakas_suly(e):
    """Dwelling equivalent (KSH counts dwellings): footprint x number of storeys; outbuilding, public, industry, commerce: 0."""
    if e["tipus"] in NEM_LAKAS or e["terulet"] < 40.0:
        return 0.0
    sz = e.get("szintek")
    if not sz and e.get("magassag") and e.get("mforras") not in (None, "", "alapertelmezett"):
        sz = float(e["magassag"]) / 3.3
    try:
        sz = max(1.0, min(float(sz), 40.0)) if sz else 2.0
    except (TypeError, ValueError):
        sz = 2.0
    return e["terulet"] * sz


def kvota_kiosztas(gray, res, R, Q, sulyok, oreg, tiltott0):
    """Quota-keeping allocation over a group of buildings. R: per-era target (dwelling equivalent) for the
    (dwelling-weighted) buildings. The weighted percentile by the order (oreg) is fitted to the era's quota band, and the mu
    shift adjusts the allocated masses to the target. tiltott0: those who may not receive the 'before 1867' era.
    Returns: {i: per-era scores}; the allocated era is the one with the highest score."""
    rend = sorted(gray, key=oreg)
    ossz_w = sum(sulyok[i] for i in gray) or 1.0
    pct, kum = {}, 0.0
    for i in rend:
        pct[i] = (kum + sulyok[i] / 2) / ossz_w
        kum += sulyok[i]
    sr = sum(R) or 1.0
    f = [r / sr for r in R]
    kozep, elo = [], 0.0
    for c in range(K):
        kozep.append(elo + f[c] / 2)
        elo += f[c]
    LQ = {i: [(-1e9 if (Q[i][c] <= 0.0 or (c == 0 and i in tiltott0)) else math.log(Q[i][c] + 1e-9) - SORREND_KAPPA * ((pct[i] - kozep[c]) / (f[c] + 0.15)) ** 2)
              for c in range(K)] for i in gray}
    mu = tomeg_illesztes(res, LQ, R, sulyok)
    return {i: [LQ[i][x] + mu[x] for x in range(K)] for i in gray}


def tomeg_illesztes(res, pont, R, sulyok):
    """Per-era shift (mu) by which the dwelling-weighted sum of the best eras by score gets close to the target (R)."""
    U = sum(sulyok[i] for i in res)
    mu = [0.0] * K
    if res and U > 0:
        lepes, legjobb = 0.6, (1e18, mu[:])
        for _ in range(60):
            mm = [0.0] * K
            for i in res:
                lq = pont[i]
                c = max(range(K), key=lambda x: lq[x] + mu[x])
                mm[c] += sulyok[i]
            hiba = sum(abs(mm[c] - R[c]) for c in range(K))
            if hiba < legjobb[0]:
                legjobb = (hiba, mu[:])
            if hiba < 0.005 * U:
                break
            eps = 0.01 * U / K
            mu = [mu[c] + lepes * math.log((R[c] + eps) / (mm[c] + eps)) for c in range(K)]
            lepes *= 0.97
        mu = legjobb[1]
    return mu


def foutak_tavolsaga(ep):
    """Outer ring (6 km+): the distance of the grey buildings from the nearest main road (OSM primary/secondary/tertiary/trunk) and
    from a main-road junction (a shared point of two main roads with different names). e['fout_pont'] = min(road, 600 m)/300 + min(junction, 1200 m)/1200:
    smaller = closer to the old settlement structure. Input: data/utak_nyers.json (utak_keszites.py). Returns the number of buildings computed."""
    ut = GYOKER / "data" / "utak_nyers.json"
    if not ut.exists():
        print("Figyelem: nincs data/utak_nyers.json - a helyi kvóta főút-sorrend nélkül fut.")
        return 0
    FO = {"primary", "secondary", "tertiary", "trunk"}
    cx_m = math.cos(math.radians(47.5)) * 111320.0
    CELLA, MAX_UT, MAX_KER = 100.0, 600.0, 1200.0
    racs, csucs = defaultdict(list), defaultdict(set)
    for u in json.load(open(ut, encoding="utf-8")):
        if u.get("h") not in FO or len(u.get("g") or []) < 2:
            continue
        pts = [((x - 19.05) * cx_m, (y - 47.5) * 110574.0) for x, y in u["g"]]
        for a, b in zip(pts, pts[1:]):
            for gx in range(int(min(a[0], b[0]) // CELLA), int(max(a[0], b[0]) // CELLA) + 1):
                for gy in range(int(min(a[1], b[1]) // CELLA), int(max(a[1], b[1]) // CELLA) + 1):
                    racs[(gx, gy)].append((a, b))
        for (x, y), p in zip(u["g"], pts):
            csucs[(round(x, 6), round(y, 6))].add(u.get("n") or str(id(u)))
    kr = defaultdict(list)
    for (x, y), nevek in csucs.items():
        if len(nevek) >= 2:
            p = ((x - 19.05) * cx_m, (y - 47.5) * 110574.0)
            kr[(int(p[0] // CELLA), int(p[1] // CELLA))].append(p)

    def szakasz(p, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = dx * dx + dy * dy
        t = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L))
        return math.dist(p, (a[0] + t * dx, a[1] + t * dy))
    ru, rk = int(MAX_UT // CELLA), int(MAX_KER // CELLA)
    db = 0
    for e in ep:
        if e["kor"] is not None or e.get("gyuru") != 3:
            continue
        p, gx, gy = (e["x"], e["y"]), int(e["x"] // CELLA), int(e["y"] // CELLA)
        du = MAX_UT
        for dx in range(-ru, ru + 1):
            for dy in range(-ru, ru + 1):
                for a, b in racs.get((gx + dx, gy + dy), ()):
                    du = min(du, szakasz(p, a, b))
        dk = MAX_KER
        for dx in range(-rk, rk + 1):
            for dy in range(-rk, rk + 1):
                for q in kr.get((gx + dx, gy + dy), ()):
                    dk = min(dk, math.dist(p, q))
        e["fout_m"] = du
        e["fout_pont"] = du / MAX_UT * 2 + dk / MAX_KER
        db += 1
    return db


def ksh_kvota(ep, szurke, PP, ksh):
    """District KSH fitting. PP: {i: the A model's distribution}. Returns: ({i: (top, q, lambda_top, rearranged)}, diagnostics).
    1) per district, computes how much dwelling-equivalent mass is missing for the KSH target after the buildings of known year (R);
    2) with per-era multipliers (lambda) it shifts the A probabilities so that R comes out in expectation;
    3) allocation: instead of the most probable class, log q + order term + mu: the order term fits the percentile by the building's
       expected era to the era's quota band (a building that looks older gets an older era), and mu adjusts the allocated
       masses to the quota. Strong A evidence (zone, neighbours) overrides the order, with weak evidence the order decides."""
    szurke_halmaz = set(szurke)
    sulyok = [lakas_suly(e) for e in ep]
    kerek = defaultdict(list)
    for i, e in enumerate(ep):
        kerek[kerulet_szam(e.get("kerulet"))].append(i)
    ossz = sum(sulyok[i] for k in ksh for i in kerek[k]) or 1.0
    atlag = [sum(ksh[k][c] * sum(sulyok[i] for i in kerek[k]) for k in ksh) / ossz for c in range(K)]
    eredmeny, diag = {}, []
    regi_szorzo = {}
    for ker, lista in sorted(kerek.items(), key=lambda kv: (kv[0] is None, kv[0] or 0)):
        T = ksh.get(ker, atlag)
        M = sum(sulyok[i] for i in lista)
        Kd = [0.0] * K
        for i in lista:
            if i not in szurke_halmaz and ep[i]["kor"] is not None:
                Kd[ep[i]["kor"]] += sulyok[i]
        gray = [i for i in lista if i in szurke_halmaz]
        res = [i for i in gray if sulyok[i] > 0]
        U = sum(sulyok[i] for i in res)
        lam = [1.0] * K
        R = [U * T[c] for c in range(K)]
        if M > 0 and U > 0:
            R = [max(M * T[c] - Kd[c], 0.0) for c in range(K)]
            sr = sum(R)
            R = [r * U / sr for r in R] if sr > 0 else [U * T[c] for c in range(K)]
            P = [PP[i] for i in res]
            W = [sulyok[i] for i in res]
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
            tiltott0 = {i for i in gray if T[0] < ELSO_KORSZAK_KERULET_MAX and PP[i][0] < ELSO_KORSZAK_MIN_P}

            def oreg(i):
                e = ep[i]
                # the A model's expected era index (from the quota-multiplied distribution) + a tiny, deterministic tie-breaker
                v = sum(c * Q[i][c] for c in range(K)) + 0.02 * ((zlib.crc32(str(e.get("id", i)).encode()) % 10000) / 10000.0)
                if HELYI_KVOTA and e.get("fout_pont") is not None:
                    # outer ring: a house closer to the main road / junction is MORE LIKELY older, but not all of them:
                    # the deterministic noise scatters the old houses (otherwise the row of houses along the road would all be old)
                    zaj = (zlib.crc32(("zaj" + str(e.get("id", i))).encode()) % 100000) / 100000.0
                    v += FOUT_SULY * e["fout_pont"] + ZAJ_SULY * zaj
                return v

            if HELYI_KVOTA:
                # local quota: within the district, per patch of HELYI_CELLA_M, the sum of the (KSH-multiplied) probabilities is allocated,
                # so the old houses stay where the model expects them (e.g. Pesthidegkút), and the district total does not change
                foltok = defaultdict(list)
                for i in gray:
                    if HELYI_CSAK_KULSO and ep[i].get("gyuru") != 3:
                        foltok["kerulet"].append(i)       # inner rings (within 6 km): the old, district-level allocation; this also takes over the demolition deficit
                    else:
                        foltok[(int(ep[i]["x"] // HELYI_CELLA_M), int(ep[i]["y"] // HELYI_CELLA_M))].append(i)
                def helyi_pont(szorzo):
                    pont, Rd = {}, [0.0] * K
                    celok = {}
                    attolt = [0.0] * K           # the target passed from the outer patches to the rest of the district (old eras +, new ones -)
                    for kulcs, tagok in foltok.items():
                        fres = [i for i in tagok if sulyok[i] > 0]
                        Rf = [0.0] * K
                        for i in fres:
                            q = [0.0 if (c == 0 and i in tiltott0) else Q[i][c] for c in range(K)]
                            z = sum(q) or 1.0
                            for c in range(K):
                                Rf[c] += sulyok[i] * q[c] / z
                        if kulcs != "kerulet" and szorzo < 1.0:
                            # garden suburb: most of the old houses were demolished -> fewer old, more recent houses in the patch
                            el = sum(Rf[c] * (1 - szorzo) for c in REGI_KORSZAKOK)
                            uj = [c for c in range(K) if c not in REGI_KORSZAKOK and c > max(REGI_KORSZAKOK)]
                            uj_ossz = sum(Rf[c] for c in uj) or 1.0
                            for c in REGI_KORSZAKOK:
                                attolt[c] += Rf[c] * (1 - szorzo)
                                Rf[c] *= szorzo
                            for c in uj:
                                d = el * Rf[c] / uj_ossz
                                Rf[c] += d
                                attolt[c] -= d
                        celok[kulcs] = (tagok, fres, Rf)
                    if "kerulet" in celok:            # the rest of the district (inner rings, zones) takes over the shortfall, so the KSH total does not change
                        tagok, fres, Rf = celok["kerulet"]
                        celok["kerulet"] = (tagok, fres, [max(a + b, 0.0) for a, b in zip(Rf, attolt)])
                    for tagok, fres, Rf in celok.values():
                        pont.update(kvota_kiosztas(tagok, fres, Rf, Q, sulyok, oreg, tiltott0))
                        Rd = [a + b for a, b in zip(Rd, Rf)]
                    # district equalisation: the rounding error of the small patches would add up, so a common shift sets the district total to the target
                    mu2 = tomeg_illesztes(res, pont, Rd, sulyok)
                    pont = {i: [v + m for v, m in zip(pont[i], mu2)] for i in gray}
                    return pont

                def elteres(pont):
                    mm = [0.0] * K
                    for i in lista:
                        cc = max(range(K), key=lambda x: pont[i][x]) if i in szurke_halmaz else ep[i]["kor"]
                        if cc is not None and sulyok[i] > 0:
                            mm[cc] += sulyok[i]
                    z = sum(mm) or 1.0
                    return max(abs(100 * mm[cc] / z - 100 * T[cc]) for cc in range(K))
                # the demolition multiplier is set per district to the strongest value at which the KSH deviation grows by at most KSH_TURES points
                pont = helyi_pont(1.0)
                hasznalt = 1.0
                if KULSO_REGI_SZORZO < 1.0:
                    alap_e = elteres(pont)
                    for sz in sorted({KULSO_REGI_SZORZO} | {s for s in (0.33, 0.5, 0.75) if s > KULSO_REGI_SZORZO}):
                        p_ = helyi_pont(sz)
                        if elteres(p_) <= alap_e + KSH_TURES:
                            pont, hasznalt = p_, sz
                            break
                regi_szorzo[ker] = hasznalt
            else:
                pont = kvota_kiosztas(gray, res, R, Q, sulyok, oreg, tiltott0)
            for i in gray:
                top = max(range(K), key=lambda x: pont[i][x])
                eredmeny[i] = (top, Q[i], lam[top], top != max(range(K), key=lambda x: PP[i][x]))

        def arany(valaszt):
            mm = [0.0] * K
            for i in lista:
                c = valaszt(i) if i in szurke_halmaz else ep[i]["kor"]
                if c is not None and sulyok[i] > 0:
                    mm[c] += sulyok[i]
            z = sum(mm) or 1.0
            return [100 * v / z for v in mm]
        elotte = arany(lambda i: max(range(K), key=lambda x: PP[i][x]))
        utana = arany(lambda i: eredmeny[i][0] if i in eredmeny else None)
        cel = [100 * v for v in T]
        diag.append({"regi_szorzo": regi_szorzo.get(ker), "ker": ker, "db": len(lista), "szurke": len(gray), "cel": cel, "elotte": elotte, "utana": utana,
                     "lam": max(lam), "elter_elotte": max(abs(a - b) for a, b in zip(elotte, cel)),
                     "elter_utana": max(abs(a - b) for a, b in zip(utana, cel)),
                     "atrendezett": sum(1 for i in gray if i in eredmeny and eredmeny[i][3])})
    return eredmeny, diag


def ksh_jelentes(diag):
    sor = ["## KSH-illesztés kerületenként (lakás-egyenérték szerinti %, a tudott évű épületekkel együtt)\n",
           "Cellák: KSH-cél / a modell az illesztés ELŐTT / az illesztés UTÁN. Az illesztés után a legnagyobb eltérésnek 0–1 százalékpont körül kell lennie.\n",
           "| ker. | épület | szürke | " + " | ".join(k[2] for k in KORSZAKOK) + " | legnagyobb eltérés előtte → utána (százalékpont) | legnagyobb szorzó | átrendezett épület | kertvárosi régi házak megmaradó része |",
           "|---|---|---|" + "---|" * K + "---|---|---|---|"]
    for d in diag:
        if d["ker"] is None:
            continue
        cella = " | ".join(f"{d['cel'][c]:.0f} / {d['elotte'][c]:.0f} / {d['utana'][c]:.0f}" for c in range(K))
        sor.append(f"| {d['ker']} | {d['db']} | {d['szurke']} | {cella} | {d['elter_elotte']:.1f} → {d['elter_utana']:.1f} | x{d['lam']:.1f} | {d['atrendezett']} | {'–' if d.get('regi_szorzo') is None else f"{100 * d['regi_szorzo']:.0f}%"} |")
    sor.append("\nNagy szorzó = a tudott évű épületek vagy a KSH-tábla nem reprezentatív abban a kerületben. "
               "Az illesztés lakás-egyenértékre (alapterület x szintszám) igaz, épületszámra nem.\n")
    return "\n".join(sor)


def gyuru_es_tipus(ep):

    """City mode: for every building a ring, type and prior distribution (e['prior']). The ring comes from the distance from Deák tér."""
    kapcsolatok_szama(ep)
    atlag = {}
    for gy in range(len(GYURU_KM) + 1):
        b, c = PRIOR_TIPUSOK.get("berhaz"), PRIOR_TIPUSOK.get("csaladi")
        if b and c:
            atlag[gy] = [(b[gy][y] + c[gy][y]) / 2 for y in range(K)]
    for e in ep:
        gy, km = gyuru_index(e["x"], e["y"])
        tip = epulet_tipus(e, gy)
        e["gyuru_km"], e["etipus"], e["gyuru"] = km, tip, gy
        e["prior"] = PRIOR_TIPUSOK[tip][gy] if tip in PRIOR_TIPUSOK else atlag.get(gy)


def egyszerusit(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return "".join(c for c in s if c.isalnum())


# ---------------------------------------------------------------- reading input
def epuletek_beolvasasa():
    g = json.load(open(ADAT / ("epuletek_vegleges.geojson" if VAROS else "belvaros_epuletek_vegleges.geojson"), encoding="utf-8"))
    lista = []
    for f in g["features"]:
        p = f["properties"]
        if p.get("resz"):
            continue  # building parts are not estimated (they inherit the parent building)
        if p.get("rom"):
            continue  # ancient/medieval ruin: a category of its own, fixed (tenyek_romok.py), not estimated
        geo = f["geometry"]
        if geo["type"] == "Polygon":
            gyuru = geo["coordinates"][0]
        elif geo["type"] == "MultiPolygon":
            gyuru = geo["coordinates"][0][0]
        else:
            continue
        pts = [((x - 19.05) * math.cos(math.radians(47.5)) * 111320.0, (y - 47.5) * 110574.0)
               for x, y in gyuru]
        a2 = cx = cy = 0.0
        for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
            c = x0 * y1 - x1 * y0
            a2 += c
            cx += (x0 + x1) * c
            cy += (y0 + y1) * c
        if abs(a2) < 1e-6:
            continue
        terulet = abs(a2) / 2
        kerulet = sum(math.dist(a, b) for a, b in zip(pts, pts[1:] + pts[:1]))
        ev = p.get("ev")
        try:
            ev = int(ev) if ev not in (None, "") else None
        except (TypeError, ValueError):
            ev = None
        lista.append({
            "kulcs": (p.get("osm_tipus") or "way", int(p["id"])),
            "x": cx / (3 * a2), "y": cy / (3 * a2), "pts": pts,
            "terulet": terulet, "kompakt": 4 * math.pi * terulet / (kerulet ** 2),
            "szintek": p.get("szintek"), "magassag": p.get("magassag"),
            "tipus": p.get("tipus") or "yes", "ev": ev,
            "kor": korszak_index(ev) if ev else None,
            "vedett": bool(p.get("vedettseg")), "nev": p.get("nev") or "",
            "zarvany": (p.get("tipus") in ZARVANY_TIPUSOK) or bool(ZARVANY_NEV.search(p.get("nev") or "")) or bool(p.get("csoport")),   # a building group merged under one name (e.g. a bath) is one enclave
            "kerulet": p.get("kerulet"), "mforras": p.get("magassag_forras"),
        })
    return lista


def utcak_beolvasasa(epuletek):
    atnev = {}
    ut = GYOKER / "forras" / "utcanev_atnevezesek.csv"
    if ut.exists():
        for r in csv.DictReader(open(ut, encoding="utf-8-sig"), delimiter=";"):
            if "|" not in (r["uj"] or ""):
                atnev[egyszerusit(r["regi"])] = r["uj"]
    cimek = {}
    ut = ADAT / "osm_cimek.csv"
    if ut.exists():
        for r in csv.DictReader(open(ut, encoding="utf-8-sig"), delimiter=";"):
            k = (r["osm_tipus"], int(r["id"]))
            u = atnev.get(egyszerusit(r["utca"]), r["utca"])
            cimek.setdefault(k, egyszerusit(u))
    for e in epuletek:
        u = cimek.get(e["kulcs"])
        e["utca"] = ((e.get("kerulet") or 0, u) if u else None) if VAROS else u


class ZonaTar:
    """In city mode: (district, street) -> zone; zones without a district (inner city) apply in any district."""

    def __init__(self):
        self.d = {}

    def get(self, kulcs):
        if not kulcs:
            return None
        return self.d.get(kulcs) or self.d.get((None, kulcs[1]))

    def __getitem__(self, kulcs):
        return self.get(kulcs)

    def __bool__(self):
        return bool(self.d)


def zona_eloszlas(tol, ig):
    atfedes = []
    for a, b, _ in KORSZAKOK:
        o = max(0, min(ig, b) - max(tol, a) + 1)
        atfedes.append(o / (ig - tol + 1))
    return [0.9 * x + 0.1 / K for x in atfedes]


def zonak_beolvasasa():
    utca_zona = ZonaTar() if VAROS else {}
    fajlok = ["varosfejlodes.json"] + (["varosfejlodes_kerulet.json"] if VAROS else [])
    for fn in fajlok:
        ut = GYOKER / "forras" / fn
        if not ut.exists():
            continue
        d = json.load(open(ut, encoding="utf-8"))
        sulyok = d.get("_sulyok", {"forrasolt": 1.0, "ellenorizendo": 0.4})
        sulyok = {"forrasolt": 1.0, "ellenorizendo": 0.4, **sulyok}
        for z in d["zonak"]:
            kerulet_zona = fn != "varosfejlodes.json"
            if not z.get("idoszak") or not z.get("utcak"):
                continue  # there is no boundary for polygon zones and zones without a street list
            if not kerulet_zona and z.get("tipus") != "utcak":
                continue
            tol, ig = z["idoszak"]
            eloszlas = zona_eloszlas(tol, ig)
            for u in z["utcak"]:
                rec = (z["id"], eloszlas, sulyok.get(z["allapot"], 0.4))
                if VAROS:
                    utca_zona.d[(z.get("kerulet") if kerulet_zona else None, egyszerusit(u))] = rec
                else:
                    utca_zona[egyszerusit(u)] = rec
    return utca_zona


# ---------------------------------------------------------------- spatial relations
def szomszedok_epitese_varos(ep):
    """City mode: only the known (labelled) buildings are kept as neighbours, the nearest MAX_SZOMSZED per building.
    Contact (shared wall) is examined only with the known buildings."""
    cimk = [j for j, e in enumerate(ep) if e["kor"] is not None]
    cella = defaultdict(list)
    for j in cimk:
        cella[(int(ep[j]["x"] // SZOMSZED_SUGAR), int(ep[j]["y"] // SZOMSZED_SUGAR))].append(j)
    csucs = defaultdict(set)
    for j in cimk:
        for x, y in ep[j]["pts"]:
            csucs[(int(x // 2), int(y // 2))].add(j)
    szomsz = []
    for i, e in enumerate(ep):
        erint = set()
        pts = e["pts"] if e.get("pts") else e["pts_fn"]()
        for x, y in pts:
            cx, cy = int(x // 2), int(y // 2)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for j in csucs.get((cx + dx, cy + dy), ()):
                        if j != i and j not in erint and any(math.dist((x, y), q) <= ERINTKEZES_M for q in ep[j]["pts"]):
                            erint.add(j)
        cx, cy = int(e["x"] // SZOMSZED_SUGAR), int(e["y"] // SZOMSZED_SUGAR)
        sor = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in cella.get((cx + dx, cy + dy), ()):
                    if j == i:
                        continue
                    d = math.dist((e["x"], e["y"]), (ep[j]["x"], ep[j]["y"]))
                    if d <= SZOMSZED_SUGAR:
                        sor.append((j, d, j in erint))
        if len(sor) > MAX_SZOMSZED + 1:
            sor.sort(key=lambda t: t[1])
            sor = sor[:MAX_SZOMSZED + 1]
        szomsz.append(sor)
    return szomsz


def szomszedok_epitese(ep):
    if VAROS:
        return szomszedok_epitese_varos(ep)
    n = len(ep)
    cella = defaultdict(list)
    for i, e in enumerate(ep):
        cella[(int(e["x"] // SZOMSZED_SUGAR), int(e["y"] // SZOMSZED_SUGAR))].append(i)
    csucs = defaultdict(set)
    for i, e in enumerate(ep):
        for x, y in e["pts"]:
            csucs[(int(x // 2), int(y // 2))].add(i)
    erint = [set() for _ in range(n)]
    for i, e in enumerate(ep):
        for x, y in e["pts"]:
            cx, cy = int(x // 2), int(y // 2)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for j in csucs.get((cx + dx, cy + dy), ()):
                        if j != i and j not in erint[i]:
                            if any(math.dist((x, y), q) <= ERINTKEZES_M for q in ep[j]["pts"]):
                                erint[i].add(j)
                                erint[j].add(i)
    szomsz = []
    for i, e in enumerate(ep):
        cx, cy = int(e["x"] // SZOMSZED_SUGAR), int(e["y"] // SZOMSZED_SUGAR)
        sor = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in cella.get((cx + dx, cy + dy), ()):
                    if j == i:
                        continue
                    d = math.dist((e["x"], e["y"]), (ep[j]["x"], ep[j]["y"]))
                    if d <= SZOMSZED_SUGAR:
                        sor.append((j, d, j in erint[i]))
        szomsz.append(sor)
    return szomsz


# ---------------------------------------------------------------- shape features
def tipus_csoport(t):
    if t == "apartments":
        return "lakoepulet"
    if t in ("yes", "residential", "house"):
        return "altalanos"
    if t in ("office", "commercial", "retail", "hotel"):
        return "kereskedelmi"
    return "kozint_egyeb"


def jellemzok(e):
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
    ter = "<150" if t < 150 else "<300" if t < 300 else "<600" if t < 600 else "<1200" if t < 1200 else "1200+"
    kom = "kompakt" if e["kompakt"] > 0.6 else "tagolt"
    return {"szint": szs, "terulet": ter, "tipus": tipus_csoport(e["tipus"]), "forma": kom}


FELT_ERTEKEK = {  # for the Laplace smoothing: how many possible values there are
    "szint": 6, "terulet": 5, "tipus": 4, "forma": 2,
}


class Modell:
    """Tables computed from the labelled buildings (class frequencies, shape tables)."""

    def __init__(self, ep, tanito):
        self.ep = ep
        self.tanito = set(tanito)
        self.db = [0] * K
        self.alak = {f: [Counter() for _ in range(K)] for f in FELT_ERTEKEK}
        self.jell = {}
        for i in self.tanito:
            self.hozzaad(i, +1)

    def hozzaad(self, i, elojel):
        e = self.ep[i]
        y = e["kor"]
        self.db[y] += elojel
        j = self.jell.get(i) or jellemzok(e)
        self.jell[i] = j
        for f, v in j.items():
            self.alak[f][y][v] += elojel

    def alapeloszlas(self, kizart=()):
        db = list(self.db)
        for i in kizart:
            if i in self.tanito:
                db[self.ep[i]["kor"]] -= 1
        ossz = sum(db)
        return [(c + 1) / (ossz + K) for c in db]


def komponensek(i, ep, szomsz, m, utca_index, zonak, kizart):
    """Returns the four pieces of evidence of the i-th building as log-probabilities (lists of length K).
    kizart: the indices whose label it must not see (itself, or the block)."""
    e = ep[i]
    kiz = set(kizart) | {i}
    alap = m.alapeloszlas(kiz)
    if VAROS and e.get("prior"):
        b = GLOBAL_KEVERES
        alap = [(1 - b) * p + b * g for p, g in zip(e["prior"], alap)]
    # neighbours
    N = [0.0] * K
    for j, d, erint in szomsz[i]:
        if j in kiz or j not in m.tanito:
            continue
        w = math.exp(-d / SZOMSZED_LECSENGES) * (ERINTKEZES_SZORZO if erint else 1.0)
        if ep[j].get("zarvany"):          # church, ruin: an enclave, not a characteristic of the surroundings
            w *= ZARVANY_SULY
        N[ep[j]["kor"]] += w
    ossz = sum(N)
    a = 0.5
    lN = [math.log((N[y] + a * alap[y]) / (ossz + a)) for y in range(K)]
    # street
    lS = [0.0] * K
    if e["utca"]:
        C = [0] * K
        for j in utca_index.get(e["utca"], ()):
            if j not in kiz and j in m.tanito:
                C[ep[j]["kor"]] += ZARVANY_SULY if ep[j].get("zarvany") else 1
        n = sum(C)
        lS = [math.log((C[y] + 2 * alap[y]) / (n + 2)) for y in range(K)]
    # shape (naive Bayes)
    j = jellemzok(e)
    db = list(m.db)
    for t in kiz:
        if t in m.tanito:
            db[ep[t]["kor"]] -= 1
    lF = [0.0] * K
    for f, v in j.items():
        for y in range(K):
            c = m.alak[f][y][v]
            for t in kiz:
                if t in m.tanito and ep[t]["kor"] == y and m.jell[t][f] == v:
                    c -= 1
            lF[y] += math.log((c + 1) / (db[y] + FELT_ERTEKEK[f]))
    # zone
    lZ = [0.0] * K
    zsuly = 0.0
    z = zonak.get(e["utca"]) if e["utca"] else None
    if z:
        lZ = [math.log(p) for p in z[1]]
        zsuly = z[2]
    l0 = [math.log(p) for p in alap]
    gy = SZOMSZED_SULY[min(e.get("gyuru", 0), len(SZOMSZED_SULY) - 1)] if VAROS else 1.0
    gf = ALAK_SULY[min(e.get("gyuru", 0), len(ALAK_SULY) - 1)] if VAROS else 1.0
    lP, psuly = None, 0.0
    if VAROS and e.get("pz") is not None:
        z = PZ_LISTA[e["pz"]]
        lP, psuly = [math.log(v) for v in z["eloszlas"]], z["suly"]
    return {"0": l0, "N": lN, "S": lS, "F": lF, "Z": lZ, "zsuly": zsuly, "gy": gy, "gf": gf, "G": e.get("ghsl_l"), "P2": lP, "p2suly": psuly}


def zona_tiltott(e):
    """Indices of the eras excluded by the smallest containing (non-test) drawn zone (an empty list if there is no zone)."""
    if not VAROS or e.get("pz") is None:
        return []
    z = PZ_LISTA[e["pz"]]
    tilt = []
    for c, (a, b, _) in enumerate(KORSZAKOK):
        if (ZONA_TOL_HATAR and b < z["tol"]) or (z.get("ig_hatar") and a > z["ig"]):
            tilt.append(c)
    return tilt if len(tilt) < K else []


def eloszlas(k, w):
    s = []
    for y in range(K):
        g = k.get("gy", 1.0)
        s.append(w["0"] * k["0"][y] + g * (w["N"] * k["N"][y] + w["S"] * k["S"][y])
                 + k.get("gf", 1.0) * w["F"] * k["F"][y] + w["Z"] * k["zsuly"] * k["Z"][y]
                 + (PZ_SULY * k["p2suly"] * k["P2"][y] if k.get("P2") else 0.0)
                 + (w.get("G", GH["suly"]) * k["G"][y] if k.get("G") else 0.0))
    mx = max(s)
    ex = [math.exp(v - mx) for v in s]
    t = sum(ex)
    return [v / t for v in ex]


# ---------------------------------------------------------------- measurement
def metrikak(par):
    """par: [(true_index, distribution)] -> dictionary"""
    if not par:
        return {"n": 0}
    n = len(par)
    pont = sum(1 for y, p in par if max(range(K), key=lambda q: p[q]) == y)
    top2 = sum(1 for y, p in par if y in sorted(range(K), key=lambda q: -p[q])[:2])
    ll = -sum(math.log(max(p[y], 1e-9)) for y, p in par) / n
    # a one-era error: an era adjacent to the true one
    kozel = sum(1 for y, p in par if abs(max(range(K), key=lambda q: p[q]) - y) <= 1)
    return {"n": n, "pontossag": pont / n, "top2": top2 / n, "logloss": ll, "legfeljebb_1_korszak_tevedes": kozel / n}


def sulyok_racs():
    for wn in (0.0, 0.5, 1.0, 1.5):
        for ws in (0.0, 0.3, 0.6):
            for wf in (0.0, 0.3, 0.6, 1.0):
                for wz in (0.0, 0.5, 1.0):
                    for w0 in ((1.0,) if VAROS else (0.0, 0.5, 1.0)):
                        yield {"0": w0, "N": wn, "S": ws, "F": wf, "Z": wz}


def bizonyossagi_kuszob(egyed, cel, felso=None, min_db=20):
    """egyed: [(probability of the most probable era, whether it hit)], in descending order.
    Returns the smallest threshold p for which the buildings falling into the band [p, felso) have an OWN hit rate of at least 'cel'
    (felso=None: no upper bound). Earlier the hits of the upper bands were included too (cumulative rate), so the
    'medium' band was reported as >=70% when it was really ~52%. If no threshold satisfies it: None."""
    lista = [(p, ok) for p, ok in egyed if felso is None or p < felso]
    legjobb = None
    talalt = 0
    for n, (p, ok) in enumerate(lista, 1):
        talalt += ok
        if n < len(lista) and lista[n][0] == p:
            continue          # guesses of equal probability can only go into a band together
        if n >= min_db and talalt / n >= cel:
            legjobb = p
    return legjobb


def kiertekel(rendezett, komp, w):
    return [(ep_y, eloszlas(k, w)) for ep_y, k in zip(rendezett, komp)]


def ghsl_beolvasasa(ep):
    """data/varos/ghsl.csv (tenyek_ghsl.py): the built-up m2 of the building's 100 m cell for several years.
    Principle: the building is a random member of the cell's present (last-year) building stock. If a share f1 of the cell's built-up area already existed
    at the first year, and f2-f1 was built between the first and second, etc., then the building's construction time comes from these
    windows, weighted by the windows. Within a window the distribution is uniform; the probability of the eras comes from the overlap of the windows with the
    era (relative to the uniform distribution, clipped to [eps, max]).
    The data comes from the map, not from the buildings of known year, so it does not leak into the test either."""
    ut = ADAT / "ghsl.csv"
    if not VAROS or not ut.exists():
        return 0
    idx = {e["kulcs"]: i for i, e in enumerate(ep)}
    KEZD, VEG = 1800, 2026
    db = 0
    for r in csv.DictReader(open(ut, encoding="utf-8-sig"), delimiter=";"):
        i = idx.get((r["osm_tipus"], int(r["id"])))
        if i is None:
            continue
        evek = sorted(int(k[3:]) for k in r if k and k.startswith("m2_"))
        ertek = [r["m2_%d" % ev] for ev in evek]
        if not evek or any(v == "" for v in ertek):
            continue
        fut, ossz = [], 0.0
        for v in ertek:
            ossz = max(ossz, float(v))
            fut.append(ossz)
        if ossz < GH["min_m2"]:
            GHSL_STAT["a cella 2020-ra sem érdemben beépített (nincs információ)"] += 1
            continue
        # windows: (start, end, mass)
        hatarok = [KEZD] + evek + [VEG]
        resz = [fut[0] / ossz] + [(fut[k] - fut[k - 1]) / ossz for k in range(1, len(fut))] + [0.0]
        u = GH["utolso"]
        resz = [(1 - u) * x + u / len(resz) for x in resz]
        sur = [(hatarok[k], hatarok[k + 1], resz[k] / (hatarok[k + 1] - hatarok[k])) for k in range(len(resz))]
        l = []
        for tol, ig, _ in KORSZAKOK:
            a, b = max(tol, KEZD), min(ig, VEG)
            hossz = b - a + 1 if b >= a else 0
            if hossz <= 0:
                l.append(math.log(1.0))
                continue
            atfedes = sum(max(0, min(b, h1) - max(a - 1, h0)) * d for h0, h1, d in sur)      # the years of the window (h0, h1]
            arany = atfedes / hossz * (VEG - KEZD)
            l.append(math.log(min(GH["max"], max(GH["eps"], arany))))
        ep[i]["ghsl_l"] = l
        f_elso = fut[0] / ossz
        ep[i]["ghsl_ablak"] = max(range(len(resz) - 1), key=lambda k: resz[k])
        ep[i]["ghsl_elso"] = f_elso
        GHSL_STAT["1975-re a cella beépítettségének >75%-a megvolt" if f_elso > 0.75 else
                  "1975-re 25–75%-a" if f_elso >= 0.25 else "1975-re <25%-a (főleg újabb)"] += 1
        db += 1
    return db


def kozelito_cimkek(ep):
    """City mode: the approximate era data of the heritage inventories ('the 1930s') counts as a label if the range
    falls into a single era and the building has no exact year. Returns: {index: text}."""
    utak = sorted(ADAT.glob("*_kozelito.csv")) if VAROS else []      # ertekleltar_, osm_, wikidata_kozelito.csv...
    if not utak:
        return {}
    idx = {e["kulcs"]: i for i, e in enumerate(ep)}
    ki = {}
    kulonbozo = defaultdict(set)
    for ut in utak:
        for r in csv.DictReader(open(ut, encoding="utf-8-sig"), delimiter=";"):
            i = idx.get((r["osm_tipus"], int(r["id"])))
            if i is None or ep[i]["kor"] is not None:
                continue
            a, b = korszak_index(int(r["ev_tol"])), korszak_index(int(r["ev_ig"]))
            if a is None or a != b:
                continue
            kulonbozo[i].add(a)
            ki[i] = (a, f"{r['szoveg']} ({r['forras']})")
    ered = {}
    for i, (k, szoveg) in ki.items():
        if len(kulonbozo[i]) == 1:
            ep[i]["kor"] = k
            ered[i] = szoveg
    return ered


def kozelito_tartomanyok(ep):
    """City mode: approximate data spanning several eras ('1920-1930-as évek' i.e. 1920s-30s, 'XIX. század' i.e. 19th century) also narrows the estimate: the grey building's
    probability is restricted to the eras in the range (data falling into a single era becomes a label, see kozelito_cimkek).
    With several sources, the intersection of the ranges; if the intersection is empty, the data are ignored. Returns: {index: (eras, text)}."""
    utak = sorted(ADAT.glob("*_kozelito.csv")) if VAROS else []
    if not utak:
        return {}
    idx = {e["kulcs"]: i for i, e in enumerate(ep)}
    gyujt = defaultdict(list)
    for ut in utak:
        for r in csv.DictReader(open(ut, encoding="utf-8-sig"), delimiter=";"):
            i = idx.get((r["osm_tipus"], int(r["id"])))
            if i is None or ep[i]["kor"] is not None:
                continue
            gyujt[i].append((int(r["ev_tol"]), int(r["ev_ig"]), f"{r['szoveg'] or str(r['ev_tol']) + '–' + str(r['ev_ig'])} ({r['forras']})"))
    ered = {}
    for i, l in gyujt.items():
        tol, ig = max(x[0] for x in l), min(x[1] for x in l)
        if tol > ig:
            continue
        ks = [q for q, (a, b, _) in enumerate(KORSZAKOK) if a <= ig and b >= tol]
        if 1 <= len(ks) < len(KORSZAKOK):
            ered[i] = (set(ks), "; ".join(x[2] for x in l[:2]))
    return ered


def main():
    ep = epuletek_beolvasasa()
    print(f"Zárvány-épület (templom, kápolna, zsinagóga, rom stb.; a szomszédokra x{ZARVANY_SULY} súllyal hat): {sum(1 for e in ep if e.get('zarvany'))}")
    utcak_beolvasasa(ep)
    if VAROS:
        poligon_zonak_beolvasasa()
        poligon_zonak_hozzarendelese(ep)
        print(f"Poligon-zónák: {len(PZ_LISTA)} (mérőpróba: {sum(1 for z in PZ_LISTA if z['mero'])}); "
              f"zónába eső épület: {sum(1 for e in ep if e['pz'] is not None)}")
    if VAROS and prior_beolvasasa():
        gyuru_es_tipus(ep)
        print("Épülettípusok:", dict(Counter(e["etipus"] for e in ep)))
        print("Gyűrűk:", dict(Counter(GYURU_NEVEK[e["gyuru"]] for e in ep)))
    lagy = kozelito_cimkek(ep)
    gdb = ghsl_beolvasasa(ep)
    if VAROS:
        print(f"GHSL-bizonyíték: {gdb} épületnél ({dict(GHSL_STAT)})")
    if VAROS:
        print(f"Címkézett épület: {sum(1 for e in ep if e['kor'] is not None)} (ebből közelítő, értékleltárból: {len(lagy)})")
    zonak = zonak_beolvasasa()
    szomsz = szomszedok_epitese(ep)
    cimkezett = [i for i, e in enumerate(ep) if e["kor"] is not None]
    szurke = [i for i, e in enumerate(ep) if e["kor"] is None]
    utca_index = defaultdict(list)
    for i, e in enumerate(ep):
        if e["utca"]:
            utca_index[e["utca"]].append(i)
    m = Modell(ep, cimkezett)

    # --- 1) "hide one at a time" components
    kp_loo = {i: komponensek(i, ep, szomsz, m, utca_index, zonak, ()) for i in cimkezett}
    # --- 2) block-exclusion components (a stricter test)
    blokk = defaultdict(list)
    for i in cimkezett:
        blokk[(int(ep[i]["x"] // BLOKK_M), int(ep[i]["y"] // BLOKK_M))].append(i)
    kp_blokk = {}
    for b, tagok in blokk.items():
        for i in tagok:
            kp_blokk[i] = komponensek(i, ep, szomsz, m, utca_index, zonak, tagok)

    # --- 3) cross-fitting the weights: tuning on one half's spatial blocks, measuring on the other
    def fel(i):
        b = (int(ep[i]["x"] // BLOKK_M), int(ep[i]["y"] // BLOKK_M))
        return (b[0] * 7 + b[1] * 13) % 2

    def legjobb_suly(indexek):
        legjobb = None
        for w in sulyok_racs():
            ll = metrikak([(ep[i]["kor"], eloszlas(kp_loo[i], w)) for i in indexek])["logloss"]
            if legjobb is None or ll < legjobb[0]:
                legjobb = (ll, w)
        return legjobb[1]

    A = [i for i in cimkezett if fel(i) == 0]
    B = [i for i in cimkezett if fel(i) == 1]
    wA, wB = legjobb_suly(A), legjobb_suly(B)
    keresztillesztett = [(ep[i]["kor"], eloszlas(kp_loo[i], wA)) for i in B] + \
                        [(ep[i]["kor"], eloszlas(kp_loo[i], wB)) for i in A]
    w_vegso = legjobb_suly(cimkezett)

    # --- 4) report
    ures = {"0": 0, "N": 0, "S": 0, "F": 0, "Z": 0, "G": 0}
    alap_csak = dict(ures, **{"0": 1.0})
    sor = {}
    sor["a legtöbbször előforduló korszak tippelése"] = metrikak([(ep[i]["kor"], eloszlas(kp_loo[i], alap_csak)) for i in cimkezett])
    sor["a végső modell (egyenként elrejtve)"] = metrikak([(ep[i]["kor"], eloszlas(kp_loo[i], w_vegso)) for i in cimkezett])
    sor["a végső modell (keresztillesztett súlyokkal)"] = metrikak(keresztillesztett)
    sor["a végső modell (300 m-es blokk kizárva)"] = metrikak([(ep[i]["kor"], eloszlas(kp_blokk[i], w_vegso)) for i in cimkezett])
    abl = {}
    for nev, kulcs in (("szomszédok nélkül", "N"), ("utca nélkül", "S"), ("alak nélkül", "F"), ("zóna nélkül", "Z"), ("alapeloszlás nélkül", "0"), ("GHSL nélkül", "G")):
        w = dict(w_vegso)
        w[kulcs] = 0.0
        abl[nev] = metrikak([(ep[i]["kor"], eloszlas(kp_loo[i], w)) for i in cimkezett])
    # the drawn (polygon) zones were made with knowledge of the buildings of known year (e.g. Wekerle estate), so in the measurement they also "see" the answer:
    # this row shows the accuracy without the drawn zone's evidence
    abl["rajzolt zóna nélkül"] = metrikak([(ep[i]["kor"], eloszlas(dict(kp_loo[i], P2=None, p2suly=0.0), w_vegso)) for i in cimkezett])

    nem_vedett = [i for i in cimkezett if not ep[i]["vedett"]]
    zonan_kivul = [i for i in nem_vedett if ep[i].get("pz") is None]
    alcsoport = {
        "védett épületek": metrikak([(ep[i]["kor"], eloszlas(kp_loo[i], w_vegso)) for i in cimkezett if ep[i]["vedett"]]),
        "NEM védett épületek": metrikak([(ep[i]["kor"], eloszlas(kp_loo[i], w_vegso)) for i in nem_vedett]),
        "NEM védett, rajzolt zónán kívül": metrikak([(ep[i]["kor"], eloszlas(kp_loo[i], w_vegso)) for i in zonan_kivul]),
    }
    korszakonkent = {}
    for y in range(K):
        par = [(ep[i]["kor"], eloszlas(kp_loo[i], w_vegso)) for i in cimkezett if ep[i]["kor"] == y]
        if par:
            talalt = sum(1 for yy, p in par if max(range(K), key=lambda q: p[q]) == yy)
            korszakonkent[y] = (len(par), talalt / len(par))
    zsor = Counter()
    for i in cimkezett:
        zsor["zónával" if kp_loo[i]["zsuly"] > 0 else "zóna nélkül"] += 1
    ossz_szurke_zona = sum(1 for i in szurke if zonak.get(ep[i]["utca"]))

    # confusion matrix and calibration
    zav = [[0] * K for _ in range(K)]
    kal = defaultdict(lambda: [0, 0])
    for i in cimkezett:
        p = eloszlas(kp_loo[i], w_vegso)
        top = max(range(K), key=lambda q: p[q])
        zav[ep[i]["kor"]][top] += 1
        sav = min(int(p[top] * 10), 9) / 10
        kal[sav][0] += 1
        kal[sav][1] += (top == ep[i]["kor"])
    # certainty thresholds
    egyed = sorted(((max(eloszlas(kp_loo[i], w_vegso)),
                     max(range(K), key=lambda q: eloszlas(kp_loo[i], w_vegso)[q]) == ep[i]["kor"])
                    for i in cimkezett), reverse=True)

    k_magas = bizonyossagi_kuszob(egyed, 0.85)
    k_kozepes = bizonyossagi_kuszob(egyed, 0.70, felso=k_magas)

    nem_vedett_kal = [i for i in cimkezett if not ep[i]["vedett"]]
    # --- calibration for the probability shown on the card/in the CSV ---
    # The raw probability is overconfident (about 2/3 of the guesses called 90-100% hit). The displayed value is therefore what the
    # model actually achieved in the measurement: the hit rate belonging to the raw probability of the most probable era, with the spatial
    # 300 m block excluded (without the neighbour's year), on NON-protected known buildings, with isotonic (PAV) smoothing.
    kal_parok = sorted(((max(pp_), max(range(K), key=lambda q: pp_[q]) == ep[i]["kor"])
                        for i in nem_vedett_kal for pp_ in [eloszlas(kp_blokk[i], w_vegso)]))
    blokkok = []                                       # [hits, count, sum of raw probabilities]
    for pv, ok in kal_parok:
        blokkok.append([float(ok), 1, pv])
        while len(blokkok) > 1 and blokkok[-2][0] / blokkok[-2][1] >= blokkok[-1][0] / blokkok[-1][1]:
            b = blokkok.pop()
            blokkok[-1] = [blokkok[-1][0] + b[0], blokkok[-1][1] + b[1], blokkok[-1][2] + b[2]]
    kal_pontok = [(b[2] / b[1], b[0] / b[1]) for b in blokkok if b[1] >= 15] or [(0.0, 1.0 / K), (1.0, 1.0 / K)]

    def kalibralt(pv):
        if pv <= kal_pontok[0][0]:
            return kal_pontok[0][1]
        for (x0, y0), (x1, y1) in zip(kal_pontok, kal_pontok[1:]):
            if pv <= x1:
                return y0 + (y1 - y0) * (pv - x0) / (x1 - x0 or 1.0)
        return kal_pontok[-1][1]

    # --- 5) estimating the grey buildings
    ut_becsles = ADAT / "ev_becsles.csv"
    szur_eredmeny = []
    PP = {i: eloszlas(komponensek(i, ep, szomsz, m, utca_index, zonak, ()), w_vegso) for i in szurke}
    zona_hatar_db = 0
    for i in szurke:                                   # zone boundary: the probability of the excluded eras is 0
        tilt = zona_tiltott(ep[i])
        if tilt:
            v = [0.0 if c in tilt else PP[i][c] for c in range(K)]
            s = sum(v)
            PP[i] = [x / s for x in v] if s > 0 else [1.0 / (K - len(tilt)) if c not in tilt else 0.0 for c in range(K)]
            zona_hatar_db += 1
    print(f"Zónahatár (építés ettől / eddig) alkalmazva {zona_hatar_db} szürke épületen")
    kozel_tart = kozelito_tartomanyok(ep)
    kozel_jel = {}
    for i in szurke:                                   # approximate (multi-era) source data: only the eras within the range remain
        if i in kozel_tart:
            ok, szoveg = kozel_tart[i]
            v = [PP[i][c] if c in ok else 0.0 for c in range(K)]
            s_ = sum(v)
            PP[i] = [x / s_ for x in v] if s_ > 0 else [1.0 / len(ok) if c in ok else 0.0 for c in range(K)]
            kozel_jel[i] = szoveg
    print(f"Közelítő (több korszakot átfogó) forrásadat szűkíti a becslést {len(kozel_jel)} szürke épületen")
    ksh_eredmeny, ksh_diag, ksh_szoveg = {}, [], ""
    if VAROS and KSH_ILLESZTES:
        ksh = ksh_beolvasasa()
        if ksh:
            if HELYI_KVOTA:
                print(f"Helyi kvóta ({HELYI_CELLA_M:.0f} m-es foltok); főút-távolság a külső gyűrű {foutak_tavolsaga(ep)} szürke épületénél")
            ksh_eredmeny, ksh_diag = ksh_kvota(ep, szurke, PP, ksh)
            ksh_szoveg = ksh_jelentes(ksh_diag)
            print(f"KSH-illesztés: {len(ksh_eredmeny)} szürke épület; "
                  f"legnagyobb kerületi eltérés: {max(d['elter_elotte'] for d in ksh_diag if d['ker']):.1f} -> "
                  f"{max(d['elter_utana'] for d in ksh_diag if d['ker']):.1f} százalékpont")
        else:
            print("Figyelem: nincs data/KSH/budapest_ksh_keruleti_eloszlas.csv (vagy hibás) - KSH-illesztés nélkül fut.")
    for i in szurke:
        p = PP[i]
        top = max(range(K), key=lambda q: p[q])
        ksh_jel = ""
        if i in ksh_eredmeny:
            top, p, lam_top, atr = ksh_eredmeny[i]
            ksh_jel = f"; KSH-kerületi illesztés (szorzó x{lam_top:.2f})" + (", a kvóta szerint átrendezve" if atr else "")
        szomsz_db = sum(1 for j, d, _ in szomsz[i] if d <= 60 and j in m.tanito)
        if k_magas is not None and p[top] >= k_magas:
            biz = "magas"
        elif k_kozepes is not None and p[top] >= k_kozepes:
            biz = "kozepes"
        else:
            biz = "alacsony"
        ent = -sum(v * math.log(v) for v in p if v > 0)
        ism_szomsz_60 = szomsz_db
        osszes_szomsz_60 = sum(1 for j, d, _ in szomsz[i] if d <= 60)
        indok = f"{ism_szomsz_60} ismert korú szomszéd 60 m-en belül" + ksh_jel
        if VAROS and "gyuru" in ep[i]:
            indok += f"; típus: {ep[i]['etipus']}, {GYURU_NEVEK[ep[i]['gyuru']]}"
        if VAROS and ep[i].get("pz") is not None:
            indok += f"; rajzolt zóna: {PZ_LISTA[ep[i]['pz']]['nev']} ({PZ_LISTA[ep[i]['pz']]['tol']}–{PZ_LISTA[ep[i]['pz']]['ig']})" + (" – zónahatár érvényes" if zona_tiltott(ep[i]) else "")
        if ep[i]["utca"] and zonak.get(ep[i]["utca"]):
            indok += f"; zóna: {zonak[ep[i]['utca']][0]}"
        if i in kozel_jel:
            indok += f"; forrásadat (közelítő): {kozel_jel[i]}"
        szur_eredmeny.append((i, p, top, biz, ent, osszes_szomsz_60 - ism_szomsz_60, indok))

    with open(ut_becsles, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["osm_tipus", "id", "becsult_korszak", "valoszinuseg", "bizonyossag"]
                   + [f"p_{k[2]}" for k in KORSZAKOK] + ["indoklas", "valoszinuseg_nyers"])
        for i, p, top, biz, ent, _, indok in szur_eredmeny:
            w.writerow([ep[i]["kulcs"][0], ep[i]["kulcs"][1], KORSZAKOK[top][2], f"{kalibralt(p[top]):.2f}", biz]
                       + [f"{v:.3f}" for v in p] + [indok, f"{p[top]:.2f}"])
        for i, szoveg in lagy.items():      # heritage inventory: an approximate but sourced era
            k = ep[i]["kor"]
            p = [0.94 if y == k else 0.06 / (K - 1) for y in range(K)]
            w.writerow([ep[i]["kulcs"][0], ep[i]["kulcs"][1], KORSZAKOK[k][2], f"{p[k]:.2f}", "magas"]
                       + [f"{v:.3f}" for v in p] + ["értékleltár: " + szoveg])

    with open(ADAT / "ev_becsles_munkalista.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["osm_tipus", "id", "nev", "becsult_korszak", "valoszinuseg", "bizonyossag",
                    "ismeretlen_szomszed_60m", "bizonytalansag", "terulet_m2", "miert"])
        sor_w = sorted(szur_eredmeny, key=lambda r: -(r[4] * (1 + r[5]) * math.sqrt(ep[r[0]]["terulet"])))
        for i, p, top, biz, ent, isz, indok in sor_w[:300]:
            w.writerow([ep[i]["kulcs"][0], ep[i]["kulcs"][1], ep[i]["nev"], KORSZAKOK[top][2],
                        f"{kalibralt(p[top]):.2f}", biz, isz, f"{ent:.2f}", int(ep[i]["terulet"]),
                        "bizonytalan és sok ismeretlen szomszéd veszi körül: egy kézi adat sokat javít"])

    def pct(x):
        return f"{100 * x:.0f}%"

    def sort(nev, d):
        if not d.get("n"):
            return f"| {nev} | 0 | – | – | – | – |"
        return f"| {nev} | {d['n']} | {pct(d['pontossag'])} | {pct(d['top2'])} | {pct(d['legfeljebb_1_korszak_tevedes'])} | {d['logloss']:.2f} |"

    fej = "| | db | találat | az első kettő között | legfeljebb 1 korszakot téved | log-veszteség (kisebb a jobb) |\n|---|---|---|---|---|---|"
    s = []
    s.append("# Építési korszak becslés: mérési jelentés\n")
    s.append(f"Címkézett (ismert évű) épület: **{len(cimkezett)}**; szürke, becsült: **{len(szurke)}**; épületrészt nem becslünk.\n")
    s.append("A mérés úgy megy, hogy minden ismert épületet egyenként elrejtünk, és megnézzük, eltalálná-e a modell.\n")
    s.append("## Fő eredmények\n\n" + fej)
    for nev, d in sor.items():
        s.append(sort(nev, d))
    s.append("\n## Mit ad az egyes bizonyíték? (a végső modellből kihagyva)\n\n" + fej)
    for nev, d in abl.items():
        s.append(sort(nev, d))
    s.append(f"\nVégső súlyok: {w_vegso}\n")
    s.append("\n## Védett és nem védett épületek külön\n\nAz ismert évű épületek jelentős része védett, a szürkék többsége viszont nem az, ezért a *nem védett* sor a reálisabb. "
             "A rajzolt zónák (pl. Wekerle-telep) a tudott évű házak ismeretében készültek, ezért a zónán belüli ismert épületeken a mérés túl jó; "
             "a szürke épületek többsége zónán kívül van, ott a *NEM védett, rajzolt zónán kívül* sor a mérvadó.\n\n" + fej)
    for nev, d in alcsoport.items():
        s.append(sort(nev, d))
    s.append("\n## Korszakonként: hányat talál el?\n\n| korszak | ismert db | találat |\n|---|---|---|")
    for y, (n, a) in korszakonkent.items():
        s.append(f"| {KORSZAKOK[y][2]} | {n} | {pct(a)} |")
    s.append("\nA 1945 utáni korszakoknál kevés az ismert példa, ezért ott a becslés megbízhatatlanabb.\n")
    s.append("## Kalibráció: amit a modell X%-osra mond, az valójában mennyi?\n\n| a modell biztonsága | db | tényleges találat |\n|---|---|---|")
    for sav in sorted(kal):
        n, t = kal[sav]
        s.append(f"| {int(sav * 100)}–{int(sav * 100) + 10}% | {n} | {pct(t / n)} |")
    def _kuszob(k, szazalek):
        return f"≥ {round(k, 2)} (mért találat ≥ {szazalek}%)" if k is not None else f"(egyik sáv sem éri el a(z) {szazalek}%-os mért találatot, ezért nincs ilyen sáv)"
    s.append(f"\nBizonyossági sávok: **magas** {_kuszob(k_magas, 85)}, **közepes** {_kuszob(k_kozepes, 70)}, különben **alacsony**.\n")
    sav_sor = []
    for nev, lo, hi in (("magas", k_magas, 2), ("közepes", k_kozepes, k_magas), ("alacsony", 0, k_kozepes if k_kozepes is not None else k_magas)):
        if lo is None or hi is None:
            continue
        a = [(ep[i]["kor"], eloszlas(kp_loo[i], w_vegso)) for i in nem_vedett]
        a = [(y, p) for y, p in a if lo <= max(p) < hi]
        if a:
            t = sum(1 for y, p in a if max(range(K), key=lambda q: p[q]) == y)
            sav_sor.append(f"- {nev}: {len(a)} nem védett ismert épületből {pct(t / len(a))} találat")
    s.append("A bizonyossági sávok tényleges találata csak a NEM védett épületeken:\n\n" + "\n".join(sav_sor) + "\n")
    kal_tabla = "\n".join(f"| {pct(x)} | {pct(kalibralt(x))} |" for x in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0))
    s.append("## Kalibrált valószínűség (ez jelenik meg a kártyán)\n\nA nyers valószínűség túlzottan magabiztos. A kártyán és az ev_becsles.csv `valoszinuseg` oszlopában "
             f"a *mért* találati arány áll: a 300 m-es blokk kizárásával, {len(nem_vedett_kal)} NEM védett ismert épületen, izotonikus illesztéssel. "
             "A nyers érték a `valoszinuseg_nyers` oszlopban marad. A bizonyossági sávok (magas/közepes/alacsony) nem változnak.\n\n"
             "| nyers valószínűség | kalibrált (mért találat) |\n|---|---|\n" + kal_tabla + "\n")
    s.append("## Zavaró mátrix (sor: igazi, oszlop: becsült)\n\n| | " + " | ".join(k[2] for k in KORSZAKOK) + " |\n|---|" + "---|" * K)
    for y in range(K):
        s.append(f"| {KORSZAKOK[y][2]} | " + " | ".join(str(v) for v in zav[y]) + " |")
    s.append("\n## A szürke épületek becslése\n")
    szamlalo = Counter((KORSZAKOK[t][2], b) for _, _, t, b, _, _, _ in szur_eredmeny)
    s.append("| korszak | magas | közepes | alacsony |\n|---|---|---|---|")
    for _, _, nev in KORSZAKOK:
        s.append(f"| {nev} | {szamlalo[(nev, 'magas')]} | {szamlalo[(nev, 'kozepes')]} | {szamlalo[(nev, 'alacsony')]} |")
    if VAROS:
        gdb = sum(1 for e in ep if e.get("ghsl_l"))
        gsz = sum(1 for e in ep if e.get("ghsl_l") and e["kor"] is None)
        s.append(f"Minimum {GH['min_m2']:.0f} m2/cella (2020), súly: {GH['suly']}. Információt ad {gdb} épületnél (szürke: {gsz}). "
                 + "; ".join(f"{k}: {v}" for k, v in GHSL_STAT.items()) + ".\n")
    s.append(f"\nZóna-támpont {ossz_szurke_zona} szürke épületnél érvényes (utca-egyezés alapján).\n")
    if VAROS and "gyuru" in ep[0]:
        s.append("\n## Gyűrűnként (városi mód)\n\n"
                 "FIGYELEM: az ismert évű épületek a külső gyűrűkben többnyire *zárványok* (védett, régi), ezért az "
                 "alábbi egyenként-elrejtős pontosság a külső gyűrűkben NEM a valódi, tipikus épületekre vonatkozik. "
                 "A szürke épületeknél a becsült eloszlás a mérvadó, ezt vesd össze a helyismereteddel.\n\n" + fej)
        for gy in range(len(GYURU_NEVEK)):
            idx = [i for i in cimkezett if ep[i]["gyuru"] == gy]
            s.append(sort(GYURU_NEVEK[gy] + " (ismert)", metrikak([(ep[i]["kor"], eloszlas(kp_loo[i], w_vegso)) for i in idx])))
        s.append("\n### A szürke épületek becsült korszaka gyűrűnként és típusonként (db)\n")
        s.append("| gyűrű | típus | " + " | ".join(k[2] for k in KORSZAKOK) + " |\n|---|---|" + "---|" * K)
        osz = defaultdict(lambda: [0] * K)
        for i, p, top, biz, ent, _, indok in szur_eredmeny:
            osz[(ep[i]["gyuru"], ep[i]["etipus"])][top] += 1
        for (gy, tip), v in sorted(osz.items()):
            s.append(f"| {GYURU_NEVEK[gy]} | {tip} | " + " | ".join(str(x) for x in v) + " |")
    if VAROS and PZ_LISTA:
        def tomeg_evek(p, tol, ig):
            t = 0.0
            for y in range(K):
                lo, hi = KORSZAKOK[y][0], min(KORSZAKOK[y][1], 2026)
                t += p[y] * max(0, min(ig, hi) - max(tol, lo) + 1) / (hi - lo + 1)
            return t
        szur_zona = defaultdict(list)
        for i, p, top, biz, ent, _, indok in szur_eredmeny:
            for zi in ep[i].get("pz_tag", []):
                szur_zona[zi].append((i, p, top))
        ism_zona = defaultdict(list)
        for i in cimkezett:
            for zi in ep[i].get("pz_tag", []):
                ism_zona[zi].append(i)
        for cim, mero in (("Rajzolt zónák (a becslő használja)", False), ("Mérőpróbák (a becslő NEM használja, csak méri)", True)):
            zl = [zi for zi, z in enumerate(PZ_LISTA) if z["mero"] == mero]
            if not zl:
                continue
            s.append(f"\n## {cim}\n")
            s.append("| zóna | évek | ismert épület benne | ebből a megadott években (a többi: zárvány) | szürke épület benne | a becslés tömege a megadott években | legvalószínűbb korszak a megadott években |\n|---|---|---|---|---|---|---|")
            ossz_t = ossz_n = 0
            for zi in zl:
                z = PZ_LISTA[zi]
                ism = ism_zona.get(zi, [])
                bent = sum(1 for i in ism if (z["tol"] <= ep[i]["ev"] <= z["ig"] if ep[i]["ev"] is not None
                                              else KORSZAKOK[ep[i]["kor"]][0] <= z["ig"] and KORSZAKOK[ep[i]["kor"]][1] >= z["tol"])) if ism else 0
                sz = szur_zona.get(zi, [])
                tomeg = sum(tomeg_evek(p, z["tol"], z["ig"]) for _, p, _ in sz)
                jo = sum(1 for _, _, top in sz if KORSZAKOK[top][0] <= z["ig"] and KORSZAKOK[top][1] >= z["tol"])
                ossz_t += tomeg
                ossz_n += len(sz)
                s.append(f"| {z['nev']} | {z['tol']}–{z['ig']} | {len(ism)} | {bent} | {len(sz)} | "
                         f"{pct(tomeg / len(sz)) if sz else '–'} | {pct(jo / len(sz)) if sz else '–'} |")
            if ossz_n:
                s.append(f"\nÖsszesen {ossz_n} szürke épület: átlagos becslési tömeg a megadott években **{pct(ossz_t / ossz_n)}**.\n")
    if ksh_szoveg:
        s.append(ksh_szoveg)
    s.append("## Amit nem tud a modell\n\n"
             "- A tanítóadat torz: sok az 1867–1918-as és a védett épület, kevés az 1945 utáni.\n"
             "- A zónák csak az utcát nézik, a háborús pótlásokat és későbbi beépítéseket nem.\n"
             "- A kortárs és modernista épületek listái (később) fogják javítani a 1945 utáni korszakokat.\n"
             "- A becslés soha nem kerül az `ev` mezőbe, és a térképen külön, halványabb rétegként látszik.\n")
    (ADAT / "ev_becsles_jelentes.md").write_text("\n".join(s), encoding="utf-8")
    print("\n".join(s))


if __name__ == "__main__":
    main()
