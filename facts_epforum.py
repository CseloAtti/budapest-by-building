"""Contemporary buildings of the Építészfórum map (epiteszforum.hu/terkep) -> data/tenyek/epforum.csv

Input:    data/epforum/budapesti_kortars_epuletek_lista.csv   (ID, name, address, architects, year, function, lat, lon)
          data/varos/epuletek.geojson                          (py city_assembly.py)
Output:   data/tenyek/epforum.csv            - 'ev' and 'tervezo' facts for assemble.py (source: 'epforum')
          data/epforum_nem_parositott.csv    - what could not be tied to a building

Run:       py facts_epforum.py

We take over only facts (architect, year, identifier); not the descriptions or the images. The year in the list is the year the contemporary
building was completed. We do not use the "Örökség" (renovated monuments), "Köztér" (public space), "Emlékhely" (memorial site) and "Infrastruktúra"
(infrastructure) categories: there the year means a renovation, the creator is not the original designer, or it is not a building.
We look for the building by the given coordinate: we choose the OSM building within whose footprint the point lies;
if there is none, the nearest one within 12 m.
"""
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import re
import unicodedata

from common import polygons, write_facts

LIST = "data/epforum/budapesti_kortars_epuletek_lista.csv"
BUILDINGS = "data/varos/epuletek.geojson"
OUTPUT = "data/tenyek/epforum.csv"
NOT_PAIRED = "data/epforum_nem_parositott.csv"
MANUAL_PAIRING = "forras/epforum_kezi_parositas.csv"   # for the unmatched items you enter the OSM identifier (osm_azonosito column)
ADDRESSES = "data/varos/osm_cimek.csv"      # fallback: if there is no building at the coordinate, we search by address
ARTICLES = "data/epforum/cikkek.csv"     # facts_epforum_articles.py: the articles of the map point (clicking the point gives Építészfórum a chooser page, so we collect the articles separately)
MAX_ARTICLE = 4


def read_articles():
    out = {}
    if Path(ARTICLES).exists():
        for r in csv.DictReader(open(ARTICLES, encoding="utf-8-sig", newline=""), delimiter=";"):
            if (r.get("url") or "").startswith("https://epiteszforum.hu/"):
                out.setdefault(r["id"], []).append(r["url"])
    return {k: "|".join(v[:MAX_ARTICLE]) for k, v in out.items()}


ARTICLE_URL = read_articles()
SKIPPED_FUNCTION = {"örökség", "köztér", "emlékhely", "infrastruktúra"}
MAX_DISTANCE_M = 12.0
CELL = 0.002          # fok (~150-220 m)
DEGREE_M_LAT = 111000.0
DEGREE_M_LON = 111000.0 * math.cos(math.radians(47.5))


def in_ring(x, y, ring_):
    inside = False
    for (x1, y1), (x2, y2) in zip(ring_, ring_[1:]):
        if (y1 > y) != (y2 > y):
            if x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                inside = not inside
    return inside


def section_distance(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    h = dx * dx + dy * dy
    t = 0.0 if h == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / h))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def area_m2(ring_):
    s = 0.0
    for (x1, y1), (x2, y2) in zip(ring_, ring_[1:]):
        s += (x1 * DEGREE_M_LON) * (y2 * DEGREE_M_LAT) - (x2 * DEGREE_M_LON) * (y1 * DEGREE_M_LAT)
    return abs(s) / 2


