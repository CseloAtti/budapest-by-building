"""Közös segédek a koordináta alapú szkriptekhez (tenyek_wikipedia_terulet.py, tenyek_wikidata_api.py):
  - adaptiv_geokeres: a területet cellákra osztja, és ahol egy keresés eléri a 500-as korlátot, négyfelé vágja
  - EpuletIndex: rácsos keresés az épületek között (az egész városnál a teljes végigpásztázás túl lassú lenne)"""
import math

from kozos import legkozelebbi_csucs_m, pont_barmelyikben, poligonok

LIMIT = 500
VAROS_DOBOZ = (47.34, 18.92, 47.62, 19.35)         # dél, nyugat, észak, kelet (a városhatárnál kicsit nagyobb)
KEZDO_LAT, KEZDO_LON = 0.07, 0.09                  # kezdő cellaméret (fok), ~7 km: a GeoData legfeljebb 10 km-es dobozt enged
MIN_CELLA = 0.0015                                 # ennél kisebbre már nem vágunk


def cellak(doboz, lat_lepes=KEZDO_LAT, lon_lepes=KEZDO_LON):
    d0, w0, d1, w1 = doboz
    ni = max(1, math.ceil((d1 - d0) / lat_lepes - 1e-9))
    nj = max(1, math.ceil((w1 - w0) / lon_lepes - 1e-9))
    for i in range(ni):
        for j in range(nj):
            yield (d0 + (d1 - d0) * i / ni, w0 + (w1 - w0) * j / nj,
                   d0 + (d1 - d0) * (i + 1) / ni, w0 + (w1 - w0) * (j + 1) / nj)


def adaptiv_geokeres(geokeres, doboz):
    """geokeres(d0, w0, d1, w1) -> az adott dobozban talált elemek listája (dict-ek). Eredmény: az összes találat."""
    osszes, vago = [], 0

    def menj(d0, w0, d1, w1):
        nonlocal vago
        lista = geokeres(d0, w0, d1, w1)
        if len(lista) >= LIMIT and (d1 - d0) > MIN_CELLA and (w1 - w0) > MIN_CELLA:
            vago += 1
            dm, wm = (d0 + d1) / 2, (w0 + w1) / 2
            for a in ((d0, w0, dm, wm), (d0, wm, dm, w1), (dm, w0, d1, wm), (dm, wm, d1, w1)):
                menj(*a)
            return
        if len(lista) >= LIMIT:
            print(f"Figyelem: a legkisebb cellában ({d0:.4f},{w0:.4f}) is elérte a {LIMIT}-as korlátot, adat hiányozhat.")
        osszes.extend(lista)

    for c in cellak(doboz):
        menj(*c)
    print(f"Földrajzi keresés kész ({vago} cella lett kisebbre vágva).")
    return osszes


class EpuletIndex:
    CELLA = 0.0005    # fok (~55 m)

    def __init__(self, feats):
        self.elemek = []
        self.racs = {}
        for ft in feats:
            pl = poligonok(ft["geometry"])
            if not pl:
                continue
            xs = [p[0] for poli in pl for gyuru in poli[:1] for p in gyuru]
            ys = [p[1] for poli in pl for gyuru in poli[:1] for p in gyuru]
            if not xs:
                continue
            n = len(self.elemek)
            self.elemek.append((ft, pl))
            for i in range(int(min(xs) / self.CELLA), int(max(xs) / self.CELLA) + 1):
                for j in range(int(min(ys) / self.CELLA), int(max(ys) / self.CELLA) + 1):
                    self.racs.setdefault((i, j), []).append(n)

    def _jeloltek(self, x, y, szomszed=0):
        ci, cj = int(x / self.CELLA), int(y / self.CELLA)
        lattak = set()
        for i in range(ci - szomszed, ci + szomszed + 1):
            for j in range(cj - szomszed, cj + szomszed + 1):
                for n in self.racs.get((i, j), ()):
                    if n not in lattak:
                        lattak.add(n)
                        yield n

    def benne(self, x, y):
        for n in self._jeloltek(x, y):
            ft, pl = self.elemek[n]
            if pont_barmelyikben(x, y, pl):
                return ft
        return None

    def kozeli(self, x, y, max_m):
        legjobb, tav = None, max_m
        for n in self._jeloltek(x, y, 1):
            ft, pl = self.elemek[n]
            d = legkozelebbi_csucs_m(x, y, pl[0][0])
            if d < tav:
                legjobb, tav = ft, d
        return legjobb
