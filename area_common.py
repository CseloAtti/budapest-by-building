"""Shared helpers for the coordinate-based scripts (facts_wikipedia_area.py, facts_wikidata_api.py):
  - adaptiv_geokeres: divides the area into cells, and where a search reaches the limit of 500, cuts it into four
  - EpuletIndex: grid search among the buildings (for the whole city a full scan would be too slow)"""
import math

from common import nearest_vertex_m, point_in_any, polygons

LIMIT = 500
CITY_BOX = (47.34, 18.92, 47.62, 19.35)         # south, west, north, east (slightly larger than the city boundary)
INITIAL_LAT, INITIAL_LON = 0.07, 0.09                  # initial cell size (degrees), ~7 km: GeoData allows a box of at most 10 km
MIN_CELL = 0.0015                                 # we do not cut smaller than this


def cells(box, lat_step=INITIAL_LAT, lon_step=INITIAL_LON):
    d0, w0, d1, w1 = box
    ni = max(1, math.ceil((d1 - d0) / lat_step - 1e-9))
    nj = max(1, math.ceil((w1 - w0) / lon_step - 1e-9))
    for i in range(ni):
        for j in range(nj):
            yield (d0 + (d1 - d0) * i / ni, w0 + (w1 - w0) * j / nj,
                   d0 + (d1 - d0) * (i + 1) / ni, w0 + (w1 - w0) * (j + 1) / nj)


def adaptive_geosearch(geosearch, box):
    """geokeres(d0, w0, d1, w1) -> the list (of dicts) of the elements found in the given box. Result: all the hits."""
    all_, cutting = [], 0

    def go(d0, w0, d1, w1):
        nonlocal cutting
        list_ = geosearch(d0, w0, d1, w1)
        if len(list_) >= LIMIT and (d1 - d0) > MIN_CELL and (w1 - w0) > MIN_CELL:
            cutting += 1
            dm, wm = (d0 + d1) / 2, (w0 + w1) / 2
            for a in ((d0, w0, dm, wm), (d0, wm, dm, w1), (dm, w0, d1, wm), (dm, wm, d1, w1)):
                go(*a)
            return
        if len(list_) >= LIMIT:
            print(f"Figyelem: a legkisebb cellában ({d0:.4f},{w0:.4f}) is elérte a {LIMIT}-as korlátot, adat hiányozhat.")
        all_.extend(list_)

    for c in cells(box):
        go(*c)
    print(f"Földrajzi keresés kész ({cutting} cella lett kisebbre vágva).")
    return all_


class BuildingIndex:
    CELL = 0.0005    # fok (~55 m)

    def __init__(self, feats):
        self.elements = []
        self.grid = {}
        for ft in feats:
            pl = polygons(ft["geometry"])
            if not pl:
                continue
            xs = [p[0] for poly in pl for ring_ in poly[:1] for p in ring_]
            ys = [p[1] for poly in pl for ring_ in poly[:1] for p in ring_]
            if not xs:
                continue
            n = len(self.elements)
            self.elements.append((ft, pl))
            for i in range(int(min(xs) / self.CELL), int(max(xs) / self.CELL) + 1):
                for j in range(int(min(ys) / self.CELL), int(max(ys) / self.CELL) + 1):
                    self.grid.setdefault((i, j), []).append(n)

    def _candidates(self, x, y, neighbor=0):
        ci, cj = int(x / self.CELL), int(y / self.CELL)
        seen = set()
        for i in range(ci - neighbor, ci + neighbor + 1):
            for j in range(cj - neighbor, cj + neighbor + 1):
                for n in self.grid.get((i, j), ()):
                    if n not in seen:
                        seen.add(n)
                        yield n

    def in_(self, x, y):
        for n in self._candidates(x, y):
            ft, pl = self.elements[n]
            if point_in_any(x, y, pl):
                return ft
        return None

    def nearby(self, x, y, max_m):
        best, distance = None, max_m
        for n in self._candidates(x, y, 1):
            ft, pl = self.elements[n]
            d = nearest_vertex_m(x, y, pl[0][0])
            if d < distance:
                best, distance = ft, d
        return best
