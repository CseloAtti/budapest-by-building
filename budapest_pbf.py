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

ADAT = Path("data")
NYERS = ADAT / "budapest_nyers"
HATAR = ADAT / "budapest_hatar.json"
PBF_MAPPA = ADAT / "pbf"
NAPLO = ADAT / "budapest_pbf_naplo.txt"
UA = {"User-Agent": "budapest-by-building/0.1 (https://github.com/CseloAtti/budapest-by-building; oktatasi projekt)"}
FORRASOK = [("BBBike Budapest", "https://download.bbbike.org/osm/bbbike/Budapest/Budapest.osm.pbf", "bbbike_budapest.osm.pbf"),
            ("Geofabrik Magyarország", "https://download.geofabrik.de/europe/hungary-latest.osm.pbf", "geofabrik_hungary.osm.pbf")]
MARGO = 0.02            # degrees; the strip around the city boundary whose nodes we keep
CELLA_LAT = 0.01
CELLA_LON = 0.015
EGYSEG = 1e7            # nodes are stored in units of 1e-7 degrees


def naplo(uzenet):
    sor = time.strftime("%Y-%m-%d %H:%M:%S ") + str(uzenet)
    print(sor, flush=True)
    NAPLO.parent.mkdir(exist_ok=True)
    with open(NAPLO, "a", encoding="utf-8") as f:
        f.write(sor + "\n")


def ne_aludjon():
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


def mezok(b):
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


def csomagolt(b):
    ki = []
    p = 0
    n = len(b)
    while p < n:
        v, p = varint(b, p)
        ki.append(v)
    return ki


def cikcakk(v):
    return (v >> 1) ^ -(v & 1)


def delta(lista):
    s = 0
    ki = []
    for v in lista:
        s += cikcakk(v)
        ki.append(s)
    return ki


def blokkok(ut):
    """The blocks of the PBF file: (type, decompressed data)."""
    with open(ut, "rb") as f:
        while True:
            h = f.read(4)
            if len(h) < 4:
                return
            hl = struct.unpack(">I", h)[0]
            fej = f.read(hl)
            tipus = None
            meret = 0
            for sz, t, v in mezok(fej):
                if sz == 1:
                    tipus = bytes(v).decode()
                elif sz == 3:
                    meret = v
            blob = f.read(meret)
            adat = None
            for sz, t, v in mezok(blob):
                if sz == 1:
                    adat = bytes(v)
                elif sz == 3:
                    adat = zlib.decompress(bytes(v))
            yield tipus, adat


def blokk_olvasas(adat):
    """One PrimitiveBlock: (strings, granularity, lat_offset, lon_offset, groups)."""
    szotar = []
    gran = 100
    lat0 = lon0 = 0
    csoportok = []
    for sz, t, v in mezok(adat):
        if sz == 1:
            szotar = [bytes(x).decode("utf-8", "replace") for s2, t2, x in mezok(v) if s2 == 1]
        elif sz == 2:
            csoportok.append(v)
        elif sz == 17:
            gran = v
        elif sz == 19:
            lat0 = v if v < (1 << 63) else v - (1 << 64)
        elif sz == 20:
            lon0 = v if v < (1 << 63) else v - (1 << 64)
    return szotar, gran, lat0, lon0, csoportok


def cimkek(szotar, kulcsok, ertekek):
    return {szotar[k]: szotar[v] for k, v in zip(kulcsok, ertekek)}


def fejlec_bbox(ut):
    """The bounding rectangle given in the file header: (south, west, north, east) in degrees, or None."""
    for tipus, adat in blokkok(ut):
        if tipus == "OSMHeader":
            for sz, t, v in mezok(adat):
                if sz == 1:
                    ertek = {}
                    for s2, t2, x in mezok(v):
                        ertek[s2] = cikcakk(x)
                    if all(k in ertek for k in (1, 2, 3, 4)):
                        return (ertek[4] / 1e9, ertek[1] / 1e9, ertek[3] / 1e9, ertek[2] / 1e9)
        return None


