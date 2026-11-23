"""Automatic pairing of heritage-inventory cards by the polygon of the lot (parcel) and the exact current address.

Input:    forras/ertekleltar_cimekkel_es_geometriaval.csv   (kerulet;cim;new cím;hrsz;...;Geometria (GeoJSON) - with EOV coordinates)
          forras/ertekleltar_kezi_parositas.csv             (the manual-check table; it does NOT touch the already filled rows)
          data/varos/epuletek.geojson, data/varos/osm_cimek.csv
Output:   forras/ertekleltar_kezi_parositas.csv  - writes the osm_azonosito into the open rows (in unambiguous cases) or the suggestion
          data/ertekleltar_telek_jelentes.csv    - every row: decision, reason, candidates; and where your manual decision differs from the lot-based one

WARNING: the "new cím" column in the source file is shifted by one row (the correct address is in the NEXT row). This script handles it;
if you fix the source file, set the value of CIM_ELTOLAS to 0.

Method: the EOV polygon is converted to WGS84 (eov.py), and we compute (by sampling) what part of the OSM buildings falls on the lot.
  - where one of the buildings falling on the lot (>= 50%) has an address in OSM that matches the current address: these buildings (max. 3) -> automatic
  - if there is no address match, but exactly one building (>= 20 m²) falls on the lot, or one building is at least 3 times as large as the others: automatic
  - otherwise: the suggestion is the largest building on the lot, with manual confirmation (probable / uncertain)
Run:  py inventory_plots.py
"""
import csv
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

import eov
import facts_corner as S
from facts_oeny import clean_street

GEO = Path("forras/ertekleltar_cimekkel_es_geometriaval.csv")
TABLE = Path("forras/ertekleltar_kezi_parositas.csv")
REPORT = Path("data/ertekleltar_telek_jelentes.csv")
ADDRESS_OFFSET = 1          # the "new cím" in the source comes this many rows earlier than the one it belongs to
MIN_AREA = 12.0           # a building smaller than this (a small shed) is not considered a candidate
COLUMNS = ["kerulet", "cim", "hrsz", "epites_ideje", "tervezo", "allapot", "javasolt_osm", "jeloltek", "osm_azonosito", "megjegyzes"]


MONTH = {"jan": 1, "febr": 2, "márc": 3, "ápr": 4, "máj": 5, "jún": 6, "júl": 7, "aug": 8, "szept": 9, "okt": 10, "nov": 11, "dec": 12}


def lot_number_fix(h):
    """Excel read the lot number '3/15' as a date ('márc.15'): converted back to '3/15'."""
    m = re.fullmatch(r"\s*([a-záéíóöőúüű]+)\.?\s*(\d+)\s*", h or "", flags=re.I)
    if m and m.group(1).lower() in MONTH:
        return f"{MONTH[m.group(1).lower()]}/{m.group(2)}"
    return (h or "").strip()


