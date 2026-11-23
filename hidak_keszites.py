"""The bridges spanning the Danube and its branches -> schematic 3D data (terkep3d/data_varos/hidak.json)

What does it do?
  1. Downloads from OpenStreetMap (Overpass) the Danube and its branches (waterway, name ~ "Duna") and the bridges (bridge)
     that cross them (data/hidak_overpass.json; if the file exists it is not downloaded again, unless you ask: py hidak_keszites.py ujra).
  2. Groups the bridges crossing within Budapest's administrative boundary (data/budapest_hatar.json) (one bridge is several OSM lines:
     carriageways, tram and railway tracks, footpath and cycle path).
  3. Computes the bridge's height from the terrain mesh (terkep3d/data_varos/terrain.bin) and the Danube's level (over the water the
     clearance, on the bank the terrain), then adds a schematic structure: piers, pylons, chains/cables, arch or truss.
  4. Takes the bridge's data (name, year built, designer, Wikipedia article, structure) from forras/hidak_adatok.csv (you can edit it;
     matched by a name pattern), and failing that from the OSM tags (name, wikipedia, wikidata, start_date, bridge:structure).

Run (py csempek_keszites.py varos must be done first, because the terrain mesh comes from there):
    py hidak_keszites.py            (downloads the OSM data only the first time)
    py hidak_keszites.py ujra       (downloads the OSM data again)
    py hidak_keszites.py teszt      (self-check, without network and data)

Output: terkep3d/data_varos/hidak.json (+ data/hidak_jelentes.md). The 3D view (app.js, hidak.js) loads this.
"""
import csv
import json
import math
import re
import struct
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

LAT0, LON0 = 47.5015, 19.0515
COSLAT = math.cos(math.radians(LAT0))
BBOX = (47.34, 18.90, 47.65, 19.35)             # south, west, north, east
OVERPASS = ["https://overpass.kumi.systems/api/interpreter", "https://overpass.private.coffee/api/interpreter",
            "https://overpass-api.de/api/interpreter"]
NYERS = Path("data/hidak_overpass.json")
HATAR = Path("data/budapest_hatar.json")
TEREP = Path("terkep3d/data_varos/terrain.bin")
ADATOK = Path("forras/hidak_adatok.csv")
KIMENET = Path("terkep3d/data_varos/hidak.json")
JELENTES = Path("data/hidak_jelentes.md")

MIN_HOSSZ_M = 60.0          # a shorter crossing is not considered a bridge
LEPES_M = 10.0              # step of the deck's height profile
VIZ_MAGASSAG = 0.6          # m: terrain lower than this = water (terrain.bin takes the Danube's level as 0)
SZABAD_M = 9.0              # the deck's default height above the water
FUGGO_KABEL = False         # suspension bridges have no cable (only pylons and deck)
HAJO_PILLER_M = 65.0        # average pier spacing


def lok(lon, lat):
    return ((lon - LON0) * COSLAT * 111320.0, -(lat - LAT0) * 110574.0)


def ascii_(s):
    return unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()


# ---------------------------------------------------------------- download
LEKERDEZES = """[out:json][timeout:240];
way["waterway"~"^(river|canal)$"]["name"~"Duna"]({b})->.viz;
(way(around.viz:8)["bridge"]["bridge"!="no"]["highway"];
 way(around.viz:8)["bridge"]["bridge"!="no"]["railway"];)->.hidak;
.hidak out geom tags;
.viz out geom tags;"""


def letoltes(ujra=False):
    if NYERS.exists() and not ujra:
        return json.load(open(NYERS, encoding="utf-8"))
    adat = urllib.parse.urlencode({"data": LEKERDEZES.format(b=",".join(str(x) for x in BBOX))}).encode()
    utolso = None
    for kor in range(3):
        for url in OVERPASS:
            print(f"Letöltés: {url}")
            try:
                with urllib.request.urlopen(urllib.request.Request(url, data=adat, headers={"User-Agent": "budapest-by-building/0.1"}), timeout=300) as r:
                    d = json.load(r)
                NYERS.parent.mkdir(parents=True, exist_ok=True)
                json.dump(d, open(NYERS, "w", encoding="utf-8"), ensure_ascii=False)
                return d
            except (urllib.error.URLError, TimeoutError, ValueError) as e:
                utolso = e
                print(f"  nem sikerült: {e}")
                time.sleep(3)
    raise SystemExit(f"Az Overpass nem válaszolt ({utolso}). Próbáld később újra.")