# ---------- pass 1: the building relations ----------
def epulet_e(cimke):
    return (("building" in cimke and cimke["building"] != "roof") or
            ("building:part" in cimke and cimke["building:part"] != "roof"))


ROMAI = {"I": 1, "V": 5, "X": 10, "L": 50}


def romai_szam(s):
    ossz = 0
    ertekek = [ROMAI[c] for c in s]
    for i, v in enumerate(ertekek):
        ossz += -v if i + 1 < len(ertekek) and v < ertekek[i + 1] else v
    return ossz


def kerulet_szama(c):
    """The number of a Budapest district from the tags of an admin_level=9 relation ('XIII. kerület' -> 13), or None."""
    if c.get("boundary") != "administrative" or c.get("admin_level") != "9":
        return None
    m = re.search(r"\b([IVXL]+)\.?\s*ker", c.get("name", ""))
    if m:
        return romai_szam(m.group(1))
    m = re.match(r"\d+", c.get("ref", "") or "")
    return int(m.group()) if m else None


def vizzold_fajta(c):
    """'viz' is the Danube and the lakes, 'park' is parks and lawns (the same rules as in download_water.py)."""
    if c.get("natural") == "water" or c.get("waterway") == "riverbank":
        return "viz"
    if c.get("leisure") in ("park", "garden") or c.get("landuse") in ("grass", "recreation_ground"):
        return "park"
    return None


def menet_kapcsolatok(ut):
    kapcsolatok = {}
    tagok = set()
    vizrel = {}             # id -> (kind, [(way id, role)])
    keruletek = {}          # district number -> [(way id, role)]
    for tipus, adat in blokkok(ut):
        if tipus != "OSMData":
            continue
        szotar, gran, lat0, lon0, csoportok = blokk_olvasas(adat)
        for cs in csoportok:
            for sz, t, v in mezok(cs):
                if sz != 4:
                    continue
                azon = 0
                kulcsok = ertekek = szerepek = azonok = tipusok = []
                for s2, t2, x in mezok(v):
                    if s2 == 1:
                        azon = x
                    elif s2 == 2:
                        kulcsok = csomagolt(x)
                    elif s2 == 3:
                        ertekek = csomagolt(x)
                    elif s2 == 8:
                        szerepek = csomagolt(x)
                    elif s2 == 9:
                        azonok = delta(csomagolt(x))
                    elif s2 == 10:
                        tipusok = csomagolt(x)
                c = cimkek(szotar, kulcsok, ertekek)
                kn = kerulet_szama(c)
                if kn:
                    keruletek[kn] = [(mid, szotar[sid]) for sid, mid, mt in zip(szerepek, azonok, tipusok) if mt == 1]
                    tagok.update(mid for mid, _ in keruletek[kn])
                    continue
                vf = vizzold_fajta(c)
                if vf and not epulet_e(c):
                    tg = [(mid, szotar[sid]) for sid, mid, mt in zip(szerepek, azonok, tipusok) if mt == 1]
                    vizrel[azon] = (vf, tg)
                    tagok.update(mid for mid, _ in tg)
                    continue
                if not epulet_e(c):
                    continue
                tg = []
                for sid, mid, mt in zip(szerepek, azonok, tipusok):
                    if mt == 1:
                        tg.append((mid, szotar[sid]))
                        tagok.add(mid)
                kapcsolatok[azon] = (c, tg)
    return kapcsolatok, tagok, keruletek, vizrel


