"""
zonak_epuletbol.py - computes a candidate boundary from the buildings for the HOUSING ESTATES not found by zonak_osm_jeloltek.py.

Run (in the project folder, after zonak_osm_jeloltek.py):
    py zonak_epuletbol.py

Method (for every missing housing estate):
  1. From the estate's name it forms a street name ("Gyakorló utcai lakótelep" -> Gyakorló...), and finds the buildings of 4+ storeys
     (or of 'apartments' type) whose address is on such a street, in the zone's district. These are the seeds.
  2. From the seeds it grows a connected patch of large buildings (neighbours within 70 m), within a radius estimated from the number of dwellings.
  3. Around the patch it draws a convex hull (+12 m); this is the candidate boundary.
Where the estate's name is not a street name (e.g. Békásmegyeri, Újhegyi, Havanna), there is no seed: those must be drawn by hand
(or the OSM search found them).

Output:
    data/zonak_jeloltek_epuletbol.geojson   the computed hulls (match = 'epuletbol')
    data/zonak_jeloltek_epuletbol.csv       per zone: seeds, the patch's building count, area (ha), remark
    data/zonak_hianyzo_vegso.csv            what is still missing even so
The hull is a rough candidate: it may extend to neighbouring large buildings. Fix it in the zone drawer.
"""
import csv
import json
import math
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

ADAT = Path("data")
VAROS = ADAT / "varos"
ROMAI = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12,
         "XIII": 13, "XIV": 14, "XV": 15, "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20, "XXI": 21,
         "XXII": 22, "XXIII": 23}
SZOMSZED_M = 70.0
BUROK_M = 12.0
MIN_SZINT = 4


def egyszerusit(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return "".join(c for c in s if c.isalnum())


def szint_szam(v):
    try:
        return int(float(str(v).replace(",", ".").split(";")[0]))
    except (TypeError, ValueError):
        return None


def vetit(lon, lat):
    return ((lon - 19.05) * math.cos(math.radians(47.5)) * 111320.0, (lat - 47.5) * 110574.0)


def vissza(x, y):
    return (x / (math.cos(math.radians(47.5)) * 111320.0) + 19.05, y / 110574.0 + 47.5)


def konvex_burok(pontok):
    pontok = sorted(set(pontok))
    if len(pontok) < 3:
        return pontok

    def kereszt(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    also = []
    for p in pontok:
        while len(also) >= 2 and kereszt(also[-2], also[-1], p) <= 0:
            also.pop()
        also.append(p)
    felso = []
    for p in reversed(pontok):
        while len(felso) >= 2 and kereszt(felso[-2], felso[-1], p) <= 0:
            felso.pop()
        felso.append(p)
    return also[:-1] + felso[:-1]


def terulet(gyuru):
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(gyuru, gyuru[1:] + gyuru[:1]))) / 2


def utcanev_toredekek(nev):
    """'Bécsi–Bojtár utcai lakótelep' -> ['becsi', 'bojtar']; it drops the words 'lakótelep' (housing estate), 'utcai', 'úti', 'téri'."""
    nev = re.sub(r"\(.*?\)", " ", nev)
    nev = re.sub(r"\b\d+\.?\s*(ütem|ph)\b.*", " ", nev, flags=re.I)
    nev = re.sub(r"(lakótelep|rekonstrukciós|kibővített|városközpont)", " ", nev, flags=re.I)
    nev = re.sub(r"\b(utcai|úti|téri|körúti|utca|út|tér|krt|kisérleti)\b", " ", nev, flags=re.I)
    reszek = [r for r in re.split(r"[–\-\s]+", nev) if r]
    ki = [egyszerusit(r) for r in reszek if len(egyszerusit(r)) >= 4]
    return ki


def epuletek_beolvasasa():
    g = json.load(open(VAROS / "epuletek_vegleges.geojson", encoding="utf-8"))
    ki = []
    for f in g["features"]:
        p = f["properties"]
        if p.get("resz"):
            continue
        geo = f["geometry"]
        if geo["type"] == "Polygon":
            gyuru = geo["coordinates"][0]
        elif geo["type"] == "MultiPolygon":
            gyuru = geo["coordinates"][0][0]
        else:
            continue
        pts = [vetit(x, y) for x, y in gyuru]
        a = terulet(pts)
        sz = szint_szam(p.get("szintek"))
        nagy = (sz is not None and sz >= MIN_SZINT) or (p.get("tipus") == "apartments" and a >= 400)
        cx = sum(x for x, _ in pts) / len(pts)
        cy = sum(y for _, y in pts) / len(pts)
        kerulet = p.get("kerulet")
        try:
            kerulet = int(kerulet)
        except (TypeError, ValueError):
            kerulet = None
        ki.append({"kulcs": (p.get("osm_tipus") or "way", str(p["id"])), "x": cx, "y": cy, "pts": pts,
                   "nagy": nagy, "kerulet": kerulet, "terulet": a})
    return ki


def cimek_beolvasasa():
    ki = {}
    ut = VAROS / "osm_cimek.csv"
    if ut.exists():
        for r in csv.DictReader(open(ut, encoding="utf-8-sig"), delimiter=";"):
            ki.setdefault((r["osm_tipus"], str(r["id"])), egyszerusit(r["utca"]))
    return ki


def lakasszam(megj):
    m = re.search(r"(\d+)\s*lakás", megj or "")
    return int(m.group(1)) if m else None


