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

from common import belso_pont, kulcs, pont_gyuruben, pont_poligonban, tenyek_olvasasa, teruletu_kozeppont

OSM = "data/belvaros_epuletek.geojson"
TENYEK_MAPPA = Path("data/tenyek")
KEZI = "forras/kezi_javitasok.csv"
KEZI_EPULETEK = "forras/kezi_epuletek.geojson"          # manually added items that are not buildings in OSM (e.g. memorials): GeoJSON, with the usual fields
CSOPORTOK = "forras/epulet_csoportok.csv"       # a building made of several OSM elements (e.g. bath, hospital): group;nev;osm_tipus;id;fo
OENY_KIZART = "forras/oeny_kizart.csv"   # osm_tipus;id;megjegyzes - drops every E-Örökség (oeny, oeny_koord) fact for the listed OSM elements (data sheet, register number, protection, year, designer)
KIZART = "forras/kizart_epuletek.csv"   # osm_tipus;id;megjegyzes - leaves the listed OSM elements (e.g. courtyard, not a building) off the map
KEZI_CIMEK = "forras/kezi_cimek.csv"       # manual override of the address shown on the card (osm_tipus;id;cim;megjegyzes)
FELOSZTAS = "forras/kezi_felosztas.csv"   # splitting one OSM outline in two along a straight line (e.g. two houses drawn as one polygon)
DUPLIKATUMOK = "forras/duplikatumok.csv"   # duplicate_finder.py + manual decision: cleaning up buildings drawn on top of each other without losing data
ALIAS = {}                                  # key of the removed (duplicate) element -> key of the kept element
PRIORITAS = "forras/prioritas.json"
RESZEK = "data/belvaros_reszek.geojson"           # building:part elements (geojson_keszites.py)
KIMENET = "data/belvaros_epuletek_vegleges.geojson"
UTKOZESEK = "data/utkozesek.csv"
CIMEK = "data/osm_cimek.csv"                      # output of download_addresses.py (OSM address points)
BECSLES = "data/ev_becsles.csv"                   # output of year_estimate.py (an estimate only, not data)
VAROS = len(sys.argv) > 1 and sys.argv[1] == "varos"
if VAROS:
    OSM = "data/varos/epuletek.geojson"
    RESZEK = "data/varos/reszek.geojson"
    KIMENET = "data/varos/epuletek_vegleges.geojson"
    UTKOZESEK = "data/varos/utkozesek.csv"
    CIMEK = "data/varos/osm_cimek.csv"
    BECSLES = "data/varos/ev_becsles.csv"
BECSLES_KORSZAKOK = ["1867 előtt", "1867–1918", "1919–1944", "1945–1956", "1957–1989", "1990–2010", "2011-től"]

DONTO_MEZOK = ["ev", "szintek", "tervezo", "magassag"]
TOROL = object()          # the marker of a manual '-' in the numeric fields
SZAMOS = {"ev", "szintek", "magassag", "lechner_ev_kezdet", "lechner_ev_veg", "szintek_kep",
          "eubucco_magassag_min", "eubucco_magassag_max", "eubucco_szintek"}


def szam(x):
    try:
        v = float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return int(v) if v == int(v) else v


def tervezo_nevek(x):
    """Normalises names: 'Feszl Frigyes (1821–1884)' and 'Feszl Frigyes' are the same; several names are separated by ',' ';' ' és '."""
    x = re.sub(r"\u00ad\s*|\u200b", "", re.sub(r"\([^)]*\)", "", str(x)))
    reszek = re.split(r",|;|\bés\b", x)
    ki = set()
    for r in reszek:
        r = " ".join(r.split()).lower().replace("ifj. ", "").replace("id. ", "")
        if r:
            ki.add(r)
    return ki


TERVEZO_NEM_NEV = re.compile(r"[-–—]+|tervező\s+nem\s+ismert", re.I)


def tervezo_tisztit(x):
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
    if TERVEZO_NEM_NEV.search(x):                    # "Tervező nem ismert" ("designer unknown") and a lone "-" are not names: the item is deleted (the other names stay)
        reszek = re.split(r"(\s*[;,]\s*|\s+és\s+)", x)
        ki = ""
        for i in range(0, len(reszek), 2):
            if TERVEZO_NEM_NEV.fullmatch(reszek[i].strip()):
                continue
            ki += (reszek[i - 1] if ki and i else "") + reszek[i]
        x = ki
    return x.strip(" ,;")


def tervezo_tisztitas(feats):
    """The designer fields (of the building and the one inherited from the zone) without parentheses; if nothing remains, the field is removed."""
    db = 0
    for ft in feats:
        pr = ft["properties"]
        for m in ("tervezo", "zona_tervezo"):
            if pr.get(m):
                uj = tervezo_tisztit(pr[m])
                if uj != pr[m]:
                    db += 1
                if uj:
                    pr[m] = uj
                else:
                    pr.pop(m, None)
                    if m == "tervezo":
                        pr.pop("tervezo_forras", None)
    return db


def tervezo_egyezik(a, b):
    na, nb = tervezo_nevek(a), tervezo_nevek(b)
    return bool(na and nb and (na <= nb or nb <= na))


# The parts may inherit these properties from the building if they have no data of their own
NEM_OROKOLT = {"id", "osm_tipus", "resz", "szulo_id", "szulo_tipus"}
EV_CSOPORT = ("ev", "ev_forras")
SZINT_CSOPORT = ("szintek", "szintek_forras", "szintek_osm", "szint_eltero")
MAGASSAG_CSOPORT = ("magassag", "magassag_forras", "magassag_szintbol")
TOVABB_FEDETT = 0.5          # for a building covered by parts to a lesser degree than this, the parts are ignored


KIS_EPULET_M2 = 50.0          # a data-less building with a smaller footprint than this is a small outbuilding
KIS_EPULET_MAGASSAG = 3.5     # m
KIOSZK_M2 = 15.0              # a building with a smaller footprint than this (kiosk, transformer) always gets the low height
KIS_EPULET_MAX_BECSLT = 6.0   # m: the estimated EUBUCCO height of a small building is at most this


def gyuru_terulet(gyuruk):
    """Area in m²: the outer ring minus the holes (courtyards)."""
    return max(teruletu_kozeppont(gyuruk[0])[0] - sum(teruletu_kozeppont(h)[0] for h in gyuruk[1:]), 1e-9)


def orokol(rp, sp):
    """The part (rp) receives the building's (sp) properties if it lacks them itself."""
    rp["szulo_id"] = sp["id"]
    rp["szulo_tipus"] = sp["osm_tipus"]
    if rp.get("tipus") in (None, "yes"):
        rp["tipus"] = sp.get("tipus")
    sajat_ev = rp.get("ev") and sp.get("ev_forras") != "kezi"
    sajat_szint = rp.get("szintek") and sp.get("szintek_forras") != "kezi"
    sajat_mag = rp.get("magassag_forras") in ("height", "szintszam", "szintterkep", "kezi") \
        and sp.get("magassag_forras") != "kezi"
    for k, v in sp.items():
        if k in NEM_OROKOLT or k == "tipus":
            continue
        if k in EV_CSOPORT and sajat_ev:
            continue
        if k in SZINT_CSOPORT and sajat_szint:
            continue
        if k in MAGASSAG_CSOPORT and sajat_mag:
            continue
        if k in EV_CSOPORT + SZINT_CSOPORT + MAGASSAG_CSOPORT or rp.get(k) in (None, ""):
            rp[k] = v


def kozos_csucsok(gy_a, gy_b):
    return len({tuple(p) for p in gy_a} & {tuple(p) for p in gy_b})


