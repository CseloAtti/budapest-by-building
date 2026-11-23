"""
build_tiles.py - building the data for the 3D view (terkep3d/).

Run (in the project folder):       py build_tiles.py          (the inner city)
                                   py build_tiles.py varos     (the whole city -> terkep3d/data_varos/)
City-mode input: data/varos/epuletek_vegleges.geojson, data/varos/viz_zold.json (budapest_pbf.py),
                 data/varos/commons_kepek.json; requirements: at least 4 GB of free memory, 15-40 minutes.
The city 3D view: http://localhost:8000/terkep3d/?adat=varos

Uses only the Python standard library.

Input:    data/belvaros_epuletek_vegleges.geojson   (assemble.py; with the ev_becsles_* fields)
          data/viz_zold.json                         (download_water.py; optional: water and parks)
          data/N47E018.SRTMGL1_NC.nc, data/N47E019.SRTMGL1_NC.nc   (NASA SRTM elevation tiles; optional)
Output:   terkep3d/data/budapest.json    - settings, tile index, year histogram
          terkep3d/data/tiles.bin        - the buildings in 600 m binary tiles
          terkep3d/data/epuletek.json    - the buildings' data for the card (the index = the building's id)
          terkep3d/data/terrain.bin      - terrain mesh (if there is an SRTM tile)
          terkep3d/data/landcover.png    - water and parks as an image onto the terrain (+ landcover.webp, if Pillow is installed) (if there is a viz_zold.json)

The tile format comes from the Amsterdam project (alexbarakov/amsterdam-by-building, MIT licence);
the tile builder here is a rewritten, Budapest version.

For the slider every building needs a year. A building of known year gets its own year. For a grey building,
within its estimated era, one year is chosen from the years of nearby buildings of known year (computed from the
building's id, so always the same value). This is only needed for display: the card marks the estimate as an estimate
and does not show the exact year.
"""
import csv
import json
import math
import statistics
import struct
import sys
import zlib
from array import array
from collections import Counter, defaultdict
from pathlib import Path

try:
    from dem import Terrain, FaultyFile
except ImportError:          # without dem.py we work without terrain
    Terrain = None
    FaultyFile = Exception

CITY = "varos" in sys.argv[1:]
DATA = Path("data")
OUTPUT = Path("terkep3d/data_varos" if CITY else "terkep3d/data")
LAT0, LON0 = 47.5015, 19.0515
COSLAT = math.cos(math.radians(LAT0))
TILE = 600.0
MAGIC = 0x34424241
FIRST_YEAR_MIN = 1700
NOW = 2026
NEIGHBOR_M = 150.0
TERRAIN_STEP = 20.0       # m: step of the terrain mesh
IMAGE_PX = 2.5             # m: size of a pixel of the water/park image
TERRAIN_MARGIN = {"nyugat": 5000.0, "kelet": 2000.0, "eszak": 2000.0, "del": 2500.0}   # m, around the buildings
if CITY:               # the whole city: coarser mesh and image, smaller margin
    TERRAIN_STEP = 40.0
    IMAGE_PX = 5.0
    TERRAIN_MARGIN = {"nyugat": 2500.0, "kelet": 2500.0, "eszak": 2500.0, "del": 2500.0}
SMOOTHING_STEP = 40       # number of passes of the strong smoothing of the floodplain (3x3 average)
FLOODPLAIN_LEVEL = 96.0       # m: the Danube's level (an approximation for the smoothing weight)
CITY_MIN_RADIUS = 3      # SRTM cell: in the built-up area the lowest point within a window of this size is taken

# identical to the era list of index.html and year_estimate.py
ERAS = [
    (1, 1866, "1866-ig – Kiegyezés előtt", "to 1866 – Before the Compromise", "#7a1f1f"),
    (1867, 1918, "1867–1918 – Dualizmus", "1867–1918 – Dualism", "#d9653b"),
    (1919, 1944, "1919–1944 – Horthy-korszak", "1919–1944 – Horthy era", "#e8b04a"),
    (1945, 1956, "1945–1956 – Rákosi-korszak", "1945–1956 – Rákosi era", "#6aa84f"),
    (1957, 1989, "1957–1989 – Kádár-korszak", "1957–1989 – Kádár era", "#2e8b8b"),
    (1990, 2010, "1990–2010 – Rendszerváltás utáni évek", "1990–2010 – Post-transition years", "#3d85c6"),
    (2011, 9999, "2011-től – Napjaink", "2011 onwards – Present day", "#8e5bb5"),
]
RUIN_ERA = 0     # ancient and medieval ruins are not a separate category: they belong to the "before 1867" era (the "rom" field is still shown on the card)


