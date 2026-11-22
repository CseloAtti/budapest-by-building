#!/usr/bin/env python3
"""Egymásra rajzolt (duplikált) épületgeometriák keresése az egész városban.

Futtatás:  py duplikatok_kereso.py [varos]

Amit talál, azt a forras/duplikatumok.csv végére FŰZI (meglévő sort soha nem ír át, nem töröl):
  mod=gyuru  – ugyanannak az OSM-elemnek egy körvonala egy másik körvonalán belül van (azonos id) → a belső körvonal törlődik,
               adat nem vész el (ugyanaz az elem).
  mod=elem   – két különböző OSM-elem fedi egymást: a törölt elem tényei (Legenda, Wikipédia, Budapest100, OENY …) átkerülnek a
               megtartottra, az OSM-tulajdonságai közül az hiányzik a megtartotton, azt átveszi.
  alkalmaz   – 'igen': az osszeepit.py alkalmazza; üres: csak jelölt, a térképen marad (te döntesz, írd át 'igen'-re).
Tiszta Python, nem kell hozzá semmi telepítés."""
import csv, json, math, sys
from collections import defaultdict
from pathlib import Path

varos = sys.argv[1] if len(sys.argv) > 1 else "varos"
OSM = Path("data") / varos / "epuletek.geojson"
KIZART = Path("forras/kizart_epuletek.csv")
KIMENET = Path("forras/duplikatumok.csv")
OSZLOPOK = ["mod", "torolt_tipus", "torolt_id", "torolt_gyuru_pontok", "megtartott_tipus", "megtartott_id", "alkalmaz", "megjegyzes"]
KX = 111000 * math.cos(math.radians(47.5)); KY = 111000
AUTO_ARANY = 0.85      # kisebb/nagyobb terület ennél több → ugyanaz az épület kétszer
LEFEDES = 0.90         # a kisebb pontjainak ennyied része a nagyobb tömör részén belül


def ter(r):
    return abs(sum(r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1] for i in range(len(r) - 1))) / 2


