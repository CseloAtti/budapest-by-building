"""
budapest_letoltes.py - Budapest teljes épületállományának és a Commons-fotók helyadatainak letöltése.
Felügyelet nélkül futtatható, és megszakítás után folytatható.

Futtatás (a projekt mappájában):   py budapest_letoltes.py

Három lépést végez, sorban (a kész lépéseket kihagyja, a félbemaradtat onnan folytatja):
  1. A városhatár letöltése (OSM)                      -> data/budapest_hatar.json
  2. Az épületek, épületrészek és címpontok letöltése  -> data/budapest_nyers/*.json.gz (kb. 1 km-es cellánként)
  3. A Commons helyadatos fájljainak keresése          -> data/cache/commons_geo_budapest.json
A napló a data/budapest_letoltes_naplo.txt fájlban van. Ha a program hibával megáll vagy a gép újraindul,
egyszerűen indítsd újra ugyanazzal a paranccsal.

Fontos: a gép ne aludjon el közben! A program Windowson maga kéri, hogy ne aludjon el, amíg fut, de a képernyő
kikapcsolhat. Az Overpass-szervereket kíméletesen használja (két kérés között szünet, hiba esetén várakozás).
Csak a Python alap könyvtárát használja.
"""
import gzip
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ADAT = Path("data")
NYERS = ADAT / "budapest_nyers"
HATAR = ADAT / "budapest_hatar.json"
NAPLO = ADAT / "budapest_letoltes_naplo.txt"
SZERVEREK = ["https://overpass.kumi.systems/api/interpreter",
             "https://overpass.private.coffee/api/interpreter",
             "https://overpass-api.de/api/interpreter"]
UA = {"User-Agent": "budapest-by-building/0.1 (https://github.com/CseloAtti/budapest-by-building; oktatasi projekt)"}
CELLA_LAT = 0.01          # kb. 1,1 km
CELLA_LON = 0.015         # kb. 1,1 km
SZUNET = 4.0              # s, két Overpass-kérés között
MAX_MELYSEG = 2           # ha egy cella túl nagy, legfeljebb ennyiszer bontjuk negyedekre


def naplo(uzenet):
    sor = time.strftime("%Y-%m-%d %H:%M:%S ") + str(uzenet)
    print(sor, flush=True)
    NAPLO.parent.mkdir(exist_ok=True)
    with open(NAPLO, "a", encoding="utf-8") as f:
        f.write(sor + "\n")