# ---------------------------------------------------------------- geometry
def pont_gyuruben(x, y, g):
    be = False
    j = len(g) - 1
    for i in range(len(g)):
        xi, yi = g[i][0], g[i][1]
        xj, yj = g[j][0], g[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            be = not be
        j = i
    return be


class Hatar:
    def __init__(self):
        self.gyuruk = []
        if HATAR.exists():
            h = json.load(open(HATAR, encoding="utf-8"))
            self.gyuruk = [[tuple(p) for p in g] for g in h.get("gyuruk", [])]

    def bent(self, lon, lat):
        if not self.gyuruk:
            return True
        return sum(pont_gyuruben(lon, lat, g) for g in self.gyuruk) % 2 == 1 if len(self.gyuruk) > 1 else pont_gyuruben(lon, lat, self.gyuruk[0])


def metszet(a, b, c, d):
    """Intersection point (x, z) of two segments, or None."""
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < 1e-9:
        return None
    t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / den
    u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / den
    if 0 <= t <= 1 and 0 <= u <= 1:
        return (a[0] + t * r[0], a[1] + t * r[1])
    return None


class Racs:
    """Fast lookup of segments by cells."""
    def __init__(self, cella=200.0):
        self.c = cella
        self.k = defaultdict(list)

    def hozzaad(self, a, b):
        x0, x1 = sorted((a[0], b[0]))
        z0, z1 = sorted((a[1], b[1]))
        for i in range(int(x0 // self.c), int(x1 // self.c) + 1):
            for j in range(int(z0 // self.c), int(z1 // self.c) + 1):
                self.k[(i, j)].append((a, b))

    def jeloltek(self, a, b):
        x0, x1 = sorted((a[0], b[0]))
        z0, z1 = sorted((a[1], b[1]))
        lat = set()
        for i in range(int(x0 // self.c), int(x1 // self.c) + 1):
            for j in range(int(z0 // self.c), int(z1 // self.c) + 1):
                for s in self.k.get((i, j), ()):
                    lat.add(s)
        return lat


def hossz(pl):
    return sum(math.hypot(pl[i + 1][0] - pl[i][0], pl[i + 1][1] - pl[i][1]) for i in range(len(pl) - 1))


def mintaz(pl, lepes):
    """Resamples a polyline every ~lepes m; returns: [(x, z, s)] (s = arc length)."""
    ki = [(pl[0][0], pl[0][1], 0.0)]
    s0 = 0.0
    for i in range(len(pl) - 1):
        a, b = pl[i], pl[i + 1]
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        if d < 1e-6:
            continue
        n = max(1, int(math.ceil(d / lepes)))
        for q in range(1, n + 1):
            t = q / n
            ki.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, s0 + d * t))
        s0 += d
    return ki


def pont_s(pl, s):
    """The (x, z, heading) belonging to an arc-length position."""
    ered = 0.0
    for i in range(len(pl) - 1):
        a, b = pl[i], pl[i + 1]
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        if ered + d >= s or i == len(pl) - 2:
            t = 0.0 if d < 1e-9 else max(0.0, min(1.0, (s - ered) / d))
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, math.atan2(b[1] - a[1], b[0] - a[0]))
        ered += d
    return (pl[-1][0], pl[-1][1], 0.0)


class Terep:
    def __init__(self, ut):
        try:
            b = open(ut, "rb").read()
        except FileNotFoundError:
            self.van = False
            return
        self.nx, self.nz, self.x0, self.z0, self.lepes, self.ref = struct.unpack("<IIffff", b[:24])
        n = self.nx * self.nz
        self.h = struct.unpack("<%dh" % n, b[24:24 + 2 * n])
        self.van = True

    def mag(self, x, z):
        if not self.van:
            return 0.0
        fx = (x - self.x0) / self.lepes
        fz = (z - self.z0) / self.lepes
        i0 = int(math.floor(fx))
        j0 = int(math.floor(fz))
        tx, tz = fx - i0, fz - j0

        def h(i, j):
            i = min(max(i, 0), self.nx - 1)
            j = min(max(j, 0), self.nz - 1)
            return self.h[j * self.nx + i] / 10.0
        return (h(i0, j0) * (1 - tx) * (1 - tz) + h(i0 + 1, j0) * tx * (1 - tz)
                + h(i0, j0 + 1) * (1 - tx) * tz + h(i0 + 1, j0 + 1) * tx * tz)


def simit(v, ablak, kor):
    for _ in range(kor):
        u = []
        for i in range(len(v)):
            a, b = max(0, i - ablak), min(len(v), i + ablak + 1)
            u.append(sum(v[a:b]) / (b - a))
        u[0], u[-1] = v[0], v[-1]
        v = u
    return v


# ---------------------------------------------------------------- the OSM elements
def vonal_tipus(c):
    hw = c.get("highway", "")
    rw = c.get("railway", "")
    if rw in ("rail", "light_rail", "tram", "subway", "narrow_gauge", "construction", "disused", "preserved"):
        return "sin", 5.5
    if hw in ("footway", "path", "pedestrian", "steps", "cycleway", "track"):
        return "gy", 3.0
    if hw:
        try:
            sav = int(str(c.get("lanes", "")).split(";")[0])
        except ValueError:
            sav = 0
        egyirany = c.get("oneway") in ("yes", "true", "1", "-1")
        szel = 3.4 * sav if sav else (7.5 if egyirany else 11.0)
        return "ut", max(5.0, min(szel, 24.0))
    return "ut", 8.0


NEV_KULCSOK = ("name", "bridge:name", "name:hu", "official_name", "alt_name", "old_name", "loc_name", "name:en", "int_name")


def cimke_nev(c):
    for k in NEV_KULCSOK:
        if c.get(k):
            return c[k]
    return ""


def csoportosit(vonalak):
    """Union-find: crossings with the same name, or (without a name) close to each other, go into one bridge."""
    sz = list(range(len(vonalak)))

    def gy(i):
        while sz[i] != i:
            sz[i] = sz[sz[i]]
            i = sz[i]
        return i
    nevek = [ascii_(cimke_nev(v["cimke"])).strip() for v in vonalak]
    for i in range(len(vonalak)):                  # 1. those with the same name
        for j in range(i + 1, len(vonalak)):
            if nevek[i] and nevek[i] == nevek[j]:
                sz[gy(i)] = gy(j)
    for i in range(len(vonalak)):                  # 2. a line without a name joins the nearest line (within 90 m)
        if nevek[i]:
            continue
        legjobb, tav = None, 90.0
        for j in range(len(vonalak)):
            if j == i:
                continue
            a, b = vonalak[i]["atkelo"], vonalak[j]["atkelo"]
            d = math.hypot(a[0] - b[0], a[1] - b[1])
            if d < tav:
                legjobb, tav = j, d
        if legjobb is not None:
            sz[gy(i)] = gy(legjobb)
    cs = defaultdict(list)
    for i in range(len(vonalak)):
        cs[gy(i)].append(vonalak[i])
    return list(cs.values())


def lancol(mag, osszes, hasznalt, max_hossz=4000.0, tol=3.0):
    """Extends the core (the line crossing the Danube) at both ends with the adjoining bridge lines (same kind, no conflicting name, continuing straight)."""
    tip0 = vonal_tipus(mag["cimke"])[0]
    nev0 = mag["cimke"].get("name", "")
    pl = list(mag["pl"])
    hasznalt.add(mag["id"])
    nevek = {nev0} if nev0 else set()
    for veg in ("vege", "eleje"):
        while hossz(pl) < max_hossz:
            if veg == "vege":
                p, q = pl[-1], pl[-2]
            else:
                p, q = pl[0], pl[1]
            dx, dz = p[0] - q[0], p[1] - q[1]
            dl = math.hypot(dx, dz) or 1.0
            legjobb, lcos = None, 0.2
            for w in osszes:
                if w["id"] in hasznalt or vonal_tipus(w["cimke"])[0] != tip0:
                    continue
                wn = w["cimke"].get("name", "")
                if wn and nevek and wn not in nevek:
                    continue
                for fordit in (False, True):
                    wp = w["pl"][::-1] if fordit else w["pl"]
                    if math.hypot(wp[0][0] - p[0], wp[0][1] - p[1]) > tol:
                        continue
                    ex, ez = wp[-1][0] - wp[0][0], wp[-1][1] - wp[0][1]
                    el = math.hypot(ex, ez) or 1.0
                    cs = (dx * ex + dz * ez) / (dl * el)
                    if cs > lcos:
                        legjobb, lcos = (w, wp), cs
            if not legjobb:
                break
            w, wp = legjobb
            hasznalt.add(w["id"])
            if w["cimke"].get("name"):
                nevek.add(w["cimke"]["name"])
            if veg == "vege":
                pl = pl + list(wp[1:])
            else:
                pl = list(wp[::-1][:-1]) + pl
    cimke = dict(mag["cimke"])
    if not cimke.get("name") and nevek:
        cimke["name"] = sorted(nevek)[0]
    return {"id": mag["id"], "cimke": cimke, "pl": pl, "atkelo": mag["atkelo"]}


def osszevon(csopok, tav=45.0, arany=0.6):
    """Merges overlapping (parallel, within ~tav m) bridge groups, so there are no two models sliding over each other."""
    def fo_pl(cs):
        return max(cs, key=lambda v: hossz(v["pl"]))["pl"]

    def fedes(a, b):
        ra, rb = fo_pl(a), fo_pl(b)
        if hossz(ra) > hossz(rb):
            ra, rb = rb, ra
        suru = mintaz(rb, 8.0)
        kis = mintaz(ra, 20.0)
        if not kis:
            return False
        jo = sum(1 for x, z, _ in kis if min((x - p[0]) ** 2 + (z - p[1]) ** 2 for p in suru) <= tav * tav)
        return jo / len(kis) >= arany

    csopok = [list(c) for c in csopok]
    van = True
    while van:
        van = False
        for i in range(len(csopok)):
            for j in range(i + 1, len(csopok)):
                if fedes(csopok[i], csopok[j]):
                    csopok[i] += csopok.pop(j)
                    van = True
                    break
            if van:
                break
    return csopok


def adatok_beolvasasa():
    sorok = []
    if ADATOK.exists():
        with open(ADATOK, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                if r.get("minta"):
                    sorok.append(r)
    return sorok


def adat_keres(sorok, nevek, ll=None, ut=True):
    t = ascii_(" ".join(nevek))
    for r in sorok:
        if (r.get("szerkezet") or "").strip() == "kihagy_ut" and not ut:
            continue                         # 'kihagy_ut': skips only a road bridge (a railway bridge with the same name stays)
        for m in r["minta"].split("|"):
            if m.strip() and ascii_(m.strip()) in t:
                return r
    if ll:                                   # a bridge without a name (or with an unknown name): by the 'hely' column (lat;lon;radius_m)
        for r in sorok:
            p = [szam(q) for q in str(r.get("hely") or "").split(";")]
            if len(p) >= 2 and None not in p[:2]:
                sug = p[2] if len(p) > 2 and p[2] else 500.0
                dz = (ll[0] - p[0]) * 110574.0
                dx = (ll[1] - p[1]) * COSLAT * 111320.0
                if math.hypot(dx, dz) <= sug:
                    return r
    return None


def szam(s, alap=None):
    try:
        return float(str(s).replace(",", ".").strip())
    except (ValueError, AttributeError):
        return alap


# ---------------------------------------------------------------- assembling one bridge
def hid_epites(csop, terep, adatsor):
    cimkek = [v["cimke"] for v in csop]
    nevek = [cimke_nev(c) for c in cimkek if cimke_nev(c)]
    nev = (adatsor or {}).get("nev") or (Counter(nevek).most_common(1)[0][0] if nevek else "")
    osm_szerk = next((c.get("bridge:structure") for c in cimkek if c.get("bridge:structure")), "")
    szerk = (adatsor or {}).get("szerkezet") or {"suspension": "fuggo", "cable-stayed": "kabeles", "arch": "iv", "truss": "racsos"}.get(osm_szerk, "gerenda")
    fo = max(csop, key=lambda v: hossz(v["pl"]))
    L = hossz(fo["pl"])
    ten = lambda x, z: terep.mag(x, z)

    # --- the deck's height profile (separately for every line, but with the same method)
    szabad = szam((adatsor or {}).get("magassag_m"), SZABAD_M)

    def profil(pl, szabad_m):
        mt = mintaz(pl, LEPES_M)
        h = [ten(x, z) for x, z, _ in mt]
        viz = [hh <= VIZ_MAGASSAG for hh in h]
        y = [(szabad_m if v else hh + 1.0) for hh, v in zip(h, viz)]
        # on both sides of the water the deck gradually rises/descends to the bank's height
        y = simit(y, 4, 5)
        y = [max(yy, (szabad_m * 0.7 if v else hh + 0.5)) for yy, hh, v in zip(y, h, viz)]
        return mt, y, viz

    mt_fo, y_fo, viz_fo = profil(fo["pl"], szabad)
    vi = [i for i, v in enumerate(viz_fo) if v]
    if vi:
        u0, u1 = mt_fo[vi[0]][2], mt_fo[vi[-1]][2]
    else:                                    # no terrain data: the middle of the bridge is the water surface
        u0, u1 = L * 0.2, L * 0.8
    Lw = max(u1 - u0, 1.0)

    def y_at(s):
        if s <= mt_fo[0][2]:
            return y_fo[0]
        for i in range(len(mt_fo) - 1):
            if mt_fo[i + 1][2] >= s:
                t = (s - mt_fo[i][2]) / max(mt_fo[i + 1][2] - mt_fo[i][2], 1e-9)
                return y_fo[i] * (1 - t) + y_fo[i + 1] * t
        return y_fo[-1]

    vonalak = []
    max_ol = 0.0
    # lateral extent measured from the nearest point of the main deck (for a curving bridge the mean normal would be wrong)
    suru = mintaz(fo["pl"], 6.0)
    suru_ir = [pont_s(fo["pl"], s_)[2] for _, _, s_ in suru]

    def oldalt(x, z):
        j = min(range(len(suru)), key=lambda q: (suru[q][0] - x) ** 2 + (suru[q][1] - z) ** 2)
        ir_ = suru_ir[j]
        return abs((x - suru[j][0]) * -math.sin(ir_) + (z - suru[j][1]) * math.cos(ir_)), math.hypot(x - suru[j][0], z - suru[j][1])

    for v in csop:
        tip, szel = vonal_tipus(v["cimke"])
        mt, y, _ = profil(v["pl"], szabad)
        for x, z, _ in mt[:: max(1, len(mt) // 20)]:
            o_, tav = oldalt(x, z)
            if tav <= 45:                     # distant, non-parallel segments must not widen the bridge
                max_ol = max(max_ol, o_ + szel / 2)
    hw = min(max(max_ol, 5.0), 22.0)
    # the bridge is a single block: one deck ribbon along the main deck, with the full width
    vonalak = [{"t": "ut", "sz": round(max(2 * hw, 8.0), 1), "p": [[round(x, 1), round(yy, 2), round(z, 1)] for (x, z, _), yy in zip(mt_fo, y_fo)]}]
    # to hide the bridge buildings in OSM (piers, stone towers): the axis points over the water (slightly widened)
    tengely = []
    for i, (x, z, _) in enumerate(mt_fo):
        if any(viz_fo[max(0, i - 2): i + 3]):
            tengely.append([round(x, 1), round(z, 1)])

    piler, tornyok, kabelek = [], [], []

    def pozicio(u):
        x, z, ir = pont_s(fo["pl"], u)
        return x, z, ir

    # --- towers
    torony_u = []
    if szerk in ("fuggo", "kabeles"):
        arany = [szam(a) for a in str((adatsor or {}).get("torony_aranyok") or "").split(";") if a.strip()]
        if len(arany) < 2:
            arany = [0.15, 0.85] if szerk == "fuggo" else [0.3, 0.7]
        torony_u = [u0 + Lw * a for a in arany]
        th = szam((adatsor or {}).get("torony_mag_m"), 24.0 if szerk == "fuggo" else 50.0)
        for u in torony_u:
            x, z, ir = pozicio(u)
            yt = y_at(u)
            tornyok.append({"x": round(x, 1), "z": round(z, 1), "r": round(ir, 4), "hsz": round(hw + 0.8, 1), "y0": -4.0,
                            "y1": round(yt + th, 1), "yd": round(yt, 1)})
    # --- piers
    pilleru = []
    if szerk not in ("fuggo", "kabeles"):
        n = max(0, int(round(Lw / HAJO_PILLER_M)) - 1) if Lw > 90 else 0
        for k in range(1, n + 1):
            u = u0 + Lw * k / (n + 1)
            if any(abs(u - tu) < 25 for tu in torony_u):
                continue
            x, z, ir = pozicio(u)
            pilleru.append(u)
            piler.append({"x": round(x, 1), "z": round(z, 1), "r": round(ir, 4), "w": round(2 * hw * 0.8, 1), "d": 3.5,
                          "y0": -4.0, "y1": round(y_at(u) - 0.8, 1)})
    # --- cables, arches, girders (on both sides: lateral = +-hw)
    def oldal(u, o):
        x, z, ir = pozicio(u)
        return (x - math.sin(ir) * o, z + math.cos(ir) * o)

    if szerk == "fuggo" and FUGGO_KABEL and len(torony_u) == 2:
        ya = [t["y1"] - 1.0 for t in tornyok]
        for o in (-hw, hw):
            pts = []
            s = 0.0
            while s <= L + 1e-6:
                if s < torony_u[0]:
                    yy = y_at(0) + 1.5 + (ya[0] - y_at(0) - 1.5) * (s / max(torony_u[0], 1e-6))
                elif s > torony_u[1]:
                    yy = y_at(L) + 1.5 + (ya[1] - y_at(L) - 1.5) * ((L - s) / max(L - torony_u[1], 1e-6))
                else:
                    uc = (torony_u[0] + torony_u[1]) / 2
                    h2 = (torony_u[1] - torony_u[0]) / 2
                    ymid = y_at(uc) + 3.0
                    yy = ymid + ((ya[0] + ya[1]) / 2 - ymid) * ((s - uc) / h2) ** 2
                x, z = oldal(s, o)
                pts.append([round(x, 1), round(yy, 1), round(z, 1)])
                s += 8.0
            kabelek.append(pts)
            # hangers
            s = torony_u[0] + 10
            while s < torony_u[1] - 5:
                uc = (torony_u[0] + torony_u[1]) / 2
                h2 = (torony_u[1] - torony_u[0]) / 2
                ymid = y_at(uc) + 3.0
                yy = ymid + ((ya[0] + ya[1]) / 2 - ymid) * ((s - uc) / h2) ** 2
                x, z = oldal(s, o)
                kabelek.append([[round(x, 1), round(y_at(s) + 0.4, 1), round(z, 1)], [round(x, 1), round(yy, 1), round(z, 1)]])
                s += 14.0
    elif szerk == "kabeles" and len(torony_u) >= 1:
        for t, u in zip(tornyok, torony_u):
            for irany in (-1, 1):
                for k in range(1, 9):
                    s = u + irany * (12.0 * k + 6)
                    if s < 0 or s > L:
                        continue
                    for o in (-hw * 0.85, hw * 0.85):
                        x, z = oldal(s, o)
                        xt, zt = oldal(u, o * 0.1)
                        kabelek.append([[round(xt, 1), round(t["y1"] - 2.0 - 0.9 * k, 1), round(zt, 1)], [round(x, 1), round(y_at(s) + 0.4, 1), round(z, 1)]])
    elif szerk == "iv":
        # the arch under the deck, one per span (as at Margit Bridge): its crown is below the deck, lowest at the pier
        tamasz = [u0] + pilleru + [u1]
        for a, b in zip(tamasz[:-1], tamasz[1:]):
            f = min(0.20 * (b - a), 14.0)
            for o in (-hw, -hw / 3.0, hw / 3.0, hw):
                pts = []
                s_ = a
                while True:
                    t = (s_ - a) / max(b - a, 1e-6)
                    x, z = oldal(s_, o)
                    ya = max(y_at(s_) - 1.6 - f * (1 - 4 * t * (1 - t)), 0.5)
                    pts.append([round(x, 1), round(ya, 1), round(z, 1)])
                    if s_ >= b - 1e-6:
                        break
                    s_ = min(s_ + 6.0, b)
                kabelek.append(pts)
            for o in (-hw, hw):
                s_ = a + 8.0
                while s_ < b - 4:
                    t = (s_ - a) / max(b - a, 1e-6)
                    x, z = oldal(s_, o)
                    ya = max(y_at(s_) - 1.6 - f * (1 - 4 * t * (1 - t)), 0.5)
                    kabelek.append([[round(x, 1), round(ya, 1), round(z, 1)], [round(x, 1), round(y_at(s_) - 0.2, 1), round(z, 1)]])
                    s_ += 8.0
    elif szerk == "racsos":
        for o in (-hw, hw):
            pts = []
            s = u0
            while s <= u1 + 1e-6:
                x, z = oldal(s, o)
                pts.append([round(x, 1), round(y_at(s) + 8.0, 1), round(z, 1)])
                s += 10.0
            kabelek.append(pts)
            s = u0
            elozo = None
            while s <= u1 + 1e-6:
                x, z = oldal(s, o)
                le = [round(x, 1), round(y_at(s) + 0.4, 1), round(z, 1)]
                fel = [round(x, 1), round(y_at(s) + 8.0, 1), round(z, 1)]
                kabelek.append([le, fel])
                if elozo:
                    kabelek.append([elozo, fel])
                elozo = le
                s += 10.0

    # --- data
    kerm = [nev] + [m.strip() for m in str((adatsor or {}).get("minta") or "").split("|") if m.strip()]
    kerm += [k.replace("híd", "bridge").replace("Híd", "Bridge") for k in kerm if "híd" in k.lower()]
    keresesek = []
    for k in kerm:
        if k and k not in keresesek:
            keresesek.append(k)
    ev = szam((adatsor or {}).get("ev"))
    start = next((c.get("start_date") for c in cimkek if c.get("start_date")), "")
    m = re.match(r"(\d{4})", start or "")
    ev_forras = "hid_adat" if ev else ("osm" if m else "")
    if not ev and m:
        ev = float(m.group(1))
    wiki = (adatsor or {}).get("wikipedia") or next((c.get("wikipedia") for c in cimkek if c.get("wikipedia")), "")
    wd = next((c.get("wikidata") for c in cimkek if c.get("wikidata")), "")
    xs = [p[0] for v in vonalak for p in v["p"]]
    zs = [p[2] for v in vonalak for p in v["p"]]
    cx, cz = sum(xs) / len(xs), sum(zs) / len(zs)
    lat = LAT0 - cz / 110574.0
    lon = LON0 + cx / (COSLAT * 111320.0)
    return {
        "nev": nev or "Névtelen híd", "szerkezet": szerk, "ev": int(ev) if ev else None, "ev_forras": ev_forras,
        "ujjaepitve": (adatsor or {}).get("ujjaepitve") or "", "tervezo": (adatsor or {}).get("tervezo") or "",
        "keresesek": keresesek, "wikipedia": wiki or "", "wikidata": wd or "", "kep": ((adatsor or {}).get("kep") or "").strip(), "hossz_m": round(L), "viz_m": round(Lw), "szabad_m": round(szabad, 1),
        "megjegyzes": (adatsor or {}).get("megjegyzes") or "", "osm": [{"t": "way", "id": v["id"]} for v in csop],
        "lat": round(lat, 6), "lon": round(lon, 6), "vonalak": vonalak, "tengely": tengely, "hw": round(hw, 1), "piler": piler, "tornyok": tornyok, "kabelek": kabelek,
        "ismeretlen": adatsor is None,
    }


def main():
    ujra = "ujra" in sys.argv[1:]
    d = letoltes(ujra)
    hatar = Hatar()
    viz = Racs()
    n_viz = 0
    for e in d.get("elements", []):
        c = e.get("tags", {})
        if e.get("type") == "way" and c.get("waterway") and "geometry" in e:
            pl = [lok(p["lon"], p["lat"]) for p in e["geometry"]]
            for i in range(len(pl) - 1):
                viz.hozzaad(pl[i], pl[i + 1])
            n_viz += 1
    if not n_viz:
        raise SystemExit("Az OSM-adatban nincs a Duna vonala. Futtasd újra: py hidak_keszites.py ujra")
    vonalak = []
    osszes = []
    kimaradt = Counter()
    for e in d.get("elements", []):
        c = e.get("tags", {})
        if e.get("type") != "way" or c.get("waterway") or "geometry" not in e or not c.get("bridge"):
            continue
        if c.get("tunnel") or c.get("indoor"):
            continue
        pl = [lok(p["lon"], p["lat"]) for p in e["geometry"]]
        if len(pl) < 2:
            continue
        osszes.append({"id": e["id"], "cimke": c, "pl": pl})
        atkelo = None
        for i in range(len(pl) - 1):
            for a, b in viz.jeloltek(pl[i], pl[i + 1]):
                m = metszet(pl[i], pl[i + 1], a, b)
                if m:
                    atkelo = m
                    break
            if atkelo:
                break
        if not atkelo:
            kimaradt["nem metszi a Dunát"] += 1
            continue
        lat = LAT0 - atkelo[1] / 110574.0
        lon = LON0 + atkelo[0] / (COSLAT * 111320.0)
        if not hatar.bent(lon, lat):
            kimaradt["a városhatáron kívül"] += 1
            continue
        if hossz(pl) < MIN_HOSSZ_M:
            kimaradt["túl rövid"] += 1
            continue
        vonalak.append({"id": e["id"], "cimke": c, "pl": pl, "atkelo": atkelo})
    hasznalt = set()
    lancolt = []
    for v in sorted(vonalak, key=lambda q: -hossz(q["pl"])):
        if v["id"] not in hasznalt:
            lancolt.append(lancol(v, osszes, hasznalt))
    print(f"Átkelő OSM-vonal: {len(vonalak)} -> láncolva {len(lancolt)}; kimaradt: {dict(kimaradt)}")
    vonalak = lancolt
    terep = Terep(TEREP)
    if not terep.van:
        print("FIGYELEM: nincs terkep3d/data_varos/terrain.bin (futtasd: py csempek_keszites.py varos); a hidak sík terepet kapnak.")
    adatsorok = adatok_beolvasasa()
    hidak = []
    for csop in osszevon(csoportosit(vonalak)):
        nevek = [cimke_nev(v["cimke"]) for v in csop if cimke_nev(v["cimke"])]
        ax, az = csop[0]["atkelo"]
        adatsor = adat_keres(adatsorok, nevek, (LAT0 - az / 110574.0, LON0 + ax / (COSLAT * 111320.0)), any(v["cimke"].get("highway") for v in csop))
        if adatsor and (adatsor.get("szerkezet") or "").strip() in ("kihagy", "kihagy_ut"):
            print(f"Kihagyva (forras/hidak_adatok.csv): {adatsor.get('nev') or nevek}")
            continue
        hidak.append(hid_epites(csop, terep, adatsor))
    hidak.sort(key=lambda h: h["lat"], reverse=True)       # from north to south
    KIMENET.parent.mkdir(parents=True, exist_ok=True)
    json.dump({"hidak": hidak}, open(KIMENET, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    sor = ["# Duna-hidak\n\n", f"{len(hidak)} híd, {len(vonalak)} OSM-vonalból.\n\n",
           "| Híd | Szerkezet | Év | Hossz (m) | Wikipédia | Adatforrás |\n|---|---|---|---|---|---|\n"]
    for h in hidak:
        sor.append(f"| {h['nev']} | {h['szerkezet']} | {h['ev'] or ''} | {h['hossz_m']} | {h['wikipedia'] or ''} | "
                   f"{'forras/hidak_adatok.csv' if not h['ismeretlen'] else 'csak OSM – tölts ki a forras/hidak_adatok.csv-be (hely: ' + str(h['lat']) + ';' + str(h['lon']) + ')'} |\n")
    JELENTES.write_text("".join(sor), encoding="utf-8")
    print("".join(sor))
    print(f"Mentve: {KIMENET}")


# ---------------------------------------------------------------- self-check
def teszt():
    global TEREP
    # a check without network and real data: an imaginary bridge over an imaginary river
    assert metszet((0, 0), (10, 10), (0, 10), (10, 0)) == (5.0, 5.0)
    assert metszet((0, 0), (1, 0), (0, 1), (1, 1)) is None
    pl = [(0, 0), (100, 0)]
    assert abs(hossz(pl) - 100) < 1e-9
    assert [round(s) for _, _, s in mintaz(pl, 30)] == [0, 25, 50, 75, 100]
    x, z, ir = pont_s(pl, 40)
    assert (round(x), round(z), round(ir)) == (40, 0, 0)

    class Ter:
        van = True
        def mag(self, x, z):          # between 150 and 350 m there is water (0 m), with a 6 m bank on both sides
            return 0.0 if 150 <= x <= 350 else 6.0
    hid = [(0, 0), (500, 0)]
    for szerk, mind in (("gerenda", 0), ("fuggo", 1), ("kabeles", 1), ("iv", 1), ("racsos", 1)):
        v = {"id": 1, "cimke": {"name": "Teszt híd", "highway": "primary", "lanes": "4"}, "pl": hid, "atkelo": (250, 0)}
        h = hid_epites([v], Ter(), {"nev": "Teszt híd", "szerkezet": szerk, "ev": "1900"})
        assert h["ev"] == 1900 and h["szerkezet"] == szerk and h["vonalak"], h
        ys = [p[1] for p in h["vonalak"][0]["p"]]
        assert min(ys) >= 6.0 and max(ys) <= 20, (szerk, min(ys), max(ys))
        if szerk == "gerenda":
            assert len(h["piler"]) >= 2 and not h["tornyok"] and not h["kabelek"]
        if szerk in ("fuggo", "kabeles"):
            assert len(h["tornyok"]) >= 1 and (h["kabelek"] or (szerk == "fuggo" and not FUGGO_KABEL))
            assert not h["piler"]
        if mind and not (szerk == "fuggo" and not FUGGO_KABEL):
            assert h["kabelek"], szerk
        assert len(h["vonalak"]) == 1 and h["tengely"] and h["hw"] >= 5
    assert vonal_tipus({"railway": "tram"})[0] == "sin" and vonal_tipus({"highway": "footway"})[0] == "gy"
    assert csoportosit([{"cimke": {"name": "A híd"}, "atkelo": (0, 0)}, {"cimke": {"name": "A híd"}, "atkelo": (500, 0)},
                        {"cimke": {}, "atkelo": (5, 5)}, {"cimke": {"name": "Más"}, "atkelo": (1, 1)}]).__len__() == 2
    print("Önellenőrzés rendben.")


if __name__ == "__main__":
    if "teszt" in sys.argv[1:]:
        teszt()
    else:
        main()