def bridges_lechner():
    """The data of the Lechner Knowledge Centre for bridges: the rows in data/tenyek/lechner.csv tied to the bridges' OSM ids (manual pairing)
    are written to the corresponding bridge in hidak.json (bridges are not in the building data, so assemble.py does not see them)."""
    path_ = OUTPUT / "hidak.json"
    facts = Path("data/tenyek/lechner.csv")
    if not path_.exists() or not facts.exists():
        return
    fields = ("lechner_nev", "lechner_epult", "lechner_ev_kezdet", "lechner_ev_veg", "lechner_tervezo", "lechner_illesztes")
    data_ = defaultdict(dict)
    with open(facts, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r.get("mezo") in fields and (r.get("ertek") or "").strip():
                data_[(r["osm_tipus"], str(r["id"]))][r["mezo"]] = r["ertek"].strip()
    h = json.load(open(path_, encoding="utf-8"))
    changed = count_ = 0
    for bridge in h.get("hidak", []):
        found = {}
        for o in bridge.get("osm", []):
            found = data_.get((o.get("t", "way"), str(o.get("id")))) or found
            if found:
                break
        for m in fields:
            new = found.get(m)
            if new != bridge.get(m) and (new or m in bridge):
                if new:
                    bridge[m] = new
                else:
                    bridge.pop(m, None)
                changed += 1
        count_ += bool(found)
    if changed:
        path_.write_text(json.dumps(h, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  Lechner-adat a hidakon: {count_} híd" + (" (hidak.json frissítve)" if changed else ""))


CARD_FIELDS = [
    "id", "osm_tipus", "nev", "tipus", "resz", "szintek",
    "magassag",
    "ev", "ev_forras", "tervezo", "tervezo_forras", "stilus", "vedettseg", "vedettseg_helyi",
    "muemlek_torzsszam", "oeny_azonosito", "budapest100_url", "budapest100_kep", "budapest100_foto", "legenda_url", "legenda_kep", "epforum_url", "commons_kep", "kep_url", "link_url", "linkek", "kepek_linkek", "felosztott_ebbol", "about", "wikipedia", "wikipedia_zona", "zona_nev", "zona_tervezo", "zona_azon", "zona_tervezo_nev", "wikidata_id", "lechner_nev", "lechner_epult",
    "lechner_tervezo", "lechner_illesztes", "nev_kozepulet", "rom", "cim", "cim_tobb",
    "ev_kozelito_tol", "ev_kozelito_ig", "ev_kozelito_szoveg", "ev_kozelito_forras",
    "sv_lat", "sv_lon",
]


def local(lon, lat):
    """Degrees -> metres in the view's coordinate system: x east, z south."""
    return ((lon - LON0) * COSLAT * 111320.0, -(lat - LAT0) * 110574.0)


def back(x, z):
    return (LAT0 - z / 110574.0, LON0 + x / (COSLAT * 111320.0))


def era_year_according_to(year):
    for i, (from_, to, *_) in enumerate(ERAS):
        if from_ <= year <= to:
            return i
    return 1


def clean_ring(ring_):
    """Converts to local metres, drops the closing (repeated) point and adjacent identical points."""
    points = []
    for lon, lat in ring_:
        p = local(lon, lat)
        if not points or math.dist(p, points[-1]) > 0.05:
            points.append(p)
    if len(points) > 1 and math.dist(points[0], points[-1]) <= 0.05:
        points.pop()
    return points if len(points) >= 3 else None


def polygons(geo):
    """The building's polygons: [[outer, hole, hole...], ...] in local metres."""
    if geo["type"] == "Polygon":
        list_ = [geo["coordinates"]]
    elif geo["type"] == "MultiPolygon":
        list_ = geo["coordinates"]
    else:
        return []
    out = []
    for poly in list_:
        rings_ = [clean_ring(g) for g in poly]
        if rings_ and rings_[0]:
            out.append([rings_[0]] + [g for g in rings_[1:] if g])
    return out


def center(poly):
    gy = poly[0]
    a2 = cx = cz = 0.0
    for (x0, z0), (x1, z1) in zip(gy, gy[1:] + gy[:1]):
        c = x0 * z1 - x1 * z0
        a2 += c
        cx += (x0 + x1) * c
        cz += (z0 + z1) * c
    if abs(a2) < 1e-9:
        return (sum(p[0] for p in gy) / len(gy), sum(p[1] for p in gy) / len(gy))
    return (cx / (3 * a2), cz / (3 * a2))


def box_blur(g):
    """3x3 average (at the edge the last value is repeated). g: [[...], ...]"""
    n, m = len(g), len(g[0])
    v = []
    for r in range(n):
        row = g[r]
        v.append([(row[max(c - 1, 0)] + row[c] + row[min(c + 1, m - 1)]) / 3 for c in range(m)])
    out = []
    for r in range(n):
        a, b, c_ = v[max(r - 1, 0)], v[r], v[min(r + 1, n - 1)]
        out.append([(a[c] + b[c] + c_[c]) / 3 for c in range(m)])
    return out


def minimum_filter(g, radius):
    """Minimum of a square window (separable: first along the rows, then along the columns)."""
    n, m = len(g), len(g[0])
    v = [[min(row[max(c - radius, 0):c + radius + 1]) for c in range(m)] for row in g]
    return [[min(v[k][c] for k in range(max(r - radius, 0), min(r + radius, n - 1) + 1)) for c in range(m)]
            for r in range(n)]


SUBSAMPLE = 4   # vertical sub-sampling per pixel for soft (anti-aliased) edges


def fill(sections, rings, w, h):
    """Even-odd fill: records the inside of the rings as spans (row -> [(a, b), ...]),
    with ALMINTA sub-rows per row. The coordinates are in pixel units."""
    ys = [p[1] for gy in rings for p in gy]
    if not ys:
        return
    buckets = defaultdict(list)       # row -> the edges touching it (otherwise every row would look at every edge)
    for gy in rings:
        for (x1, y1), (x2, y2) in zip(gy, gy[1:] + gy[:1]):
            if y1 != y2:
                e = (min(y1, y2), max(y1, y2), x1, y1, x2, y2)
                for r in range(max(0, int(math.floor(e[0]))), min(h - 1, int(math.floor(e[1]))) + 1):
                    buckets[r].append(e)
    for r in range(max(0, int(math.floor(min(ys)))), min(h - 1, int(math.floor(max(ys)))) + 1):
        el = buckets.get(r, ())
        for k in range(SUBSAMPLE):
            yc = r + (k + 0.5) / SUBSAMPLE
            xs = [x1 + (yc - y1) * (x2 - x1) / (y2 - y1) for (lo, hi, x1, y1, x2, y2) in el if lo <= yc < hi]
            xs.sort()
            for a, b in zip(xs[::2], xs[1::2]):
                a, b = max(a, 0.0), min(b, float(w))
                if b > a:
                    sections[r].append((a, b))


def cover(sections, w, h):
    """From the spans, 0..255 coverage per row (bytes), where the fractions at the edge give the anti-aliasing."""
    rows = []
    weight = 255.0 / SUBSAMPLE
    for r in range(h):
        sp = sections[r]
        if not sp:
            rows.append(bytes(w))
            continue
        d = {}                   # the inner, fully covered cells (only where there is a span: fast for large images)
        p = {}                   # the edge, partially covered cells
        for a, b in sp:
            ia, ib = int(a), int(b)
            if ia == ib:
                p[ia] = p.get(ia, 0.0) + (b - a)
            else:
                p[ia] = p.get(ia, 0.0) + (ia + 1 - a)
                p[ib] = p.get(ib, 0.0) + (b - ib)
                d[ia + 1] = d.get(ia + 1, 0.0) + 1.0
                d[ib] = d.get(ib, 0.0) - 1.0
        row = bytearray(w)
        acc = 0.0
        ks = sorted(set(d) | set(p))

        def convert(v):
            return 255 if v >= 254.5 else int(v + 0.5)

        for n, c in enumerate(ks):
            acc += d.get(c, 0.0)
            if c < w:
                row[c] = convert((acc + p.get(c, 0.0)) * weight)
            if n + 1 < len(ks) and ks[n + 1] > c + 1 and acc > 1e-9:       # between two cells of interest the coverage is constant
                hi = min(ks[n + 1], w)
                if hi > c + 1:
                    row[c + 1:hi] = bytes([convert(acc * weight)]) * (hi - c - 1)
        rows.append(bytes(row))
    return rows


def png_write(path_, w, h, rows_rgb):
    """A simple RGB PNG (with the standard library). sorok_rgb: h rows, w*3 bytes per row."""
    def chunk(type_, data_):
        c = struct.pack(">I", len(data_)) + type_ + data_
        return c + struct.pack(">I", zlib.crc32(type_ + data_) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes(s) for s in rows_rgb)
    Path(path_).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                         + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def ring_area(ring_):
    return abs(sum(x0 * z1 - x1 * z0 for (x0, z0), (x1, z1) in zip(ring_, ring_[1:] + ring_[:1]))) / 2


class Terrain_:
    """Terrain from SRTM: a mesh for display, and the base height of the buildings."""

    def __init__(self, ep, water):
        xs = [e["x"] for e in ep]
        zs = [e["z"] for e in ep]
        self.x0 = math.floor((min(xs) - TERRAIN_MARGIN["nyugat"]) / TERRAIN_STEP) * TERRAIN_STEP
        self.x1 = math.ceil((max(xs) + TERRAIN_MARGIN["kelet"]) / TERRAIN_STEP) * TERRAIN_STEP
        self.z0 = math.floor((min(zs) - TERRAIN_MARGIN["eszak"]) / TERRAIN_STEP) * TERRAIN_STEP
        self.z1 = math.ceil((max(zs) + TERRAIN_MARGIN["del"]) / TERRAIN_STEP) * TERRAIN_STEP
        self.nx = int((self.x1 - self.x0) / TERRAIN_STEP) + 1
        self.nz = int((self.z1 - self.z0) / TERRAIN_STEP) + 1
        lat_e, lon_ny = back(self.x0, self.z0)
        lat_d, lon_k = back(self.x1, self.z1)
        d = Terrain(DATA)
        degree = Terrain.DEGREE
        ny, kel = math.floor(lon_ny * degree) / degree, math.ceil(lon_k * degree) / degree
        de, ez = math.floor(lat_d * degree) / degree, math.ceil(lat_e * degree) / degree
        row, class_, self.lat_f, self.lon_ny, g = d.grid(ny, kel, de, ez)
        # missing values (if there were any) with the median height
        valid = [v for r in g for v in r if v == v]
        med = statistics.median(valid)
        g = [[v if v == v else med for v in r] for r in g]
        self.dsm_stat = (min(valid), max(valid))
        # in the built-up areas SRTM also measures the buildings (surface model): there the nearby lowest point is taken
        density = [[0.0] * class_ for _ in range(row)]
        cell_m2 = (110574.0 / degree) * (111320.0 * COSLAT / degree)
        for e in ep:
            r = int(round((self.lat_f - back(e["x"], e["z"])[0]) * degree))
            c = int(round((back(e["x"], e["z"])[1] - self.lon_ny) * degree))
            if 0 <= r < row and 0 <= c < class_:
                density[r][c] += sum(ring_area(p[0]) for p in e["poly"]) / cell_m2
        density = box_blur(box_blur([[min(1.0, v) for v in r] for r in density]))
        plain = box_blur(g)
        low = box_blur(minimum_filter(g, CITY_MIN_RADIUS))
        self.g = [[plain[r][c] + (low[r][c] - plain[r][c]) * min(1.0, density[r][c] * 2.5) for c in range(class_)]
                  for r in range(row)]
        # on the floodplain (Pest) the noise of SRTM and the remains of the buildings would give a bumpy surface: it is strongly smoothed there,
        # on the hills (the height between 15 and 45 m above the Danube's level, gradually) the detail is kept
        self.g0 = self.g          # the unsmoothed grid for measuring the water level
        strong = self.g
        for _ in range(SMOOTHING_STEP):
            strong = box_blur(strong)
        self.g = [[self.g[r][c] + (strong[r][c] - self.g[r][c])
                   * min(1.0, max(0.0, (45.0 - (strong[r][c] - FLOODPLAIN_LEVEL)) / 30.0))
                   for c in range(class_)] for r in range(row)]
        self.row, self.class_ = row, class_
        # image of water and parks
        self.kep_w = int((self.x1 - self.x0) / IMAGE_PX) + 1
        self.kep_h = int((self.z1 - self.z0) / IMAGE_PX) + 1
        park_sz = [[] for _ in range(self.kep_h)]
        water_sz = [[] for _ in range(self.kep_h)]
        self.van_kep = False
        for p in water or []:
            rings = []
            for gy in p["gyuruk"]:
                pts = []
                for lon, lat in gy:
                    x, z = local(lon, lat)
                    pts.append(((x - self.x0) / IMAGE_PX, (z - self.z0) / IMAGE_PX))
                rings.append(pts)
            fill(water_sz if p["fajta"] == "viz" else park_sz, rings, self.kep_w, self.kep_h)
            self.van_kep = True
        self.park = cover(park_sz, self.kep_w, self.kep_h)
        self.water = cover(water_sz, self.kep_w, self.kep_h)
        # the Danube's level: the median of the water surface (this becomes the view's zero level)
        water_ = []
        for r in range(0, self.kep_h, 4):
            row_ = self.water[r]
            for c in range(0, self.kep_w, 4):
                if row_[c] > 200:
                    water_.append(self.dsm(self.x0 + c * IMAGE_PX, self.z0 + r * IMAGE_PX, self.g0))
        self.ref = statistics.median(water_) if water_ else 96.0
        self.vizi_cellak = len(water_)
        self.part_grid()

    def part_grid(self):
        """For the water level of lakes: the lowest height of the land near the water surface (on a coarse grid).
        Lakes lying higher (e.g. Lake Naplás) are therefore at their shore's level, not at the Danube's level (in a pit)."""
        K = 3
        degree = Terrain.DEGREE
        nr, nc = (self.row + K - 1) // K, (self.class_ + K - 1) // K
        INF = 1e9
        middle = [[0.0] * nc for _ in range(nr)]
        dry = [[INF] * nc for _ in range(nr)]
        for i in range(nr):
            r = min(i * K + K // 2, self.row - 1)
            for j in range(nc):
                c = min(j * K + K // 2, self.class_ - 1)
                middle[i][j] = self.g[r][c]
                x, z = local(self.lon_ny + c / degree, self.lat_f - r / degree)
                if not self.on_water(x, z):
                    dry[i][j] = self.g[r][c]
        mn = minimum_filter(dry, 8)                    # ~700 m surroundings
        self.part = box_blur([[mn[i][j] if mn[i][j] < INF else middle[i][j] for j in range(nc)] for i in range(nr)])
        self.part_k = K

    def part_level(self, x, z):
        """The shore level around the point (x, z) (m above sea level), with bilinear interpolation on the coarse grid."""
        lat, lon = back(x, z)
        degree = Terrain.DEGREE
        K = self.part_k
        r = ((self.lat_f - lat) * degree - K // 2) / K
        c = ((lon - self.lon_ny) * degree - K // 2) / K
        nr, nc = len(self.part), len(self.part[0])
        r = min(max(r, 0.0), nr - 1.001)
        c = min(max(c, 0.0), nc - 1.001)
        r0, c0 = int(r), int(c)
        fr, fc = r - r0, c - c0
        g = self.part
        return (g[r0][c0] * (1 - fc) + g[r0][c0 + 1] * fc) * (1 - fr) + (g[r0 + 1][c0] * (1 - fc) + g[r0 + 1][c0 + 1] * fc) * fr

    def dsm(self, x, z, g=None):
        """The height computed from SRTM (m above sea level) at the point (x, z), with bilinear interpolation."""
        lat, lon = back(x, z)
        degree = Terrain.DEGREE
        r = (self.lat_f - lat) * degree
        c = (lon - self.lon_ny) * degree
        r = min(max(r, 0.0), self.row - 1.001)
        c = min(max(c, 0.0), self.class_ - 1.001)
        r0, c0 = int(r), int(c)
        fr, fc = r - r0, c - c0
        g = g or self.g
        return (g[r0][c0] * (1 - fc) + g[r0][c0 + 1] * fc) * (1 - fr) + (g[r0 + 1][c0] * (1 - fc) + g[r0 + 1][c0 + 1] * fc) * fr

    def ground(self, x, z):
        """The ground height relative to the Danube's level (the view's level 0), at least 0."""
        return max(0.0, self.dsm(x, z) - self.ref)

    def on_water(self, x, z):
        c = int((x - self.x0) / IMAGE_PX)
        r = int((z - self.z0) / IMAGE_PX)
        return 0 <= r < self.kep_h and 0 <= c < self.kep_w and self.water[r][c] > 127

    def water_ratio(self, x, z):
        """Water coverage in the ~20 m surroundings of the point (0..1): the soft transition of the shoreline in the terrain."""
        c0 = (x - self.x0) / IMAGE_PX
        r0 = (z - self.z0) / IMAGE_PX
        half = TERRAIN_STEP * 0.75 / IMAGE_PX
        count_ = 0
        n = 0
        for dr in range(-4, 5):
            r = int(r0 + dr * half / 4)
            if not 0 <= r < self.kep_h:
                continue
            row = self.water[r]
            for dc in range(-4, 5):
                c = int(c0 + dc * half / 4)
                if 0 <= c < self.kep_w:
                    n += 1
                    count_ += row[c]
        return count_ / (255.0 * n) if n else 0.0

    def write(self, output):
        """terrain.bin and landcover.png."""
        hs = array("h")
        for j in range(self.nz):
            z = self.z0 + j * TERRAIN_STEP
            for i in range(self.nx):
                x = self.x0 + i * TERRAIN_STEP
                f = self.water_ratio(x, z)
                dry = max(0.0, self.dsm(x, z) - self.ref)
                level = 0.0
                if f > 0.0:
                    # the lake stands at its shore's level (the Danube and the small lakes of the floodplain stay at zero level)
                    p = self.part_level(x, z) - self.ref
                    t = min(1.0, max(0.0, (p - 4.0) / 8.0))
                    level = max(0.0, p) * t * t * (3 - 2 * t)
                h = (1.0 - f) * dry + f * level
                hs.append(int(round(h * 10)))
        if sys.byteorder != "little":
            hs.byteswap()
        (output / "terrain.bin").write_bytes(struct.pack("<IIffff", self.nx, self.nz, self.x0, self.z0,
                                                          TERRAIN_STEP, self.ref) + hs.tobytes())
        if self.van_kep:
            rows = []
            for r in range(self.kep_h):
                row_ = bytearray(self.kep_w * 3)
                row_[0::3] = self.park[r]
                row_[1::3] = self.water[r]
                rows.append(row_)
            png_write(output / "landcover.png", self.kep_w, self.kep_h, rows)
            try:  # optional: a lossless WebP is ~40% smaller; needs Pillow (pip install pillow), the PNG is the fallback
                from PIL import Image
                Image.MAX_IMAGE_PIXELS = None
                Image.open(output / "landcover.png").save(output / "landcover.webp", lossless=True, method=6, exact=True)
            except ImportError:
                print("  (Pillow is not installed: landcover.webp was not made, the PNG is used)")


def bridge_axes():
    """The axis points of the Danube bridges over the water (terkep3d/data_varos/hidak.json, build_bridges.py): the dedicated bridge model is shown
    instead of the bridge buildings in OSM (piers, stone towers). Grid: (cell) -> [(x, z, radius)]."""
    path_ = OUTPUT / "hidak.json"
    if not CITY or not path_.exists():
        return {}
    grid = defaultdict(list)
    for h in json.load(open(path_, encoding="utf-8")).get("hidak", []):
        r = float(h.get("hw") or 8.0) + 6.0
        for x, z in h.get("tengely", []):
            grid[(int(x // 40), int(z // 40))].append((x, z, r))
    return grid


def bridge_under(grid, x, z):
    cx, cz = int(x // 40), int(z // 40)
    for dx in (-1, 0, 1):
        for dz in (-1, 0, 1):
            for px, pz, r in grid.get((cx + dx, cz + dz), ()):
                if (px - x) ** 2 + (pz - z) ** 2 <= r * r:
                    return True
    return False


def known_statistics(ep):
    """The numbers of the About window: how many different buildings have an exact year, and how many different buildings there are. Several
    outlines of one building (OSM element) and the parts of a building drawn from parts count as one building; bridge elements and ruins do not count."""
    def building_key(e):
        pr = e["pr"]
        if pr.get("resz") and pr.get("szulo_id"):
            return (pr.get("szulo_tipus") or "way", pr["szulo_id"])
        return (pr.get("osm_tipus") or "way", pr.get("id"))
    unique = {building_key(e) for e in ep}
    known = {building_key(e) for e in ep if e["ev"] is not None and not e["rom"]}
    return {"epulet_egyedi": len(unique), "ismert_ev_epulet": len(known)}


def random_(building_key):
    """A value between 0 and 1 computed from the id (so always the same)."""
    return (zlib.crc32(building_key.encode()) % 10000 + 0.5) / 10000


def main():
    path_ = DATA / ("varos/epuletek_vegleges.geojson" if CITY else "belvaros_epuletek_vegleges.geojson")
    print(f"Beolvasás: {path_}")
    gj = json.load(open(path_, encoding="utf-8"))
    ep = []
    bridge_grid = bridge_axes()
    bridge_hidden = 0
    for f in gj["features"]:
        pr = f["properties"]
        polyk = polygons(f["geometry"])
        if not polyk:
            continue
        kp = [center(p) for p in polyk]
        x = sum(p[0] for p in kp) / len(kp)
        z = sum(p[1] for p in kp) / len(kp)
        if bridge_grid and bridge_under(bridge_grid, x, z):      # the OSM bridge building (pier, stone tower) in place of the dedicated bridge model
            bridge_hidden += 1
            continue
        year = pr.get("ev")
        try:
            year = int(year) if year not in (None, "") else None
        except (TypeError, ValueError):
            year = None
        if year is not None and not (1 <= year <= NOW):
            year = None
        ruin = bool(pr.get("rom"))
        if ruin:
            year = None
        ep.append({"pr": pr, "poly": polyk, "x": x, "z": z, "ev": year, "rom": ruin,
                   "est": None if ruin else pr.get("ev_becsles_korszak"), "ev_kep": None, "fajta": None, "kor": None})
    print(f"Épületek: {len(ep)}" + (f" (a Duna-hidak alatt/helyén kihagyva: {bridge_hidden} OSM-épület, mert a hidakat a saját modell mutatja)" if bridge_grid else ""))
    gj = None

    # grid for the neighbour search
    grid = defaultdict(list)
    for i, e in enumerate(ep):
        grid[(int(e["x"] // NEIGHBOR_M), int(e["z"] // NEIGHBOR_M))].append(i)

    def near(e, condition, radius=NEIGHBOR_M):
        cx, cz = int(e["x"] // NEIGHBOR_M), int(e["z"] // NEIGHBOR_M)
        r = int(math.ceil(radius / NEIGHBOR_M))
        out = []
        for dx in range(-r, r + 1):
            for dz in range(-r, r + 1):
                for j in grid.get((cx + dx, cz + dz), ()):
                    o = ep[j]
                    if condition(o) and math.hypot(o["x"] - e["x"], o["z"] - e["z"]) <= radius:
                        out.append(j)
        return out

    # 0) ruins (ancient, medieval remains): they go into the "before 1867" era, are visible from the first year, and affect nothing else
    for e in ep:
        if e["rom"]:
            e["ev_kep"], e["fajta"], e["kor"] = FIRST_YEAR_MIN, 0, RUIN_ERA

    # 1) known years
    known_per_era = defaultdict(list)
    for e in ep:
        if e["ev"]:
            e["ev_kep"], e["fajta"] = e["ev"], 0
            e["kor"] = era_year_according_to(e["ev"])
            known_per_era[e["kor"]].append(e["ev"])

    # 2) buildings of estimated era: a year from the nearby known years of the same era
    estimated = 0
    for e in ep:
        if e["fajta"] is not None or e["est"] is None:
            continue
        k = int(e["est"])
        nearby = [ep[j]["ev"] for j in near(e, lambda o, k=k: o["ev"] and o["kor"] == k)]
        list_ = sorted(nearby) if nearby else sorted(known_per_era.get(k, []))
        if not list_:
            from_, to = ERAS[k][0], min(ERAS[k][1], NOW)
            list_ = [(from_ + to) // 2]
        q = random_(f'{e["pr"].get("osm_tipus")}{e["pr"]["id"]}')
        e["ev_kep"], e["fajta"], e["kor"] = list_[min(int(q * len(list_)), len(list_) - 1)], 1, k
        estimated += 1

    # 3) the rest (e.g. building parts without an estimate): they get the year of the nearest building that already has one
    remainder = [e for e in ep if e["fajta"] is None]
    if CITY:
        # in the whole city many buildings have no year: they get the year of the nearest building with a known (or estimated) year,
        # for this a separate grid is built from the known ones only (for fast lookup)
        repeat = defaultdict(list)
        for e in ep:
            if e["fajta"] is not None and not e["rom"]:
                repeat[(int(e["x"] // NEIGHBOR_M), int(e["z"] // NEIGHBOR_M))].append(e)
        # the parts (building:part) of one building get an era together: that of the building nearest to the parts' common centre.
        # Earlier each part was searched separately, and the parts of one house could get different colours (42 buildings).
        grp_ = defaultdict(list)
        distant = 0
        for e in remainder:
            sz = e["pr"].get("szulo_id")
            grp_[(e["pr"].get("szulo_tipus"), sz) if sz else id(e)].append(e)
        for members in grp_.values():
            e = {"x": sum(t["x"] for t in members) / len(members), "z": sum(t["z"] for t in members) / len(members)}
            cx, cz = int(e["x"] // NEIGHBOR_M), int(e["z"] // NEIGHBOR_M)
            for radius in (NEIGHBOR_M, 400.0, 1500.0):
                r = int(math.ceil(radius / NEIGHBOR_M))
                best, distance = None, radius
                for dx in range(-r, r + 1):
                    for dz in range(-r, r + 1):
                        for o in repeat.get((cx + dx, cz + dz), ()):
                            dd = math.hypot(o["x"] - e["x"], o["z"] - e["z"])
                            if dd <= distance:
                                best, distance = o, dd
                if best:
                    value = (best["ev_kep"], best["kor"], 2)
                    break
            else:
                value = (1890, 1, 2)
                distant += len(members)
            for t in members:
                t["ev_kep"], t["kor"], t["fajta"] = value
        if distant:
            print(f"  Figyelem: {distant} épületnek 1500 m-en belül sincs korszakos szomszédja: 1890-et kapott")
    for e in ([] if CITY else remainder):
        for radius in (NEIGHBOR_M, 400.0, 1500.0):
            sign = near(e, lambda o: o["fajta"] is not None and o is not e and not o["rom"], radius)
            if sign:
                j = min(sign, key=lambda j: math.hypot(ep[j]["x"] - e["x"], ep[j]["z"] - e["z"]))
                e["ev_kep"], e["kor"] = ep[j]["ev_kep"], ep[j]["kor"]
                e["fajta"] = 2
                break
        else:
            e["ev_kep"], e["kor"], e["fajta"] = 1890, 1, 2
    print(f"  ismert év: {sum(1 for e in ep if e['fajta'] == 0)}, becsült korszak: {estimated}, "
          f"szomszédtól átvett: {len(remainder)}")

    # terrain
    terrain = None
    water = None
    water_path = DATA / ("varos/viz_zold.json" if CITY else "viz_zold.json")
    if water_path.exists():
        water = json.load(open(water_path, encoding="utf-8"))
        print(f"  víz és parkok: {len(water)} sokszög ({water_path})")
    else:
        print(f"  (nincs {water_path}: víz és parkok nélkül)")
    if Terrain is None:
        print("  (nincs dem.py: domborzat nélkül)")
    else:
        try:
            terrain = Terrain_(ep, water)
            print(f"  domborzat: {terrain.nx}x{terrain.nz} pont, a Duna szintje {terrain.ref:.1f} m "
                  f"({terrain.vizi_cellak} vízminta), az SRTM értékei {terrain.dsm_stat[0]:.0f}-{terrain.dsm_stat[1]:.0f} m")
        except FaultyFile as error_:
            print(f"  (domborzat nélkül: {error_})")
    for e in ep:
        e["base"] = 0.0
        if terrain:
            e["base"] = min(terrain.ground(x, z) for poly in e["poly"] for (x, z) in poly[0])

    # number of storeys for every element; the parts (building:part) of one building get the largest number of storeys,
    # so that in the storeys view the whole building has one colour (e.g. the Parliament)
    for e in ep:
        pr = e["pr"]
        level = pr.get("szintek")
        try:
            level = int(round(float(level))) if level not in (None, "") else None
        except (TypeError, ValueError):
            level = None
        if not level:
            level = int(round(max(3.0, float(pr.get("magassag") or 12.0)) / 3.2))
        elif pr.get("magassag_forras") == "height":
            # the storeys view's colour should follow the actual height: data that records few storeys (e.g. a church with 4 'storeys',
            # 96 m tall) should not light up pale next to equally tall but multi-storey buildings
            try:
                level = max(level, int(round(float(pr["magassag"]) / 3.2)))
            except (TypeError, ValueError, KeyError):
                pass
        e["szint"] = max(1, min(127, level))
    group_ = defaultdict(int)
    for e in ep:
        if e["pr"].get("szulo_id"):
            k = (e["pr"].get("szulo_tipus"), e["pr"]["szulo_id"])
            group_[k] = max(group_[k], e["szint"])
    for e in ep:
        if e["pr"].get("szulo_id"):
            e["szint"] = group_[(e["pr"].get("szulo_tipus"), e["pr"]["szulo_id"])]

    # tiles
    tiles = defaultdict(list)
    for gid, e in enumerate(ep):
        e["gid"] = gid
        tiles[(int(e["x"] // TILE), int(e["z"] // TILE))].append(e)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    pack = bytearray()
    register = []
    histogram = defaultdict(lambda: [0] * len(ERAS))
    year_min = NOW
    for (tx, tz), list_ in sorted(tiles.items()):
        ox, oz = tx * TILE, tz * TILE
        gid_, year_, flag_, per_, flo_, en_, l0_, l1_ = (array("I"), array("h"), array("B"), array("B"),
                                                         array("B"), array("B"), array("I"), array("I"))
        part_start, core_, ring_start, vertex_start, hole_ = (array("I", [0]), array("f"), array("I", [0]),
                                                           array("I", [0]), array("B"))
        xz_, y_ = array("h"), array("h")
        for e in list_:
            pr = e["pr"]
            h = float(pr.get("magassag") or 12.0)
            h = max(3.0, h)
            level = e["szint"]
            gid_.append(e["gid"])
            year_.append(max(FIRST_YEAR_MIN, int(e["ev_kep"])))   # buildings from before 1700 also appear in the first year
            flag_.append(e["fajta"])
            per_.append(e["kor"])
            flo_.append(level)
            en_.append(0)
            l0_.append(int(round((e["base"] + 100) * 10)))   # base height in dm, with a +100 m offset
            l1_.append(0)
            year_min = min(year_min, e["ev_kep"])
            histogram[e["ev_kep"]][e["kor"]] += 1
            for poly in e["poly"]:
                core_.append(h)
                for k, ring_ in enumerate(poly):
                    for (x, z) in ring_:
                        xz_.append(max(-32768, min(32767, int(round((x - ox) * 10)))))
                        xz_.append(max(-32768, min(32767, int(round((z - oz) * 10)))))
                        y_.append(0)
                    vertex_start.append(len(y_))
                    hole_.append(0 if k == 0 else 1)
                ring_start.append(len(hole_))
            part_start.append(len(core_))

        def pad(b):
            return b + b"\0" * (-len(b) % 4)

        def bytes_(a):
            if sys.byteorder != "little":
                a = array(a.typecode, a)
                a.byteswap()
            return pad(a.tobytes())

        head = struct.pack("<IIIIIff", MAGIC, len(gid_), len(core_), len(hole_), len(y_), float(ox), float(oz))
        tile = head
        for a in (gid_, year_, flag_, per_, flo_, en_, l0_, l1_, part_start, core_, ring_start, vertex_start,
                  hole_, xz_, y_):
            tile += bytes_(a)
        register.append({"file": f"{tx}_{tz}", "pack": "tiles.bin", "offset": len(pack), "length": len(tile)})
        pack += tile
    (OUTPUT / "tiles.bin").write_bytes(bytes(pack))

    # the card's data
    records = []
    images = {}
    images_path = DATA / ("varos/commons_kepek.json" if CITY else "commons_kepek.json")
    if images_path.exists():
        images = json.load(open(images_path, encoding="utf-8"))
        print(f"  Commons-fotók: {len(images)} épületcsoport")
    for e in ep:
        pr = e["pr"]
        r = {k: pr[k] for k in CARD_FIELDS if pr.get(k) not in (None, "", False)}
        lat, lon = back(e["x"], e["z"])
        r["lat"], r["lon"] = (round(lat, 5), round(lon, 5)) if CITY else (round(lat, 6), round(lon, 6))
        if images:
            if pr.get("resz") and pr.get("szulo_id"):
                kk = f"{pr.get('szulo_tipus') or 'way'}:{pr['szulo_id']}"
            else:
                kk = f"{pr.get('osm_tipus') or 'way'}:{pr.get('id')}"
            k = images.get(kk)
            if k:
                r["kep"] = [k["f"], k.get("a", ""), k.get("l", ""), k.get("u", ""), k.get("m", ""), k.get("r", 0)]
        r["kor"] = e["kor"]
        records.append(r)
    (OUTPUT / "epuletek.json").write_text(json.dumps(records, ensure_ascii=False, separators=(",", ":")),
                                           encoding="utf-8")

    bridges_lechner()

    xs = [e["x"] for e in ep]
    zs = [e["z"] for e in ep]
    middle = ((min(xs) + max(xs)) / 2, (min(zs) + max(zs)) / 2)
    span = max(max(xs) - min(xs), max(zs) - min(zs))
    year_min = max(FIRST_YEAR_MIN, year_min)
    config = {
        "name": "Budapest, épületenként",
        "yearMin": int(year_min), "yearMax": NOW,
        "periods": [{"from": a, "to": b, "label": hu, "label_en": en, "color": color}
                    for a, b, hu, en, color in ERAS],
        "home": ({"x": 340, "z": 1100, "azimuth": -40, "elevation": 24, "span": 3300} if CITY else
                 {"x": round(middle[0]), "z": round(middle[1]), "azimuth": 20, "elevation": 38, "span": round(span * 0.9)}),
        "stats": {"buildings": len(ep), **known_statistics(ep)},
        "packs": ["tiles.bin"], "tiles": register,
        "histogram": {str(max(y, year_min)): v for y, v in sorted(histogram.items())},
    }
    # years below ev_min (if there were any) go into the first year
    hist = defaultdict(lambda: [0] * len(ERAS))
    for y, v in histogram.items():
        yy = max(y, int(year_min))
        for i, c in enumerate(v):
            hist[yy][i] += c
    config["histogram"] = {str(y): v for y, v in sorted(hist.items())}
    if terrain:
        terrain.write(OUTPUT)
        config["terep"] = {"van": True, "ref": terrain.ref, "kep": terrain.van_kep,
                           "x0": terrain.x0, "z0": terrain.z0, "w": terrain.x1 - terrain.x0 + 0.0, "h": terrain.z1 - terrain.z0 + 0.0,
                           "eszrevetel": "SRTM: NASA, Shuttle Radar Topography Mission"}
        bases = sorted(e["base"] for e in ep)
        print(f"  épület-talpmagasság: 0-{bases[-1]:.0f} m, medián {bases[len(bases) // 2]:.1f} m")
    (OUTPUT / "budapest.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

    size = (OUTPUT / "tiles.bin").stat().st_size
    print(f"Csempék: {len(register)}, tiles.bin: {size // 1024} KB")
    print(f"Kész: {OUTPUT}/ (a 3D nézet: terkep3d/index.html, kiszolgálva a szerkesztő szerverrel)")


if __name__ == "__main__":
    main()
