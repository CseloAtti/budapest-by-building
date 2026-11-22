"""Építészfórum térkép (epiteszforum.hu/terkep) kortárs épületei -> data/tenyek/epforum.csv

Bemenet:  data/epforum/budapesti_kortars_epuletek_lista.csv   (ID, név, cím, építészek, év, funkció, lat, lon)
          data/varos/epuletek.geojson                          (py varos_osszeallitas.py)
Kimenet:  data/tenyek/epforum.csv            - 'ev' és 'tervezo' tények az osszeepit.py-hoz (forrás: 'epforum')
          data/epforum_nem_parositott.csv    - amit nem sikerült épülethez kötni

Futtatás:  py tenyek_epforum.py

Csak tényeket veszünk át (építész, év, azonosító); a leírásokat és a képeket nem. A listában szereplő év a kortárs
épület elkészültének éve. Az "Örökség" (felújított műemlékek), a "Köztér", az "Emlékhely" és az "Infrastruktúra"
kategóriát nem használjuk: ott az év felújítást jelent, az alkotó nem az eredeti tervező, vagy nem épület.
Az épületet a megadott koordináta alapján keressük: azt az OSM-épületet választjuk, amelynek alapterületén belül van
a pont; ha egyik sem, a legközelebbit 12 m-en belül.
"""
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import re
import unicodedata

from kozos import poligonok, tenyek_irasa

LISTA = "data/epforum/budapesti_kortars_epuletek_lista.csv"
EPULETEK = "data/varos/epuletek.geojson"
KIMENET = "data/tenyek/epforum.csv"
NEM_PAROSITOTT = "data/epforum_nem_parositott.csv"
KEZI_PAROSITAS = "forras/epforum_kezi_parositas.csv"   # a nem párosított tételekhez te írod be az OSM-azonosítót (osm_azonosito oszlop)
CIMEK = "data/varos/osm_cimek.csv"      # tartalék: ha a koordinátán nincs épület, a cím alapján keressük
CIKKEK = "data/epforum/cikkek.csv"     # tenyek_epforum_cikkek.py: a térképpont cikkei (a pontra kattintva az Építészfórum választóoldalt ad, ezért a cikkeket külön gyűjtjük)
MAX_CIKK = 4


def cikkek_beolvasasa():
    ki = {}
    if Path(CIKKEK).exists():
        for r in csv.DictReader(open(CIKKEK, encoding="utf-8-sig", newline=""), delimiter=";"):
            if (r.get("url") or "").startswith("https://epiteszforum.hu/"):
                ki.setdefault(r["id"], []).append(r["url"])
    return {k: "|".join(v[:MAX_CIKK]) for k, v in ki.items()}


CIKK_URL = cikkek_beolvasasa()
KIHAGYOTT_FUNKCIO = {"örökség", "köztér", "emlékhely", "infrastruktúra"}
MAX_TAV_M = 12.0
CELLA = 0.002          # fok (~150-220 m)
FOK_M_LAT = 111000.0
FOK_M_LON = 111000.0 * math.cos(math.radians(47.5))


def gyuruben(x, y, gyuru):
    bent = False
    for (x1, y1), (x2, y2) in zip(gyuru, gyuru[1:]):
        if (y1 > y) != (y2 > y):
            if x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                bent = not bent
    return bent


def szakasz_tav(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    h = dx * dx + dy * dy
    t = 0.0 if h == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / h))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def terulet_m2(gyuru):
    s = 0.0
    for (x1, y1), (x2, y2) in zip(gyuru, gyuru[1:]):
        s += (x1 * FOK_M_LON) * (y2 * FOK_M_LAT) - (x2 * FOK_M_LON) * (y1 * FOK_M_LAT)
    return abs(s) / 2