def reszek_kezelese(feats):
    """Assigns the building parts (building:part) to the building containing them.

    1. If a part's interior point lies within the building's outer outline (courtyards
       also belong to the building), the part belongs to the building.
    2. If the parts cover at least half of the building's outline, the parts are drawn
       instead of the outline; if less, the parts are dropped and the outline stays.
    3. Parts outside the building but connected to it (shared vertices, or one of the
       part's vertices lies inside the building) also inherit the building's data, but appear on their own.
    Name, protection etc. are inherited; the part keeps its own year, number of storeys
    and height (given in OSM or corrected by hand)."""
    reszek = [ft for ft in feats if ft["properties"].get("resz")]
    szulok = [ft for ft in feats if not ft["properties"].get("resz")]
    stat = Counter()
    if not reszek:
        return feats, stat
    adatok = []
    for s in szulok:
        gy = s["geometry"]["coordinates"]
        xs = [p[0] for p in gy[0]]
        ys = [p[1] for p in gy[0]]
        adatok.append((min(xs), max(xs), min(ys), max(ys), gyuru_terulet(gy), s))
    RACS = 0.002                                  # degrees: fast lookup among the surrounding buildings
    racs = defaultdict(list)
    for a in adatok:
        for ci in range(int(a[0] / RACS), int(a[1] / RACS) + 1):
            for cj in range(int(a[2] / RACS), int(a[3] / RACS) + 1):
                racs[(ci, cj)].append(a)

    def kozeli(x0, x1, y0, y1):
        lat = {}
        for ci in range(int(x0 / RACS), int(x1 / RACS) + 1):
            for cj in range(int(y0 / RACS), int(y1 / RACS) + 1):
                for a in racs.get((ci, cj), ()):
                    lat[id(a)] = a
        return list(lat.values())

    csoportok = defaultdict(list)                 # id(parent) -> [part]
    kapcsolodo = []                               # (part, parent feature)
    for r in reszek:
        gy = r["geometry"]["coordinates"]
        x, y = belso_pont([gy])
        jeloltek = [a for a in kozeli(x, x, y, y) if a[0] <= x <= a[1] and a[2] <= y <= a[3]
                    and pont_gyuruben(x, y, a[5]["geometry"]["coordinates"][0])]
        if jeloltek:
            szulo = min(jeloltek, key=lambda a: a[4])
            csoportok[id(szulo[5])].append((r, szulo))
            continue
        # not in any outline: is it connected to one of them?
        rx = [p[0] for p in gy[0]]
        ry = [p[1] for p in gy[0]]
        legjobb, pont = None, 0
        for a in kozeli(min(rx), max(rx), min(ry), max(ry)):
            if a[1] < min(rx) or a[0] > max(rx) or a[3] < min(ry) or a[2] > max(ry):
                continue
            kulso = a[5]["geometry"]["coordinates"][0]
            kozos = kozos_csucsok(gy[0], kulso)
            bent = sum(1 for px, py in gy[0][:-1] if pont_gyuruben(px, py, kulso))
            if kozos >= 2 or bent >= 1:
                p_ = kozos * 2 + bent
                if p_ > pont:
                    legjobb, pont = a, p_
        if legjobb:
            kapcsolodo.append((r, legjobb[5]))
        else:
            stat["önálló rész (nincs épületkontúr)"] += 1
    kihagy = set()
    for lista in csoportok.values():
        szulo = lista[0][1][5]
        szulo_ter = lista[0][1][4]
        fedett = sum(gyuru_terulet(r["geometry"]["coordinates"]) for r, _ in lista) / szulo_ter
        if fedett < TOVABB_FEDETT:
            for r, _ in lista:
                kihagy.add(id(r))
            stat["rész kihagyva (kevéssé fedi le az épületet)"] += len(lista)
            continue
        kihagy.add(id(szulo))
        stat["épület helyett részei"] += 1
        stat["rész az épületen belül"] += len(lista)
        for r, _ in lista:
            orokol(r["properties"], szulo["properties"])
    for r, szulo in kapcsolodo:
        orokol(r["properties"], szulo["properties"])
        stat["épületen kívüli, de hozzá kapcsolódó rész (örökli az adatait)"] += 1
    return [ft for ft in feats if id(ft) not in kihagy], stat


def becsles_hozzafuzese(feats):
    """From ev_becsles.csv, adds separate 'ev_becsles_*' fields to the GREY (year-less) buildings.
    The 'ev' field is not touched: an estimate never counts as data."""
    if not Path(BECSLES).exists():
        print(f"Becslés: nincs {BECSLES} (futtasd: py year_estimate.py)")
        return 0
    becsles = {}
    with open(BECSLES, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            becsles[(r["osm_tipus"], int(r["id"]))] = r
    db = 0
    for x in feats:
        pr = x["properties"]
        if pr.get("ev"):
            continue
        if pr.get("resz"):
            # a building part (building:part) inherits the estimate of its parent building if the parent has one
            # previously the part was left without an estimate, and the tiling gave it the era of the nearest building (32 parts)
            if not pr.get("szulo_id"):
                continue
            r = becsles.get((pr.get("szulo_tipus") or "way", int(pr["szulo_id"])))
        else:
            r = becsles.get(kulcs(pr))
        if not r or r["becsult_korszak"] not in BECSLES_KORSZAKOK:
            continue
        pr["ev_becsles_korszak"] = BECSLES_KORSZAKOK.index(r["becsult_korszak"])
        pr["ev_becsles_valoszinuseg"] = float(r["valoszinuseg"])
        pr["ev_becsles_bizonyossag"] = r["bizonyossag"]
        pr["ev_becsles_indoklas"] = r["indoklas"]
        db += 1
    return db


def kozelito_hozzafuzese(feats):
    """From the textual era data of data/varos/*_kozelito.csv ('1920-1930-as évek', i.e. "the 1920s-30s"), 'ev_kozelito_*' fields for year-less buildings.
    This is data too (roughly when it was built, according to the source), but not an exact year: the 'ev' field is not touched. With several sources the narrowest range is output."""
    if not VAROS:
        return 0
    jelolt = defaultdict(list)
    for ut in sorted(Path("data/varos").glob("*_kozelito.csv")):
        with open(ut, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                try:
                    jelolt[(r["osm_tipus"], int(r["id"]))].append((int(r["ev_ig"]) - int(r["ev_tol"]), int(r["ev_tol"]), int(r["ev_ig"]), (r.get("szoveg") or "").strip(), (r.get("forras") or "").strip()))
                except (KeyError, ValueError):
                    continue
    db = 0
    for x in feats:
        pr = x["properties"]
        if pr.get("ev") or pr.get("resz"):
            continue
        l = jelolt.get(kulcs(pr))
        if not l:
            continue
        _, tol, ig, szoveg, forras = min(l)
        pr["ev_kozelito_tol"], pr["ev_kozelito_ig"] = tol, ig
        if szoveg:
            pr["ev_kozelito_szoveg"] = szoveg
        if forras:
            pr["ev_kozelito_forras"] = forras
        db += 1
    return db


def cimek_hozzafuzese(feats):
    """The 'cim' (first address, e.g. 'Alkotmány utca 2') and 'cim_tobb' (how many further addresses) fields for the card."""
    if not Path(CIMEK).exists():
        return 0
    cimek = defaultdict(list)
    with open(CIMEK, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r["utca"] and r["hazszam"]:
                cimek[(r["osm_tipus"], int(r["id"]))].append(f'{r["utca"]} {r["hazszam"]}')
    db = 0
    for x in feats:
        pr = x["properties"]
        lista = cimek.get(kulcs(pr))
        if not lista and pr.get("szulo_id") and pr.get("szulo_tipus"):
            lista = cimek.get((pr["szulo_tipus"], int(pr["szulo_id"])))   # building part: the parent's address
        if lista:
            lista = list(dict.fromkeys(lista))
            pr["cim"] = lista[0]
            if len(lista) > 1:
                pr["cim_tobb"] = len(lista) - 1
            db += 1
    return db


def zona_wikipedia_hozzafuzese(feats):
    """The Wikipedia article given in the zone editor (forras/zonak_poligon.geojson, 'wikipedia' field) is the default article of the
    buildings falling in the zone. If the building has its own article (from any source, or by hand), that stays; with several zones
    the smallest zone that has an article wins. The 'wikipedia_zona' field on the building shows which zone it came from."""
    ut = Path("forras/zonak_poligon.geojson")
    if not ut.exists():
        return 0
    zonak = []
    for f in json.load(open(ut, encoding="utf-8")).get("features", []):
        p, g = f.get("properties", {}), f.get("geometry", {})
        if not p.get("wikipedia") or g.get("type") != "Polygon":
            continue
        gy = g["coordinates"][0]
        xs, ys = [q[0] for q in gy], [q[1] for q in gy]
        terulet = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(gy, gy[1:]))) / 2
        zonak.append((terulet, min(xs), min(ys), max(xs), max(ys), g["coordinates"], p["wikipedia"], p.get("nev") or p["id"]))
    if not zonak:
        return 0
    zonak.sort(key=lambda z: z[0])               # from small to large: the first match is the smallest
    db = 0
    for ft in feats:
        pr = ft["properties"]
        if pr.get("wikipedia"):          # (ruins also get the zone's article if they have none of their own)
            continue
        g = ft["geometry"]
        if g["type"] == "Polygon":
            gyuru = g["coordinates"][0]
        elif g["type"] == "MultiPolygon":
            gyuru = g["coordinates"][0][0]
        else:
            continue
        _, x, y = teruletu_kozeppont(gyuru)
        for _, x0, y0, x1, y1, koord, cikk, nev in zonak:
            if x0 <= x <= x1 and y0 <= y <= y1 and pont_poligonban(x, y, koord):
                pr["wikipedia"], pr["wikipedia_zona"] = cikk, nev
                db += 1
                break
    return db


ZONA_NEV_TIPUSOK = {"lakotelep"}   # the name of these drawn zone types goes into the building's "zona_nev" field (the card's title, if the building has no name of its own)


def zona_nev_hozzarendeles(feats):
    """The names of the drawn housing-estate zones (forras/zonak_poligon.geojson, tipus: lakotelep) for the buildings falling in the zone: 'zona_nev'.
    With several zones the smallest wins. The building's own name (nev, lechner_nev, nev_kozepulet) stays regardless."""
    ut = Path("forras/zonak_poligon.geojson")
    if not ut.exists():
        return 0
    zonak = []
    for f in json.load(open(ut, encoding="utf-8")).get("features", []):
        p, g = f.get("properties", {}), f.get("geometry", {})
        nev = (p.get("nev") or "").strip()
        jel = p.get("zona_nev_hozzaad")          # the zone editor's tick box; if not set, the zone type decides
        if jel is None:
            jel = p.get("tipus") in ZONA_NEV_TIPUSOK
        if not jel or not nev:
            continue
        polik = [g["coordinates"]] if g.get("type") == "Polygon" else g["coordinates"] if g.get("type") == "MultiPolygon" else []
        for koord in polik:
            gy = koord[0]
            xs, ys = [q[0] for q in gy], [q[1] for q in gy]
            terulet = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(gy, gy[1:]))) / 2
            zonak.append((terulet, min(xs), min(ys), max(xs), max(ys), koord, nev))
    if not zonak:
        return 0
    zonak.sort(key=lambda z: z[0])               # from small to large
    db = 0
    for ft in feats:
        pr = ft["properties"]
        pr.pop("zona_nev", None)
        if pr.get("rom"):
            continue
        g = ft["geometry"]
        if g["type"] == "Polygon":
            gyuru = g["coordinates"][0]
        elif g["type"] == "MultiPolygon":
            gyuru = g["coordinates"][0][0]
        else:
            continue
        _, x, y = teruletu_kozeppont(gyuru)
        for _, x0, y0, x1, y1, koord, nev in zonak:
            if x0 <= x <= x1 and y0 <= y <= y1 and pont_poligonban(x, y, koord):
                pr["zona_nev"] = nev
                db += 1
                break
    return db