def main():
    hiany_ut = ADAT / "zonak_hianyzo.csv"
    if not hiany_ut.exists():
        sys.exit("Nincs data/zonak_hianyzo.csv - előbb futtasd a zonak_osm_jeloltek.py-t.")
    hianyzok = list(csv.DictReader(open(hiany_ut, encoding="utf-8-sig"), delimiter=";"))
    lista = {r["id"]: r for r in csv.DictReader(open("forras/zona_lista.csv", encoding="utf-8-sig"), delimiter=";")}
    epuletek = epuletek_beolvasasa()
    cimek = cimek_beolvasasa()
    print("épület:", len(epuletek), "| nagy (4+ szint):", sum(e["nagy"] for e in epuletek), "| cím:", len(cimek))
    for e in epuletek:
        e["utca"] = cimek.get(e["kulcs"], "")
    nagyok = [e for e in epuletek if e["nagy"]]
    racs = defaultdict(list)
    for i, e in enumerate(nagyok):
        racs[(int(e["x"] // SZOMSZED_M), int(e["y"] // SZOMSZED_M))].append(i)

    jellemzok, sorok, maradt = [], [], []
    for h in hianyzok:
        zid = h["id"]
        z = lista.get(zid)
        if not z or not zid.startswith("lt_"):
            maradt.append([zid, h["nev"], h["kerulet"], "nem lakótelep (kézzel)"])
            continue
        ker = ROMAI.get(z["kerulet"].split("–")[0].strip())
        toredekek = utcanev_toredekek(z["nev"])
        if not toredekek:
            maradt.append([zid, h["nev"], h["kerulet"], "a név nem utcanév"])
            continue
        magok = [i for i, e in enumerate(nagyok)
                 if (ker is None or e["kerulet"] == ker) and any(e["utca"].startswith(t) for t in toredekek)]
        if not magok:
            maradt.append([zid, h["nev"], h["kerulet"], "nincs mag (%s)" % ",".join(toredekek)])
            continue
        xs = sorted(nagyok[i]["x"] for i in magok)
        ys = sorted(nagyok[i]["y"] for i in magok)
        kx, ky = xs[len(xs) // 2], ys[len(ys) // 2]
        db = lakasszam(z["megjegyzes"])
        sugar = 150 + 9 * math.sqrt(db) if db else 400.0
        # of the seeds only those near the median (the far end of a long street should not be taken)
        magok = [i for i in magok if math.hypot(nagyok[i]["x"] - kx, nagyok[i]["y"] - ky) <= sugar * 1.2]
        if not magok:
            maradt.append([zid, h["nev"], h["kerulet"], "a magok szétszórtak"])
            continue
        lattam = set(magok)
        sor = list(magok)
        while sor:
            i = sor.pop()
            e = nagyok[i]
            cx, cy = int(e["x"] // SZOMSZED_M), int(e["y"] // SZOMSZED_M)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for j in racs.get((cx + dx, cy + dy), ()):
                        if j in lattam:
                            continue
                        f = nagyok[j]
                        if (ker is not None and f["kerulet"] != ker):
                            continue
                        if math.hypot(f["x"] - e["x"], f["y"] - e["y"]) > SZOMSZED_M:
                            continue
                        if math.hypot(f["x"] - kx, f["y"] - ky) > sugar:
                            continue
                        lattam.add(j)
                        sor.append(j)
        pontok = []
        for i in lattam:
            for (x, y) in nagyok[i]["pts"]:
                for k in range(8):
                    a = k * math.pi / 4
                    pontok.append((round(x + BUROK_M * math.cos(a), 1), round(y + BUROK_M * math.sin(a), 1)))
        burok = konvex_burok(pontok)
        if len(burok) < 3:
            maradt.append([zid, h["nev"], h["kerulet"], "túl kevés épület"])
            continue
        ha = terulet(burok) / 10000
        koord = [list(vissza(x, y)) for x, y in burok]
        koord.append(koord[0])
        jellemzok.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [koord]}, "properties": {
            "id": zid, "nev": z["nev"], "tipus": z["tipus"], "kerulet": z["kerulet"],
            "ev_tol": int(z["ev_tol"]), "ev_ig": int(z["ev_ig"]), "allapot": z["allapot"],
            "forras": z["forras"], "egyezes": "epuletbol", "osm": "", "osm_nev": "",
            "mag_db": len(magok), "folt_db": len(lattam), "terulet_ha": round(ha, 1)}})
        sorok.append([zid, z["nev"], z["kerulet"], len(magok), len(lattam), round(ha, 1), z["megjegyzes"]])

    json.dump({"type": "FeatureCollection", "features": jellemzok},
              open(ADAT / "zonak_jeloltek_epuletbol.geojson", "w", encoding="utf-8"), ensure_ascii=False)
    with open(ADAT / "zonak_jeloltek_epuletbol.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["id", "nev", "kerulet", "mag_db", "folt_db", "terulet_ha", "megjegyzes"])
        w.writerows(sorok)
    with open(ADAT / "zonak_hianyzo_vegso.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["id", "nev", "kerulet", "ok"])
        w.writerows(maradt)
    print("Épületből számolt burok: %d | még hiányzik: %d" % (len(jellemzok), len(maradt)))
    from collections import Counter
    for ok, n in Counter(m[3].split(" (")[0] for m in maradt).most_common():
        print("   hiány oka: %-28s %d" % (ok, n))


if __name__ == "__main__":
    main()
