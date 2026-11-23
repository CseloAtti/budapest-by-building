"""
budapest_pbf.py - Budapest's building stock from a single OSM extract (without Overpass).

Run (in the project folder):   py budapest_pbf.py
  or with an already downloaded file:        py budapest_pbf.py path\\file.osm.pbf

What does it do?
  1. Downloads the Budapest extract (BBBike, about 100-200 MB), and if that does not cover the city, Geofabrik's
     Hungary extract (about 350 MB). The download resumes after an interruption.
  2. Reads the buildings, building parts and address points from it (own PBF reader, only the Python standard library is needed).
  2b. Also reads the boundaries of the 23 districts (data/kerulethatarok.json), for pairing addresses per district.
  3. Saves the elements within the city boundary (data/budapest_hatar.json) in the same format as the Overpass downloader:
     data/budapest_nyers/pbf_<i>_<j>.json.gz   (each element once, with no cell-boundary duplicates)

The city boundary has already been downloaded by download_budapest.py (data/budapest_hatar.json). If the Overpass downloader is also
running meanwhile, no problem: the processor filters out duplicates by type+id anyway.
The log: data/budapest_pbf_naplo.txt. Running time: about 10-30 minutes, memory: 1-2 GB.
"""
import gzip
import json
import re
import struct
import sys
import time
import urllib.request
import zlib
from pathlib import Path

DATA = Path("data")
RAW = DATA / "budapest_nyers"
BOUNDARY = DATA / "budapest_hatar.json"
PBF_FOLDER = DATA / "pbf"
LOG = DATA / "budapest_pbf_naplo.txt"
UA = {"User-Agent": "budapest-by-building/0.1 (https://github.com/CseloAtti/budapest-by-building; oktatasi projekt)"}
SOURCES = [("BBBike Budapest", "https://download.bbbike.org/osm/bbbike/Budapest/Budapest.osm.pbf", "bbbike_budapest.osm.pbf"),
            ("Geofabrik Magyarország", "https://download.geofabrik.de/europe/hungary-latest.osm.pbf", "geofabrik_hungary.osm.pbf")]
MARGIN = 0.02            # degrees; the strip around the city boundary whose nodes we keep
CELL_LAT = 0.01
CELL_LON = 0.015
UNIT = 1e7            # nodes are stored in units of 1e-7 degrees