def zona_tervezo_hozzarendeles(feats):
    """The designer(s) given in the zone editor (forras/zonak_poligon.geojson, 'tervezo' field, e.g. of a housing estate) for the buildings
    falling in the zone: 'zona_tervezo' (the text), 'zona_azon' (the zone's id) and 'zona_tervezo_nev' (the zone's name). The building's own 'tervezo'
    field is not overwritten. With several zones the smallest wins. When an architect is highlighted, the 3D view also watches this, and counts the estate as 1 project."""
    ut = Path("forras/zonak_poligon.geojson")
    if not ut.exists():
        return 0
    zonak = []
    for f in json.load(open(ut, encoding="utf-8")).get("features", []):
        p, g = f.get("properties", {}), f.get("geometry", {})
        terv = (p.get("tervezo") or "").strip()
        if not terv:
            continue
        polik = [g["coordinates"]] if g.get("type") == "Polygon" else g["coordinates"] if g.get("type") == "MultiPolygon" else []
        for koord in polik:
            gy = koord[0]
            xs, ys = [q[0] for q in gy], [q[1] for q in gy]
            terulet = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(gy, gy[1:]))) / 2
            zonak.append((terulet, min(xs), min(ys), max(xs), max(ys), koord, terv, p.get("id") or "", (p.get("nev") or "").strip()))
    for ft in feats:                                  # the result of the previous run must not remain
        for k in ("zona_tervezo", "zona_azon", "zona_tervezo_nev"):
            ft["properties"].pop(k, None)
    if not zonak:
        return 0
    zonak.sort(key=lambda z: z[0])
    db = 0
    for ft in feats:
        pr = ft["properties"]
        if pr.get("rom"):
            continue
        g = ft["geometry"]
        if g["type"] == "Polygon":
            gyuru = g["coordinates"][0]
        elif g["type"] == "MultiPolygon":
            gyuru = g["coordinates"][0][0]
        else:
            continue
        _, x, y = teruletu_kozeppont(gyuru)
        for _, x0, y0, x1, y1, koord, terv, azon, nev in zonak:
            if x0 <= x <= x1 and y0 <= y <= y1 and pont_poligonban(x, y, koord):
                pr["zona_tervezo"], pr["zona_azon"], pr["zona_tervezo_nev"] = terv, azon, nev or azon
                db += 1
                break
    return db


GYENGE_EV_FORRASOK = {"eubucco", "wikidata_kozeli"}   # the least reliable year sources
ZONA_FELULIRJA_GYENGE_EVET = True                      # a weak-source year outside the drawn zone's boundary is overridden by the zone


def zona_gyenge_ev_felulirasa(feats):
    """If a building's year comes from a weak source (EUBUCCO, a nearby Wikidata match) and falls outside the hard boundary of the drawn zone
    (built from this year on; with the 'ig_hatar' switch also up to this year), the year is dropped: the building turns grey and the estimate
    decides within the zone boundary. The year of strong sources (manual, OSM, monument, OENY, heritage inventory, Budapest100 etc.) is left alone."""
    ut = Path("forras/zonak_poligon.geojson")
    if not ZONA_FELULIRJA_GYENGE_EVET or not ut.exists():
        return 0
    zonak = []
    for f in json.load(open(ut, encoding="utf-8")).get("features", []):
        p, g = f.get("properties", {}), f.get("geometry", {})
        if p.get("tipus") == "muemlek" or p.get("mero") or g.get("type") != "Polygon":
            continue
        try:
            tol, ig = int(p["ev_tol"]), int(p["ev_ig"])
        except (KeyError, TypeError, ValueError):
            continue
        gy = g["coordinates"][0]
        xs, ys = [q[0] for q in gy], [q[1] for q in gy]
        terulet = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(gy, gy[1:]))) / 2
        zonak.append((terulet, min(xs), min(ys), max(xs), max(ys), g["coordinates"], tol, ig, bool(p.get("ig_hatar"))))
    zonak.sort(key=lambda z: z[0])
    db = 0
    for ft in feats:
        pr = ft["properties"]
        if not pr.get("ev") or pr.get("ev_forras") not in GYENGE_EV_FORRASOK or pr.get("rom"):
            continue
        g = ft["geometry"]
        gyuru = g["coordinates"][0] if g["type"] == "Polygon" else g["coordinates"][0][0] if g["type"] == "MultiPolygon" else None
        if gyuru is None:
            continue
        _, x, y = teruletu_kozeppont(gyuru)
        for _, x0, y0, x1, y1, koord, tol, ig, ig_h in zonak:
            if x0 <= x <= x1 and y0 <= y <= y1 and pont_poligonban(x, y, koord):
                try:
                    ev = int(pr["ev"])
                except (TypeError, ValueError):
                    break
                if ev < tol or (ig_h and ev > ig):
                    pr["ev_eldobott"] = ev
                    pr["ev_eldobott_forras"] = pr.get("ev_forras")
                    pr.pop("ev", None)
                    pr.pop("ev_forras", None)
                    db += 1
                break
    return db


