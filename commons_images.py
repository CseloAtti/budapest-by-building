"""
commons_images.py - photos from Wikimedia Commons for the buildings (for the card image).

Run (in the project folder):   py commons_images.py
Output:   data/commons_kepek.json        (the best photo per building: file name, author, licence)
          data/commons_kepek_jelentes.md (summary and examples for checking)
Then:     py build_tiles.py          (the 3D view takes the images from here)

The method follows the s10_commons.py step of the Amsterdam project:
1. It walks the area with circles of 300 m radius and requests Commons' geotagged files (geosearch).
2. From the file name it reads the address (street + house number) or the building's name.
3. A photo is assigned to a building only if the file name names this building AND the photo's location is close to it
   (180 m by address, 120 m by name). This rules out a photo of a same-named street in another district ending up here.
4. The best match is kept per building (an address is stronger than a name, a nearer one stronger than a farther one).
5. The author and licence of the selected files are given by Commons; only freely licensed, sufficiently large images remain.

Uses only the Python standard library. The first run takes a few minutes; the downloaded raw data is saved
(data/cache/commons_geo.json), so repeated runs are fast.
"""
import csv
import html
import json
import math
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "budapest-by-building/0.1 (https://github.com/CseloAtti/budapest-by-building; oktatasi projekt)"}
SZUNET = 1.2         # s, between two requests (Wikimedia asks us not to overload it)
ADAT = Path("data")
CACHE = ADAT / "cache" / "commons_geo.json"
DEL, NYUGAT, ESZAK, KELET = 47.488, 19.038, 47.515, 19.064      # slightly larger than the building area
SUGAR = 300           # m, radius of one query
LEPES = 400           # m, distance between the circles' centres
CIM_TAV = 180.0       # m: maximum distance between the photo and the building for an address match
NEV_TAV = 120.0       # m: for a name match
MIN_SZELES = 600      # pixels: smaller images are not used
TILTOTT = ("terkep", "térkép", "map", "plan", "alaprajz", "logo", "címer", "cimer", "coat of arms", "diagram",
           "plakat", "poster", "stamp", "bélyeg")
# detail photos (plaque, altar, staircase...): these do not show the building but a detail or the interior of it
RESZLET = re.compile(r"\b(?:emlektabl|emlekhely|emlekmu|emlekmuv|plaque|stolperstein|oltar|szoszek|olvasoterem|"
                     r"lepcsohaz|lifthaz|bejarat|kapu|kapualj|udvar|erkely|detail|reszlet|szobor|statue|kut|fountain|"
                     r"freskó|mennyezet|csillar|ablak|ajto|kilincs|folyoso|terem|aula|nagyterem|kupola|sirko|koporso|"
                     r"mellekoltar|orgona|keresztut|stalla|interior|lobby|room|stairs|staircase|ceiling|window|door|"
                     r"gazcso|atepites alatt|haztartasi|elelmiszer|vendeglo|etterem teraszan|belso|inside)\w*\b")
ALTALANOS_NEV = {"budapest", "irodahaz", "iroda", "lakohaz", "haz", "epulet", "szallo", "hotel", "templom",
                 "iskola", "bank", "uzlet", "garazs", "parkolo", "ovoda", "szekhaz", "palota"}

SZUFFIX = {"utca": "utca", "u": "utca", "ut": "ut", "ter": "ter", "korut": "korut", "krt": "korut",
           "rakpart": "rakpart", "rkp": "rakpart", "koz": "koz", "setany": "setany", "fasor": "fasor",
           "sor": "sor", "park": "park", "lepcso": "lepcso"}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def tavolsag(lat1, lon1, lat2, lon2):
    dy = (lat2 - lat1) * 111_000.0
    dx = (lon2 - lon1) * 111_320.0 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


def get(params):
    for kiserlet in range(8):
        try:
            kerés = urllib.request.Request(API + "?" + urllib.parse.urlencode(dict(params, format="json")), headers=UA)
            with urllib.request.urlopen(kerés, timeout=60) as v:
                return json.load(v)
        except urllib.error.HTTPError as hiba:
            if hiba.code in (429, 503):
                var = hiba.headers.get("Retry-After")
                var = int(var) if var and var.isdigit() else 30 * (kiserlet + 1)
                print(f"    a Commons lassítást kér ({hiba.code}), várok {var} másodpercet...")
                time.sleep(var)
            else:
                print(f"    újrapróbálom ({hiba})")
                time.sleep(2 ** kiserlet)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as hiba:
            print(f"    újrapróbálom ({hiba})")
            time.sleep(2 ** kiserlet)
    raise SystemExit("A Commons nem válaszol. Futtasd újra később: a program onnan folytatja, ahol abbamaradt.")


