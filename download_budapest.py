"""
download_budapest.py - downloading Budapest's whole building stock and the location data of the Commons photos.
It can run unattended and can be resumed after an interruption.

Run (in the project folder):   py download_budapest.py

It performs three steps in order (it skips the finished steps and resumes an unfinished one from where it stopped):
  1. Download the city boundary (OSM)                   -> data/budapest_hatar.json
  2. Download the buildings, building parts and address points  -> data/budapest_nyers/*.json.gz (about 1 km cells)
  3. Search for Commons' geotagged files                -> data/cache/commons_geo_budapest.json
The log is in the data/budapest_letoltes_naplo.txt file. If the program stops with an error or the machine restarts,
just start it again with the same command.

Important: the machine must not go to sleep meanwhile! On Windows the program itself asks not to sleep while it runs, but the screen
may switch off. It uses the Overpass servers gently (a pause between two requests, waiting after an error).
Uses only the Python standard library.
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

DATA = Path("data")
RAW = DATA / "budapest_nyers"
BOUNDARY = DATA / "budapest_hatar.json"
LOG = DATA / "budapest_letoltes_naplo.txt"
SERVERS = ["https://overpass.kumi.systems/api/interpreter",
             "https://overpass.private.coffee/api/interpreter",
             "https://overpass-api.de/api/interpreter"]
UA = {"User-Agent": "budapest-by-building/0.1 (https://github.com/CseloAtti/budapest-by-building; oktatasi projekt)"}
CELL_LAT = 0.01          # kb. 1,1 km
CELL_LON = 0.015         # kb. 1,1 km
PAUSE = 4.0              # s, between two Overpass requests
MAX_DEPTH = 2           # if a cell is too large, it is split into quarters at most this many times


def log(message):
    row = time.strftime("%Y-%m-%d %H:%M:%S ") + str(message)
    print(row, flush=True)
    LOG.parent.mkdir(exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(row + "\n")


def keep_awake():
    """On Windows: while the program runs, the machine must not go into sleep mode."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)    # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        except Exception:
            pass


# ---------- Overpass ----------
def overpass(query, timeout_=240):
    """One Overpass query. Returns the elements; None if the server found it too large (remark/timeout);
    raises an exception if no server answers."""
    data_ = urllib.parse.urlencode({"data": query}).encode("utf-8")
    for era in range(4):
        for server in SERVERS:
            try:
                k = urllib.request.Request(server, data=data_, headers=UA)
                with urllib.request.urlopen(k, timeout=timeout_ + 60) as v:
                    j = json.load(v)
            except urllib.error.HTTPError as h:
                var = 60 * (era + 1) if h.code in (429, 502, 503, 504) else 15
                log(f"    {server.split('/')[2]}: HTTP {h.code}, várok {var} s")
                time.sleep(var)
                continue
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as h:
                log(f"    {server.split('/')[2]}: {type(h).__name__}")
                time.sleep(10)
                continue
            if j.get("remark"):
                if "timed out" in j["remark"] or "out of memory" in j["remark"] or "memory" in j["remark"]:
                    return None        # the cell is too large: it must be split
                log(f"    a szerver figyelmeztet: {j['remark'][:120]}")
                time.sleep(20)
                continue
            return j.get("elements", [])
        log("    minden szerver hibázott, 2 perc várakozás...")
        time.sleep(120)
    raise RuntimeError("Az Overpass-szerverek nem válaszolnak")


# ---------- 1. the city boundary ----------
def into_rings_append(sections):
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
    return rings


def area(gy):
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(gy, gy[1:] + gy[:1]))) / 2