def ne_aludjon():
    """Windowson: amíg a program fut, a gép ne kapcsoljon alvó állapotba."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)    # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        except Exception:
            pass


# ---------- Overpass ----------
def overpass(lekerdezes, idokorlat=240):
    """Egy Overpass-lekérdezés. Visszaadja az elemeket; None, ha a szerver túl nagynak találta (remark/időkorlát);
    kivételt dob, ha egyik szerver sem válaszol."""
    adat = urllib.parse.urlencode({"data": lekerdezes}).encode("utf-8")
    for kor in range(4):
        for szerver in SZERVEREK:
            try:
                k = urllib.request.Request(szerver, data=adat, headers=UA)
                with urllib.request.urlopen(k, timeout=idokorlat + 60) as v:
                    j = json.load(v)
            except urllib.error.HTTPError as h:
                var = 60 * (kor + 1) if h.code in (429, 502, 503, 504) else 15
                naplo(f"    {szerver.split('/')[2]}: HTTP {h.code}, várok {var} s")
                time.sleep(var)
                continue
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as h:
                naplo(f"    {szerver.split('/')[2]}: {type(h).__name__}")
                time.sleep(10)
                continue
            if j.get("remark"):
                if "timed out" in j["remark"] or "out of memory" in j["remark"] or "memory" in j["remark"]:
                    return None        # a cella túl nagy: bontani kell
                naplo(f"    a szerver figyelmeztet: {j['remark'][:120]}")
                time.sleep(20)
                continue
            return j.get("elements", [])
        naplo("    minden szerver hibázott, 2 perc várakozás...")
        time.sleep(120)
    raise RuntimeError("Az Overpass-szerverek nem válaszolnak")


# ---------- 1. a városhatár ----------
def gyurukke_fuz(szakaszok):
    szakaszok = [list(s) for s in szakaszok if len(s) >= 2]
    gyuruk = []
    while szakaszok:
        gyuru = szakaszok.pop(0)
        while gyuru[0] != gyuru[-1]:
            for i, s in enumerate(szakaszok):
                if s[0] == gyuru[-1]:
                    gyuru.extend(s[1:])
                elif s[-1] == gyuru[-1]:
                    gyuru.extend(reversed(s[:-1]))
                elif s[-1] == gyuru[0]:
                    gyuru = s[:-1] + gyuru
                elif s[0] == gyuru[0]:
                    gyuru = list(reversed(s[1:])) + gyuru
                else:
                    continue
                szakaszok.pop(i)
                break
            else:
                break
        if gyuru[0] == gyuru[-1] and len(gyuru) >= 4:
            gyuruk.append(gyuru)
    return gyuruk


def terulet(gy):
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(gy, gy[1:] + gy[:1]))) / 2


def pont_gyuruben(x, y, gyuru):
    bent = False
    for (x1, y1), (x2, y2) in zip(gyuru, gyuru[1:] + gyuru[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            bent = not bent
    return bent


def hatar_letoltese():
    if HATAR.exists():
        return json.loads(HATAR.read_text(encoding="utf-8"))
    naplo("1. lépés: a városhatár letöltése")
    q = ('[out:json][timeout:120];relation["boundary"="administrative"]["name"="Budapest"]'
         '["admin_level"~"^(5|6|7)$"];out geom;')
    elemek = overpass(q)
    legjobb = None
    for e in elemek or []:
        kulso = [[(p["lon"], p["lat"]) for p in m["geometry"]] for m in e.get("members", [])
                 if m.get("type") == "way" and m.get("role") == "outer" and m.get("geometry")]
        gyuruk = gyurukke_fuz(kulso)
        if gyuruk:
            nagy = max(terulet(g) for g in gyuruk)
            if legjobb is None or nagy > legjobb[0]:
                legjobb = (nagy, gyuruk, e.get("id"))
    if not legjobb:
        raise RuntimeError("Nem találtam a városhatárt")
    gyuruk = [[list(p) for p in g] for g in legjobb[1]]
    adat = {"osm_relacio": legjobb[2], "gyuruk": gyuruk,
            "bbox": [min(p[1] for g in gyuruk for p in g), min(p[0] for g in gyuruk for p in g),
                     max(p[1] for g in gyuruk for p in g), max(p[0] for g in gyuruk for p in g)]}
    HATAR.write_text(json.dumps(adat), encoding="utf-8")
    naplo(f"   városhatár kész (relation {legjobb[2]}), befoglaló téglalap: {adat['bbox']}")
    return adat


# ---------- 2. az épületek ----------
def cellak(hatar):
    gyuruk = [[tuple(p) for p in g] for g in hatar["gyuruk"]]
    del_, ny, eszak, kelet = hatar["bbox"]
    ki = []
    for i in range(math.floor(del_ / CELLA_LAT), math.ceil(eszak / CELLA_LAT)):
        for j in range(math.floor(ny / CELLA_LON), math.ceil(kelet / CELLA_LON)):
            d, n = i * CELLA_LAT, j * CELLA_LON
            e, k = d + CELLA_LAT, n + CELLA_LON
            pontok = [(n + (k - n) * a / 6, d + (e - d) * b / 6) for a in range(7) for b in range(7)]
            bent = any(pont_gyuruben(x, y, g) for (x, y) in pontok for g in gyuruk)
            if not bent:       # a határ csúcsa a cellában (vékony szelet)
                bent = any(d <= p[1] <= e and n <= p[0] <= k for g in gyuruk for p in g)
            if bent:
                ki.append((i, j))
    return ki


def epulet_lekerdezes(d, n, e, k):
    bbox = f"{d:.6f},{n:.6f},{e:.6f},{k:.6f}"
    return (f'[out:json][timeout:240];'
            f'way["building"]["building"!="roof"]({bbox});out tags geom;'
            f'relation["building"]["building"!="roof"]({bbox});out body geom;'
            f'way["building:part"]["building:part"!="roof"]({bbox});out tags geom;'
            f'relation["building:part"]["building:part"!="roof"]({bbox});out body geom;'
            f'node["addr:housenumber"]["addr:street"]({bbox});out;')


def terulet_letolt(d, n, e, k, melyseg=0):
    """Egy téglalap elemei; ha a szerver túl nagynak találja, négy részre bontja."""
    elemek = overpass(epulet_lekerdezes(d, n, e, k))
    time.sleep(SZUNET)
    if elemek is not None:
        return elemek
    if melyseg >= MAX_MELYSEG:
        raise RuntimeError(f"Egy cella túl nagy még bontva is: {d},{n},{e},{k}")
    naplo(f"    a cella túl nagy, négy részre bontom ({melyseg + 1}. szint)")
    kd, kn = (d + e) / 2, (n + k) / 2
    ki = []
    for a, b, c, f in ((d, n, kd, kn), (d, kn, kd, k), (kd, n, e, kn), (kd, kn, e, k)):
        ki += terulet_letolt(a, b, c, f, melyseg + 1)
    return ki


def epuletek_letoltese(hatar):
    NYERS.mkdir(parents=True, exist_ok=True)
    lista = cellak(hatar)
    hianyzik = [c for c in lista if not (NYERS / f"c_{c[0]}_{c[1]}.json.gz").exists()]
    naplo(f"2. lépés: épületek letöltése: {len(lista)} cella, ebből {len(lista) - len(hianyzik)} már megvan")
    kezdet = time.time()
    for sorszam, (i, j) in enumerate(hianyzik, 1):
        d, n = i * CELLA_LAT, j * CELLA_LON
        elemek = terulet_letolt(d, n, d + CELLA_LAT, n + CELLA_LON)
        ut = NYERS / f"c_{i}_{j}.json.gz"
        tmp = ut.with_suffix(".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump(elemek, f, ensure_ascii=False)
        tmp.replace(ut)
        if sorszam % 10 == 0 or sorszam == len(hianyzik):
            eltelt = time.time() - kezdet
            hatra = eltelt / sorszam * (len(hianyzik) - sorszam)
            naplo(f"   épületek: {sorszam}/{len(hianyzik)} cella kész, kb. {hatra / 60:.0f} perc van hátra")
    # összesítés
    db = {"way": 0, "relation": 0, "node": 0}
    for ut in NYERS.glob("c_*.json.gz"):
        with gzip.open(ut, "rt", encoding="utf-8") as f:
            for e in json.load(f):
                db[e["type"]] = db.get(e["type"], 0) + 1
    naplo(f"   épületek kész: {len(list(NYERS.glob('c_*.json.gz')))} cella; elemek (a cellahatárokon kétszer is lehet): {db}")


# ---------- 3. Commons ----------
def commons_letoltese(hatar):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import commons_kepek
    naplo("3. lépés: a Commons helyadatos fájljainak keresése (ez a leghosszabb, akár több óra)")
    commons_kepek.varos_fajlok_lekerese([[tuple(p) for p in g] for g in hatar["gyuruk"]], naplo)


def lepes_ujraprobalva(nev, fuggveny, *args):
    """Felügyelet nélkül: ha egy lépés hibával megáll, 10 perc múlva újra próbálja, legfeljebb 30-szor."""
    for kiserlet in range(1, 31):
        try:
            return fuggveny(*args)
        except (SystemExit, Exception) as h:
            if isinstance(h, KeyboardInterrupt):
                raise
            naplo(f"!! {nev}: hiba ({type(h).__name__}: {h}); {kiserlet}. kísérlet, 10 perc múlva újra")
            time.sleep(600)
    raise SystemExit(f"{nev}: nem sikerült, indítsd újra később")


def main():
    ne_aludjon()
    naplo("=== Budapest letöltése indul ===")
    hatar = lepes_ujraprobalva("városhatár", hatar_letoltese)
    lepes_ujraprobalva("épületek", epuletek_letoltese, hatar)
    lepes_ujraprobalva("Commons", commons_letoltese, hatar)
    naplo("=== MINDEN LETÖLTÉS KÉSZ. Most jöhet a feldolgozás. ===")


if __name__ == "__main__":
    main()