# ---------- 1. Commons' geotagged files ----------
def kor_lekerdez(lat, lon, sugar):
    """The results of one circle. If Commons returns an error message (this can also be a 200 response), we wait and retry:
    an erroneous response must never be saved as an empty result."""
    for kiserlet in range(6):
        j = get({"action": "query", "list": "geosearch", "gscoord": f"{lat}|{lon}", "gsradius": int(round(sugar)),
                 "gsnamespace": 6, "gslimit": 500})
        if "error" in j or "query" not in j:
            print(f"    a Commons hibát jelzett: {str(j.get('error') or j)[:200]} - várok és újrapróbálom")
            time.sleep(20 * (kiserlet + 1))
            continue
        return j["query"].get("geosearch", [])
    raise SystemExit("A Commons hibát ad a kérésekre. Futtasd újra később: a program onnan folytatja, ahol abbamaradt.")


def kor_bejar(lat, lon, sugar, melyseg=0):
    talalatok = kor_lekerdez(lat, lon, sugar)
    time.sleep(SZUNET)
    if len(talalatok) >= 500 and melyseg < 3:          # full: split into four smaller circles
        ki = []
        d = sugar / 2 / 111_000.0
        dl = d / math.cos(math.radians(lat))
        for a, b in ((d, dl), (d, -dl), (-d, dl), (-d, -dl)):
            ki += kor_bejar(lat + a, lon + b, max(10, int(round(sugar / 1.5))), melyseg + 1)
        return ki
    return talalatok


def fajlok_lekerese():
    """The results of the circles saved circle by circle (CACHE), so an interrupted run can be continued."""
    adat = {"kesz": False, "cellak": {}}
    if CACHE.exists():
        regi = json.loads(CACHE.read_text(encoding="utf-8"))
        if isinstance(regi, dict):
            adat = regi
    egyedi = lambda: {f["title"]: f for lista in adat["cellak"].values() for f in lista}
    if adat.get("kesz"):
        return list(egyedi().values())
    dlat = LEPES / 111_000.0
    dlon = LEPES / (111_320.0 * math.cos(math.radians((DEL + ESZAK) / 2)))
    kozepek = []
    lat = DEL
    while lat <= ESZAK + dlat / 2:
        lon = NYUGAT
        while lon <= KELET + dlon / 2:
            kozepek.append((lat, lon))
            lon += dlon
        lat += dlat
    print(f"Commons-keresés: {len(kozepek)} kör ({len(adat['cellak'])} már megvan)")
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    for i, (lat, lon) in enumerate(kozepek, 1):
        kulcs = f"{lat:.5f}|{lon:.5f}"
        if kulcs in adat["cellak"]:
            continue
        adat["cellak"][kulcs] = [{"title": f["title"], "lat": f["lat"], "lon": f["lon"]}
                                 for f in kor_bejar(lat, lon, SUGAR)]
        CACHE.write_text(json.dumps(adat, ensure_ascii=False), encoding="utf-8")
        print(f"  {i}/{len(kozepek)} kör kész ({len(adat['cellak'][kulcs])} találat a körben), eddig {len(egyedi())} egyedi fájl")
    adat["kesz"] = True
    CACHE.write_text(json.dumps(adat, ensure_ascii=False), encoding="utf-8")
    return list(egyedi().values())