def egyszeru(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", "".join(c for c in s if unicodedata.category(c) != "Mn")).strip()


def cim_kulcs(cim):
    """'Budapest, 1117, Buda-part tér 2.' -> ('buda part ter', '2')"""
    m = re.match(r"Budapest,\s*\d{4},\s*(.+?)\s+(\d+[A-Za-z]?)(?:\s*[-–/]\s*\d+[A-Za-z]?)?\.?$", (cim or "").strip())
    return (egyszeru(m.group(1)), egyszeru(m.group(2))) if m else None


def cim_index():
    idx = defaultdict(set)
    try:
        with open(CIMEK, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f, delimiter=";"):
                idx[(egyszeru(r["utca"]), egyszeru(r["hazszam"]))].add((r["osm_tipus"], int(r["id"])))
    except FileNotFoundError:
        print(f"Figyelem: nincs {CIMEK}, a cím alapú tartalék nem működik (py varos_osszeallitas.py).")
    return idx


def main():
    sorok = list(csv.DictReader(open(LISTA, encoding="utf-8-sig"), delimiter=";"))
    cimek = cim_index()
    cimhasznalat = defaultdict(int)         # hány lista-bejegyzés mutat ugyanarra a címre (pl. BudaPart: Buda-part tér 2.)
    for r in sorok:
        k = cim_kulcs(r["Cím"])
        if k:
            cimhasznalat[k] += 1
    racs = defaultdict(list)
    with open(EPULETEK, encoding="utf-8") as f:
        for ft in json.load(f)["features"]:
            pr = ft["properties"]
            for poly in poligonok(ft["geometry"]):
                kulso = poly[0]
                xs = [c[0] for c in kulso]
                ys = [c[1] for c in kulso]
                rec = (pr["osm_tipus"], int(pr["id"]), poly, terulet_m2(kulso))
                for i in range(int((min(xs) - 0.0002) // CELLA), int((max(xs) + 0.0002) // CELLA) + 1):
                    for j in range(int((min(ys) - 0.0002) // CELLA), int((max(ys) + 0.0002) // CELLA) + 1):
                        racs[(i, j)].append(rec)
    kesz, kimaradt = set(), []
    stat = defaultdict(int)
    # A kézi párosítású tételeknél (osm_azonosito ki van töltve) az automatikus párosítás év/tervező tényei elmaradnak,
    # a cikk-linkek közül pedig azok, amelyeket a kézi sor 'cikk_url' oszlopa megnevez (üres oszlop = mind), átkerülnek az új épületre.
    kezi_athelyez = {}
    if Path(KEZI_PAROSITAS).exists():
        for kr in csv.DictReader(open(KEZI_PAROSITAS, encoding="utf-8-sig"), delimiter=";"):
            if re.search(r"\d{3,}", kr.get("osm_azonosito") or "") and (kr.get("epforum_id") or "").strip():
                kezi_athelyez[kr["epforum_id"].strip()] = {u.strip() for u in re.split(r"[|\s]+", kr.get("cikk_url") or "") if u.strip()}
    for r in sorok:
        funkcio = (r["Funkció"] or "").strip()
        if funkcio.lower() in KIHAGYOTT_FUNKCIO:
            stat["kihagyott kategória"] += 1
            continue
        if not r["Cím"].startswith("Budapest"):
            stat["nem budapesti"] += 1
            continue
        try:
            lat, lon = float(r["Lat"]), float(r["Lon"])
        except ValueError:
            kimaradt.append([r["ID"], r["Épület neve"], r["Cím"], "nincs koordináta"])
            continue
        cell = (int(lon // CELLA), int(lat // CELLA))
        jel = racs.get(cell, [])
        bent = [(t, i, a) for t, i, poly, a in jel if gyuruben(lon, lat, poly[0]) and not any(gyuruben(lon, lat, h) for h in poly[1:])]
        mod = "alapterületen belül"
        if not bent:
            legjobb = None
            for t, i, poly, a in jel:
                d = min(szakasz_tav((lon) * FOK_M_LON, (lat) * FOK_M_LAT, x1 * FOK_M_LON, y1 * FOK_M_LAT, x2 * FOK_M_LON, y2 * FOK_M_LAT)
                        for (x1, y1), (x2, y2) in zip(poly[0], poly[0][1:]))
                if d <= MAX_TAV_M and (legjobb is None or d < legjobb[0]):
                    legjobb = (d, t, i, a)
            if legjobb:
                bent = [(legjobb[1], legjobb[2], legjobb[3])]
                mod = f"{legjobb[0]:.0f} m-re a ponttól"
        if not bent:
            # tartalék: cím alapján, de csak ha pontosan egy OSM-épületen van az a cím, és a listában is csak egy bejegyzés
            # mutat rá (egy nagy telepnél, pl. BudaPart, ugyanaz a cím sok épület: azt nem találgatjuk)
            k = cim_kulcs(r["Cím"])
            talalat = cimek.get(k, set()) if k else set()
            if len(talalat) == 1 and cimhasznalat[k] == 1:
                t0, i0 = next(iter(talalat))
                bent = [(t0, i0, 0.0)]
                mod = "a cím alapján (a koordinátán nem volt épület)"
                stat["cím alapján"] += 1
        if not bent:
            kimaradt.append([r["ID"], r["Épület neve"], r["Cím"], "a koordinátán nincs OSM-épület, a cím sem egyértelmű"])
            stat["nincs épület"] += 1
            continue
        # több épület: a legkisebb alapterületű (a legszűkebb tartalmazó)
        t, i, _ = min(bent, key=lambda b: b[2])
        stat["párosítva"] += 1
        megj = f"Építészfórum térkép, ID {r['ID']}, {funkcio}; {mod}"
        athelyezett = kezi_athelyez.get(r["ID"])
        if athelyezett is None:
            if r["Évtized"].isdigit():
                kesz.add((t, i, "ev", int(r["Évtized"]), "epforum", megj + " (az elkészülés éve)"))
            if r["Építészek"].strip():
                kesz.add((t, i, "tervezo", r["Építészek"].strip(), "epforum", megj))
        urlek = [u for u in (CIKK_URL.get(r["ID"]) or "").split("|") if u and not (athelyezett is not None and (not athelyezett or u in athelyezett))]
        if urlek:
            kesz.add((t, i, "epforum_url", "|".join(urlek), "epforum", megj))
    # kézi párosítás: forras/epforum_kezi_parositas.csv; az osm_azonosito oszlopba egy vagy több elem (| vagy ; közt),
    # pl. "way 1127749031", "1127749031" (way), "relation 123" vagy az OSM-oldal linkje. Az év és a tervező a táblából jön.
    kezi_kesz = set()
    if Path(KEZI_PAROSITAS).exists():
        for r in csv.DictReader(open(KEZI_PAROSITAS, encoding="utf-8-sig"), delimiter=";"):
            azok = []
            for resz in re.split(r"[|;,\n]+", r.get("osm_azonosito") or ""):
                m = re.search(r"(?:(way|relation|node)[/ :]*)?(\d{3,})", resz.strip(), flags=re.I)
                if m:
                    azok.append(((m.group(1) or "way").lower(), int(m.group(2))))
            if not azok:
                continue
            megj = f"Építészfórum térkép, ID {r['epforum_id']}, {r.get('funkcio', '')}; kézi párosítás ({KEZI_PAROSITAS})"
            ev = (r.get("ev") or "").strip()
            for t, i in azok:
                if ev.isdigit():
                    kezi_kesz.add((t, i, "ev", int(ev), "epforum", megj + " (az elkészülés éve)"))
                if (r.get("epitesz") or "").strip():
                    kezi_kesz.add((t, i, "tervezo", r["epitesz"].strip(), "epforum", megj))
                kezi_url = "|".join(u for u in (CIKK_URL.get((r.get("epforum_id") or "").strip()) or "").split("|")
                                    if u and (not (r.get("cikk_url") or "").strip() or u in (r.get("cikk_url") or "")))
                if kezi_url:
                    kezi_kesz.add((t, i, "epforum_url", kezi_url, "epforum", megj))
            kimaradt = [k for k in kimaradt if str(k[0]) != str(r["epforum_id"])]
            stat["kézi párosítás"] += 1
    kesz |= kezi_kesz
    tenyek_irasa(KIMENET, sorted(kesz, key=lambda s: (s[0], s[1], s[2])))
    with open(NEM_PAROSITOTT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["id", "nev", "cim", "miert"])
        w.writerows(kimaradt)
    print(f"Bejegyzés: {len(sorok)}; párosítva: {stat['párosítva']}; nem párosított: {len(kimaradt)}; "
          f"ebből cím alapján: {stat['cím alapján']}; kézi párosítás: {stat['kézi párosítás']}; kihagyott kategória: {stat['kihagyott kategória']}; nem budapesti: {stat['nem budapesti']}")
    print(f"Tények: {len(kesz)} sor -> {KIMENET}; nem párosított lista: {NEM_PAROSITOTT}")


if __name__ == "__main__":
    main()