# ---------- pass 2: the nodes ----------
def menet_csomopontok(ut, doboz):
    """box = (south, west, north, east) in degrees. Returns: {id: lat*2^32+lon (in 1e-7 degrees, offset)}, address points."""
    d, ny, e, k = (int(round(x * EGYSEG)) for x in doboz)
    pontok = {}
    cimpontok = []
    db = 0
    for tipus, adat in blokkok(ut):
        if tipus != "OSMData":
            continue
        szotar, gran, lat0, lon0, csoportok = blokk_olvasas(adat)
        for cs in csoportok:
            for sz, t, v in mezok(cs):
                if sz == 2:                       # dense nodes
                    azonok = lat = lon = kv = None
                    for s2, t2, x in mezok(v):
                        if s2 == 1:
                            azonok = delta(csomagolt(x))
                        elif s2 == 8:
                            lat = delta(csomagolt(x))
                        elif s2 == 9:
                            lon = delta(csomagolt(x))
                        elif s2 == 10:
                            kv = csomagolt(x)
                    if azonok is None:
                        continue
                    db += len(azonok)
                    # the tags: key, value, ..., 0 for every node
                    cimke_poz = {}
                    if kv:
                        i = 0
                        sorsz = 0
                        n = len(kv)
                        while i < n:
                            if kv[i] == 0:
                                i += 1
                                sorsz += 1
                            else:
                                j = i
                                while j < n and kv[j] != 0:
                                    j += 2
                                cimke_poz[sorsz] = kv[i:j]
                                i = j
                    for idx, (a, la, lo) in enumerate(zip(azonok, lat, lon)):
                        la_e = (lat0 + gran * la) // 100          # 1e-9 -> 1e-7 degrees
                        lo_e = (lon0 + gran * lo) // 100
                        if la_e < d or la_e > e or lo_e < ny or lo_e > k:
                            continue
                        pontok[a] = (la_e << 32) | lo_e
                        kp = cimke_poz.get(idx)
                        if kp:
                            c = {szotar[kp[q]]: szotar[kp[q + 1]] for q in range(0, len(kp), 2)}
                            if "addr:housenumber" in c and "addr:street" in c:
                                cimpontok.append({"type": "node", "id": a, "lat": la_e / EGYSEG, "lon": lo_e / EGYSEG, "tags": c})
                elif sz == 1:                     # sparse: a non-dense node
                    azon = la = lo = 0
                    kulcsok = ertekek = []
                    for s2, t2, x in mezok(v):
                        if s2 == 1:
                            azon = cikcakk(x)
                        elif s2 == 2:
                            kulcsok = csomagolt(x)
                        elif s2 == 3:
                            ertekek = csomagolt(x)
                        elif s2 == 8:
                            la = cikcakk(x)
                        elif s2 == 9:
                            lo = cikcakk(x)
                    la_e = (lat0 + gran * la) // 100
                    lo_e = (lon0 + gran * lo) // 100
                    if d <= la_e <= e and ny <= lo_e <= k:
                        pontok[azon] = (la_e << 32) | lo_e
                        c = cimkek(szotar, kulcsok, ertekek)
                        if "addr:housenumber" in c and "addr:street" in c:
                            cimpontok.append({"type": "node", "id": azon, "lat": la_e / EGYSEG, "lon": lo_e / EGYSEG, "tags": c})
        if db and (db // 8000) % 100 == 0:
            pass
    return pontok, cimpontok


def pont(kod):
    return {"lat": (kod >> 32) / EGYSEG, "lon": (kod & 0xFFFFFFFF) / EGYSEG}


# ---------- pass 3: the ways ----------
def menet_vonalak(ut, pontok, tagok):
    vonalak = {}      # id -> (tag, [point codes])
    vizvonalak = {}   # id -> kind (the water/park ways with their own tags)
    for tipus, adat in blokkok(ut):
        if tipus != "OSMData":
            continue
        szotar, gran, lat0, lon0, csoportok = blokk_olvasas(adat)
        for cs in csoportok:
            for sz, t, v in mezok(cs):
                if sz != 3:
                    continue
                azon = 0
                kulcsok = ertekek = hivatkozasok = []
                for s2, t2, x in mezok(v):
                    if s2 == 1:
                        azon = x
                    elif s2 == 2:
                        kulcsok = csomagolt(x)
                    elif s2 == 3:
                        ertekek = csomagolt(x)
                    elif s2 == 8:
                        hivatkozasok = x
                c = cimkek(szotar, kulcsok, ertekek)
                epulet = epulet_e(c)
                vf = vizzold_fajta(c)
                if not epulet and not vf and azon not in tagok:
                    continue
                refs = delta(csomagolt(hivatkozasok))
                kodok = [pontok.get(r) for r in refs]
                if None in kodok:
                    if epulet:
                        continue
                    # water/park/boundary: from a way cut off at the extract's edge we keep the longest intact section
                    legjobb, akt = [], []
                    for q in kodok + [None]:
                        if q is None:
                            if len(akt) > len(legjobb):
                                legjobb = akt
                            akt = []
                        else:
                            akt.append(q)
                    kodok = legjobb
                if len(kodok) < 2:
                    continue
                vonalak[azon] = (c if epulet else {}, kodok, epulet)
                if vf and not epulet:
                    vizvonalak[azon] = vf
    return vonalak, vizvonalak


def gyurukke_fuz(szakaszok, nyitottak=None):
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
        elif nyitottak is not None and gyuru[0] != gyuru[-1]:
            nyitottak.append(gyuru)
    return gyuruk


def tav_m(a, b):
    return ((a[0] - b[0]) * 76000.0) ** 2 + ((a[1] - b[1]) * 111000.0) ** 2


def kifele(lanc, vegen, hossz_m=4000.0):
    """The point beyond the end (vegen=True) or the start of the chain: in the direction of the final segment, hossz_m metres away."""
    if vegen:
        a, b = lanc[-2], lanc[-1]
    else:
        a, b = lanc[1], lanc[0]
    dx, dy = (b[0] - a[0]) * 76000.0, (b[1] - a[1]) * 111000.0
    n = (dx * dx + dy * dy) ** 0.5 or 1.0
    return [b[0] + dx / n * hossz_m / 76000.0, b[1] + dy / n * hossz_m / 111000.0]


def szelen_van(p, doboz, sav=0.02):
    return doboz is not None and (p[1] < doboz[0] + sav or p[1] > doboz[2] - sav or
                                  p[0] < doboz[1] + sav or p[0] > doboz[3] - sav)


def lancok_zarasa(lancok, max_m=2500.0, doboz=None):
    """Joining chains cut off at the extract's edge (e.g. the Danube's two banks): the nearest end points to each other,
    if they are closer than max_m metres; a lone chain closes on itself if its end is also close.
    If the join is at the extract's edge, the water extends along the line's direction beyond the extract too (the river continues),
    so it does not break off at the edge of the 3D terrain either."""
    lancok = [list(l) for l in lancok if len(l) >= 2]
    gyuruk = []
    lim = max_m ** 2
    while lancok:
        l = lancok.pop(0)
        while True:
            legjobb = None
            for i, m in enumerate(lancok):
                for vege, kezd in ((l[-1], m[0]), (l[-1], m[-1])):
                    d = tav_m(vege, kezd)
                    if d < lim and (legjobb is None or d < legjobb[0]):
                        legjobb = (d, i, vege is l[-1] and kezd is m[-1])
            if legjobb is None:
                break
            _, i, fordit = legjobb
            m = lancok.pop(i)
            if fordit:
                m = m[::-1]
            if szelen_van(l[-1], doboz) and szelen_van(m[0], doboz):
                l = l + [kifele(l, True), kifele(m, False)] + m
            else:
                l = l + m
        if len(l) >= 4 and tav_m(l[0], l[-1]) < lim:
            if szelen_van(l[-1], doboz) and szelen_van(l[0], doboz):
                l = l + [kifele(l, True), kifele(l, False)]
            gyuruk.append(l + [l[0]])
    return gyuruk


def vizzold_iras(vonalak, vizvonalak, vizrel, doboz=None):
    """Polygons of water and parks -> data/varos/viz_zold.json (like the output of download_water.py, but for the whole city)."""
    lista = []
    stat = {"viz": 0, "park": 0, "nem_zarhato": 0}

    def pontok(azon):
        return [[pont(q)["lon"], pont(q)["lat"]] for q in vonalak[azon][1]]

    for azon, f in vizvonalak.items():
        gy = pontok(azon)
        if len(gy) >= 4 and gy[0] == gy[-1]:
            lista.append({"fajta": f, "gyuruk": [gy]})
            stat[f] += 1
    for azon, (f, tg) in vizrel.items():
        kulso = [pontok(m) for m, szerep in tg if m in vonalak and szerep != "inner"]
        belso = [pontok(m) for m, szerep in tg if m in vonalak and szerep == "inner"]
        nyitott = []
        kulsok = gyurukke_fuz(kulso, nyitott)
        if nyitott:
            extra = lancok_zarasa(nyitott, doboz=doboz)
            if extra:
                kulsok += extra
            else:
                stat["nem_zarhato"] += 1
        belsok = gyurukke_fuz(belso)
        for k in kulsok:
            lyukak = [b for b in belsok if pont_gyuruben_lonlat(b[0], k)]
            lista.append({"fajta": f, "gyuruk": [k] + lyukak})
            stat[f] += 1
    (ADAT / "varos").mkdir(parents=True, exist_ok=True)
    (ADAT / "varos" / "viz_zold.json").write_text(json.dumps(lista), encoding="utf-8")
    # diagnostics: the bounding box of the waters (whether the Danube and its branches end at the extract's edge)
    sor = []
    for q in lista:
        if q["fajta"] != "viz":
            continue
        xs = [p[0] for g in q["gyuruk"][:1] for p in g]
        ys = [p[1] for g in q["gyuruk"][:1] for p in g]
        if len(xs) > 200:
            sor.append(f"{len(xs)} pont; lat {min(ys):.4f}-{max(ys):.4f}; lon {min(xs):.4f}-{max(xs):.4f}")
    (ADAT / "varos" / "viz_diagnosztika.txt").write_text("\n".join(sorted(sor)), encoding="utf-8")
    naplo(f"   víz/park sokszögek: víz {stat['viz']}, park {stat['park']}, nem zárható kapcsolat: {stat['nem_zarhato']} "
          f"-> data/varos/viz_zold.json")


def pont_gyuruben_lonlat(p, gyuru):
    return pont_gyuruben(p[0], p[1], [tuple(q) for q in gyuru])


# ---------- city boundary ----------
def pont_gyuruben(x, y, gyuru):
    bent = False
    for (x1, y1), (x2, y2) in zip(gyuru, gyuru[1:] + gyuru[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            bent = not bent
    return bent


class Hatar:
    """A fast "is it in the city" test: a precomputed answer for the grid cells far from the boundary, an exact
    polygon test for the cells along the boundary."""
    R = 0.002

    def __init__(self, hatar):
        self.gyuruk = [[tuple(p) for p in g] for g in hatar["gyuruk"]]
        self.hatar_cellak = set()
        self.bent_cache = {}
        for g in self.gyuruk:
            for (x1, y1), (x2, y2) in zip(g, g[1:] + g[:1]):
                lepes = max(1, int(max(abs(x2 - x1), abs(y2 - y1)) / (self.R / 4)) + 1)
                for q in range(lepes + 1):
                    x = x1 + (x2 - x1) * q / lepes
                    y = y1 + (y2 - y1) * q / lepes
                    cx, cy = int(x // self.R), int(y // self.R)
                    for ax in (-1, 0, 1):
                        for ay in (-1, 0, 1):
                            self.hatar_cellak.add((cx + ax, cy + ay))

    def pontos(self, lon, lat):
        return sum(pont_gyuruben(lon, lat, g) for g in self.gyuruk) % 2 == 1 if len(self.gyuruk) > 1 else \
            pont_gyuruben(lon, lat, self.gyuruk[0])

    def bent(self, lon, lat):
        c = (int(lon // self.R), int(lat // self.R))
        if c in self.hatar_cellak:
            return self.pontos(lon, lat)
        if c not in self.bent_cache:
            self.bent_cache[c] = self.pontos((c[0] + 0.5) * self.R, (c[1] + 0.5) * self.R)
        return self.bent_cache[c]


# ---------- download ----------
def letoltes(nev, url, ut):
    PBF_MAPPA.mkdir(parents=True, exist_ok=True)
    kesz = ut.with_suffix(ut.suffix + ".kesz")
    if kesz.exists() and ut.exists():
        return
    tmp = ut.with_suffix(ut.suffix + ".resz")
    naplo(f"letöltés: {nev} ({url})")
    for kiserlet in range(1, 11):
        van = tmp.stat().st_size if tmp.exists() else 0
        k = urllib.request.Request(url, headers={**UA, **({"Range": f"bytes={van}-"} if van else {})})
        try:
            with urllib.request.urlopen(k, timeout=120) as v:
                if van and v.status != 206:
                    van = 0
                with open(tmp, "ab" if van else "wb") as f:
                    utolso = time.time()
                    while True:
                        adag = v.read(1 << 20)
                        if not adag:
                            break
                        f.write(adag)
                        if time.time() - utolso > 30:
                            naplo(f"   letöltve: {f.tell() / 1e6:.0f} MB")
                            utolso = time.time()
            tmp.replace(ut)
            kesz.write_text("ok")
            naplo(f"   kész: {ut.stat().st_size / 1e6:.0f} MB")
            return
        except Exception as h:
            if getattr(h, "code", None) == 416 and tmp.exists():     # already complete
                tmp.replace(ut)
                kesz.write_text("ok")
                return
            naplo(f"   hiba ({type(h).__name__}: {h}); {kiserlet}. kísérlet, 60 s múlva újra")
            time.sleep(60)
    raise RuntimeError(f"{nev}: a letöltés nem sikerült")


def forras_kivalasztasa(doboz):
    """The first extract whose header covers the city."""
    d, ny, e, k = doboz
    for nev, url, fajl in FORRASOK:
        ut = PBF_MAPPA / fajl
        try:
            letoltes(nev, url, ut)
        except Exception as h:
            naplo(f"   {nev}: nem érhető el ({h})")
            continue
        fb = fejlec_bbox(ut)
        if fb is None or (fb[0] <= d + 0.001 and fb[1] <= ny + 0.001 and fb[2] >= e - 0.001 and fb[3] >= k - 0.001):
            naplo(f"{nev}: a kivonat lefedi a várost (fejléc: {fb})")
            return ut
        naplo(f"{nev}: a kivonat NEM fedi le a teljes várost (fejléc: {fb}), a következő forrást próbálom")
    raise RuntimeError("Egyik forrás sem használható")


# ---------- main ----------
def main():
    ne_aludjon()
    naplo("=== Budapest épületei OSM-kivonatból ===")
    if not HATAR.exists():
        raise SystemExit("Hiányzik a data/budapest_hatar.json - előbb a download_budapest.py városhatár-lépése kell (az már lefutott).")
    hatar = json.loads(HATAR.read_text(encoding="utf-8"))
    hb = Hatar(hatar)
    d, ny, e, k = hatar["bbox"]
    doboz = (d - MARGO, ny - MARGO, e + MARGO, k + MARGO)

    ut = Path(sys.argv[1]) if len(sys.argv) > 1 else forras_kivalasztasa(doboz)
    # we keep the nodes from the whole area of the extract (at most up to 0.15 degrees around the city): so the Danube and
    # other long waters are not cut off in the strip around the city boundary
    fb = fejlec_bbox(ut)
    if fb:
        doboz = (max(fb[0], d - 0.15), max(fb[1], ny - 0.15), min(fb[2], e + 0.15), min(fb[3], k + 0.15))
        naplo(f"csomópontok tárolása a kivonat teljes területén: {doboz}")
    t0 = time.time()

    naplo("1/3 menet: épület-kapcsolatok (többrészes épületek)")
    kapcsolatok, tagok, keruletek, vizrel = menet_kapcsolatok(ut)
    naplo(f"   {len(kapcsolatok)} épület-kapcsolat, {len(tagok)} tagvonal, {len(keruletek)} kerülethatár ({(time.time() - t0) / 60:.1f} perc)")

    naplo("2/3 menet: csomópontok és címpontok (ez a leghosszabb)")
    pontok, cimpontok = menet_csomopontok(ut, doboz)
    naplo(f"   {len(pontok)} csomópont a város környékén, {len(cimpontok)} címpont ({(time.time() - t0) / 60:.1f} perc)")

    naplo("3/3 menet: épületvonalak")
    vonalak, vizvonalak = menet_vonalak(ut, pontok, tagok)
    naplo(f"   {len(vonalak)} vonal ({(time.time() - t0) / 60:.1f} perc)")

    vizzold_iras(vonalak, vizvonalak, vizrel, doboz)

    kerulet_hatarok = {}
    for kn, tagsag in sorted(keruletek.items()):
        szakaszok = [[[pont(q)["lon"], pont(q)["lat"]] for q in vonalak[mid][1]]
                     for mid, szerep in tagsag if mid in vonalak and szerep in ("outer", "")]
        gyuruk = gyurukke_fuz(szakaszok)
        if gyuruk:
            kerulet_hatarok[str(kn)] = gyuruk
    if kerulet_hatarok:
        (ADAT / "kerulethatarok.json").write_text(json.dumps(kerulet_hatarok), encoding="utf-8")
    naplo(f"   kerülethatárok: {len(kerulet_hatarok)}/23 kerület -> data/kerulethatarok.json")

    elemek = []
    for azon, (c, kodok, epulet) in vonalak.items():
        if epulet:
            elemek.append({"type": "way", "id": azon, "tags": c, "geometry": [pont(q) for q in kodok]})
    for azon, (c, tg) in kapcsolatok.items():
        tagsag = []
        for mid, szerep in tg:
            v = vonalak.get(mid)
            if v:
                tagsag.append({"type": "way", "ref": mid, "role": szerep, "geometry": [pont(q) for q in v[1]]})
        if tagsag:
            elemek.append({"type": "relation", "id": azon, "tags": c, "members": tagsag})
    elemek += cimpontok

    # filtering to the city boundary and sorting into cells (by the first point)
    cellak = {}
    bent = 0
    for el in elemek:
        if el["type"] == "node":
            lat, lon = el["lat"], el["lon"]
        elif el["type"] == "way":
            lat, lon = el["geometry"][0]["lat"], el["geometry"][0]["lon"]
        else:
            g = el["members"][0]["geometry"][0]
            lat, lon = g["lat"], g["lon"]
        if not hb.bent(lon, lat):
            continue
        bent += 1
        cellak.setdefault((int(lat // CELLA_LAT), int(lon // CELLA_LON)), []).append(el)
    NYERS.mkdir(parents=True, exist_ok=True)
    for r in NYERS.glob("pbf_*.json.gz"):
        r.unlink()
    for (i, j), lista in cellak.items():
        tmp = NYERS / f"pbf_{i}_{j}.tmp"
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump(lista, f, ensure_ascii=False)
        tmp.replace(NYERS / f"pbf_{i}_{j}.json.gz")
    db = {}
    for el in elemek:
        db[el["type"]] = db.get(el["type"], 0) + 1
    naplo(f"=== KÉSZ: {bent} elem a városhatáron belül ({len(cellak)} cellafájl: data/budapest_nyers/pbf_*.json.gz); "
          f"összesen a kivonatban: {db}; {(time.time() - t0) / 60:.1f} perc ===")


if __name__ == "__main__":
    main()