# ---------- 2. the buildings: addresses, names, location ----------
def epuletek_beolvasasa():
    cimek = defaultdict(list)       # (type, id) -> [(street, [house numbers])]
    ut = ADAT / ("varos/osm_cimek.csv" if VAROS else "osm_cimek.csv")
    if ut.exists():
        with open(ut, encoding="utf-8-sig", newline="") as f:
            for sor in csv.DictReader(f, delimiter=";"):
                cimek[(sor["osm_tipus"], str(sor["id"]))].append((sor["utca"], szamok(sor["hazszam"])))
    g = json.load(open(ADAT / ("varos/epuletek_vegleges.geojson" if VAROS else "belvaros_epuletek_vegleges.geojson"),
                       encoding="utf-8"))
    ep = {}
    for ft in g["features"]:
        p = ft["properties"]
        gy = ft["geometry"]
        kulso = gy["coordinates"][0][0] if gy["type"] == "MultiPolygon" else gy["coordinates"][0]
        lon = sum(c[0] for c in kulso) / len(kulso)
        lat = sum(c[1] for c in kulso) / len(kulso)
        tip, az = p.get("osm_tipus") or "way", str(p.get("id"))
        kulcs = (tip, az)
        if p.get("resz") and p.get("szulo_id"):
            kulcs_cim = (p.get("szulo_tipus") or "way", str(p["szulo_id"]))
        else:
            kulcs_cim = kulcs
        nevek = set()
        for n in (p.get("nev"), (p.get("lechner_nev") or "").split("/")[0], ):
            if n:
                nevek.add(norm(n))
        for c in str(p.get("wikipedia") or "").split("|"):
            if ":" in c:
                nevek.add(norm(re.sub(r"\s*\(.*\)$", "", c.split(":", 1)[1])))
        nevek = {n for n in nevek if nev_hasznalhato(n)}
        # the photo goes under the key of the building group (parent), so the parts get it too
        csoport = kulcs_cim if p.get("resz") and p.get("szulo_id") else kulcs
        ep[kulcs] = {"kulcs": f"{csoport[0]}:{csoport[1]}", "lat": lat, "lon": lon, "gyuru": kulso,
                     "resz": bool(p.get("resz")),
                     "wikidata": p.get("wikidata"), "commons": p.get("commons"),
                     "cimek": cimek.get(kulcs_cim, []), "nevek": nevek, "nev": p.get("nev")}
    return ep


def szamok(h):
    ki = set()
    for m in re.finditer(r"(\d+)\s*[-–]\s*(\d+)|(\d+)", str(h)):
        if m.group(1):
            a, b = int(m.group(1)), int(m.group(2))
            if 0 < b - a <= 30:
                ki.update(range(a, b + 1, 2))
                ki.add(b)
            else:
                ki.update((a, b))
        else:
            ki.add(int(m.group(3)))
    return ki


def nev_hasznalhato(n):
    t = n.split()
    if not t:
        return False
    if len(t) == 1:
        return len(n) >= 8 and n not in ALTALANOS_NEV
    return not all(x in ALTALANOS_NEV for x in t)


def utca_szuro(utca):
    """(core, suffix) from the normalised street name: 'Arany János utca' -> ('arany janos', 'utca')."""
    t = norm(utca).split()
    if len(t) >= 2 and t[-1] in SZUFFIX:
        return " ".join(t[:-1]), SZUFFIX[t[-1]]
    return " ".join(t), ""