def _zona_b100_linkek(feats):
    """The Budapest100 link given in the zone editor ('budapest100' field) is the default link of the buildings in the zone, if the
    building has no 'budapest100_url' of its own. With several zones the smallest zone that has a link wins."""
    ut = Path("forras/zonak_poligon.geojson")
    if not ut.exists():
        return 0
    zonak = []
    for f in json.load(open(ut, encoding="utf-8")).get("features", []):
        p, g = f.get("properties", {}), f.get("geometry", {})
        b100 = p.get("budapest100")
        if not b100:                       # for zones taken over from the zone list the URL often appears only in the remark
            m_ = re.search(r"https?://(?:www\.)?budapest100\.hu/[^\s;,)\"]+", str(p.get("megjegyzes") or ""))
            b100 = m_.group(0) if m_ else None
        if not b100 or g.get("type") != "Polygon":
            continue
        gy = g["coordinates"][0]
        xs, ys = [q[0] for q in gy], [q[1] for q in gy]
        terulet = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(gy, gy[1:]))) / 2
        zonak.append((terulet, min(xs), min(ys), max(xs), max(ys), g["coordinates"], b100))
    if not zonak:
        return 0
    zonak.sort(key=lambda z: z[0])
    db = 0
    for ft in feats:
        pr = ft["properties"]
        if pr.get("budapest100_url") or pr.get("rom"):
            continue
        g = ft["geometry"]
        gyuru = g["coordinates"][0] if g["type"] == "Polygon" else g["coordinates"][0][0] if g["type"] == "MultiPolygon" else None
        if gyuru is None:
            continue
        _, x, y = teruletu_kozeppont(gyuru)
        for _, x0, y0, x1, y1, koord, url in zonak:
            if x0 <= x <= x1 and y0 <= y <= y1 and pont_poligonban(x, y, koord):
                pr["budapest100_url"] = url
                db += 1
                break
    return db