def point_in_ring(x, y, ring_):
    inside = False
    for (x1, y1), (x2, y2) in zip(ring_, ring_[1:] + ring_[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def download_boundary():
    if BOUNDARY.exists():
        return json.loads(BOUNDARY.read_text(encoding="utf-8"))
    log("1. lépés: a városhatár letöltése")
    q = ('[out:json][timeout:120];relation["boundary"="administrative"]["name"="Budapest"]'
         '["admin_level"~"^(5|6|7)$"];out geom;')
    elements = overpass(q)
    best = None
    for e in elements or []:
        outer = [[(p["lon"], p["lat"]) for p in m["geometry"]] for m in e.get("members", [])
                 if m.get("type") == "way" and m.get("role") == "outer" and m.get("geometry")]
        rings = into_rings_append(outer)
        if rings:
            large = max(area(g) for g in rings)
            if best is None or large > best[0]:
                best = (large, rings, e.get("id"))
    if not best:
        raise RuntimeError("Nem találtam a városhatárt")
    rings = [[list(p) for p in g] for g in best[1]]
    data_ = {"osm_relacio": best[2], "gyuruk": rings,
            "bbox": [min(p[1] for g in rings for p in g), min(p[0] for g in rings for p in g),
                     max(p[1] for g in rings for p in g), max(p[0] for g in rings for p in g)]}
    BOUNDARY.write_text(json.dumps(data_), encoding="utf-8")
    log(f"   városhatár kész (relation {best[2]}), befoglaló téglalap: {data_['bbox']}")
    return data_


# ---------- 2. the buildings ----------
def cells(boundary):
    rings = [[tuple(p) for p in g] for g in boundary["gyuruk"]]
    del_, ny, north, east = boundary["bbox"]
    out = []
    for i in range(math.floor(del_ / CELL_LAT), math.ceil(north / CELL_LAT)):
        for j in range(math.floor(ny / CELL_LON), math.ceil(east / CELL_LON)):
            d, n = i * CELL_LAT, j * CELL_LON
            e, k = d + CELL_LAT, n + CELL_LON
            points = [(n + (k - n) * a / 6, d + (e - d) * b / 6) for a in range(7) for b in range(7)]
            inside = any(point_in_ring(x, y, g) for (x, y) in points for g in rings)
            if not inside:       # the boundary's vertex lies in the cell (a thin slice)
                inside = any(d <= p[1] <= e and n <= p[0] <= k for g in rings for p in g)
            if inside:
                out.append((i, j))
    return out


def building_query(d, n, e, k):
    bbox = f"{d:.6f},{n:.6f},{e:.6f},{k:.6f}"
    return (f'[out:json][timeout:240];'
            f'way["building"]["building"!="roof"]({bbox});out tags geom;'
            f'relation["building"]["building"!="roof"]({bbox});out body geom;'
            f'way["building:part"]["building:part"!="roof"]({bbox});out tags geom;'
            f'relation["building:part"]["building:part"!="roof"]({bbox});out body geom;'
            f'node["addr:housenumber"]["addr:street"]({bbox});out;')


def area_download(d, n, e, k, depth=0):
    """The elements of a rectangle; if the server finds it too large, it splits it into four parts."""
    elements = overpass(building_query(d, n, e, k))
    time.sleep(PAUSE)
    if elements is not None:
        return elements
    if depth >= MAX_DEPTH:
        raise RuntimeError(f"Egy cella túl nagy még bontva is: {d},{n},{e},{k}")
    log(f"    a cella túl nagy, négy részre bontom ({depth + 1}. szint)")
    kd, kn = (d + e) / 2, (n + k) / 2
    out = []
    for a, b, c, f in ((d, n, kd, kn), (d, kn, kd, k), (kd, n, e, kn), (kd, kn, e, k)):
        out += area_download(a, b, c, f, depth + 1)
    return out


def download_buildings(boundary):
    RAW.mkdir(parents=True, exist_ok=True)
    list_ = cells(boundary)
    missing = [c for c in list_ if not (RAW / f"c_{c[0]}_{c[1]}.json.gz").exists()]
    log(f"2. lépés: épületek letöltése: {len(list_)} cella, ebből {len(list_) - len(missing)} már megvan")
    start_ = time.time()
    for serial, (i, j) in enumerate(missing, 1):
        d, n = i * CELL_LAT, j * CELL_LON
        elements = area_download(d, n, d + CELL_LAT, n + CELL_LON)
        path_ = RAW / f"c_{i}_{j}.json.gz"
        tmp = path_.with_suffix(".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump(elements, f, ensure_ascii=False)
        tmp.replace(path_)
        if serial % 10 == 0 or serial == len(missing):
            elapsed = time.time() - start_
            back = elapsed / serial * (len(missing) - serial)
            log(f"   épületek: {serial}/{len(missing)} cella kész, kb. {back / 60:.0f} perc van hátra")
    # summary
    count_ = {"way": 0, "relation": 0, "node": 0}
    for path_ in RAW.glob("c_*.json.gz"):
        with gzip.open(path_, "rt", encoding="utf-8") as f:
            for e in json.load(f):
                count_[e["type"]] = count_.get(e["type"], 0) + 1
    log(f"   épületek kész: {len(list(RAW.glob('c_*.json.gz')))} cella; elemek (a cellahatárokon kétszer is lehet): {count_}")


# ---------- 3. Commons ----------
def download_commons(boundary):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import commons_images
    log("3. lépés: a Commons helyadatos fájljainak keresése (ez a leghosszabb, akár több óra)")
    commons_images.fetch_city_files([[tuple(p) for p in g] for g in boundary["gyuruk"]], log)


def step_retrying(name_, function, *args):
    """Unattended: if a step stops with an error, it retries after 10 minutes, at most 30 times."""
    for attempt in range(1, 31):
        try:
            return function(*args)
        except (SystemExit, Exception) as h:
            if isinstance(h, KeyboardInterrupt):
                raise
            log(f"!! {name_}: hiba ({type(h).__name__}: {h}); {attempt}. kísérlet, 10 perc múlva újra")
            time.sleep(600)
    raise SystemExit(f"{name_}: nem sikerült, indítsd újra később")


def main():
    keep_awake()
    log("=== Budapest letöltése indul ===")
    boundary = step_retrying("városhatár", download_boundary)
    step_retrying("épületek", download_buildings, boundary)
    step_retrying("Commons", download_commons, boundary)
    log("=== MINDEN LETÖLTÉS KÉSZ. Most jöhet a feldolgozás. ===")


if __name__ == "__main__":
    main()