# ---------- 3. the matching ----------
def paros(fajlok, ep):
    utcak = {}      # (core, suffix) -> {house number -> [key]}
    for kulcs, e in ep.items():
        for utca, hsz in e["cimek"]:
            mag, szuf = utca_szuro(utca)
            if not mag:
                continue
            for n in hsz:
                utcak.setdefault((mag, szuf), {}).setdefault(n, []).append(kulcs)
    mag_db = defaultdict(int)
    for (mag, szuf) in utcak:
        mag_db[mag] += 1
    regexek = {}
    for (mag, szuf) in utcak:
        regexek[(mag, szuf)] = re.compile(
            r"\b" + re.escape(mag) + r"(?: (utca|u|ut|ter|korut|krt|rakpart|rkp|koz|setany|fasor|sor|park|lepcso))?"
            r" (\d{1,3})(?: ([a-z])\b)?(?: (\d{1,3})\b)?")
    nev_index = defaultdict(list)
    for kulcs, e in ep.items():
        for n in e["nevek"]:
            nev_index[n].append(kulcs)

    # grid for the "which building contains the photo's location" lookup
    racs = defaultdict(list)
    for kulcs, e in ep.items():
        xs = [c[0] for c in e["gyuru"]]
        ys = [c[1] for c in e["gyuru"]]
        e["doboz"] = (min(xs), max(xs), min(ys), max(ys))
        for i in range(int(e["doboz"][0] / 0.001), int(e["doboz"][1] / 0.001) + 1):
            for j in range(int(e["doboz"][2] / 0.001), int(e["doboz"][3] / 0.001) + 1):
                racs[(i, j)].append(kulcs)

    def hol_van(lat, lon):
        legjobb, kis = None, None
        for kulcs in racs.get((int(lon / 0.001), int(lat / 0.001)), ()):
            e = ep[kulcs]
            d = e["doboz"]
            if d[0] <= lon <= d[1] and d[2] <= lat <= d[3] and _pont_gyuruben(lon, lat, e["gyuru"]):
                ter = (d[1] - d[0]) * (d[3] - d[2])
                if kis is None or ter < kis:
                    legjobb, kis = kulcs, ter
        return legjobb

    jeloltek = defaultdict(list)    # group key -> [(score, mode, file)]
    for f in fajlok:
        cim = f["title"].split(":", 1)[-1]
        cim = re.sub(r"\.[A-Za-z0-9]{3,4}$", "", cim)
        t = norm(cim)
        if any(norm(x) in t for x in TILTOTT):
            continue
        # a detail photo (plaque, interior...) is better than nothing: it just ranks behind the facade photo
        bonusz = (-40 if RESZLET.search(t) else 0) + (10 if "homlokzat" in t or "facade" in t else 0) - (15 if "fortepan" in t else 0)
        talalat = {}                # key -> (score, mode)
        for (mag, szuf), re_ in regexek.items():
            if mag not in t:
                continue
            for m in re_.finditer(t):
                kapott = SZUFFIX.get(m.group(1) or "", "")
                if kapott and szuf and kapott != szuf:
                    continue
                if not kapott and szuf and mag_db[mag] > 1:
                    continue
                n1 = int(m.group(2))
                n2 = int(m.group(4)) if m.group(4) else None
                szamok_ = {n1} if n2 is None or not (0 < n2 - n1 <= 30) else set(range(n1, n2 + 1))
                for n in szamok_:
                    for kulcs in utcak[(mag, szuf)].get(n, []):
                        d = tavolsag(f["lat"], f["lon"], ep[kulcs]["lat"], ep[kulcs]["lon"])
                        if d <= CIM_TAV:
                            pont = 100 + (CIM_TAV - d) / 18 + bonusz
                            if kulcs not in talalat or talalat[kulcs][0] < pont:
                                talalat[kulcs] = (pont, "cim")
        if not talalat:
            for n, kulcsok in nev_index.items():
                if n in t and re.search(r"\b" + re.escape(n) + r"\b", t):     # the quick substring test first
                    for kulcs in kulcsok:
                        d = tavolsag(f["lat"], f["lon"], ep[kulcs]["lat"], ep[kulcs]["lon"])
                        if d <= NEV_TAV:
                            talalat[kulcs] = (60 + (NEV_TAV - d) / 12 + bonusz, "nev")
        if not talalat and VAROS:
            # no address or name in the file name: the building at the photo's location (in city mode only)
            kulcs = hol_van(f["lat"], f["lon"])
            if kulcs:
                talalat[kulcs] = (30 + bonusz, "hely")
        # if the file names several buildings, the nearest gets it
        if talalat:
            kulcs, (pont, mod) = max(talalat.items(), key=lambda kv: kv[1][0])
            jeloltek[ep[kulcs]["kulcs"]].append((pont, mod, f["title"], kulcs))
    legjobb = {}
    for csoport, lista in jeloltek.items():
        lista.sort(key=lambda x: -x[0])
        legjobb[csoport] = lista[:3]          # a fallback too: if the first has no free licence or is small
    return legjobb


# ---------- 4. author, licence, size ----------
def szoveg(h):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", str(h or "")))).strip()


INFO_CACHE = ADAT / "cache" / "commons_info.json"


