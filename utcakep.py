"""utcakep.py - a kártya "Utcakép" linkjéhez: minden címmel rendelkező épülethez egy pont az utcán, a ház előtt.

A Google Street View a megadott ponthoz a legközelebbi felvételt keresi; az épület középpontjából ez gyakran a házon belüli
udvar vagy egy melléksikátor. Az utca vonalát itt a címadatokból becsüljük: az azonos nevű utca (osm_cimek.csv) házainak
középpontjai az utca két oldalán sorakoznak. Az épület 110 m-es környezetében lévő, azonos utcanevű házak főtengelyt adnak
(az utca iránya), a két oldal házsorának középvonala között félúton van az utca tengelye; az 'sv_lat'/'sv_lon' ennek az
épület melletti pontja. Nem ad pontot, ha nincs elég szomszéd, az utca nem egyenes (tér, kanyar), a házak csak az utca
egyik oldalán vannak, vagy a pont épület belsejébe esne - ilyenkor a kártya az épület középpontját használja.
Csak a Python alap könyvtárát használja.
"""
import csv
import math
from collections import defaultdict
from pathlib import Path

LON0, LAT0 = 19.05, 47.5
KX = math.cos(math.radians(LAT0)) * 111320.0
KY = 110574.0
SUGAR = 110.0             # m: az utca vonalát ennyi sugarú környezet azonos utcás házaiból illesztjük
MIN_SZOMSZED = 4          # legalább ennyi ház kell az illesztéshez (a ház magával együtt)
MIN_NYUJTOTTSAG = 1.6     # a főtengely mentén legalább ennyiszer nagyobb a szórás, mint rá merőlegesen
MIN_UTCASZELESSEG = 14.0  # m: a két oldal házsorának középvonala között legalább ennyi legyen
MAX_TAVOLSAG = 45.0       # m: ennél messzebb lévő pontot nem fogadunk el (udvari ház, hibás illesztés)
CELLA = 110.0


def gyuru_xy(geo):
    gyuru = geo["coordinates"][0] if geo["type"] == "Polygon" else geo["coordinates"][0][0]
    return [((p[0] - LON0) * KX, (p[1] - LAT0) * KY) for p in gyuru]


def kozeppont(xy):
    a2 = cx = cy = 0.0
    for i in range(len(xy) - 1):
        c = xy[i][0] * xy[i + 1][1] - xy[i + 1][0] * xy[i][1]
        a2 += c
        cx += (xy[i][0] + xy[i + 1][0]) * c
        cy += (xy[i][1] + xy[i + 1][1]) * c
    if abs(a2) < 1e-6:
        return sum(p[0] for p in xy) / len(xy), sum(p[1] for p in xy) / len(xy)
    return cx / (3 * a2), cy / (3 * a2)


def benne_van(xy, x, y):
    be = False
    for i in range(len(xy) - 1):
        (x0, y0), (x1, y1) = xy[i], xy[i + 1]
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            be = not be
    return be


class Racs:
    def __init__(self, cella):
        self.c = cella
        self.d = defaultdict(list)

    def hozzaad(self, x, y, adat):
        self.d[(int(x // self.c), int(y // self.c))].append((x, y, adat))

    def kozel(self, x, y, r):
        cx, cy = int(x // self.c), int(y // self.c)
        n = int(r // self.c) + 1
        r2 = r * r
        for i in range(cx - n, cx + n + 1):
            for j in range(cy - n, cy + n + 1):
                for px, py, a in self.d.get((i, j), ()):
                    if (px - x) ** 2 + (py - y) ** 2 <= r2:
                        yield px, py, a


def szamol(feats, cimek_csv):
    if not Path(cimek_csv).exists():
        return 0
    utca = {}
    with open(cimek_csv, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r["utca"] and r["hazszam"]:
                utca.setdefault((r["osm_tipus"], int(r["id"])), r["utca"].strip())
    alap = Racs(CELLA)               # az összes épület alaprajza: az utcai pont nem eshet épület belsejébe
    csoport = defaultdict(list)      # utcanév -> [(feature, x, y)]
    for ft in feats:
        if ft["geometry"]["type"] not in ("Polygon", "MultiPolygon"):
            continue
        xy = gyuru_xy(ft["geometry"])
        x, y = kozeppont(xy)
        alap.hozzaad(x, y, xy)
        pr = ft["properties"]
        if pr.get("resz"):
            continue
        u = utca.get((pr.get("osm_tipus") or "way", int(pr["id"])))
        if u:
            csoport[u].append((ft, x, y))

    def epuletben(px, py):
        return any(benne_van(xy, px, py) for _, _, xy in alap.kozel(px, py, 90.0))

    db = 0
    for u, lista in csoport.items():
        if len(lista) < MIN_SZOMSZED:
            continue
        racs = Racs(CELLA)
        for _, x, y in lista:
            racs.hozzaad(x, y, None)
        for ft, x, y in lista:
            q = [(px, py) for px, py, _ in racs.kozel(x, y, SUGAR)]
            if len(q) < MIN_SZOMSZED:
                continue
            mx = sum(p[0] for p in q) / len(q)
            my = sum(p[1] for p in q) / len(q)
            sxx = sum((p[0] - mx) ** 2 for p in q) / len(q)
            syy = sum((p[1] - my) ** 2 for p in q) / len(q)
            sxy = sum((p[0] - mx) * (p[1] - my) for p in q) / len(q)
            kozep = (sxx + syy) / 2
            sug = math.sqrt(((sxx - syy) / 2) ** 2 + sxy ** 2)
            nagy, kicsi = kozep + sug, kozep - sug
            if kicsi <= 1e-9 or math.sqrt(nagy / kicsi) < MIN_NYUJTOTTSAG:
                continue
            fi = 0.5 * math.atan2(2 * sxy, sxx - syy)
            dx, dy = math.cos(fi), math.sin(fi)          # az utca iránya
            nx, ny = -dy, dx                              # rá merőleges
            s_ = [(p[0] - mx) * nx + (p[1] - my) * ny for p in q]
            fent = [v for v in s_ if v > 0]
            lent = [v for v in s_ if v <= 0]
            if len(fent) < 2 or len(lent) < 2:
                continue                  # csak az utca egyik oldalán vannak azonos nevű házak: nem tudjuk, merre van az utca
            af, al = sum(fent) / len(fent), sum(lent) / len(lent)
            if af - al < MIN_UTCASZELESSEG:
                continue
            t = (x - mx) * dx + (y - my) * dy
            kozepvonal = (af + al) / 2
            px = mx + t * dx + kozepvonal * nx
            py = my + t * dy + kozepvonal * ny
            if math.hypot(px - x, py - y) > MAX_TAVOLSAG or epuletben(px, py):
                continue
            ft["properties"]["sv_lat"] = round(LAT0 + py / KY, 6)
            ft["properties"]["sv_lon"] = round(LON0 + px / KX, 6)
            db += 1
    return db