def zona_budapest100_hozzafuzese(feats):
    """The link inherited from the zone + the Budapest100 page's image and photographer for every building that has a budapest100_url
    (from the zone, from manual editing or from the building pairing) but no budapest100_kep of its own yet (data/bp100/kepek.json)."""
    db = _zona_b100_linkek(feats)
    try:
        kepek = json.load(open("data/bp100/kepek.json", encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return db
    kep_db = 0
    for ft in feats:
        pr = ft["properties"]
        k = kepek.get((pr.get("budapest100_url") or "").strip())
        if k is None:
            continue
        # the image and the photographer always belong to the page whose link is on the card
        # (if several Budapest100 pages belong to the building, the link, the image and the photographer must not get mixed up)
        if k.get("kep"):
            if pr.get("budapest100_kep") != k["kep"] or pr.get("budapest100_foto", "") != k.get("foto", ""):
                kep_db += 1
            pr["budapest100_kep"] = k["kep"]
            if k.get("foto"):
                pr["budapest100_foto"] = k["foto"]
            else:
                pr.pop("budapest100_foto", None)
        else:
            pr.pop("budapest100_kep", None)
            pr.pop("budapest100_foto", None)
    print(f"  Budapest100-kép a kártyán álló link oldalához igazítva: {kep_db}")
    return db


# A building group (e.g. the many OSM pieces of the Rudas bath) differs in geometry piece by piece, but is one building: one name, one card.
CSOPORT_RESZENKENT = {"wikipedia_zona", "id", "osm_tipus", "tipus", "resz", "szulo_id", "szulo_tipus", "kerulet", "lat", "lon", "csoport", "csoport_nev",
                      "csoport_reszek", "csoport_osm", "cim_tobb", "sv_lat", "sv_lon", "ev", "ev_forras", "nev", "wikidata_nev", "kep"}
CSOPORT_EGYESITETT = {"wikipedia", "oeny_azonosito"}                 # the articles/data sheets of the group's pieces combined (at most 3)
CSOPORT_SZOVEG_EGYESITETT = {"tervezo", "about"}                      # the different texts are placed side by side


# Automatic groups: parts (building:part) drawn instead of a building's outline are treated as one building,
# if no link would be lost by it (see auto_csoportok).
AUTO_CSOPORT = True
LINK_EGYEDI = ("budapest100_url", "budapest100_kep", "legenda_url", "legenda_kep", "epforum_url", "commons_kep")     # at most one different value per piece
LINK_EGYESITETT = ("oeny_azonosito", "wikipedia")                                      # the merge carries over at most 3 different values


def auto_csoportok(feats, kulcsok_kezi, index):
    """From the parts that replace a building's outline (same szulo_id, the parent is not in the output) it forms a group, but only if
    merging the group would lose nothing: the OENY id, Wikipedia (at most 3 together), the Budapest100 and
    Legenda link (and image) have at most one different value each, and no two different years occur (the year of Építészfórum/OENY/...
    would be taken over uniformly by the group). Returns: (rows for the groups table, statistics)."""
    stat = Counter()
    csopi = defaultdict(list)
    for ft in feats:
        p = ft["properties"]
        if p.get("resz") and p.get("szulo_id") and p.get("szulo_tipus") and kulcs(p) not in kulcsok_kezi:
            if (p["szulo_tipus"], int(p["szulo_id"])) in index:
                continue                      # the parent remained: this part is only connected to it, it stays independent
            csopi[(p["szulo_tipus"], int(p["szulo_id"]))].append(ft)
    sorok = {}
    for (st, sid), tagok in csopi.items():
        if len(tagok) < 2:
            continue
        pr = [ft["properties"] for ft in tagok]
        gond = None
        for k in LINK_EGYEDI:
            if len({p[k] for p in pr if p.get(k)}) > 1:
                gond = k
        for k in LINK_EGYESITETT:
            ossz = {x for p in pr for x in str(p.get(k) or "").split("|") if x}
            if len(ossz) > 3:
                gond = k
        if len({p["ev"] for p in pr if p.get("ev")}) > 1:
            gond = "ev"
        if gond:
            stat["kimaradt (különböző " + gond + " menne veszendőbe)"] += 1
            continue
        fo = max(tagok, key=lambda ft: (bool(ft["properties"].get("ev")), ft["properties"].get("magassag") or 0))
        azon = f"auto_{st}_{sid}"
        sorok[azon] = [{"csoport": azon, "nev": "", "osm_tipus": ft["properties"]["osm_tipus"], "id": str(ft["properties"]["id"]),
                        "fo": "1" if ft is fo else "0", "auto": "1"} for ft in tagok]
        stat["automatikus csoport"] += 1
        stat["automatikus csoport – darab"] += len(tagok)
    return sorok, stat


def csoportok_osszevonasa(feats):
    """forras/epulet_csoportok.csv: several OSM elements as one building. Every piece of the group
    - gets the same name (nev) and the year (ev) of the group's 'fo' (main) piece - so the colour and the card are uniform;
    - gets the data of all the group's pieces: what a piece lacks it takes from the others (address, protection, Wikipedia,
      Lechner, designer ...), with the Wikipedia articles and designers combined;
    - the card shows each piece's own data (csoport_reszek) and its OSM link (csoport_osm) in the 'Parts of the building' section.
    The pieces' own geometry, number of storeys and height do not change."""
    sorok = defaultdict(list)
    if Path(CSOPORTOK).exists():
        with open(CSOPORTOK, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                if (r.get("csoport") or "").strip() and (r.get("id") or "").strip():
                    sorok[r["csoport"].strip()].append(r)
    index = {kulcs(ft["properties"]): ft for ft in feats}
    if AUTO_CSOPORT:
        kezi_kulcsok = {((r.get("osm_tipus") or "way").strip(), int(r["id"])) for l in sorok.values() for r in l}
        auto, auto_stat = auto_csoportok(feats, kezi_kulcsok, index)
        sorok.update(auto)
        for k_, db_ in auto_stat.items():
            print(f"  épületcsoport – {k_}: {db_}")
    csoport_db = resz_db = 0
    for azon, lista in sorok.items():
        nev = next(((r.get("nev") or "").strip() for r in lista if (r.get("nev") or "").strip()), None)
        if nev is None and not azon.startswith(("auto_", "kez_")):
            nev = azon     # the name of a group created in the editor (kez_) is the pieces' shared, inherited name, not the group's id
        if nev is None:   # automatic group: the pieces' shared, inherited name (if any)
            nev = next((index[(r.get("osm_tipus") or "way", int(r["id"]))]["properties"].get("nev") for r in lista
                        if (r.get("osm_tipus") or "way", int(r["id"])) in index
                        and index[(r.get("osm_tipus") or "way", int(r["id"]))]["properties"].get("nev")), "")
        tagok = []                                   # [(feature, main?)]
        for r in lista:
            _k = ((r.get("osm_tipus") or "way").strip(), int(r["id"]))
            ft = index.get(ALIAS.get(_k, _k))
            if ft and any(ft is x for x, _ in tagok):
                continue
            if ft:
                tagok.append((ft, (r.get("fo") or "").strip() in ("1", "igen", "x")))
            else:
                print(f"  épületcsoport '{azon}': nincs ilyen épület: {r.get('osm_tipus')} {r.get('id')}")
        if len(tagok) < 2:
            continue
        fo = next((ft for ft, f_ in tagok if f_), tagok[0][0])
        tagok_sorrend = [fo] + [ft for ft, _ in tagok if ft is not fo]
        fo_azon = "%s:%s" % kulcs(fo["properties"])
        # per-piece summary (the own data, before the year is unified)
        reszek = []
        for ft in tagok_sorrend:
            p = ft["properties"]
            adat = []
            if p.get("nev") and p["nev"] != nev:
                adat.append(str(p["nev"]))
            if p.get("ev"):
                adat.append(f"{p['ev']} ({p.get('ev_forras') or '?'})")
            if p.get("tervezo"):
                adat.append("tervező: " + str(p["tervezo"]))
            if p.get("lechner_epult"):
                adat.append("Lechner: " + str(p["lechner_epult"]))
            if p.get("stilus"):
                adat.append("stílus: " + str(p["stilus"]))
            if p.get("vedettseg") or p.get("muemlek_torzsszam"):
                adat.append("védett" + (f" (törzsszám {p['muemlek_torzsszam']})" if p.get("muemlek_torzsszam") else ""))
            if p.get("wikipedia"):
                adat.append("Wikipédia: " + str(p["wikipedia"]).replace("hu:", "").replace("|", ", "))
            if p.get("cim"):
                adat.append(str(p["cim"]))
            if p.get("szintek"):
                adat.append(f"{p['szintek']:g} szint" if isinstance(p["szintek"], (int, float)) else f"{p['szintek']} szint")
            if p.get("ev_becsles_korszak") is not None and not p.get("ev"):
                adat.append("évszáma becsült")
            reszek.append("%s %s: %s" % (*kulcs(p), "; ".join(adat) if adat else "nincs külön adat"))
        # collected data
        osszes = {}
        for ft in tagok_sorrend:
            for k, v in ft["properties"].items():
                if k in CSOPORT_RESZENKENT or k.startswith(("eubucco_", "ev_becsles_", "ev_kozelito_", "szintek", "magassag")) or v in (None, "", False):
                    continue
                if k in CSOPORT_EGYESITETT:
                    jelen = [x for x in str(osszes.get(k, "")).split("|") if x]
                    for x in str(v).split("|"):
                        if x and x not in jelen:
                            jelen.append(x)
                    osszes[k] = "|".join(jelen[:3])
                elif k in CSOPORT_SZOVEG_EGYESITETT:
                    jelen = [x for x in str(osszes.get(k, "")).split("; ") if x]
                    if str(v) not in jelen and not any(str(v) in j or j in str(v) for j in jelen):
                        jelen.append(str(v))
                    osszes[k] = "; ".join(jelen)
                elif k not in osszes:
                    osszes[k] = v
        # The mark of a Wikipedia article inherited from a zone ('wikipedia_zona') spreads to the group only if none of the group's articles is
        # the piece's own article; otherwise a piece with its own article would look zone-derived (and drop out of the Wikipedia layer).
        zona_cikk = [ft["properties"] for ft in tagok_sorrend if ft["properties"].get("wikipedia")]
        zona_jelzes = next((p["wikipedia_zona"] for p in zona_cikk if p.get("wikipedia_zona")), None) \
            if zona_cikk and all(p.get("wikipedia_zona") for p in zona_cikk) else None
        wd_nev = fo["properties"].get("wikidata_nev") or next((ft["properties"].get("wikidata_nev") for ft in tagok_sorrend if ft["properties"].get("wikidata_nev")), None)
        ev = next((ft["properties"].get("ev") for ft in tagok_sorrend if ft["properties"].get("ev")), None)
        ev_forras = next((ft["properties"].get("ev_forras") for ft in tagok_sorrend if ft["properties"].get("ev")), None)
        osm = "|".join("%s:%s" % kulcs(ft["properties"]) for ft in tagok_sorrend)
        for ft in tagok_sorrend:
            p = ft["properties"]
            for k, v in osszes.items():
                if k in CSOPORT_EGYESITETT or k in CSOPORT_SZOVEG_EGYESITETT or p.get(k) in (None, "", False):
                    p[k] = v
            if nev:
                p["nev"] = nev
            if wd_nev:
                p["wikidata_nev"] = wd_nev
            if zona_jelzes and p.get("wikipedia"):
                p["wikipedia_zona"] = zona_jelzes
            else:
                p.pop("wikipedia_zona", None)
            p["csoport"], p["csoport_nev"] = fo_azon, nev or None
            p["csoport_reszek"], p["csoport_osm"] = "\n".join(reszek), osm
            if ev:
                p["ev"], p["ev_forras"] = ev, ev_forras
                for k in [k for k in p if k.startswith("ev_becsles_")]:
                    del p[k]
            resz_db += 1
        csoport_db += 1
    return csoport_db, resz_db


def zona_muemlek_hozzafuzese(feats):
    """The 'muemlek' (monument) type zones drawn in the zone editor (id: oeny_<register number>[_...]) write the monument register number,
    the protection and the E-Örökség (OENY) data-sheet id onto the buildings falling in them. A building that already has its
    own monument register number (from the address-based OENY pairing or by hand) is left alone."""
    ut = Path("forras/zonak_poligon.geojson")
    if not ut.exists():
        return 0
    try:
        azon = json.load(open("data/oeny_azonositok.json", encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        azon = {}
    zonak = []
    for f in json.load(open(ut, encoding="utf-8")).get("features", []):
        p, g = f.get("properties", {}), f.get("geometry", {})
        if p.get("tipus") != "muemlek" or g.get("type") != "Polygon":
            continue
        m = re.match(r"oeny_(\d+)", str(p.get("lista_id") or p.get("id") or ""))
        if not m:
            continue
        gy = g["coordinates"][0]
        xs, ys = [q[0] for q in gy], [q[1] for q in gy]
        zonak.append((min(xs), min(ys), max(xs), max(ys), g["coordinates"], m.group(1)))
    db = 0
    for ft in feats:
        pr = ft["properties"]
        if pr.get("muemlek_torzsszam") or pr.get("rom"):
            continue
        g = ft["geometry"]
        gyuru = g["coordinates"][0] if g["type"] == "Polygon" else g["coordinates"][0][0] if g["type"] == "MultiPolygon" else None
        if gyuru is None:
            continue
        _, x, y = teruletu_kozeppont(gyuru)
        for x0, y0, x1, y1, koord, tsz in zonak:
            if x0 <= x <= x1 and y0 <= y <= y1 and pont_poligonban(x, y, koord):
                pr["muemlek_torzsszam"] = tsz
                if not pr.get("vedettseg"):
                    pr["vedettseg"] = "M"
                if azon.get(tsz):
                    pr["oeny_azonosito"] = "|".join(azon[tsz][:3])
                db += 1
                break
    return db


def ertek(mezo, x):
    return szam(x) if mezo in SZAMOS else x


def _felvag(gyuru, p1, p2, bal):
    """Sutherland-Hodgman: the part of the ring (lon, lat) on one side of the line p1->p2 (bal=True: the left side of the direction of travel).
    Computed in a metric-proportional plane (a degree of longitude is shorter)."""
    kx = math.cos(math.radians(47.5))
    def oldal(p):
        v = ((p2[0] - p1[0]) * kx) * (p[1] - p1[1]) - (p2[1] - p1[1]) * ((p[0] - p1[0]) * kx)
        return v if bal else -v
    ki = []
    n = len(gyuru) - 1 if gyuru[0] == gyuru[-1] else len(gyuru)
    for i in range(n):
        a, b = gyuru[i], gyuru[(i + 1) % n]
        oa, ob = oldal(a), oldal(b)
        if oa >= 0:
            ki.append(a)
        if (oa >= 0) != (ob >= 0):
            t = oa / (oa - ob)
            ki.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
    if len(ki) < 3:
        return None
    ki.append(ki[0])
    return [list(p) for p in ki]


def felosztas(feats):
    """forras/kezi_felosztas.csv: cuts one outline into two buildings along the line (lat1,lon1)->(lat2,lon2).
    a_id/b_id: ids of the new elements (empty: the original id*10+1 / *10+2); a = the left, b = the right side of the line's direction of travel.
    a_cim/b_cim: addresses of the new houses. Give the new elements' facts (ev, tervezo, szintek ...) in kezi_javitasok.csv under the new id."""
    if not Path(FELOSZTAS).exists():
        return feats
    sorok = [r for r in csv.DictReader(open(FELOSZTAS, encoding="utf-8-sig", newline=""), delimiter=";") if (r.get("id") or "").strip().isdigit()]
    if not sorok:
        return feats
    ki, db = [], 0
    for ft in feats:
        pr = ft["properties"]
        k = ((pr.get("osm_tipus") or "way"), int(pr.get("id") or 0))
        r = next((x for x in sorok if ((x.get("osm_tipus") or "way").strip(), int(x["id"])) == k), None)
        gy = ft["geometry"]["coordinates"]
        if r is None or len(gy) != 1:        # an outline with a hole is not cut
            ki.append(ft)
            continue
        p1, p2 = (float(r["lon1"]), float(r["lat1"])), (float(r["lon2"]), float(r["lat2"]))
        reszek = []
        for oldal, bal in (("a", True), ("b", False)):
            uj = _felvag([tuple(p) for p in gy[0]], p1, p2, bal)
            if uj is None:
                continue
            azon = (r.get(oldal + "_id") or "").strip()
            azon = int(azon) if azon.isdigit() else k[1] * 10 + (1 if bal else 2)
            pr2 = dict(pr)
            pr2["id"] = azon
            pr2["felosztott_ebbol"] = f"{k[0]}:{k[1]}"
            if (r.get(oldal + "_cim") or "").strip():
                pr2["felosztas_cim"] = r[oldal + "_cim"].strip()
            reszek.append({"type": "Feature", "properties": pr2, "geometry": {"type": "Polygon", "coordinates": [uj]}})
        if len(reszek) == 2:
            ki.extend(reszek)
            db += 1
        else:
            ki.append(ft)
    if db:
        print(f"Felosztott épületek ({FELOSZTAS}): {db} körvonal kettévágva")
    return ki


def duplikatok_kezelese(feats):
    """Cleans geometries drawn on top of each other from the rows of forras/duplikatumok.csv ('alkalmaz' = igen), without losing data:
    - mod=gyuru: the same element's inner, redundant outline is deleted (gyuru_pontok is the vertex count of the outer ring);
    - mod=elem: all outlines of the deleted element are deleted; its facts (ALIAS) go to the kept element, and of its OSM properties
      it hands over whatever the kept one lacks (name, Wikidata, a more precise type, the actual number of storeys/height)."""
    if not Path(DUPLIKATUMOK).exists():
        return feats
    sorok = []
    with open(DUPLIKATUMOK, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if (r.get("alkalmaz") or "").strip().lower() in ("igen", "i", "x", "1") and (r.get("torolt_id") or "").strip().isdigit():
                sorok.append(r)
    if not sorok:
        return feats
    kulcs_ = lambda t, i: ((t or "way").strip(), int(i))
    gyuru_torles = defaultdict(set)
    elem_torles = {}
    for r in sorok:
        t = kulcs_(r["torolt_tipus"], r["torolt_id"])
        if r.get("mod", "").strip() == "gyuru":
            if (r.get("torolt_gyuru_pontok") or "").strip().isdigit():
                gyuru_torles[t].add(int(r["torolt_gyuru_pontok"]))
        elif (r.get("megtartott_id") or "").strip().isdigit():
            elem_torles[t] = kulcs_(r["megtartott_tipus"], r["megtartott_id"])
    kulcsok = defaultdict(list)
    for ft in feats:
        kulcsok[kulcs(ft["properties"])].append(ft)
    kidob = set()
    gy_db = 0
    for t, pontok in gyuru_torles.items():
        lista = kulcsok.get(t, [])
        torlendo = [ft for ft in lista if len(ft["geometry"]["coordinates"][0]) in pontok]
        if torlendo and len(torlendo) < len(lista):      # at least one outline always remains
            kidob.update(id(ft) for ft in torlendo)
            gy_db += len(torlendo)
    el_db = 0
    for t, m in elem_torles.items():
        if t == m or t not in kulcsok or m not in kulcsok:
            print(f"  duplikátum: kihagyva {t} -> {m} (nincs meg valamelyik)")
            continue
        for ft in kulcsok[m]:
            mp = ft["properties"]
            for d in kulcsok[t]:
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
        for ft in kulcsok[t]:
            kidob.add(id(ft))
        ALIAS[t] = m
        el_db += 1
    for t in list(ALIAS):                                  # resolving chains
        m = ALIAS[t]
        for _ in range(5):
            if m in ALIAS:
                m = ALIAS[m]
        ALIAS[t] = m
    print(f"Duplikátumok ({DUPLIKATUMOK}): {el_db} elem és {gy_db} fölösleges körvonal törölve, a tények átirányítva")
    return [ft for ft in feats if id(ft) not in kidob]


def main():
    with open(PRIORITAS, encoding="utf-8") as f:
        pri = json.load(f)
    tol = pri.get("ev_tolerancia", 2)

    with open(OSM, encoding="utf-8") as f:
        gj = json.load(f)
    elozo = len(gj["features"])
    gj["features"] = [x for x in gj["features"] if x["properties"].get("tipus") != "roof"]
    if len(gj["features"]) != elozo:
        print(f"Tető-elemek kihagyva: {elozo - len(gj['features'])}")
    feats = gj["features"]
    if Path(RESZEK).exists():
        with open(RESZEK, encoding="utf-8") as f:
            reszek = json.load(f)["features"]
        van = {kulcs(ft["properties"]) for ft in feats}
        reszek = [r for r in reszek if kulcs(r["properties"]) not in van]
        for r in reszek:
            r["properties"]["resz"] = True
        feats.extend(reszek)
        print(f"  épületrészek (building:part): {len(reszek)}")
    if Path(KEZI_EPULETEK).exists():
        with open(KEZI_EPULETEK, encoding="utf-8") as f:
            kezi_ep = json.load(f)["features"]
        van = {kulcs(ft["properties"]) for ft in feats}
        kezi_ep = [x for x in kezi_ep if kulcs(x["properties"]) not in van]
        feats.extend(kezi_ep)
        print(f"  kézzel felvett elemek ({KEZI_EPULETEK}): {len(kezi_ep)}")
    if Path(KIZART).exists():
        kizart = set()
        with open(KIZART, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                if (r.get("id") or "").strip().isdigit():
                    kizart.add(((r.get("osm_tipus") or "way").strip(), int(r["id"].strip())))
        elozo = len(feats)
        feats = [ft for ft in feats if (ft["properties"].get("osm_tipus") or "way", int(ft["properties"].get("id") or 0)) not in kizart]
        gj["features"] = feats
        print(f"Kizárt épületek ({KIZART}): {elozo - len(feats)} elem kihagyva a listán szereplő {len(kizart)} közül")
    feats = felosztas(feats)
    feats = duplikatok_kezelese(feats)
    gj["features"] = feats
    index = defaultdict(list)
    for ft in feats:
        index[kulcs(ft["properties"])].append(ft)

    # ---- collecting the facts ----
    tenyek = []
    for ut in sorted(TENYEK_MAPPA.glob("*.csv")):
        sorok = tenyek_olvasasa(ut)
        tenyek += sorok
        print(f"  {ut.name}: {len(sorok)} sor")
    if Path(OENY_KIZART).exists():
        oeny_ki, oeny_reszleges = set(), defaultdict(set)   # full exclusion / removal of only one register number (data sheet)
        with open(OENY_KIZART, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                if (r.get("id") or "").strip().isdigit():
                    kl = ((r.get("osm_tipus") or "way").strip(), int(r["id"].strip()))
                    tsz = (r.get("torzsszam") or "").strip()
                    if tsz.isdigit():
                        oeny_reszleges[kl].add(tsz)
                    else:
                        oeny_ki.add(kl)
        elozo_t = len(tenyek)

        def oeny_marad(r):
            if r.get("forras") not in ("oeny", "oeny_koord"):
                return True
            kl = ((r.get("osm_tipus") or "way").strip(), int(r["id"]))
            if kl in oeny_ki:
                return False
            if kl in oeny_reszleges:
                m = re.search(r"törzsszám (\d+)", r.get("megjegyzes") or "")
                tsz = m.group(1) if m else (str(r.get("ertek")).strip() if r.get("mezo") == "muemlek_torzsszam" else "")
                if tsz in oeny_reszleges[kl]:
                    return False
            return True
        tenyek = [r for r in tenyek if oeny_marad(r)]
        print(f"  E-Örökség kizárás ({OENY_KIZART}): {elozo_t - len(tenyek)} tény eldobva a listán szereplő {len(oeny_ki)} elemről + {sum(len(v) for v in oeny_reszleges.values())} egyedi adatlapról")
    kezi_sorok = tenyek_olvasasa(KEZI, "kezi") if Path(KEZI).exists() else []
    for r in kezi_sorok:
        r["forras"] = "kezi"
    print(f"  kézi javítások: {len(kezi_sorok)} sor")

    # manual row without an id: the building is found by coordinates
    nem_talalt = 0
    for r in kezi_sorok:
        if (r.get("id") or "").strip():
            continue
        try:
            x, y = float(r["lon"]), float(r["lat"])
        except (TypeError, ValueError):
            nem_talalt += 1
            r["id"] = ""
            continue
        for ft in feats:
            if pont_poligonban(x, y, ft["geometry"]["coordinates"]):
                r["osm_tipus"], r["id"] = kulcs(ft["properties"])
                break
        else:
            nem_talalt += 1
            r["id"] = ""
    tenyek += kezi_sorok

    szedett = defaultdict(lambda: defaultdict(list))   # key -> field -> [(source, value, remark)]
    ismeretlen = 0
    for r in tenyek:
        try:
            k = ((r.get("osm_tipus") or "way").strip(), int(r["id"]))
        except (TypeError, ValueError):
            ismeretlen += 1
            continue
        k = ALIAS.get(k, k)
        if k not in index:
            ismeretlen += 1
            continue
        v = ertek(r["mezo"], r["ertek"])
        if r["forras"] == "kezi" and r["mezo"] in SZAMOS and str(r["ertek"]).strip() == "-":
            v = TOROL           # '-' in a manual correction: deletes the numeric field (year, storeys, height); it used to be lost silently
        if v in (None, ""):
            continue
        szedett[k][r["mezo"]].append((r["forras"], v, r.get("megjegyzes", "")))
    if ismeretlen or nem_talalt:
        print(f"Figyelem: {ismeretlen} tény-sor olyan épületre hivatkozik, ami nincs az OSM-fájlban; "
              f"{nem_talalt} kézi sor nem azonosítható.")

    utkozesek = []
    stat = {m: Counter() for m in DONTO_MEZOK}
    for k, lista in index.items():
        for ft in lista:
            pr = ft["properties"]
            tn = szedett.get(k, {})
            # OSM's own data count as a source too
            jel = {m: list(tn.get(m, [])) for m in DONTO_MEZOK}
            if pr.get("ev"):
                jel["ev"].append(("osm", pr["ev"], pr.get("ev_forras") or ""))
            if pr.get("szintek"):
                jel["szintek"].append(("osm", pr["szintek"], "building:levels"))
            if pr.get("magassag_forras") == "height":
                jel["magassag"].append(("osm_height", pr["magassag"], "height"))
            osm_ev_forras = pr.get("ev_forras")
            for m in DONTO_MEZOK:          # manual deletion ('-'): if the latest manual row is a deletion, every source of the field drops out
                kezi_m = [x for x in jel[m] if x[0] == "kezi"]
                jel[m] = [] if kezi_m and kezi_m[-1][1] is TOROL else [x for x in jel[m] if x[1] is not TOROL]

            for m in ("ev", "tervezo", "szintek"):
                valasztott = None
                for forras in pri[m]:
                    # for the manual correction the last value entered wins
                    for f_, v, megj in (reversed(jel[m]) if forras == "kezi" else jel[m]):
                        if f_ == forras:
                            valasztott = (f_, v, megj)
                            break
                    if valasztott:
                        break
                for f_, v, megj in jel[m]:   # conflicts
                    if valasztott and f_ != valasztott[0] and v != valasztott[1] and (
                            m != "ev" or abs(v - valasztott[1]) > tol) and (
                            m != "tervezo" or not tervezo_egyezik(v, valasztott[1])):
                        utkozesek.append((k[0], k[1], pr.get("nev") or "", m,
                                          f"{valasztott[0]}={valasztott[1]}", f"{f_}={v}"))
                if valasztott:
                    f_, v, _ = valasztott
                    pr[m] = v
                    stat[m][f_] += 1
                    if m == "tervezo":
                        pr["tervezo_forras"] = f_
                    if m == "ev":
                        pr["ev_forras"] = osm_ev_forras if f_ == "osm" else f_
                    elif m == "szintek":
                        pr["szintek_forras"] = f_
                else:
                    pr.pop(m, None)
                    if m == "tervezo":
                        pr.pop("tervezo_forras", None)
                    if m == "ev":
                        pr["ev_forras"] = None
            osm_szint = next((v for f_, v, _ in jel["szintek"] if f_ == "osm"), None)
            if osm_szint is not None:
                pr["szintek_osm"] = osm_szint
            if pr.get("szintek") and osm_szint and pr["szintek"] != osm_szint:
                pr["szint_eltero"] = True
            else:
                pr.pop("szint_eltero", None)
            if pr.get("szintek") is None:
                pr.pop("szintek_forras", None)

            # height: the one computed from the number of storeys and the default are also marked
            if pr.get("szintek"):
                jel["magassag"].append(("szintbol", pr["szintek"] * pri["meter_szintenkent"], ""))
                pr["magassag_szintbol"] = pr["szintek"] * pri["meter_szintenkent"]
            jel["magassag"].append(("alapertelmezett", pri["alapertelmezett_magassag"], ""))
            valasztott = None
            for forras in pri["magassag"]:
                for f_, v, megj in (reversed(jel["magassag"]) if forras == "kezi" else jel["magassag"]):
                    if f_ == forras:
                        valasztott = (f_, v)
                        break
                if valasztott:
                    break
            f_, v = valasztott
            if f_ in ("alapertelmezett", "eubucco_becsles"):
                # no measured height data: a small outbuilding (shed, pantry, kiosk) must not get 15 m, and the estimated EUBUCCO height
                # should not be taken over either if it comes from a larger neighbouring building of EUBUCCO (the kiosk falls into the large building's footprint)
                g_ = ft.get("geometry") or {}
                if g_.get("type") == "Polygon" and g_.get("coordinates"):
                    ter_ = gyuru_terulet(g_["coordinates"])
                    if ter_ < KIS_EPULET_M2:
                        v = KIS_EPULET_MAGASSAG if (f_ == "alapertelmezett" or ter_ < KIOSZK_M2) else min(v, KIS_EPULET_MAX_BECSLT)
            pr["magassag"] = v
            stat["magassag"][f_] += 1
            if f_ == "osm_height":
                pr["magassag_forras"] = "height"
            elif f_ == "szintbol":
                pr["magassag_forras"] = "szintterkep" if pr.get("szintek_forras") == "szintterkep" else "szintszam"
            else:
                pr["magassag_forras"] = f_

            # every other fact as a simple property (the last item of the list is valid)
            for mezo, vals in tn.items():
                if mezo in DONTO_MEZOK:
                    continue
                kezi = [x for x in vals if x[0] == "kezi"]
                if not kezi and mezo == "oeny_azonosito":   # a data sheet paired by OENY coordinates is more precise than one based on register number/address
                    kezi = [x for x in vals if x[0] == "oeny_koord"]
                if kezi:                            # the manual correction wins for the other fields as well
                    pr[mezo] = kezi[-1][1]
                elif mezo in ("wikipedia", "oeny_azonosito"):   # articles / data sheets from several sources combined (at most 3)
                    egyedi = list(dict.fromkeys(str(x[1]) for x in vals))
                    pr[mezo] = "|".join(egyedi[:3])
                else:
                    pr[mezo] = vals[-1][1]
                if pr.get(mezo) is TOROL or pr.get(mezo) in ("-", ""):       # '-' = the manual correction removes the field
                    pr.pop(mezo, None)

    gj["features"], resz_stat = reszek_kezelese(feats)
    zona_eldobott_db = zona_gyenge_ev_felulirasa(gj["features"])
    becsles_db = becsles_hozzafuzese(gj["features"])
    kozelito_db = kozelito_hozzafuzese(gj["features"])
    print(f"  Közelítő korszakadat (pl. '1920-as évek') a kártyára: {kozelito_db} épület")
    cim_db = cimek_hozzafuzese(gj["features"])
    import streetview
    print(f"  Utcai pont (utcakép-link): {streetview.szamol(gj['features'], CIMEK)} épület")
    for ft in gj["features"]:                       # manually given address of the split houses
        if ft["properties"].get("felosztas_cim"):
            ft["properties"]["cim"] = ft["properties"].pop("felosztas_cim")
            ft["properties"].pop("cim_tobb", None)
    kezi_cimek = {}                                  # forras/kezi_cimek.csv: osm_tipus;id;cim;megjegyzes - manual override of the address shown on the card
    if Path(KEZI_CIMEK).exists():
        with open(KEZI_CIMEK, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                if (r.get("id") or "").strip().isdigit() and (r.get("cim") or "").strip():
                    kezi_cimek[((r.get("osm_tipus") or "way").strip(), int(r["id"]))] = r["cim"].strip()
    for ft in gj["features"]:
        k = kulcs(ft["properties"])
        if k in kezi_cimek:
            ft["properties"]["cim"] = kezi_cimek[k]
            ft["properties"].pop("cim_tobb", None)
    zona_wiki_db = zona_wikipedia_hozzafuzese(gj["features"])
    zona_nev_db = zona_nev_hozzarendeles(gj["features"])
    print(f"  lakótelep-zóna neve: {zona_nev_db} épületen")
    zona_terv_db = zona_tervezo_hozzarendeles(gj["features"])
    print(f"  zónából tervezőt kapott: {zona_terv_db} épület")
    tervezo_tisztitas(gj["features"])        # before the groups are merged as well: so the same name is not duplicated
    zona_muemlek_db = zona_muemlek_hozzafuzese(gj["features"])
    zona_bp100_db = zona_budapest100_hozzafuzese(gj["features"])
    for ft in gj["features"]:   # local protection = a protection type of its own (HV), if there is no higher-level (M, MJ, VK, MK, MJT) protection
        pr = ft["properties"]
        if pr.get("vedettseg_helyi") and not pr.get("vedettseg"):
            pr["vedettseg"] = "HV"
    csoport_db, csoport_resz_db = csoportok_osszevonasa(gj["features"])
    tervezo_zarojel_db = tervezo_tisztitas(gj["features"])
    print(f"  tervező-mező zárójeles tartalma törölve: {tervezo_zarojel_db} elemnél (az utolsó körben)")
    with open(KIMENET, "w", encoding="utf-8") as f:
        json.dump(gj, f, ensure_ascii=False)
    kiz_ut = Path("forras/epitesz_irodak.csv")      # the names excluded (not persons) from the Architects tab as a static file for the public site
    kizart = []
    if kiz_ut.exists():
        with open(kiz_ut, encoding="utf-8-sig", newline="") as f:
            kizart = sorted({r["kulcs"] for r in csv.DictReader(f, delimiter=";")
                             if r.get("kulcs") and r.get("tipus") in ("iroda", "intezmeny", "tobb_szemely", "nem_nev")})
    Path("terkep3d/epitesz_kizart.json").write_text(json.dumps(kizart, ensure_ascii=False), encoding="utf-8")
    Path(UTKOZESEK).parent.mkdir(exist_ok=True)
    with open(UTKOZESEK, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["osm_tipus", "id", "nev", "mezo", "gyoztes", "eltero_forras"])
        w.writerows(utkozesek)

    print(f"\nÉpületek: {len(feats)}")
    print(f"  műemlék-zónákból műemléki adatot kapott: {zona_muemlek_db}")
    print(f"  zónából Budapest100-linket kapott: {zona_bp100_db}")
    print(f"  épületcsoport (több OSM-elem egy épületként): {csoport_db} csoport, {csoport_resz_db} darab")
    print(f"  zónahatáron kívüli, gyenge forrású (EUBUCCO / közeli Wikidata) évszám eldobva, szürke lett: {zona_eldobott_db}")
    for kulcs_, db in resz_stat.items():
        print(f"  épületrészek – {kulcs_}: {db}")
    print(f"  kiírt elemek: {len(gj['features'])}")
    print(f"  becsült korszakkal ellátott szürke épület: {becsles_db}")
    print(f"  címmel ellátott elem: {cim_db}")
    print(f"  zóna-cikket kapott épület (Wikipédia): {zona_wiki_db}")
    for m in DONTO_MEZOK:
        print(f"  {m}: {dict(stat[m])}")
    ossz = Counter(u[3] for u in utkozesek)
    print(f"Ütközések (források eltérnek): {dict(ossz)}  -> {UTKOZESEK}")
    print(f"Mentve: {KIMENET}")


if __name__ == "__main__":
    main()