def benne(x, y, r):
    be = False
    j = len(r) - 1
    for i in range(len(r)):
        xi, yi = r[i]; xj, yj = r[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            be = not be
        j = i
    return be


def tomor(f, x, y):
    if not benne(x, y, f["gy"][0]):
        return False
    return not any(benne(x, y, h) for h in f["gy"][1:])


def main():
    kiz = set()
    if KIZART.exists():
        for r in csv.DictReader(open(KIZART, encoding="utf-8-sig", newline=""), delimiter=";"):
            if (r.get("id") or "").strip().isdigit():
                kiz.add(((r.get("osm_tipus") or "way").strip(), int(r["id"])))
    F = []
    for ft in json.load(open(OSM, encoding="utf-8"))["features"]:
        p = ft["properties"]
        if p.get("tipus") == "roof" or p.get("resz"):
            continue
        k = (p.get("osm_tipus") or "way", int(p["id"]))
        if k in kiz:
            continue
        gy = [[(x * KX, y * KY) for x, y in r] for r in ft["geometry"]["coordinates"]]
        xs = [a for a, _ in gy[0]]; ys = [b for _, b in gy[0]]
        o = ter(gy[0]) - sum(ter(h) for h in gy[1:])
        F.append(dict(i=len(F), k=k, p=p, gy=gy, ar=o, bb=(min(xs), max(xs), min(ys), max(ys))))
    print(f"{len(F)} épület-körvonal vizsgálata …")
    CELL = 60.0
    racs = defaultdict(list)
    for f in F:
        a, b, c, d = f["bb"]
        for i in range(int(a // CELL), int(b // CELL) + 1):
            for j in range(int(c // CELL), int(d // CELL) + 1):
                racs[(i, j)].append(f["i"])
    jeloltek = set()
    for v in racs.values():
        for x in range(len(v)):
            for y in range(x + 1, len(v)):
                jeloltek.add((v[x], v[y]))
    talalt = []
    for a, b in jeloltek:
        A, B = F[a], F[b]
        ba, bb = A["bb"], B["bb"]
        if min(ba[1], bb[1]) - max(ba[0], bb[0]) <= 0 or min(ba[3], bb[3]) - max(ba[2], bb[2]) <= 0:
            continue
        kis, nagy = (A, B) if A["ar"] <= B["ar"] else (B, A)
        if kis["ar"] < 4:
            continue
        sb = kis["bb"]
        lep = max(1.0, math.sqrt(kis["ar"]) / 14)
        pontok = []
        x = sb[0] + lep / 2
        while x < sb[1]:
            y = sb[2] + lep / 2
            while y < sb[3]:
                if tomor(kis, x, y):
                    pontok.append((x, y))
                y += lep
            x += lep
        if len(pontok) < 3:
            continue
        arany = sum(1 for x, y in pontok if tomor(nagy, x, y)) / len(pontok)
        if arany >= 0.5:
            talalt.append((arany, kis, nagy))

    def pontja(f):
        return len(f["gy"][0])

    def pontossag(p):
        return sum(1 for m in ("nev", "wikidata", "commons") if p.get(m)) + (0 if p.get("tipus") in (None, "yes") else 0.5)

    sorok = []
    for arany, kis, nagy in sorted(talalt, key=lambda t: -t[0]):
        hasonlo = kis["ar"] / nagy["ar"]
        if kis["k"] == nagy["k"]:
            if arany >= LEFEDES:
                sorok.append(dict(mod="gyuru", torolt_tipus=kis["k"][0], torolt_id=kis["k"][1], torolt_gyuru_pontok=pontja(kis),
                                  megtartott_tipus=nagy["k"][0], megtartott_id=nagy["k"][1], alkalmaz="igen",
                                  megjegyzes=f"azonos elem egymásba ágyazott körvonala ({kis['ar']:.0f} m² a {nagy['ar']:.0f} m²-ben)"))
            continue
        auto = arany >= LEFEDES and hasonlo >= AUTO_ARANY
        t, m = (kis, nagy)
        if auto and pontossag(kis["p"]) > pontossag(nagy["p"]):
            t, m = nagy, kis       # a gazdagabb adatú maradjon
        sorok.append(dict(mod="elem", torolt_tipus=t["k"][0], torolt_id=t["k"][1], torolt_gyuru_pontok="",
                          megtartott_tipus=m["k"][0], megtartott_id=m["k"][1], alkalmaz="igen" if auto else "",
                          megjegyzes=("azonos alakú, kétszer berajzolva" if auto else
                                      f"kisebb ({kis['ar']:.0f} m²) teljesen a nagyobbon belül ({nagy['ar']:.0f} m²) – ellenőrizendő: ha tényleg külön épület, hagyd üresen")
                                     + f"; {t['p'].get('tipus')}→{m['p'].get('tipus')}"))
    letezo = set()
    if KIMENET.exists():
        for r in csv.DictReader(open(KIMENET, encoding="utf-8-sig", newline=""), delimiter=";"):
            letezo.add((r["mod"], r["torolt_tipus"], str(r["torolt_id"]), str(r.get("torolt_gyuru_pontok") or "")))
    uj = [r for r in sorok if (r["mod"], r["torolt_tipus"], str(r["torolt_id"]), str(r["torolt_gyuru_pontok"])) not in letezo]
    if uj:
        van = KIMENET.exists()
        with open(KIMENET, "a", encoding="utf-8-sig" if not van else "utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=OSZLOPOK, delimiter=";")
            if not van:
                w.writeheader()
            w.writerows(uj)
    print(f"Talált átfedés: {len(sorok)}; új sor a {KIMENET}-ben: {len(uj)} (ebből 'igen': {sum(1 for r in uj if r['alkalmaz'] == 'igen')})")


main()