def imageinfo(cimek):
    """Image data (size, author, licence); the ones already requested are taken from the cache."""
    eredmeny = json.loads(INFO_CACHE.read_text(encoding="utf-8")) if INFO_CACHE.exists() else {}
    cimek = sorted(c for c in set(cimek) if c not in eredmeny)
    if not cimek:
        return eredmeny
    for i in range(0, len(cimek), 40):
        reszlet = cimek[i:i + 40]
        j = get({"action": "query", "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
                 "titles": "|".join(reszlet)})
        for lap in ((j.get("query") or {}).get("pages") or {}).values():
            ii = (lap.get("imageinfo") or [None])[0]
            if ii:
                eredmeny[lap["title"]] = ii
        # Commons may normalise the titles (e.g. underscore -> space): we key them back the same way
        for atirt in ((j.get("query") or {}).get("normalized") or []):
            if atirt["to"] in eredmeny:
                eredmeny[atirt["from"]] = eredmeny[atirt["to"]]
        INFO_CACHE.write_text(json.dumps(eredmeny, ensure_ascii=False), encoding="utf-8")
        time.sleep(SZUNET)
        print(f"  képadatok: {min(i + 40, len(cimek))}/{len(cimek)}")
    return eredmeny


# ---------- the whole city (called by download_budapest.py) ----------
CACHE_VAROS = ADAT / "cache" / "commons_geo_budapest.json"