def log(message):
    row = time.strftime("%Y-%m-%d %H:%M:%S ") + str(message)
    print(row, flush=True)
    LOG.parent.mkdir(exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(row + "\n")


def keep_awake():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
        except Exception:
            pass


# ---------- protobuf ----------
def varint(b, p):
    x = 0
    s = 0
    while True:
        c = b[p]
        p += 1
        x |= (c & 0x7F) << s
        if c < 0x80:
            return x, p
        s += 7


def fields(b):
    """(field_number, type, value) triples from a message. type 0: number, 2: bytes, 1/5: raw bytes."""
    p = 0
    n = len(b)
    while p < n:
        k, p = varint(b, p)
        f, t = k >> 3, k & 7
        if t == 0:
            v, p = varint(b, p)
        elif t == 2:
            l, p = varint(b, p)
            v = b[p:p + l]
            p += l
        elif t == 1:
            v = b[p:p + 8]
            p += 8
        elif t == 5:
            v = b[p:p + 4]
            p += 4
        else:
            raise ValueError("ismeretlen protobuf-típus")
        yield f, t, v


def packed(b):
    out = []
    p = 0
    n = len(b)
    while p < n:
        v, p = varint(b, p)
        out.append(v)
    return out


def zigzag(v):
    return (v >> 1) ^ -(v & 1)


def delta(list_):
    s = 0
    out = []
    for v in list_:
        s += zigzag(v)
        out.append(s)
    return out


def blocks(path_):
    """The blocks of the PBF file: (type, decompressed data)."""
    with open(path_, "rb") as f:
        while True:
            h = f.read(4)
            if len(h) < 4:
                return
            hl = struct.unpack(">I", h)[0]
            head = f.read(hl)
            type_ = None
            size = 0
            for sz, t, v in fields(head):
                if sz == 1:
                    type_ = bytes(v).decode()
                elif sz == 3:
                    size = v
            blob = f.read(size)
            data_ = None
            for sz, t, v in fields(blob):
                if sz == 1:
                    data_ = bytes(v)
                elif sz == 3:
                    data_ = zlib.decompress(bytes(v))
            yield type_, data_


def block_read(data_):
    """One PrimitiveBlock: (strings, granularity, lat_offset, lon_offset, groups)."""
    dict_ = []
    grain = 100
    lat0 = lon0 = 0
    groups = []
    for sz, t, v in fields(data_):
        if sz == 1:
            dict_ = [bytes(x).decode("utf-8", "replace") for s2, t2, x in fields(v) if s2 == 1]
        elif sz == 2:
            groups.append(v)
        elif sz == 17:
            grain = v
        elif sz == 19:
            lat0 = v if v < (1 << 63) else v - (1 << 64)
        elif sz == 20:
            lon0 = v if v < (1 << 63) else v - (1 << 64)
    return dict_, grain, lat0, lon0, groups


def labels(dict_, keys, values_):
    return {dict_[k]: dict_[v] for k, v in zip(keys, values_)}


def header_bbox(path_):
    """The bounding rectangle given in the file header: (south, west, north, east) in degrees, or None."""
    for type_, data_ in blocks(path_):
        if type_ == "OSMHeader":
            for sz, t, v in fields(data_):
                if sz == 1:
                    value = {}
                    for s2, t2, x in fields(v):
                        value[s2] = zigzag(x)
                    if all(k in value for k in (1, 2, 3, 4)):
                        return (value[4] / 1e9, value[1] / 1e9, value[3] / 1e9, value[2] / 1e9)
        return None


# ---------- pass 1: the building relations ----------
def building_e(label):
    return (("building" in label and label["building"] != "roof") or
            ("building:part" in label and label["building:part"] != "roof"))


ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50}


def roman_number(s):
    total = 0
    values_ = [ROMAN[c] for c in s]
    for i, v in enumerate(values_):
        total += -v if i + 1 < len(values_) and v < values_[i + 1] else v
    return total


def district_number(c):
    """The number of a Budapest district from the tags of an admin_level=9 relation ('XIII. kerület' -> 13), or None."""
    if c.get("boundary") != "administrative" or c.get("admin_level") != "9":
        return None
    m = re.search(r"\b([IVXL]+)\.?\s*ker", c.get("name", ""))
    if m:
        return roman_number(m.group(1))
    m = re.match(r"\d+", c.get("ref", "") or "")
    return int(m.group()) if m else None


def water_green_kind(c):
    """'viz' is the Danube and the lakes, 'park' is parks and lawns (the same rules as in download_water.py)."""
    if c.get("natural") == "water" or c.get("waterway") == "riverbank":
        return "viz"
    if c.get("leisure") in ("park", "garden") or c.get("landuse") in ("grass", "recreation_ground"):
        return "park"
    return None


def pass_connections(path_):
    connections = {}
    members = set()
    water_relations = {}             # id -> (kind, [(way id, role)])
    districts = {}          # district number -> [(way id, role)]
    for type_, data_ in blocks(path_):
        if type_ != "OSMData":
            continue
        dict_, grain, lat0, lon0, groups = block_read(data_)
        for cs in groups:
            for sz, t, v in fields(cs):
                if sz != 4:
                    continue
                id_ = 0
                keys = values_ = roles = ids_ = types_ = []
                for s2, t2, x in fields(v):
                    if s2 == 1:
                        id_ = x
                    elif s2 == 2:
                        keys = packed(x)
                    elif s2 == 3:
                        values_ = packed(x)
                    elif s2 == 8:
                        roles = packed(x)
                    elif s2 == 9:
                        ids_ = delta(packed(x))
                    elif s2 == 10:
                        types_ = packed(x)
                c = labels(dict_, keys, values_)
                kn = district_number(c)
                if kn:
                    districts[kn] = [(mid, dict_[sid]) for sid, mid, mt in zip(roles, ids_, types_) if mt == 1]
                    members.update(mid for mid, _ in districts[kn])
                    continue
                vf = water_green_kind(c)
                if vf and not building_e(c):
                    tg = [(mid, dict_[sid]) for sid, mid, mt in zip(roles, ids_, types_) if mt == 1]
                    water_relations[id_] = (vf, tg)
                    members.update(mid for mid, _ in tg)
                    continue
                if not building_e(c):
                    continue
                tg = []
                for sid, mid, mt in zip(roles, ids_, types_):
                    if mt == 1:
                        tg.append((mid, dict_[sid]))
                        members.add(mid)
                connections[id_] = (c, tg)
    return connections, members, districts, water_relations


