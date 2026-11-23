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
Run:  py ertekleltar_telek.py
"""
import csv
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

import eov
import tenyek_sarok as S
from tenyek_oeny import tisztit_utca

GEO = Path("forras/ertekleltar_cimekkel_es_geometriaval.csv")
TABLA = Path("forras/ertekleltar_kezi_parositas.csv")
JELENTES = Path("data/ertekleltar_telek_jelentes.csv")
CIM_ELTOLAS = 1          # the "new cím" in the source comes this many rows earlier than the one it belongs to
MIN_TER = 12.0           # a building smaller than this (a small shed) is not considered a candidate
OSZLOPOK = ["kerulet", "cim", "hrsz", "epites_ideje", "tervezo", "allapot", "javasolt_osm", "jeloltek", "osm_azonosito", "megjegyzes"]


HONAP = {"jan": 1, "febr": 2, "márc": 3, "ápr": 4, "máj": 5, "jún": 6, "júl": 7, "aug": 8, "szept": 9, "okt": 10, "nov": 11, "dec": 12}


def hrsz_javit(h):
    """Excel read the lot number '3/15' as a date ('márc.15'): converted back to '3/15'."""
    m = re.fullmatch(r"\s*([a-záéíóöőúüű]+)\.?\s*(\d+)\s*", h or "", flags=re.I)
    if m and m.group(1).lower() in HONAP:
        return f"{HONAP[m.group(1).lower()]}/{m.group(2)}"
    return (h or "").strip()


def pip(x, y, gyuru):
    be = False
    for (x1, y1), (x2, y2) in zip(gyuru, gyuru[1:] + gyuru[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            be = not be
    return be


def poligonok(geojson):
    j = json.loads(geojson)
    polys = j["coordinates"] if j["type"] == "MultiPolygon" else [j["coordinates"]]
    ki = []
    for p in polys:
        ll = [eov.eov_wgs84(a, b) for a, b in p[0]]
        ki.append([((lo - S.LON0) * S.KX, (la - S.LAT0) * S.KY) for la, lo in ll])
    return ki


def minta(pts, n=7):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    ki = [(min(xs) + (i + .5) * (max(xs) - min(xs)) / n, min(ys) + (j + .5) * (max(ys) - min(ys)) / n) for i in range(n) for j in range(n)]
    ki = [p for p in ki if pip(p[0], p[1], pts)]
    return ki or [(sum(xs) / len(xs), sum(ys) / len(ys))]


def atfedes(T, gyuruk):
    xs = [p[0] for g in gyuruk for p in g]
    ys = [p[1] for g in gyuruk for p in g]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    R = max(max(xs) - min(xs), max(ys) - min(ys)) / 2 + 20
    ki = {}
    for d, e in T.kozel((cx, cy), R):
        m = minta(T.b[e]["pts"])
        f = sum(1 for p in m if any(pip(p[0], p[1], g) for g in gyuruk)) / len(m)
        if f > 0:
            ki[e] = f
    return ki, (cx, cy)


def uj_cimek(szoveg):
    ki = []
    for resz in (szoveg or "").split("|"):
        m = re.search(r"ker\.,\s*(.+?)\s+(\d+)", resz.strip())
        if m:
            ki.append((tisztit_utca(m.group(1)), int(m.group(2))))
    return ki


def cim_egyezik(T, e, cimek):
    for u, n in T.b[e]["cim"]:
        for u2, n2 in cimek:
            if n == n2 and u[:6] == u2[:6]:
                return True
    return False


def dontes(T, ov, cimek):
    """-> (status, [buildings], reason)"""
    jel = {e: f for e, f in ov.items() if f >= 0.5 and T.b[e]["ter"] >= MIN_TER}
    if not jel:
        jel = {e: f for e, f in ov.items() if f >= 0.2 and T.b[e]["ter"] >= MIN_TER}
    if not jel:
        return "nincs", [], "a telekre nem esik épület"
    egyezo = [e for e in jel if cim_egyezik(T, e, cimek)]
    if egyezo and len(egyezo) <= 3:
        return "auto", egyezo, "a telekre eső épület OSM-címe egyezik a mai címmel"
    if len(jel) == 1:
        return "auto", list(jel), "egyetlen épület esik a telekre"
    rendezve = sorted(jel, key=lambda e: -T.b[e]["ter"])
    if T.b[rendezve[0]]["ter"] >= 3 * T.b[rendezve[1]]["ter"]:
        return "auto", [rendezve[0]], "a telekre eső épületek közül a főépület (legalább 3-szor akkora, mint a többi)"
    return "valoszinu" if egyezo else "bizonytalan", rendezve, "több hasonló épület esik a telekre" + (", és több is egyezik a címmel" if egyezo else "")


def main():
    atn = {}
    try:
        with open(S.ATNEVEZES, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                if r.get("regi") and r.get("uj") and "|" not in r["uj"]:
                    atn[tisztit_utca(r["regi"])] = tisztit_utca(r["uj"])
    except FileNotFoundError:
        pass
    T = S.Terkep(S.geometria(), S.CIMEK, atn)
    geo = list(csv.DictReader(open(GEO, encoding="utf-8-sig", newline=""), delimiter=";"))
    tabla = list(csv.DictReader(open(TABLA, encoding="utf-8-sig", newline=""), delimiter=";"))
    kulcs = lambda r: (r["kerulet"].strip(), r["cim"].strip(), hrsz_javit(r["hrsz"]))
    idx = {kulcs(r): r for r in tabla}
    stat, jelentes = Counter(), []
    for i, g in enumerate(geo):
        k = kulcs(g)
        sor = idx.get(k)
        if sor is None:
            stat["nincs a kézi táblában"] += 1
            continue
        geom = (g.get("Geometria (GeoJSON)") or "").strip()
        if not geom:
            stat["nincs geometria"] += 1
            continue
        mai = geo[i + CIM_ELTOLAS]["new cím"] if i + CIM_ELTOLAS < len(geo) else ""
        cimek = uj_cimek(mai)
        gyuruk = poligonok(geom)
        ov, kozep = atfedes(T, gyuruk)
        allapot, epuletek, indok = dontes(T, ov, cimek)
        azon = " | ".join(f"{e[0]} {e[1]}" for e in epuletek)
        kezi = (sor.get("osm_azonosito") or "").strip()
        eltero = ""
        if kezi:
            van = {(a, int(b)) for a, b in re.findall(r"(way|relation)\s+(\d+)", kezi)}
            if allapot == "auto" and van != set(epuletek):
                eltero = "a kézi döntés eltér a telek szerintitől"
            elif allapot != "auto" and not van & set(epuletek):
                eltero = "a kézi döntés nincs a telekre eső jelöltek között"
            stat["kézi döntés: " + ("eltér" if eltero else "egyezik/rendben")] += 1
        elif not (sor.get("megjegyzes") or "").strip():
            jelolt = " | ".join(f"{e[0]} {e[1]} ({round(((T.b[e]['c'][0]-kozep[0])**2+(T.b[e]['c'][1]-kozep[1])**2)**.5)} m)" for e in epuletek[:6])
            if allapot == "auto":
                sor["osm_azonosito"] = azon
                sor["megjegyzes"] = "automatikus (telek+cím): " + indok
                sor["allapot"] = "automatikusan párosítva (telek alapján)"
                sor["jeloltek"] = jelolt or sor.get("jeloltek", "")
            elif allapot in ("valoszinu", "bizonytalan"):
                sor["javasolt_osm"] = f"{epuletek[0][0]} {epuletek[0][1]}" if allapot == "valoszinu" else ""
                sor["jeloltek"] = jelolt
                sor["allapot"] = ("valószínű (telek alapján, kézi megerősítés kell)" if allapot == "valoszinu" else "bizonytalan, jelöltekkel (telek alapján)")
            stat["nyitott -> " + allapot] += 1
        else:
            stat["már megjegyzéssel lezárva"] += 1
        jelentes.append([k[0], k[1], k[2], mai[:80], allapot, azon, indok, eltero, kezi])
    # writing back the manual table (only the modified rows changed)
    b = io.StringIO(newline="")
    w = csv.DictWriter(b, fieldnames=OSZLOPOK, delimiter=";", lineterminator="\r\n", extrasaction="ignore")
    w.writeheader()
    w.writerows(tabla)
    tmp = TABLA.with_suffix(".csv.tmp")
    tmp.write_bytes(b.getvalue().encode("utf-8-sig"))
    tmp.replace(TABLA)
    with open(JELENTES, "w", encoding="utf-8-sig", newline="") as f:
        w2 = csv.writer(f, delimiter=";")
        w2.writerow(["kerulet", "cim", "hrsz", "mai_cim", "dontes", "osm", "indok", "eltero", "kezi_dontes"])
        w2.writerows(jelentes)
    for a, v in sorted(stat.items()):
        print(f"  {a}: {v}")
    print(f"Jelentés: {JELENTES}")


if __name__ == "__main__":
    main()
