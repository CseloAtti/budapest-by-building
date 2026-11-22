"""
csempek_keszites.py - a 3D nézet (terkep3d/) adatainak elkészítése.

Futtatás (a projekt mappájában):   py csempek_keszites.py          (a belváros)
                                   py csempek_keszites.py varos     (az egész város -> terkep3d/data_varos/)
Városi mód bemenete: data/varos/epuletek_vegleges.geojson, data/varos/viz_zold.json (budapest_pbf.py),
                     data/varos/commons_kepek.json; gépigény: legalább 4 GB szabad memória, 15-40 perc.
A városi 3D nézet: http://localhost:8000/terkep3d/?adat=varos

Csak a Python alap könyvtárát használja.

Bemenet:  data/belvaros_epuletek_vegleges.geojson   (osszeepit.py; az ev_becsles_* mezőkkel együtt)
          data/viz_zold.json                         (viz_letoltes.py; elhagyható: víz és parkok)
          data/N47E018.SRTMGL1_NC.nc, data/N47E019.SRTMGL1_NC.nc   (NASA SRTM magassági csempék; elhagyható)
Kimenet:  terkep3d/data/budapest.json    - beállítások, csempék jegyzéke, évhisztogram
          terkep3d/data/tiles.bin        - az épületek 600 m-es bináris csempékben
          terkep3d/data/epuletek.json    - az épületek adatai a kártyához (a sorszám = az épület azonosítója)
          terkep3d/data/terrain.bin      - domborzati háló (ha van SRTM-csempe)
          terkep3d/data/landcover.png    - víz és parkok képként a domborzatra (ha van viz_zold.json)

A csempe-formátum az amszterdami projektből való (alexbarakov/amsterdam-by-building, MIT licenc);
a csempe-készítő itt újraírt, budapesti változat.

A csúszkához minden épületnek kell év. Az ismert évű épület a saját évét kapja. A szürke épületnek a
becsült korszakán belül, a közeli ismert évű épületek évei közül választunk egyet (az épület azonosítójából
számolt, mindig ugyanaz az érték). Ez csak a megjelenítéshez kell: a kártya a becslést becslésként jelöli,
és a pontos évet nem mutatja.
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
    from dem import Domborzat, HibasFajl
except ImportError:          # dem.py hiányában domborzat nélkül dolgozunk
    Domborzat = None
    HibasFajl = Exception

VAROS = "varos" in sys.argv[1:]
ADAT = Path("data")
KIMENET = Path("terkep3d/data_varos" if VAROS else "terkep3d/data")
LAT0, LON0 = 47.5015, 19.0515
COSLAT = math.cos(math.radians(LAT0))
CSEMPE = 600.0
MAGIC = 0x34424241
ELSO_EV_MIN = 1700
MOST = 2026
SZOMSZED_M = 150.0
TEREP_LEPES = 20.0       # m: a domborzati háló lépésköze
KEP_PX = 2.5             # m: a víz/park kép képpontjának mérete
TEREP_MARGO = {"nyugat": 5000.0, "kelet": 2000.0, "eszak": 2000.0, "del": 2500.0}   # m, az épületek köré
if VAROS:               # az egész város: durvább háló és kép, kisebb margó
    TEREP_LEPES = 40.0
    KEP_PX = 5.0
    TEREP_MARGO = {"nyugat": 2500.0, "kelet": 2500.0, "eszak": 2500.0, "del": 2500.0}
SIMITAS_LEPES = 40       # az árterület erős simításának lépésszáma (3x3-as átlag)
ARTER_SZINT = 96.0       # m: a Duna szintje (közelítés a simítási súlyhoz)
VAROS_MIN_SUGAR = 3      # SRTM-cella: a beépített részen ekkora ablakban vesszük a legalacsonyabb pontot

# azonos az index.html és az ev_becsles.py korszaklistájával
KORSZAKOK = [
    (1, 1866, "1866-ig – Kiegyezés előtt", "to 1866 – Before the Compromise", "#7a1f1f"),
    (1867, 1918, "1867–1918 – Dualizmus", "1867–1918 – Dualism", "#d9653b"),
    (1919, 1944, "1919–1944 – Horthy-korszak", "1919–1944 – Horthy era", "#e8b04a"),
    (1945, 1956, "1945–1956 – Rákosi-korszak", "1945–1956 – Rákosi era", "#6aa84f"),
    (1957, 1989, "1957–1989 – Kádár-korszak", "1957–1989 – Kádár era", "#2e8b8b"),
    (1990, 2010, "1990–2010 – Rendszerváltás utáni évek", "1990–2010 – Post-transition years", "#3d85c6"),
    (2011, 9999, "2011-től – Napjaink", "2011 onwards – Present day", "#8e5bb5"),
]
ROM_KOR = 0     # az ókori és középkori romok nem külön kategória: az "1867 előtt" korszakba tartoznak (a "rom" mező a kártyán továbbra is látszik)


def hidak_lechner():
    """A Lechner Tudásközpont adatai a hidakra: a data/tenyek/lechner.csv-ben a hidak OSM-azonosítóihoz (kézi párosítás) kötött sorokat
    átírja a hidak.json megfelelő hídjához (a hidak nem az épületadatban vannak, ezért az osszeepit.py nem látja őket)."""
    ut = KIMENET / "hidak.json"
    tenyek = Path("data/tenyek/lechner.csv")
    if not ut.exists() or not tenyek.exists():
        return
    mezok = ("lechner_nev", "lechner_epult", "lechner_ev_kezdet", "lechner_ev_veg", "lechner_tervezo", "lechner_illesztes")
    adat = defaultdict(dict)
    with open(tenyek, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r.get("mezo") in mezok and (r.get("ertek") or "").strip():
                adat[(r["osm_tipus"], str(r["id"]))][r["mezo"]] = r["ertek"].strip()
    h = json.load(open(ut, encoding="utf-8"))
    valtozott = db = 0
    for hid in h.get("hidak", []):
        talalt = {}
        for o in hid.get("osm", []):
            talalt = adat.get((o.get("t", "way"), str(o.get("id")))) or talalt
            if talalt:
                break
        for m in mezok:
            uj = talalt.get(m)
            if uj != hid.get(m) and (uj or m in hid):
                if uj:
                    hid[m] = uj
                else:
                    hid.pop(m, None)
                valtozott += 1
        db += bool(talalt)
    if valtozott:
        ut.write_text(json.dumps(h, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  Lechner-adat a hidakon: {db} híd" + (" (hidak.json frissítve)" if valtozott else ""))


KARTYA_MEZOK = [
    "id", "osm_tipus", "nev", "tipus", "resz", "szintek",
    "magassag",
    "ev", "ev_forras", "tervezo", "tervezo_forras", "stilus", "vedettseg", "vedettseg_helyi",
    "muemlek_torzsszam", "oeny_azonosito", "budapest100_url", "budapest100_kep", "budapest100_foto", "legenda_url", "legenda_kep", "epforum_url", "commons_kep", "kep_url", "link_url", "linkek", "kepek_linkek", "felosztott_ebbol", "about", "wikipedia", "wikipedia_zona", "zona_nev", "zona_tervezo", "zona_azon", "zona_tervezo_nev", "wikidata_id", "lechner_nev", "lechner_epult",
    "lechner_tervezo", "lechner_illesztes", "nev_kozepulet", "rom", "cim", "cim_tobb",
    "ev_kozelito_tol", "ev_kozelito_ig", "ev_kozelito_szoveg", "ev_kozelito_forras",
    "sv_lat", "sv_lon",
]


def lokalis(lon, lat):
    """Fok -> méter a nézet koordinátarendszerében: x kelet, z dél."""
    return ((lon - LON0) * COSLAT * 111320.0, -(lat - LAT0) * 110574.0)


def vissza(x, z):
    return (LAT0 - z / 110574.0, LON0 + x / (COSLAT * 111320.0))


def korszak_ev_szerint(ev):
    for i, (tol, ig, *_) in enumerate(KORSZAKOK):
        if tol <= ev <= ig:
            return i
    return 1


def gyuru_tisztitas(gyuru):
    """Lokális méterekre vált, elhagyja a záró (ismétlődő) pontot és az egymás melletti azonos pontokat."""
    pontok = []
    for lon, lat in gyuru:
        p = lokalis(lon, lat)
        if not pontok or math.dist(p, pontok[-1]) > 0.05:
            pontok.append(p)
    if len(pontok) > 1 and math.dist(pontok[0], pontok[-1]) <= 0.05:
        pontok.pop()
    return pontok if len(pontok) >= 3 else None


def poligonok(geo):
    """Az épület poligonjai: [[kulso, lyuk, lyuk...], ...] lokális méterekben."""
    if geo["type"] == "Polygon":
        lista = [geo["coordinates"]]
    elif geo["type"] == "MultiPolygon":
        lista = geo["coordinates"]
    else:
        return []
    ki = []
    for poly in lista:
        gyurukk = [gyuru_tisztitas(g) for g in poly]
        if gyurukk and gyurukk[0]:
            ki.append([gyurukk[0]] + [g for g in gyurukk[1:] if g])
    return ki


def kozeppont(poly):
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


def doboz_elmos(g):
    """3x3-as átlag (a szélén az utolsó érték ismétlődik). g: [[...], ...]"""
    n, m = len(g), len(g[0])
    v = []
    for r in range(n):
        sor = g[r]
        v.append([(sor[max(c - 1, 0)] + sor[c] + sor[min(c + 1, m - 1)]) / 3 for c in range(m)])
    ki = []
    for r in range(n):
        a, b, c_ = v[max(r - 1, 0)], v[r], v[min(r + 1, n - 1)]
        ki.append([(a[c] + b[c] + c_[c]) / 3 for c in range(m)])
    return ki


def minimum_szuro(g, sugar):
    """Négyzet alakú ablak minimuma (elválasztható: előbb a sorokban, aztán az oszlopokban)."""
    n, m = len(g), len(g[0])
    v = [[min(sor[max(c - sugar, 0):c + sugar + 1]) for c in range(m)] for sor in g]
    return [[min(v[k][c] for k in range(max(r - sugar, 0), min(r + sugar, n - 1) + 1)) for c in range(m)]
            for r in range(n)]


ALMINTA = 4   # függőleges részminta képpontonként a lágy (élsimított) széleshez


def kitolt(szakaszok, gyuruk, w, h):
    """Páros-páratlan szabályú kitöltés: a gyűrűk belsejét szakaszokként (sor -> [(a, b), ...]) jegyzi fel,
    ALMINTA részsorral soronként. A koordináták képpontegységben vannak."""
    ys = [p[1] for gy in gyuruk for p in gy]
    if not ys:
        return
    vodrok = defaultdict(list)       # sor -> az azt érintő élek (különben minden sor minden élt végignézne)
    for gy in gyuruk:
        for (x1, y1), (x2, y2) in zip(gy, gy[1:] + gy[:1]):
            if y1 != y2:
                e = (min(y1, y2), max(y1, y2), x1, y1, x2, y2)
                for r in range(max(0, int(math.floor(e[0]))), min(h - 1, int(math.floor(e[1]))) + 1):
                    vodrok[r].append(e)
    for r in range(max(0, int(math.floor(min(ys)))), min(h - 1, int(math.floor(max(ys)))) + 1):
        el = vodrok.get(r, ())
        for k in range(ALMINTA):
            yc = r + (k + 0.5) / ALMINTA
            xs = [x1 + (yc - y1) * (x2 - x1) / (y2 - y1) for (lo, hi, x1, y1, x2, y2) in el if lo <= yc < hi]
            xs.sort()
            for a, b in zip(xs[::2], xs[1::2]):
                a, b = max(a, 0.0), min(b, float(w))
                if b > a:
                    szakaszok[r].append((a, b))


def lefed(szakaszok, w, h):
    """A szakaszokból soronként 0..255 fedettség (bytes), ahol a szél törtrészei adják az élsimítást."""
    sorok = []
    suly = 255.0 / ALMINTA
    for r in range(h):
        sp = szakaszok[r]
        if not sp:
            sorok.append(bytes(w))
            continue
        d = {}                   # a belső, teljesen fedett cellák (csak ahol van szakasz: gyors a nagy képeknél)
        p = {}                   # a szélső, részben fedett cellák
        for a, b in sp:
            ia, ib = int(a), int(b)
            if ia == ib:
                p[ia] = p.get(ia, 0.0) + (b - a)
            else:
                p[ia] = p.get(ia, 0.0) + (ia + 1 - a)
                p[ib] = p.get(ib, 0.0) + (b - ib)
                d[ia + 1] = d.get(ia + 1, 0.0) + 1.0
                d[ib] = d.get(ib, 0.0) - 1.0
        sor = bytearray(w)
        acc = 0.0
        ks = sorted(set(d) | set(p))

        def atvalt(v):
            return 255 if v >= 254.5 else int(v + 0.5)

        for n, c in enumerate(ks):
            acc += d.get(c, 0.0)
            if c < w:
                sor[c] = atvalt((acc + p.get(c, 0.0)) * suly)
            if n + 1 < len(ks) and ks[n + 1] > c + 1 and acc > 1e-9:       # két érdekes cella között állandó a fedettség
                hi = min(ks[n + 1], w)
                if hi > c + 1:
                    sor[c + 1:hi] = bytes([atvalt(acc * suly)]) * (hi - c - 1)
        sorok.append(bytes(sor))
    return sorok


def png_iras(ut, w, h, sorok_rgb):
    """Egyszerű RGB PNG (alap könyvtárral). sorok_rgb: h darab, soronként w*3 bájt."""
    def chunk(tipus, adat):
        c = struct.pack(">I", len(adat)) + tipus + adat
        return c + struct.pack(">I", zlib.crc32(tipus + adat) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes(s) for s in sorok_rgb)
    Path(ut).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                         + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def gyuru_terulet(gyuru):
    return abs(sum(x0 * z1 - x1 * z0 for (x0, z0), (x1, z1) in zip(gyuru, gyuru[1:] + gyuru[:1]))) / 2


class Terep:
    """Domborzat az SRTM-ből: háló a megjelenítéshez, és az épületek talpmagassága."""

    def __init__(self, ep, viz):
        xs = [e["x"] for e in ep]
        zs = [e["z"] for e in ep]
        self.x0 = math.floor((min(xs) - TEREP_MARGO["nyugat"]) / TEREP_LEPES) * TEREP_LEPES
        self.x1 = math.ceil((max(xs) + TEREP_MARGO["kelet"]) / TEREP_LEPES) * TEREP_LEPES
        self.z0 = math.floor((min(zs) - TEREP_MARGO["eszak"]) / TEREP_LEPES) * TEREP_LEPES
        self.z1 = math.ceil((max(zs) + TEREP_MARGO["del"]) / TEREP_LEPES) * TEREP_LEPES
        self.nx = int((self.x1 - self.x0) / TEREP_LEPES) + 1
        self.nz = int((self.z1 - self.z0) / TEREP_LEPES) + 1
        lat_e, lon_ny = vissza(self.x0, self.z0)
        lat_d, lon_k = vissza(self.x1, self.z1)
        d = Domborzat(ADAT)
        fok = Domborzat.FOK
        ny, kel = math.floor(lon_ny * fok) / fok, math.ceil(lon_k * fok) / fok
        de, ez = math.floor(lat_d * fok) / fok, math.ceil(lat_e * fok) / fok
        sor, osz, self.lat_f, self.lon_ny, g = d.racs(ny, kel, de, ez)
        # hiányzó értékek (ha lennének) a medián magassággal
        ervenyes = [v for r in g for v in r if v == v]
        med = statistics.median(ervenyes)
        g = [[v if v == v else med for v in r] for r in g]
        self.dsm_stat = (min(ervenyes), max(ervenyes))
        # a beépített részeken az SRTM az épületeket is méri (felszínmodell): ott a közeli legalacsonyabb pontot vesszük
        suruseg = [[0.0] * osz for _ in range(sor)]
        cella_m2 = (110574.0 / fok) * (111320.0 * COSLAT / fok)
        for e in ep:
            r = int(round((self.lat_f - vissza(e["x"], e["z"])[0]) * fok))
            c = int(round((vissza(e["x"], e["z"])[1] - self.lon_ny) * fok))
            if 0 <= r < sor and 0 <= c < osz:
                suruseg[r][c] += sum(gyuru_terulet(p[0]) for p in e["poly"]) / cella_m2
        suruseg = doboz_elmos(doboz_elmos([[min(1.0, v) for v in r] for r in suruseg]))
        sima = doboz_elmos(g)
        alacsony = doboz_elmos(minimum_szuro(g, VAROS_MIN_SUGAR))
        self.g = [[sima[r][c] + (alacsony[r][c] - sima[r][c]) * min(1.0, suruseg[r][c] * 2.5) for c in range(osz)]
                  for r in range(sor)]
        # az árterületen (Pest) az SRTM zaja és az épületek maradványa hepehupás felszínt adna: ott erősen simítunk,
        # a dombokon (a magasság a Duna szintje fölött 15-45 m között fokozatosan) megmarad a részletesség
        self.g0 = self.g          # a víz szintjének méréséhez a simítatlan rács
        eros = self.g
        for _ in range(SIMITAS_LEPES):
            eros = doboz_elmos(eros)
        self.g = [[self.g[r][c] + (eros[r][c] - self.g[r][c])
                   * min(1.0, max(0.0, (45.0 - (eros[r][c] - ARTER_SZINT)) / 30.0))
                   for c in range(osz)] for r in range(sor)]
        self.sor, self.osz = sor, osz
        # víz és parkok képe
        self.kep_w = int((self.x1 - self.x0) / KEP_PX) + 1
        self.kep_h = int((self.z1 - self.z0) / KEP_PX) + 1
        park_sz = [[] for _ in range(self.kep_h)]
        viz_sz = [[] for _ in range(self.kep_h)]
        self.van_kep = False
        for p in viz or []:
            gyuruk = []
            for gy in p["gyuruk"]:
                pts = []
                for lon, lat in gy:
                    x, z = lokalis(lon, lat)
                    pts.append(((x - self.x0) / KEP_PX, (z - self.z0) / KEP_PX))
                gyuruk.append(pts)
            kitolt(viz_sz if p["fajta"] == "viz" else park_sz, gyuruk, self.kep_w, self.kep_h)
            self.van_kep = True
        self.park = lefed(park_sz, self.kep_w, self.kep_h)
        self.viz = lefed(viz_sz, self.kep_w, self.kep_h)
        # a Duna szintje: a vízfelszín mediánja (ez lesz a nézet nulla szintje)
        vizi = []
        for r in range(0, self.kep_h, 4):
            sor_ = self.viz[r]
            for c in range(0, self.kep_w, 4):
                if sor_[c] > 200:
                    vizi.append(self.dsm(self.x0 + c * KEP_PX, self.z0 + r * KEP_PX, self.g0))
        self.ref = statistics.median(vizi) if vizi else 96.0
        self.vizi_cellak = len(vizi)
        self.part_racs()

    def part_racs(self):
        """A tavak vízszintjéhez: a vízfelület közelében lévő szárazföld legalacsonyabb magassága (durva rácson).
        A magasabban fekvő tavak (pl. a Naplás-tó) így a partjuk szintjén lesznek, nem a Duna szintjén (gödörben)."""
        K = 3
        fok = Domborzat.FOK
        nr, nc = (self.sor + K - 1) // K, (self.osz + K - 1) // K
        INF = 1e9
        kozep = [[0.0] * nc for _ in range(nr)]
        szaraz = [[INF] * nc for _ in range(nr)]
        for i in range(nr):
            r = min(i * K + K // 2, self.sor - 1)
            for j in range(nc):
                c = min(j * K + K // 2, self.osz - 1)
                kozep[i][j] = self.g[r][c]
                x, z = lokalis(self.lon_ny + c / fok, self.lat_f - r / fok)
                if not self.vizen(x, z):
                    szaraz[i][j] = self.g[r][c]
        mn = minimum_szuro(szaraz, 8)                    # ~700 m-es környezet
        self.part = doboz_elmos([[mn[i][j] if mn[i][j] < INF else kozep[i][j] for j in range(nc)] for i in range(nr)])
        self.part_k = K

    def part_szint(self, x, z):
        """A part szintje a (x, z) pont környékén (m tengerszint felett), kétvonalas interpolációval a durva rácson."""
        lat, lon = vissza(x, z)
        fok = Domborzat.FOK
        K = self.part_k
        r = ((self.lat_f - lat) * fok - K // 2) / K
        c = ((lon - self.lon_ny) * fok - K // 2) / K
        nr, nc = len(self.part), len(self.part[0])
        r = min(max(r, 0.0), nr - 1.001)
        c = min(max(c, 0.0), nc - 1.001)
        r0, c0 = int(r), int(c)
        fr, fc = r - r0, c - c0
        g = self.part
        return (g[r0][c0] * (1 - fc) + g[r0][c0 + 1] * fc) * (1 - fr) + (g[r0 + 1][c0] * (1 - fc) + g[r0 + 1][c0 + 1] * fc) * fr

    def dsm(self, x, z, g=None):
        """Az SRTM-ből számolt magasság (m tengerszint felett) a (x, z) pontban, kétvonalas interpolációval."""
        lat, lon = vissza(x, z)
        fok = Domborzat.FOK
        r = (self.lat_f - lat) * fok
        c = (lon - self.lon_ny) * fok
        r = min(max(r, 0.0), self.sor - 1.001)
        c = min(max(c, 0.0), self.osz - 1.001)
        r0, c0 = int(r), int(c)
        fr, fc = r - r0, c - c0
        g = g or self.g
        return (g[r0][c0] * (1 - fc) + g[r0][c0 + 1] * fc) * (1 - fr) + (g[r0 + 1][c0] * (1 - fc) + g[r0 + 1][c0 + 1] * fc) * fr

    def talaj(self, x, z):
        """A talaj magassága a Duna szintjéhez (a nézet 0 szintjéhez) képest, legalább 0."""
        return max(0.0, self.dsm(x, z) - self.ref)

    def vizen(self, x, z):
        c = int((x - self.x0) / KEP_PX)
        r = int((z - self.z0) / KEP_PX)
        return 0 <= r < self.kep_h and 0 <= c < self.kep_w and self.viz[r][c] > 127

    def vizarany(self, x, z):
        """A vízfedettség a pont ~20 m-es környezetében (0..1): a partvonal lágy átmenete a domborzatban."""
        c0 = (x - self.x0) / KEP_PX
        r0 = (z - self.z0) / KEP_PX
        fel = TEREP_LEPES * 0.75 / KEP_PX
        db = 0
        n = 0
        for dr in range(-4, 5):
            r = int(r0 + dr * fel / 4)
            if not 0 <= r < self.kep_h:
                continue
            sor = self.viz[r]
            for dc in range(-4, 5):
                c = int(c0 + dc * fel / 4)
                if 0 <= c < self.kep_w:
                    n += 1
                    db += sor[c]
        return db / (255.0 * n) if n else 0.0

    def iras(self, kimenet):
        """terrain.bin és landcover.png."""
        hs = array("h")
        for j in range(self.nz):
            z = self.z0 + j * TEREP_LEPES
            for i in range(self.nx):
                x = self.x0 + i * TEREP_LEPES
                f = self.vizarany(x, z)
                szaraz = max(0.0, self.dsm(x, z) - self.ref)
                szint = 0.0
                if f > 0.0:
                    # a tó a partja szintjén áll (a Duna és az árterület kis tavai a nulla szinten maradnak)
                    p = self.part_szint(x, z) - self.ref
                    t = min(1.0, max(0.0, (p - 4.0) / 8.0))
                    szint = max(0.0, p) * t * t * (3 - 2 * t)
                h = (1.0 - f) * szaraz + f * szint
                hs.append(int(round(h * 10)))
        if sys.byteorder != "little":
            hs.byteswap()
        (kimenet / "terrain.bin").write_bytes(struct.pack("<IIffff", self.nx, self.nz, self.x0, self.z0,
                                                          TEREP_LEPES, self.ref) + hs.tobytes())
        if self.van_kep:
            sorok = []
            for r in range(self.kep_h):
                sor_ = bytearray(self.kep_w * 3)
                sor_[0::3] = self.park[r]
                sor_[1::3] = self.viz[r]
                sorok.append(sor_)
            png_iras(kimenet / "landcover.png", self.kep_w, self.kep_h, sorok)


def hid_tengelyek():
    """A Duna-hidak víz fölötti tengelypontjai (terkep3d/data_varos/hidak.json, hidak_keszites.py): az OSM-ben szereplő
    híd-épületek (pillérek, kőtornyok) helyett a saját hídmodell látszik. Rács: (cella) -> [(x, z, sugár)]."""
    ut = KIMENET / "hidak.json"
    if not VAROS or not ut.exists():
        return {}
    racs = defaultdict(list)
    for h in json.load(open(ut, encoding="utf-8")).get("hidak", []):
        r = float(h.get("hw") or 8.0) + 6.0
        for x, z in h.get("tengely", []):
            racs[(int(x // 40), int(z // 40))].append((x, z, r))
    return racs


def hid_alatt(racs, x, z):
    cx, cz = int(x // 40), int(z // 40)
    for dx in (-1, 0, 1):
        for dz in (-1, 0, 1):
            for px, pz, r in racs.get((cx + dx, cz + dz), ()):
                if (px - x) ** 2 + (pz - z) ** 2 <= r * r:
                    return True
    return False


def ismert_statisztika(ep):
    """A Névjegy számai: hány különböző épületnek van pontos éve, és hány különböző épület van. Egy épület (OSM-elem) több
    körvonala és a részekből kirajzolt épület részei egy épületnek számítanak; a híd-elemek és a romok nem számítanak."""
    def kulcs(e):
        pr = e["pr"]
        if pr.get("resz") and pr.get("szulo_id"):
            return (pr.get("szulo_tipus") or "way", pr["szulo_id"])
        return (pr.get("osm_tipus") or "way", pr.get("id"))
    egyedi = {kulcs(e) for e in ep}
    ismert = {kulcs(e) for e in ep if e["ev"] is not None and not e["rom"]}
    return {"epulet_egyedi": len(egyedi), "ismert_ev_epulet": len(ismert)}


def veletlen(kulcs):
    """0 és 1 közötti, az azonosítóból számolt (tehát mindig ugyanaz) érték."""
    return (zlib.crc32(kulcs.encode()) % 10000 + 0.5) / 10000


def main():
    ut = ADAT / ("varos/epuletek_vegleges.geojson" if VAROS else "belvaros_epuletek_vegleges.geojson")
    print(f"Beolvasás: {ut}")
    gj = json.load(open(ut, encoding="utf-8"))
    ep = []
    hid_racs = hid_tengelyek()
    hid_elrejtve = 0
    for f in gj["features"]:
        pr = f["properties"]
        polyk = poligonok(f["geometry"])
        if not polyk:
            continue
        kp = [kozeppont(p) for p in polyk]
        x = sum(p[0] for p in kp) / len(kp)
        z = sum(p[1] for p in kp) / len(kp)
        if hid_racs and hid_alatt(hid_racs, x, z):      # az OSM híd-épülete (pillér, kőtorony) a saját hídmodell helyett
            hid_elrejtve += 1
            continue
        ev = pr.get("ev")
        try:
            ev = int(ev) if ev not in (None, "") else None
        except (TypeError, ValueError):
            ev = None
        if ev is not None and not (1 <= ev <= MOST):
            ev = None
        rom = bool(pr.get("rom"))
        if rom:
            ev = None
        ep.append({"pr": pr, "poly": polyk, "x": x, "z": z, "ev": ev, "rom": rom,
                   "est": None if rom else pr.get("ev_becsles_korszak"), "ev_kep": None, "fajta": None, "kor": None})
    print(f"Épületek: {len(ep)}" + (f" (a Duna-hidak alatt/helyén kihagyva: {hid_elrejtve} OSM-épület, mert a hidakat a saját modell mutatja)" if hid_racs else ""))
    gj = None

    # rács a szomszédkereséshez
    racs = defaultdict(list)
    for i, e in enumerate(ep):
        racs[(int(e["x"] // SZOMSZED_M), int(e["z"] // SZOMSZED_M))].append(i)

    def kozel(e, felt, sugar=SZOMSZED_M):
        cx, cz = int(e["x"] // SZOMSZED_M), int(e["z"] // SZOMSZED_M)
        r = int(math.ceil(sugar / SZOMSZED_M))
        ki = []
        for dx in range(-r, r + 1):
            for dz in range(-r, r + 1):
                for j in racs.get((cx + dx, cz + dz), ()):
                    o = ep[j]
                    if felt(o) and math.hypot(o["x"] - e["x"], o["z"] - e["z"]) <= sugar:
                        ki.append(j)
        return ki

    # 0) romok (ókori, középkori maradványok): az "1867 előtt" korszakba kerülnek, az első évtől látszanak, másra nem hatnak
    for e in ep:
        if e["rom"]:
            e["ev_kep"], e["fajta"], e["kor"] = ELSO_EV_MIN, 0, ROM_KOR

    # 1) ismert évek
    ismert_korszakonkent = defaultdict(list)
    for e in ep:
        if e["ev"]:
            e["ev_kep"], e["fajta"] = e["ev"], 0
            e["kor"] = korszak_ev_szerint(e["ev"])
            ismert_korszakonkent[e["kor"]].append(e["ev"])

    # 2) becsült korszakú épületek: év a közeli, azonos korszakú ismert évek közül
    becsult = 0
    for e in ep:
        if e["fajta"] is not None or e["est"] is None:
            continue
        k = int(e["est"])
        kozeli = [ep[j]["ev"] for j in kozel(e, lambda o, k=k: o["ev"] and o["kor"] == k)]
        lista = sorted(kozeli) if kozeli else sorted(ismert_korszakonkent.get(k, []))
        if not lista:
            tol, ig = KORSZAKOK[k][0], min(KORSZAKOK[k][1], MOST)
            lista = [(tol + ig) // 2]
        q = veletlen(f'{e["pr"].get("osm_tipus")}{e["pr"]["id"]}')
        e["ev_kep"], e["fajta"], e["kor"] = lista[min(int(q * len(lista)), len(lista) - 1)], 1, k
        becsult += 1

    # 3) a többi (pl. épületrészek becslés nélkül): a legközelebbi, már évvel rendelkező épület évét kapják
    maradek = [e for e in ep if e["fajta"] is None]
    if VAROS:
        # az egész városban sok az évszám nélküli épület: a legközelebbi ismert évű (vagy becsült) épület évét kapják,
        # ehhez külön rács készül csak az ismertekből (a gyors kereséshez)
        ism = defaultdict(list)
        for e in ep:
            if e["fajta"] is not None and not e["rom"]:
                ism[(int(e["x"] // SZOMSZED_M), int(e["z"] // SZOMSZED_M))].append(e)
        # egy épület részei (building:part) együtt kapnak korszakot: a részek közös középpontjához legközelebbi épületét.
        # Korábban részenként külön kerestünk, és egy ház részei eltérő színt kaphattak (42 épület).
        csop = defaultdict(list)
        tavoli = 0
        for e in maradek:
            sz = e["pr"].get("szulo_id")
            csop[(e["pr"].get("szulo_tipus"), sz) if sz else id(e)].append(e)
        for tagok in csop.values():
            e = {"x": sum(t["x"] for t in tagok) / len(tagok), "z": sum(t["z"] for t in tagok) / len(tagok)}
            cx, cz = int(e["x"] // SZOMSZED_M), int(e["z"] // SZOMSZED_M)
            for sugar in (SZOMSZED_M, 400.0, 1500.0):
                r = int(math.ceil(sugar / SZOMSZED_M))
                legjobb, tav = None, sugar
                for dx in range(-r, r + 1):
                    for dz in range(-r, r + 1):
                        for o in ism.get((cx + dx, cz + dz), ()):
                            dd = math.hypot(o["x"] - e["x"], o["z"] - e["z"])
                            if dd <= tav:
                                legjobb, tav = o, dd
                if legjobb:
                    ertek = (legjobb["ev_kep"], legjobb["kor"], 2)
                    break
            else:
                ertek = (1890, 1, 2)
                tavoli += len(tagok)
            for t in tagok:
                t["ev_kep"], t["kor"], t["fajta"] = ertek
        if tavoli:
            print(f"  Figyelem: {tavoli} épületnek 1500 m-en belül sincs korszakos szomszédja: 1890-et kapott")
    for e in ([] if VAROS else maradek):
        for sugar in (SZOMSZED_M, 400.0, 1500.0):
            jel = kozel(e, lambda o: o["fajta"] is not None and o is not e and not o["rom"], sugar)
            if jel:
                j = min(jel, key=lambda j: math.hypot(ep[j]["x"] - e["x"], ep[j]["z"] - e["z"]))
                e["ev_kep"], e["kor"] = ep[j]["ev_kep"], ep[j]["kor"]
                e["fajta"] = 2
                break
        else:
            e["ev_kep"], e["kor"], e["fajta"] = 1890, 1, 2
    print(f"  ismert év: {sum(1 for e in ep if e['fajta'] == 0)}, becsült korszak: {becsult}, "
          f"szomszédtól átvett: {len(maradek)}")

    # domborzat
    terep = None
    viz = None
    viz_ut = ADAT / ("varos/viz_zold.json" if VAROS else "viz_zold.json")
    if viz_ut.exists():
        viz = json.load(open(viz_ut, encoding="utf-8"))
        print(f"  víz és parkok: {len(viz)} sokszög ({viz_ut})")
    else:
        print(f"  (nincs {viz_ut}: víz és parkok nélkül)")
    if Domborzat is None:
        print("  (nincs dem.py: domborzat nélkül)")
    else:
        try:
            terep = Terep(ep, viz)
            print(f"  domborzat: {terep.nx}x{terep.nz} pont, a Duna szintje {terep.ref:.1f} m "
                  f"({terep.vizi_cellak} vízminta), az SRTM értékei {terep.dsm_stat[0]:.0f}-{terep.dsm_stat[1]:.0f} m")
        except HibasFajl as hiba:
            print(f"  (domborzat nélkül: {hiba})")
    for e in ep:
        e["base"] = 0.0
        if terep:
            e["base"] = min(terep.talaj(x, z) for poly in e["poly"] for (x, z) in poly[0])

    # szintszám minden elemhez; az egy épülethez tartozó részek (building:part) a legnagyobb szintszámot kapják,
    # hogy a szintek nézetben az egész épület egyszínű legyen (pl. az Országház)
    for e in ep:
        pr = e["pr"]
        szint = pr.get("szintek")
        try:
            szint = int(round(float(szint))) if szint not in (None, "") else None
        except (TypeError, ValueError):
            szint = None
        if not szint:
            szint = int(round(max(3.0, float(pr.get("magassag") or 12.0)) / 3.2))
        elif pr.get("magassag_forras") == "height":
            # a szintek nézet színe a tényleges magasságot kövesse: a kevés szintet rögzítő adat (pl. templom 4 'szinttel',
            # amely 96 m magas) ne világítson halványan a vele egymagas, de szintes épületek mellett
            try:
                szint = max(szint, int(round(float(pr["magassag"]) / 3.2)))
            except (TypeError, ValueError, KeyError):
                pass
        e["szint"] = max(1, min(127, szint))
    csoport = defaultdict(int)
    for e in ep:
        if e["pr"].get("szulo_id"):
            k = (e["pr"].get("szulo_tipus"), e["pr"]["szulo_id"])
            csoport[k] = max(csoport[k], e["szint"])
    for e in ep:
        if e["pr"].get("szulo_id"):
            e["szint"] = csoport[(e["pr"].get("szulo_tipus"), e["pr"]["szulo_id"])]

    # csempék
    csempek = defaultdict(list)
    for gid, e in enumerate(ep):
        e["gid"] = gid
        csempek[(int(e["x"] // CSEMPE), int(e["z"] // CSEMPE))].append(e)

    KIMENET.mkdir(parents=True, exist_ok=True)
    pack = bytearray()
    jegyzek = []
    hisztogram = defaultdict(lambda: [0] * len(KORSZAKOK))
    ev_min = MOST
    for (tx, tz), lista in sorted(csempek.items()):
        ox, oz = tx * CSEMPE, tz * CSEMPE
        gid_, ev_, flag_, per_, flo_, en_, l0_, l1_ = (array("I"), array("h"), array("B"), array("B"),
                                                         array("B"), array("B"), array("I"), array("I"))
        part_start, mag_, ring_start, vert_start, hole_ = (array("I", [0]), array("f"), array("I", [0]),
                                                           array("I", [0]), array("B"))
        xz_, y_ = array("h"), array("h")
        for e in lista:
            pr = e["pr"]
            h = float(pr.get("magassag") or 12.0)
            h = max(3.0, h)
            szint = e["szint"]
            gid_.append(e["gid"])
            ev_.append(max(ELSO_EV_MIN, int(e["ev_kep"])))   # a 1700 előtti épületek is az első évben jelennek meg
            flag_.append(e["fajta"])
            per_.append(e["kor"])
            flo_.append(szint)
            en_.append(0)
            l0_.append(int(round((e["base"] + 100) * 10)))   # talpmagasság dm-ben, +100 m eltolással
            l1_.append(0)
            ev_min = min(ev_min, e["ev_kep"])
            hisztogram[e["ev_kep"]][e["kor"]] += 1
            for poly in e["poly"]:
                mag_.append(h)
                for k, gyuru in enumerate(poly):
                    for (x, z) in gyuru:
                        xz_.append(max(-32768, min(32767, int(round((x - ox) * 10)))))
                        xz_.append(max(-32768, min(32767, int(round((z - oz) * 10)))))
                        y_.append(0)
                    vert_start.append(len(y_))
                    hole_.append(0 if k == 0 else 1)
                ring_start.append(len(hole_))
            part_start.append(len(mag_))

        def pad(b):
            return b + b"\0" * (-len(b) % 4)

        def bytes_(a):
            if sys.byteorder != "little":
                a = array(a.typecode, a)
                a.byteswap()
            return pad(a.tobytes())

        head = struct.pack("<IIIIIff", MAGIC, len(gid_), len(mag_), len(hole_), len(y_), float(ox), float(oz))
        tile = head
        for a in (gid_, ev_, flag_, per_, flo_, en_, l0_, l1_, part_start, mag_, ring_start, vert_start,
                  hole_, xz_, y_):
            tile += bytes_(a)
        jegyzek.append({"file": f"{tx}_{tz}", "pack": "tiles.bin", "offset": len(pack), "length": len(tile)})
        pack += tile
    (KIMENET / "tiles.bin").write_bytes(bytes(pack))

    # a kártya adatai
    rekordok = []
    kepek = {}
    kepek_ut = ADAT / ("varos/commons_kepek.json" if VAROS else "commons_kepek.json")
    if kepek_ut.exists():
        kepek = json.load(open(kepek_ut, encoding="utf-8"))
        print(f"  Commons-fotók: {len(kepek)} épületcsoport")
    for e in ep:
        pr = e["pr"]
        r = {k: pr[k] for k in KARTYA_MEZOK if pr.get(k) not in (None, "", False)}
        lat, lon = vissza(e["x"], e["z"])
        r["lat"], r["lon"] = (round(lat, 5), round(lon, 5)) if VAROS else (round(lat, 6), round(lon, 6))
        if kepek:
            if pr.get("resz") and pr.get("szulo_id"):
                kk = f"{pr.get('szulo_tipus') or 'way'}:{pr['szulo_id']}"
            else:
                kk = f"{pr.get('osm_tipus') or 'way'}:{pr.get('id')}"
            k = kepek.get(kk)
            if k:
                r["kep"] = [k["f"], k.get("a", ""), k.get("l", ""), k.get("u", ""), k.get("m", ""), k.get("r", 0)]
        r["kor"] = e["kor"]
        rekordok.append(r)
    (KIMENET / "epuletek.json").write_text(json.dumps(rekordok, ensure_ascii=False, separators=(",", ":")),
                                           encoding="utf-8")

    hidak_lechner()

    xs = [e["x"] for e in ep]
    zs = [e["z"] for e in ep]
    kozep = ((min(xs) + max(xs)) / 2, (min(zs) + max(zs)) / 2)
    span = max(max(xs) - min(xs), max(zs) - min(zs))
    ev_min = max(ELSO_EV_MIN, ev_min)
    config = {
        "name": "Budapest, épületenként",
        "yearMin": int(ev_min), "yearMax": MOST,
        "periods": [{"from": a, "to": b, "label": hu, "label_en": en, "color": szin}
                    for a, b, hu, en, szin in KORSZAKOK],
        "home": ({"x": 340, "z": 1100, "azimuth": -40, "elevation": 24, "span": 3300} if VAROS else
                 {"x": round(kozep[0]), "z": round(kozep[1]), "azimuth": 20, "elevation": 38, "span": round(span * 0.9)}),
        "stats": {"buildings": len(ep), **ismert_statisztika(ep)},
        "packs": ["tiles.bin"], "tiles": jegyzek,
        "histogram": {str(max(y, ev_min)): v for y, v in sorted(hisztogram.items())},
    }
    # az ev_min alatti évek (ha lennének) az első évbe kerülnek
    hist = defaultdict(lambda: [0] * len(KORSZAKOK))
    for y, v in hisztogram.items():
        yy = max(y, int(ev_min))
        for i, c in enumerate(v):
            hist[yy][i] += c
    config["histogram"] = {str(y): v for y, v in sorted(hist.items())}
    if terep:
        terep.iras(KIMENET)
        config["terep"] = {"van": True, "ref": terep.ref, "kep": terep.van_kep,
                           "x0": terep.x0, "z0": terep.z0, "w": terep.x1 - terep.x0 + 0.0, "h": terep.z1 - terep.z0 + 0.0,
                           "eszrevetel": "SRTM: NASA, Shuttle Radar Topography Mission"}
        alapok = sorted(e["base"] for e in ep)
        print(f"  épület-talpmagasság: 0-{alapok[-1]:.0f} m, medián {alapok[len(alapok) // 2]:.1f} m")
    (KIMENET / "budapest.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

    meret = (KIMENET / "tiles.bin").stat().st_size
    print(f"Csempék: {len(jegyzek)}, tiles.bin: {meret // 1024} KB")
    print(f"Kész: {KIMENET}/ (a 3D nézet: terkep3d/index.html, kiszolgálva a szerkesztő szerverrel)")


if __name__ == "__main__":
    main()