# ---------- pass 2: the nodes ----------
def pass_nodes(path_, box):
    """box = (south, west, north, east) in degrees. Returns: {id: lat*2^32+lon (in 1e-7 degrees, offset)}, address points."""
    d, ny, e, k = (int(round(x * UNIT)) for x in box)
    points = {}
    address_points = []
    count_ = 0
    for type_, data_ in blocks(path_):
        if type_ != "OSMData":
            continue
        dict_, grain, lat0, lon0, groups = block_read(data_)
        for cs in groups:
            for sz, t, v in fields(cs):
                if sz == 2:                       # dense nodes
                    ids_ = lat = lon = kv = None
                    for s2, t2, x in fields(v):
                        if s2 == 1:
                            ids_ = delta(packed(x))
                        elif s2 == 8:
                            lat = delta(packed(x))
                        elif s2 == 9:
                            lon = delta(packed(x))
                        elif s2 == 10:
                            kv = packed(x)
                    if ids_ is None:
                        continue
                    count_ += len(ids_)
                    # the tags: key, value, ..., 0 for every node
                    label_pos = {}
                    if kv:
                        i = 0
                        serial = 0
                        n = len(kv)
                        while i < n:
                            if kv[i] == 0:
                                i += 1
                                serial += 1
                            else:
                                j = i
                                while j < n and kv[j] != 0:
                                    j += 2
                                label_pos[serial] = kv[i:j]
                                i = j
                    for idx, (a, la, lo) in enumerate(zip(ids_, lat, lon)):
                        la_e = (lat0 + grain * la) // 100          # 1e-9 -> 1e-7 degrees
                        lo_e = (lon0 + grain * lo) // 100
                        if la_e < d or la_e > e or lo_e < ny or lo_e > k:
                            continue
                        points[a] = (la_e << 32) | lo_e
                        kp = label_pos.get(idx)
                        if kp:
                            c = {dict_[kp[q]]: dict_[kp[q + 1]] for q in range(0, len(kp), 2)}
                            if "addr:housenumber" in c and "addr:street" in c:
                                address_points.append({"type": "node", "id": a, "lat": la_e / UNIT, "lon": lo_e / UNIT, "tags": c})
                elif sz == 1:                     # sparse: a non-dense node
                    id_ = la = lo = 0
                    keys = values_ = []
                    for s2, t2, x in fields(v):
                        if s2 == 1:
                            id_ = zigzag(x)
                        elif s2 == 2:
                            keys = packed(x)
                        elif s2 == 3:
                            values_ = packed(x)
                        elif s2 == 8:
                            la = zigzag(x)
                        elif s2 == 9:
                            lo = zigzag(x)
                    la_e = (lat0 + grain * la) // 100
                    lo_e = (lon0 + grain * lo) // 100
                    if d <= la_e <= e and ny <= lo_e <= k:
                        points[id_] = (la_e << 32) | lo_e
                        c = labels(dict_, keys, values_)
                        if "addr:housenumber" in c and "addr:street" in c:
                            address_points.append({"type": "node", "id": id_, "lat": la_e / UNIT, "lon": lo_e / UNIT, "tags": c})
        if count_ and (count_ // 8000) % 100 == 0:
            pass
    return points, address_points


def point(code_):
    return {"lat": (code_ >> 32) / UNIT, "lon": (code_ & 0xFFFFFFFF) / UNIT}


# ---------- pass 3: the ways ----------
def pass_lines(path_, points, members):
    lines = {}      # id -> (tag, [point codes])
    waterlines = {}   # id -> kind (the water/park ways with their own tags)
    for type_, data_ in blocks(path_):
        if type_ != "OSMData":
            continue
        dict_, grain, lat0, lon0, groups = block_read(data_)
        for cs in groups:
            for sz, t, v in fields(cs):
                if sz != 3:
                    continue
                id_ = 0
                keys = values_ = references = []
                for s2, t2, x in fields(v):
                    if s2 == 1:
                        id_ = x
                    elif s2 == 2:
                        keys = packed(x)
                    elif s2 == 3:
                        values_ = packed(x)
                    elif s2 == 8:
                        references = x
                c = labels(dict_, keys, values_)
                building = building_e(c)
                vf = water_green_kind(c)
                if not building and not vf and id_ not in members:
                    continue
                refs = delta(packed(references))
                codes = [points.get(r) for r in refs]
                if None in codes:
                    if building:
                        continue
                    # water/park/boundary: from a way cut off at the extract's edge we keep the longest intact section
                    best, current = [], []
                    for q in codes + [None]:
                        if q is None:
                            if len(current) > len(best):
                                best = current
                            current = []
                        else:
                            current.append(q)
                    codes = best
                if len(codes) < 2:
                    continue
                lines[id_] = (c if building else {}, codes, building)
                if vf and not building:
                    waterlines[id_] = vf
    return lines, waterlines


def into_rings_append(sections, opened=None):
    sections = [list(s) for s in sections if len(s) >= 2]
    rings = []
    while sections:
        ring_ = sections.pop(0)
        while ring_[0] != ring_[-1]:
            for i, s in enumerate(sections):
                if s[0] == ring_[-1]:
                    ring_.extend(s[1:])
                elif s[-1] == ring_[-1]:
                    ring_.extend(reversed(s[:-1]))
                elif s[-1] == ring_[0]:
                    ring_ = s[:-1] + ring_
                elif s[0] == ring_[0]:
                    ring_ = list(reversed(s[1:])) + ring_
                else:
                    continue
                sections.pop(i)
                break
            else:
                break
        if ring_[0] == ring_[-1] and len(ring_) >= 4:
            rings.append(ring_)
        elif opened is not None and ring_[0] != ring_[-1]:
            opened.append(ring_)
    return rings


def distance_m(a, b):
    return ((a[0] - b[0]) * 76000.0) ** 2 + ((a[1] - b[1]) * 111000.0) ** 2


def outward(chain, at_end, length_m=4000.0):
    """The point beyond the end (vegen=True) or the start of the chain: in the direction of the final segment, hossz_m metres away."""
    if at_end:
        a, b = chain[-2], chain[-1]
    else:
        a, b = chain[1], chain[0]
    dx, dy = (b[0] - a[0]) * 76000.0, (b[1] - a[1]) * 111000.0
    n = (dx * dx + dy * dy) ** 0.5 or 1.0
    return [b[0] + dx / n * length_m / 76000.0, b[1] + dy / n * length_m / 111000.0]


def at_edge_has(p, box, band=0.02):
    return box is not None and (p[1] < box[0] + band or p[1] > box[2] - band or
                                  p[0] < box[1] + band or p[0] > box[3] - band)


def chains_closing(chains, max_m=2500.0, box=None):
    """Joining chains cut off at the extract's edge (e.g. the Danube's two banks): the nearest end points to each other,
    if they are closer than max_m metres; a lone chain closes on itself if its end is also close.
    If the join is at the extract's edge, the water extends along the line's direction beyond the extract too (the river continues),
    so it does not break off at the edge of the 3D terrain either."""
    chains = [list(l) for l in chains if len(l) >= 2]
    rings = []
    lim = max_m ** 2
    while chains:
        l = chains.pop(0)
        while True:
            best = None
            for i, m in enumerate(chains):
                for end_, start_ in ((l[-1], m[0]), (l[-1], m[-1])):
                    d = distance_m(end_, start_)
                    if d < lim and (best is None or d < best[0]):
                        best = (d, i, end_ is l[-1] and start_ is m[-1])
            if best is None:
                break
            _, i, translate = best
            m = chains.pop(i)
            if translate:
                m = m[::-1]
            if at_edge_has(l[-1], box) and at_edge_has(m[0], box):
                l = l + [outward(l, True), outward(m, False)] + m
            else:
                l = l + m
        if len(l) >= 4 and distance_m(l[0], l[-1]) < lim:
            if at_edge_has(l[-1], box) and at_edge_has(l[0], box):
                l = l + [outward(l, True), outward(l, False)]
            rings.append(l + [l[0]])
    return rings


def water_green_write(lines, waterlines, water_relations, box=None):
    """Polygons of water and parks -> data/varos/viz_zold.json (like the output of download_water.py, but for the whole city)."""
    list_ = []
    stat = {"viz": 0, "park": 0, "nem_zarhato": 0}

    def points(id_):
        return [[point(q)["lon"], point(q)["lat"]] for q in lines[id_][1]]

    for id_, f in waterlines.items():
        gy = points(id_)
        if len(gy) >= 4 and gy[0] == gy[-1]:
            list_.append({"fajta": f, "gyuruk": [gy]})
            stat[f] += 1
    for id_, (f, tg) in water_relations.items():
        outer = [points(m) for m, role in tg if m in lines and role != "inner"]
        inner = [points(m) for m, role in tg if m in lines and role == "inner"]
        open_ = []
        outer_ = into_rings_append(outer, open_)
        if open_:
            extra = chains_closing(open_, box=box)
            if extra:
                outer_ += extra
            else:
                stat["nem_zarhato"] += 1
        inner_ = into_rings_append(inner)
        for k in outer_:
            holes = [b for b in inner_ if point_in_ring_lonlat(b[0], k)]
            list_.append({"fajta": f, "gyuruk": [k] + holes})
            stat[f] += 1
    (DATA / "varos").mkdir(parents=True, exist_ok=True)
    (DATA / "varos" / "viz_zold.json").write_text(json.dumps(list_), encoding="utf-8")
    # diagnostics: the bounding box of the waters (whether the Danube and its branches end at the extract's edge)
    row = []
    for q in list_:
        if q["fajta"] != "viz":
            continue
        xs = [p[0] for g in q["gyuruk"][:1] for p in g]
        ys = [p[1] for g in q["gyuruk"][:1] for p in g]
        if len(xs) > 200:
            row.append(f"{len(xs)} pont; lat {min(ys):.4f}-{max(ys):.4f}; lon {min(xs):.4f}-{max(xs):.4f}")
    (DATA / "varos" / "viz_diagnosztika.txt").write_text("\n".join(sorted(row)), encoding="utf-8")
    log(f"   víz/park sokszögek: víz {stat['viz']}, park {stat['park']}, nem zárható kapcsolat: {stat['nem_zarhato']} "
          f"-> data/varos/viz_zold.json")


def point_in_ring_lonlat(p, ring_):
    return point_in_ring(p[0], p[1], [tuple(q) for q in ring_])


# ---------- city boundary ----------
def point_in_ring(x, y, ring_):
    inside = False
    for (x1, y1), (x2, y2) in zip(ring_, ring_[1:] + ring_[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


class Boundary:
    """A fast "is it in the city" test: a precomputed answer for the grid cells far from the boundary, an exact
    polygon test for the cells along the boundary."""
    R = 0.002

    def __init__(self, boundary):
        self.rings = [[tuple(p) for p in g] for g in boundary["gyuruk"]]
        self.hatar_cellak = set()
        self.bent_cache = {}
        for g in self.rings:
            for (x1, y1), (x2, y2) in zip(g, g[1:] + g[:1]):
                step = max(1, int(max(abs(x2 - x1), abs(y2 - y1)) / (self.R / 4)) + 1)
                for q in range(step + 1):
                    x = x1 + (x2 - x1) * q / step
                    y = y1 + (y2 - y1) * q / step
                    cx, cy = int(x // self.R), int(y // self.R)
                    for ax in (-1, 0, 1):
                        for ay in (-1, 0, 1):
                            self.hatar_cellak.add((cx + ax, cy + ay))

    def exact(self, lon, lat):
        return sum(point_in_ring(lon, lat, g) for g in self.rings) % 2 == 1 if len(self.rings) > 1 else \
            point_in_ring(lon, lat, self.rings[0])

    def inside(self, lon, lat):
        c = (int(lon // self.R), int(lat // self.R))
        if c in self.hatar_cellak:
            return self.exact(lon, lat)
        if c not in self.bent_cache:
            self.bent_cache[c] = self.exact((c[0] + 0.5) * self.R, (c[1] + 0.5) * self.R)
        return self.bent_cache[c]


# ---------- download ----------
def download(name_, url, path_):
    PBF_FOLDER.mkdir(parents=True, exist_ok=True)
    done = path_.with_suffix(path_.suffix + ".kesz")
    if done.exists() and path_.exists():
        return
    tmp = path_.with_suffix(path_.suffix + ".resz")
    log(f"letöltés: {name_} ({url})")
    for attempt in range(1, 11):
        has = tmp.stat().st_size if tmp.exists() else 0
        k = urllib.request.Request(url, headers={**UA, **({"Range": f"bytes={has}-"} if has else {})})
        try:
            with urllib.request.urlopen(k, timeout=120) as v:
                if has and v.status != 206:
                    has = 0
                with open(tmp, "ab" if has else "wb") as f:
                    last = time.time()
                    while True:
                        chunk = v.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
                        if time.time() - last > 30:
                            log(f"   letöltve: {f.tell() / 1e6:.0f} MB")
                            last = time.time()
            tmp.replace(path_)
            done.write_text("ok")
            log(f"   kész: {path_.stat().st_size / 1e6:.0f} MB")
            return
        except Exception as h:
            if getattr(h, "code", None) == 416 and tmp.exists():     # already complete
                tmp.replace(path_)
                done.write_text("ok")
                return
            log(f"   hiba ({type(h).__name__}: {h}); {attempt}. kísérlet, 60 s múlva újra")
            time.sleep(60)
    raise RuntimeError(f"{name_}: a letöltés nem sikerült")


def select_source(box):
    """The first extract whose header covers the city."""
    d, ny, e, k = box
    for name_, url, file in SOURCES:
        path_ = PBF_FOLDER / file
        try:
            download(name_, url, path_)
        except Exception as h:
            log(f"   {name_}: nem érhető el ({h})")
            continue
        fb = header_bbox(path_)
        if fb is None or (fb[0] <= d + 0.001 and fb[1] <= ny + 0.001 and fb[2] >= e - 0.001 and fb[3] >= k - 0.001):
            log(f"{name_}: a kivonat lefedi a várost (fejléc: {fb})")
            return path_
        log(f"{name_}: a kivonat NEM fedi le a teljes várost (fejléc: {fb}), a következő forrást próbálom")
    raise RuntimeError("Egyik forrás sem használható")


# ---------- main ----------
def main():
    keep_awake()
    log("=== Budapest épületei OSM-kivonatból ===")
    if not BOUNDARY.exists():
        raise SystemExit("Hiányzik a data/budapest_hatar.json - előbb a download_budapest.py városhatár-lépése kell (az már lefutott).")
    boundary = json.loads(BOUNDARY.read_text(encoding="utf-8"))
    hb = Boundary(boundary)
    d, ny, e, k = boundary["bbox"]
    box = (d - MARGIN, ny - MARGIN, e + MARGIN, k + MARGIN)

    path_ = Path(sys.argv[1]) if len(sys.argv) > 1 else select_source(box)
    # we keep the nodes from the whole area of the extract (at most up to 0.15 degrees around the city): so the Danube and
    # other long waters are not cut off in the strip around the city boundary
    fb = header_bbox(path_)
    if fb:
        box = (max(fb[0], d - 0.15), max(fb[1], ny - 0.15), min(fb[2], e + 0.15), min(fb[3], k + 0.15))
        log(f"csomópontok tárolása a kivonat teljes területén: {box}")
    t0 = time.time()

    log("1/3 menet: épület-kapcsolatok (többrészes épületek)")
    connections, members, districts, water_relations = pass_connections(path_)
    log(f"   {len(connections)} épület-kapcsolat, {len(members)} tagvonal, {len(districts)} kerülethatár ({(time.time() - t0) / 60:.1f} perc)")

    log("2/3 menet: csomópontok és címpontok (ez a leghosszabb)")
    points, address_points = pass_nodes(path_, box)
    log(f"   {len(points)} csomópont a város környékén, {len(address_points)} címpont ({(time.time() - t0) / 60:.1f} perc)")

    log("3/3 menet: épületvonalak")
    lines, waterlines = pass_lines(path_, points, members)
    log(f"   {len(lines)} vonal ({(time.time() - t0) / 60:.1f} perc)")

    water_green_write(lines, waterlines, water_relations, box)

    district_boundaries = {}
    for kn, members_ in sorted(districts.items()):
        sections = [[[point(q)["lon"], point(q)["lat"]] for q in lines[mid][1]]
                     for mid, role in members_ if mid in lines and role in ("outer", "")]
        rings = into_rings_append(sections)
        if rings:
            district_boundaries[str(kn)] = rings
    if district_boundaries:
        (DATA / "kerulethatarok.json").write_text(json.dumps(district_boundaries), encoding="utf-8")
    log(f"   kerülethatárok: {len(district_boundaries)}/23 kerület -> data/kerulethatarok.json")

    elements = []
    for id_, (c, codes, building) in lines.items():
        if building:
            elements.append({"type": "way", "id": id_, "tags": c, "geometry": [point(q) for q in codes]})
    for id_, (c, tg) in connections.items():
        members_ = []
        for mid, role in tg:
            v = lines.get(mid)
            if v:
                members_.append({"type": "way", "ref": mid, "role": role, "geometry": [point(q) for q in v[1]]})
        if members_:
            elements.append({"type": "relation", "id": id_, "tags": c, "members": members_})
    elements += address_points

    # filtering to the city boundary and sorting into cells (by the first point)
    cells = {}
    inside = 0
    for el in elements:
        if el["type"] == "node":
            lat, lon = el["lat"], el["lon"]
        elif el["type"] == "way":
            lat, lon = el["geometry"][0]["lat"], el["geometry"][0]["lon"]
        else:
            g = el["members"][0]["geometry"][0]
            lat, lon = g["lat"], g["lon"]
        if not hb.inside(lon, lat):
            continue
        inside += 1
        cells.setdefault((int(lat // CELL_LAT), int(lon // CELL_LON)), []).append(el)
    RAW.mkdir(parents=True, exist_ok=True)
    for r in RAW.glob("pbf_*.json.gz"):
        r.unlink()
    for (i, j), list_ in cells.items():
        tmp = RAW / f"pbf_{i}_{j}.tmp"
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump(list_, f, ensure_ascii=False)
        tmp.replace(RAW / f"pbf_{i}_{j}.json.gz")
    count_ = {}
    for el in elements:
        count_[el["type"]] = count_.get(el["type"], 0) + 1
    log(f"=== KÉSZ: {inside} elem a városhatáron belül ({len(cells)} cellafájl: data/budapest_nyers/pbf_*.json.gz); "
          f"összesen a kivonatban: {count_}; {(time.time() - t0) / 60:.1f} perc ===")


if __name__ == "__main__":
    main()