def _pont_gyuruben(x, y, gyuru):
    bent = False
    for (x1, y1), (x2, y2) in zip(gyuru, gyuru[1:] + gyuru[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            bent = not bent
    return bent


def varos_fajlok_lekerese(gyuruk, naplo=print):
    """Commons' geotagged files within the whole city boundary. The circle grid is the same as in the inner-city search
    (starting from DEL, NYUGAT), so the circles already downloaded (data/cache/commons_geo.json) are not downloaded again.
    The results are saved circle by circle: an interrupted download can be continued."""
    adat = {"kesz": False, "cellak": {}}
    if CACHE_VAROS.exists():
        adat = json.loads(CACHE_VAROS.read_text(encoding="utf-8"))
    if adat.get("kesz"):
        return
    if CACHE.exists():     # the circles of the inner-city search
        regi = json.loads(CACHE.read_text(encoding="utf-8"))
        if isinstance(regi, dict):
            for k, v in regi.get("cellak", {}).items():
                la, lo = k.split("|")
                adat["cellak"].setdefault(f"{float(la):.4f}|{float(lo):.4f}", v)
    dlat = LEPES / 111_000.0
    dlon = LEPES / (111_320.0 * math.cos(math.radians((DEL + ESZAK) / 2)))
    xs = [p[0] for g in gyuruk for p in g]
    ys = [p[1] for g in gyuruk for p in g]
    kozepek = []
    for i in range(math.floor((min(ys) - DEL) / dlat) - 1, math.ceil((max(ys) - DEL) / dlat) + 2):
        for j in range(math.floor((min(xs) - NYUGAT) / dlon) - 1, math.ceil((max(xs) - NYUGAT) / dlon) + 2):
            lat, lon = DEL + i * dlat, NYUGAT + j * dlon
            # a circle is needed if its centre or the 8 points around it (about 450 m) lie within the city boundary
            pontok = [(lon, lat)] + [(lon + a * 450 / (111_320 * math.cos(math.radians(lat))), lat + b * 450 / 111_000)
                                     for a in (-1, 0, 1) for b in (-1, 0, 1) if a or b]
            if any(_pont_gyuruben(px, py, g) for (px, py) in pontok for g in gyuruk):
                kozepek.append((lat, lon))
    naplo(f"Commons-keresés az egész városra: {len(kozepek)} kör, ebből {sum(1 for l, o in kozepek if f'{l:.4f}|{o:.4f}' in adat['cellak'])} már megvan")
    CACHE_VAROS.parent.mkdir(parents=True, exist_ok=True)
    keszek = 0
    for n, (lat, lon) in enumerate(kozepek, 1):
        kulcs = f"{lat:.4f}|{lon:.4f}"
        if kulcs in adat["cellak"]:
            continue
        adat["cellak"][kulcs] = [{"title": f["title"], "lat": f["lat"], "lon": f["lon"]}
                                 for f in kor_bejar(lat, lon, SUGAR)]
        keszek += 1
        if keszek % 5 == 0:
            CACHE_VAROS.write_text(json.dumps(adat, ensure_ascii=False), encoding="utf-8")
        if keszek % 50 == 0:
            naplo(f"  Commons: {n}/{len(kozepek)} kör, eddig {len({f['title'] for l in adat['cellak'].values() for f in l})} fájl")
    adat["kesz"] = True
    CACHE_VAROS.write_text(json.dumps(adat, ensure_ascii=False), encoding="utf-8")
    naplo(f"Commons: kész, {len({f['title'] for l in adat['cellak'].values() for f in l})} egyedi fájl az egész városban")


def varos_fajlok():
    """The Commons files of the whole city (saved by download_budapest.py / varos_fajlok_lekerese)."""
    if not CACHE_VAROS.exists():
        raise SystemExit("Nincs data/cache/commons_geo_budapest.json - előbb a Commons-letöltés kell.")
    adat = json.loads(CACHE_VAROS.read_text(encoding="utf-8"))
    return list({f["title"]: f for lista in adat["cellak"].values() for f in lista}.values())


VAROS = len(sys.argv) > 1 and sys.argv[1] == "varos"      # py commons_images.py varos


def main():
    ep = epuletek_beolvasasa()
    print(f"Épületek: {len(ep)}")
    fajlok = varos_fajlok() if VAROS else fajlok_lekerese()
    print(f"Commons-fájlok a területen: {len(fajlok)}")
    legjobb = paros(fajlok, ep)
    print(f"Névvel vagy címmel párosított épületek: {len(legjobb)}")
    ii = imageinfo([t for lista in legjobb.values() for (_, _, t, _) in lista])
    kimenet = {}
    mod_db = defaultdict(int)
    for csoport, lista in legjobb.items():
        for pont, mod, cim, kulcs in lista:
            info = ii.get(cim) or ii.get(cim.replace("_", " "))
            if not info:
                continue
            if not str(info.get("mime", "")).startswith("image/") or info.get("mime") in ("image/svg+xml", "image/gif"):
                continue
            if info.get("width", 0) < MIN_SZELES:
                continue
            em = info.get("extmetadata") or {}
            licenc = szoveg((em.get("LicenseShortName") or {}).get("value"))
            if not licenc or "non-free" in licenc.lower() or licenc.lower().startswith("fair use"):
                continue
            kimenet[csoport] = {
                "f": cim.split(":", 1)[-1].replace(" ", "_"),
                "a": szoveg((em.get("Artist") or {}).get("value"))[:90],
                "l": licenc,
                "u": szoveg((em.get("LicenseUrl") or {}).get("value")),
                "m": mod,
                "r": 1 if RESZLET.search(norm(re.sub(r"\.[A-Za-z0-9]{3,4}$", "", cim.split(":", 1)[-1]))) else 0,
            }
            mod_db[mod] += 1
            break
    kimenet_ut = ADAT / ("varos/commons_kepek.json" if VAROS else "commons_kepek.json")
    jelentes_ut = ADAT / ("varos/commons_kepek_jelentes.md" if VAROS else "commons_kepek_jelentes.md")
    kimenet_ut.parent.mkdir(parents=True, exist_ok=True)
    kimenet_ut.write_text(json.dumps(kimenet, ensure_ascii=False, indent=0), encoding="utf-8")
    sorok = ["# Commons-fotók az épületekhez", "",
             f"- Commons-fájl a területen: {len(fajlok)}",
             f"- épület fotóval: {len(kimenet)} (cím alapján: {mod_db['cim']}, név alapján: {mod_db['nev']}, helyadat alapján: {mod_db['hely']})", "",
             "## Példák az ellenőrzéshez (mód; épület; fájl)", ""]
    nevek = {e["kulcs"]: (e["nev"] or "") for e in ep.values()}
    for csoport, k in list(kimenet.items())[:60]:
        sorok.append(f"- {k['m']}; {nevek.get(csoport) or csoport}; https://commons.wikimedia.org/wiki/File:{k['f']}")
    jelentes_ut.write_text("\n".join(sorok) + "\n", encoding="utf-8")
    print(f"Kész: {len(kimenet)} épületnek van fotója (cím: {mod_db['cim']}, név: {mod_db['nev']}, helyadat: {mod_db['hely']}).")
    print(f"Mentve: {kimenet_ut}, {jelentes_ut}  (most futtasd: py build_tiles.py)")


if __name__ == "__main__":
    main()