def simple(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", "".join(c for c in s if unicodedata.category(c) != "Mn")).strip()


def address_key(address):
    """'Budapest, 1117, Buda-part tér 2.' -> ('buda part ter', '2')"""
    m = re.match(r"Budapest,\s*\d{4},\s*(.+?)\s+(\d+[A-Za-z]?)(?:\s*[-–/]\s*\d+[A-Za-z]?)?\.?$", (address or "").strip())
    return (simple(m.group(1)), simple(m.group(2))) if m else None


def address_index():
    idx = defaultdict(set)
    try:
        with open(ADDRESSES, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f, delimiter=";"):
                idx[(simple(r["utca"]), simple(r["hazszam"]))].add((r["osm_tipus"], int(r["id"])))
    except FileNotFoundError:
        print(f"Figyelem: nincs {ADDRESSES}, a cím alapú tartalék nem működik (py city_assembly.py).")
    return idx


def main():
    rows = list(csv.DictReader(open(LIST, encoding="utf-8-sig"), delimiter=";"))
    addresses = address_index()
    address_use = defaultdict(int)         # how many list entries point to the same address (e.g. BudaPart: Buda-part tér 2.)
    for r in rows:
        k = address_key(r["Cím"])
        if k:
            address_use[k] += 1
    grid = defaultdict(list)
    with open(BUILDINGS, encoding="utf-8") as f:
        for ft in json.load(f)["features"]:
            pr = ft["properties"]
            for poly in polygons(ft["geometry"]):
                outer = poly[0]
                xs = [c[0] for c in outer]
                ys = [c[1] for c in outer]
                rec = (pr["osm_tipus"], int(pr["id"]), poly, area_m2(outer))
                for i in range(int((min(xs) - 0.0002) // CELL), int((max(xs) + 0.0002) // CELL) + 1):
                    for j in range(int((min(ys) - 0.0002) // CELL), int((max(ys) + 0.0002) // CELL) + 1):
                        grid[(i, j)].append(rec)
    done, left_out = set(), []
    stat = defaultdict(int)
    # For the items with manual matching (osm_azonosito is filled in) the year/designer facts of the automatic matching are omitted,
    # and of the article links, those named by the manual row's 'cikk_url' column (empty column = all) are carried over to the new building.
    manual_relocate = {}
    if Path(MANUAL_PAIRING).exists():
        for kr in csv.DictReader(open(MANUAL_PAIRING, encoding="utf-8-sig"), delimiter=";"):
            if re.search(r"\d{3,}", kr.get("osm_azonosito") or "") and (kr.get("epforum_id") or "").strip():
                manual_relocate[kr["epforum_id"].strip()] = {u.strip() for u in re.split(r"[|\s]+", kr.get("cikk_url") or "") if u.strip()}
    for r in rows:
        function = (r["Funkció"] or "").strip()
        if function.lower() in SKIPPED_FUNCTION:
            stat["kihagyott kategória"] += 1
            continue
        if not r["Cím"].startswith("Budapest"):
            stat["nem budapesti"] += 1
            continue
        try:
            lat, lon = float(r["Lat"]), float(r["Lon"])
        except ValueError:
            left_out.append([r["ID"], r["Épület neve"], r["Cím"], "nincs koordináta"])
            continue
        cell = (int(lon // CELL), int(lat // CELL))
        sign = grid.get(cell, [])
        inside = [(t, i, a) for t, i, poly, a in sign if in_ring(lon, lat, poly[0]) and not any(in_ring(lon, lat, h) for h in poly[1:])]
        mode = "alapterületen belül"
        if not inside:
            best = None
            for t, i, poly, a in sign:
                d = min(section_distance((lon) * DEGREE_M_LON, (lat) * DEGREE_M_LAT, x1 * DEGREE_M_LON, y1 * DEGREE_M_LAT, x2 * DEGREE_M_LON, y2 * DEGREE_M_LAT)
                        for (x1, y1), (x2, y2) in zip(poly[0], poly[0][1:]))
                if d <= MAX_DISTANCE_M and (best is None or d < best[0]):
                    best = (d, t, i, a)
            if best:
                inside = [(best[1], best[2], best[3])]
                mode = f"{best[0]:.0f} m-re a ponttól"
        if not inside:
            # fallback: by address, but only if that address is on exactly one OSM building, and only one list entry
            # points to it (for a large estate, e.g. BudaPart, the same address belongs to many buildings: we do not guess there)
            k = address_key(r["Cím"])
            hit = addresses.get(k, set()) if k else set()
            if len(hit) == 1 and address_use[k] == 1:
                t0, i0 = next(iter(hit))
                inside = [(t0, i0, 0.0)]
                mode = "a cím alapján (a koordinátán nem volt épület)"
                stat["cím alapján"] += 1
        if not inside:
            left_out.append([r["ID"], r["Épület neve"], r["Cím"], "a koordinátán nincs OSM-épület, a cím sem egyértelmű"])
            stat["nincs épület"] += 1
            continue
        # several buildings: the one with the smallest footprint (the tightest containing one)
        t, i, _ = min(inside, key=lambda b: b[2])
        stat["párosítva"] += 1
        remark = f"Építészfórum térkép, ID {r['ID']}, {function}; {mode}"
        relocated = manual_relocate.get(r["ID"])
        if relocated is None:
            if r["Évtized"].isdigit():
                done.add((t, i, "ev", int(r["Évtized"]), "epforum", remark + " (az elkészülés éve)"))
            if r["Építészek"].strip():
                done.add((t, i, "tervezo", r["Építészek"].strip(), "epforum", remark))
        urls = [u for u in (ARTICLE_URL.get(r["ID"]) or "").split("|") if u and not (relocated is not None and (not relocated or u in relocated))]
        if urls:
            done.add((t, i, "epforum_url", "|".join(urls), "epforum", remark))
    # manual matching: forras/epforum_kezi_parositas.csv; the osm_azonosito column holds one or more items (separated by | or ;),
    # e.g. "way 1127749031", "1127749031" (way), "relation 123" or the link of the OSM page. The year and the designer come from the table.
    manual_done = set()
    if Path(MANUAL_PAIRING).exists():
        for r in csv.DictReader(open(MANUAL_PAIRING, encoding="utf-8-sig"), delimiter=";"):
            those = []
            for part in re.split(r"[|;,\n]+", r.get("osm_azonosito") or ""):
                m = re.search(r"(?:(way|relation|node)[/ :]*)?(\d{3,})", part.strip(), flags=re.I)
                if m:
                    those.append(((m.group(1) or "way").lower(), int(m.group(2))))
            if not those:
                continue
            remark = f"Építészfórum térkép, ID {r['epforum_id']}, {r.get('funkcio', '')}; kézi párosítás ({MANUAL_PAIRING})"
            year = (r.get("ev") or "").strip()
            for t, i in those:
                if year.isdigit():
                    manual_done.add((t, i, "ev", int(year), "epforum", remark + " (az elkészülés éve)"))
                if (r.get("epitesz") or "").strip():
                    manual_done.add((t, i, "tervezo", r["epitesz"].strip(), "epforum", remark))
                manual_url = "|".join(u for u in (ARTICLE_URL.get((r.get("epforum_id") or "").strip()) or "").split("|")
                                    if u and (not (r.get("cikk_url") or "").strip() or u in (r.get("cikk_url") or "")))
                if manual_url:
                    manual_done.add((t, i, "epforum_url", manual_url, "epforum", remark))
            left_out = [k for k in left_out if str(k[0]) != str(r["epforum_id"])]
            stat["kézi párosítás"] += 1
    done |= manual_done
    write_facts(OUTPUT, sorted(done, key=lambda s: (s[0], s[1], s[2])))
    with open(NOT_PAIRED, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["id", "nev", "cim", "miert"])
        w.writerows(left_out)
    print(f"Bejegyzés: {len(rows)}; párosítva: {stat['párosítva']}; nem párosított: {len(left_out)}; "
          f"ebből cím alapján: {stat['cím alapján']}; kézi párosítás: {stat['kézi párosítás']}; kihagyott kategória: {stat['kihagyott kategória']}; nem budapesti: {stat['nem budapesti']}")
    print(f"Tények: {len(done)} sor -> {OUTPUT}; nem párosított lista: {NOT_PAIRED}")


if __name__ == "__main__":
    main()