def pip(x, y, ring_):
    be = False
    for (x1, y1), (x2, y2) in zip(ring_, ring_[1:] + ring_[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            be = not be
    return be


def polygons(geojson):
    j = json.loads(geojson)
    polys = j["coordinates"] if j["type"] == "MultiPolygon" else [j["coordinates"]]
    out = []
    for p in polys:
        ll = [eov.eov_wgs84(a, b) for a, b in p[0]]
        out.append([((lo - S.LON0) * S.KX, (la - S.LAT0) * S.KY) for la, lo in ll])
    return out


def sample(pts, n=7):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    out = [(min(xs) + (i + .5) * (max(xs) - min(xs)) / n, min(ys) + (j + .5) * (max(ys) - min(ys)) / n) for i in range(n) for j in range(n)]
    out = [p for p in out if pip(p[0], p[1], pts)]
    return out or [(sum(xs) / len(xs), sum(ys) / len(ys))]


def overlap(T, rings):
    xs = [p[0] for g in rings for p in g]
    ys = [p[1] for g in rings for p in g]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    R = max(max(xs) - min(xs), max(ys) - min(ys)) / 2 + 20
    out = {}
    for d, e in T.near((cx, cy), R):
        m = sample(T.b[e]["pts"])
        f = sum(1 for p in m if any(pip(p[0], p[1], g) for g in rings)) / len(m)
        if f > 0:
            out[e] = f
    return out, (cx, cy)


def new_addresses(text_):
    out = []
    for part in (text_ or "").split("|"):
        m = re.search(r"ker\.,\s*(.+?)\s+(\d+)", part.strip())
        if m:
            out.append((clean_street(m.group(1)), int(m.group(2))))
    return out


def address_matches(T, e, addresses):
    for u, n in T.b[e]["cim"]:
        for u2, n2 in addresses:
            if n == n2 and u[:6] == u2[:6]:
                return True
    return False


def decision(T, ov, addresses):
    """-> (status, [buildings], reason)"""
    sign = {e: f for e, f in ov.items() if f >= 0.5 and T.b[e]["ter"] >= MIN_AREA}
    if not sign:
        sign = {e: f for e, f in ov.items() if f >= 0.2 and T.b[e]["ter"] >= MIN_AREA}
    if not sign:
        return "nincs", [], "a telekre nem esik épület"
    matching = [e for e in sign if address_matches(T, e, addresses)]
    if matching and len(matching) <= 3:
        return "auto", matching, "a telekre eső épület OSM-címe egyezik a mai címmel"
    if len(sign) == 1:
        return "auto", list(sign), "egyetlen épület esik a telekre"
    sorted_ = sorted(sign, key=lambda e: -T.b[e]["ter"])
    if T.b[sorted_[0]]["ter"] >= 3 * T.b[sorted_[1]]["ter"]:
        return "auto", [sorted_[0]], "a telekre eső épületek közül a főépület (legalább 3-szor akkora, mint a többi)"
    return "valoszinu" if matching else "bizonytalan", sorted_, "több hasonló épület esik a telekre" + (", és több is egyezik a címmel" if matching else "")


def main():
    atn = {}
    try:
        with open(S.RENAMING, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                if r.get("regi") and r.get("uj") and "|" not in r["uj"]:
                    atn[clean_street(r["regi"])] = clean_street(r["uj"])
    except FileNotFoundError:
        pass
    T = S.Map(S.geometry(), S.ADDRESSES, atn)
    geo = list(csv.DictReader(open(GEO, encoding="utf-8-sig", newline=""), delimiter=";"))
    table = list(csv.DictReader(open(TABLE, encoding="utf-8-sig", newline=""), delimiter=";"))
    building_key = lambda r: (r["kerulet"].strip(), r["cim"].strip(), lot_number_fix(r["hrsz"]))
    idx = {building_key(r): r for r in table}
    stat, report = Counter(), []
    for i, g in enumerate(geo):
        k = building_key(g)
        row = idx.get(k)
        if row is None:
            stat["nincs a kézi táblában"] += 1
            continue
        geom = (g.get("Geometria (GeoJSON)") or "").strip()
        if not geom:
            stat["nincs geometria"] += 1
            continue
        current = geo[i + ADDRESS_OFFSET]["new cím"] if i + ADDRESS_OFFSET < len(geo) else ""
        addresses = new_addresses(current)
        rings = polygons(geom)
        ov, middle = overlap(T, rings)
        state, buildings, reason = decision(T, ov, addresses)
        id_ = " | ".join(f"{e[0]} {e[1]}" for e in buildings)
        manual = (row.get("osm_azonosito") or "").strip()
        differing = ""
        if manual:
            has = {(a, int(b)) for a, b in re.findall(r"(way|relation)\s+(\d+)", manual)}
            if state == "auto" and has != set(buildings):
                differing = "a kézi döntés eltér a telek szerintitől"
            elif state != "auto" and not has & set(buildings):
                differing = "a kézi döntés nincs a telekre eső jelöltek között"
            stat["kézi döntés: " + ("eltér" if differing else "egyezik/rendben")] += 1
        elif not (row.get("megjegyzes") or "").strip():
            candidate = " | ".join(f"{e[0]} {e[1]} ({round(((T.b[e]['c'][0]-middle[0])**2+(T.b[e]['c'][1]-middle[1])**2)**.5)} m)" for e in buildings[:6])
            if state == "auto":
                row["osm_azonosito"] = id_
                row["megjegyzes"] = "automatikus (telek+cím): " + reason
                row["allapot"] = "automatikusan párosítva (telek alapján)"
                row["jeloltek"] = candidate or row.get("jeloltek", "")
            elif state in ("valoszinu", "bizonytalan"):
                row["javasolt_osm"] = f"{buildings[0][0]} {buildings[0][1]}" if state == "valoszinu" else ""
                row["jeloltek"] = candidate
                row["allapot"] = ("valószínű (telek alapján, kézi megerősítés kell)" if state == "valoszinu" else "bizonytalan, jelöltekkel (telek alapján)")
            stat["nyitott -> " + state] += 1
        else:
            stat["már megjegyzéssel lezárva"] += 1
        report.append([k[0], k[1], k[2], current[:80], state, id_, reason, differing, manual])
    # writing back the manual table (only the modified rows changed)
    b = io.StringIO(newline="")
    w = csv.DictWriter(b, fieldnames=COLUMNS, delimiter=";", lineterminator="\r\n", extrasaction="ignore")
    w.writeheader()
    w.writerows(table)
    tmp = TABLE.with_suffix(".csv.tmp")
    tmp.write_bytes(b.getvalue().encode("utf-8-sig"))
    tmp.replace(TABLE)
    with open(REPORT, "w", encoding="utf-8-sig", newline="") as f:
        w2 = csv.writer(f, delimiter=";")
        w2.writerow(["kerulet", "cim", "hrsz", "mai_cim", "dontes", "osm", "indok", "eltero", "kezi_dontes"])
        w2.writerows(report)
    for a, v in sorted(stat.items()):
        print(f"  {a}: {v}")
    print(f"Jelentés: {REPORT}")


if __name__ == "__main__":
    main()
