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
PAUSE = 1.2         # s, between two requests (Wikimedia asks us not to overload it)
DATA = Path("data")
CACHE = DATA / "cache" / "commons_geo.json"
DEL, WEST, NORTH, EAST = 47.488, 19.038, 47.515, 19.064      # slightly larger than the building area
RADIUS = 300           # m, radius of one query
STEP = 400           # m, distance between the circles' centres
ADDRESS_DISTANCE = 180.0       # m: maximum distance between the photo and the building for an address match
NAME_DISTANCE = 120.0       # m: for a name match
MIN_WIDE = 600      # pixels: smaller images are not used
BANNED = ("terkep", "térkép", "map", "plan", "alaprajz", "logo", "címer", "cimer", "coat of arms", "diagram",
           "plakat", "poster", "stamp", "bélyeg")
# detail photos (plaque, altar, staircase...): these do not show the building but a detail or the interior of it
DETAIL = re.compile(r"\b(?:emlektabl|emlekhely|emlekmu|emlekmuv|plaque|stolperstein|oltar|szoszek|olvasoterem|"
                     r"lepcsohaz|lifthaz|bejarat|kapu|kapualj|udvar|erkely|detail|reszlet|szobor|statue|kut|fountain|"
                     r"freskó|mennyezet|csillar|ablak|ajto|kilincs|folyoso|terem|aula|nagyterem|kupola|sirko|koporso|"
                     r"mellekoltar|orgona|keresztut|stalla|interior|lobby|room|stairs|staircase|ceiling|window|door|"
                     r"gazcso|atepites alatt|haztartasi|elelmiszer|vendeglo|etterem teraszan|belso|inside)\w*\b")
GENERAL_NAME = {"budapest", "irodahaz", "iroda", "lakohaz", "haz", "epulet", "szallo", "hotel", "templom",
                 "iskola", "bank", "uzlet", "garazs", "parkolo", "ovoda", "szekhaz", "palota"}

SUFFIX = {"utca": "utca", "u": "utca", "ut": "ut", "ter": "ter", "korut": "korut", "krt": "korut",
           "rakpart": "rakpart", "rkp": "rakpart", "koz": "koz", "setany": "setany", "fasor": "fasor",
           "sor": "sor", "park": "park", "lepcso": "lepcso"}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def distance(lat1, lon1, lat2, lon2):
    dy = (lat2 - lat1) * 111_000.0
    dx = (lon2 - lon1) * 111_320.0 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


def get(params):
    for attempt in range(8):
        try:
            district_s = urllib.request.Request(API + "?" + urllib.parse.urlencode(dict(params, format="json")), headers=UA)
            with urllib.request.urlopen(district_s, timeout=60) as v:
                return json.load(v)
        except urllib.error.HTTPError as error_:
            if error_.code in (429, 503):
                var = error_.headers.get("Retry-After")
                var = int(var) if var and var.isdigit() else 30 * (attempt + 1)
                print(f"    a Commons lassítást kér ({error_.code}), várok {var} másodpercet...")
                time.sleep(var)
            else:
                print(f"    újrapróbálom ({error_})")
                time.sleep(2 ** attempt)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error_:
            print(f"    újrapróbálom ({error_})")
            time.sleep(2 ** attempt)
    raise SystemExit("A Commons nem válaszol. Futtasd újra később: a program onnan folytatja, ahol abbamaradt.")


# ---------- 1. Commons' geotagged files ----------
def era_query(lat, lon, radius):
    """The results of one circle. If Commons returns an error message (this can also be a 200 response), we wait and retry:
    an erroneous response must never be saved as an empty result."""
    for attempt in range(6):
        j = get({"action": "query", "list": "geosearch", "gscoord": f"{lat}|{lon}", "gsradius": int(round(radius)),
                 "gsnamespace": 6, "gslimit": 500})
        if "error" in j or "query" not in j:
            print(f"    a Commons hibát jelzett: {str(j.get('error') or j)[:200]} - várok és újrapróbálom")
            time.sleep(20 * (attempt + 1))
            continue
        return j["query"].get("geosearch", [])
    raise SystemExit("A Commons hibát ad a kérésekre. Futtasd újra később: a program onnan folytatja, ahol abbamaradt.")


def era_walk(lat, lon, radius, depth=0):
    hits = era_query(lat, lon, radius)
    time.sleep(PAUSE)
    if len(hits) >= 500 and depth < 3:          # full: split into four smaller circles
        out = []
        d = radius / 2 / 111_000.0
        dl = d / math.cos(math.radians(lat))
        for a, b in ((d, dl), (d, -dl), (-d, dl), (-d, -dl)):
            out += era_walk(lat + a, lon + b, max(10, int(round(radius / 1.5))), depth + 1)
        return out
    return hits


def fetch_files():
    """The results of the circles saved circle by circle (CACHE), so an interrupted run can be continued."""
    data_ = {"kesz": False, "cellak": {}}
    if CACHE.exists():
        old = json.loads(CACHE.read_text(encoding="utf-8"))
        if isinstance(old, dict):
            data_ = old
    unique = lambda: {f["title"]: f for list_ in data_["cellak"].values() for f in list_}
    if data_.get("kesz"):
        return list(unique().values())
    dlat = STEP / 111_000.0
    dlon = STEP / (111_320.0 * math.cos(math.radians((DEL + NORTH) / 2)))
    middles = []
    lat = DEL
    while lat <= NORTH + dlat / 2:
        lon = WEST
        while lon <= EAST + dlon / 2:
            middles.append((lat, lon))
            lon += dlon
        lat += dlat
    print(f"Commons-keresés: {len(middles)} kör ({len(data_['cellak'])} már megvan)")
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    for i, (lat, lon) in enumerate(middles, 1):
        building_key = f"{lat:.5f}|{lon:.5f}"
        if building_key in data_["cellak"]:
            continue
        data_["cellak"][building_key] = [{"title": f["title"], "lat": f["lat"], "lon": f["lon"]}
                                 for f in era_walk(lat, lon, RADIUS)]
        CACHE.write_text(json.dumps(data_, ensure_ascii=False), encoding="utf-8")
        print(f"  {i}/{len(middles)} kör kész ({len(data_['cellak'][building_key])} találat a körben), eddig {len(unique())} egyedi fájl")
    data_["kesz"] = True
    CACHE.write_text(json.dumps(data_, ensure_ascii=False), encoding="utf-8")
    return list(unique().values())


# ---------- 2. the buildings: addresses, names, location ----------
def read_buildings():
    addresses = defaultdict(list)       # (type, id) -> [(street, [house numbers])]
    path_ = DATA / ("varos/osm_cimek.csv" if CITY else "osm_cimek.csv")
    if path_.exists():
        with open(path_, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f, delimiter=";"):
                addresses[(row["osm_tipus"], str(row["id"]))].append((row["utca"], numbers_(row["hazszam"])))
    g = json.load(open(DATA / ("varos/epuletek_vegleges.geojson" if CITY else "belvaros_epuletek_vegleges.geojson"),
                       encoding="utf-8"))
    ep = {}
    for ft in g["features"]:
        p = ft["properties"]
        gy = ft["geometry"]
        outer = gy["coordinates"][0][0] if gy["type"] == "MultiPolygon" else gy["coordinates"][0]
        lon = sum(c[0] for c in outer) / len(outer)
        lat = sum(c[1] for c in outer) / len(outer)
        kind, az = p.get("osm_tipus") or "way", str(p.get("id"))
        building_key = (kind, az)
        if p.get("resz") and p.get("szulo_id"):
            key_address = (p.get("szulo_tipus") or "way", str(p["szulo_id"]))
        else:
            key_address = building_key
        names = set()
        for n in (p.get("nev"), (p.get("lechner_nev") or "").split("/")[0], ):
            if n:
                names.add(norm(n))
        for c in str(p.get("wikipedia") or "").split("|"):
            if ":" in c:
                names.add(norm(re.sub(r"\s*\(.*\)$", "", c.split(":", 1)[1])))
        names = {n for n in names if name_usable(n)}
        # the photo goes under the key of the building group (parent), so the parts get it too
        group_ = key_address if p.get("resz") and p.get("szulo_id") else building_key
        ep[building_key] = {"kulcs": f"{group_[0]}:{group_[1]}", "lat": lat, "lon": lon, "gyuru": outer,
                     "resz": bool(p.get("resz")),
                     "wikidata": p.get("wikidata"), "commons": p.get("commons"),
                     "cimek": addresses.get(key_address, []), "nevek": names, "nev": p.get("nev")}
    return ep


def numbers_(h):
    out = set()
    for m in re.finditer(r"(\d+)\s*[-–]\s*(\d+)|(\d+)", str(h)):
        if m.group(1):
            a, b = int(m.group(1)), int(m.group(2))
            if 0 < b - a <= 30:
                out.update(range(a, b + 1, 2))
                out.add(b)
            else:
                out.update((a, b))
        else:
            out.add(int(m.group(3)))
    return out


def name_usable(n):
    t = n.split()
    if not t:
        return False
    if len(t) == 1:
        return len(n) >= 8 and n not in GENERAL_NAME
    return not all(x in GENERAL_NAME for x in t)


def street_filter(street):
    """(core, suffix) from the normalised street name: 'Arany János utca' -> ('arany janos', 'utca')."""
    t = norm(street).split()
    if len(t) >= 2 and t[-1] in SUFFIX:
        return " ".join(t[:-1]), SUFFIX[t[-1]]
    return " ".join(t), ""


# ---------- 3. the matching ----------
def even(files, ep):
    streets = {}      # (core, suffix) -> {house number -> [key]}
    for building_key, e in ep.items():
        for street, house_no in e["cimek"]:
            height, suffix = street_filter(street)
            if not height:
                continue
            for n in house_no:
                streets.setdefault((height, suffix), {}).setdefault(n, []).append(building_key)
    core_count = defaultdict(int)
    for (height, suffix) in streets:
        core_count[height] += 1
    regexes = {}
    for (height, suffix) in streets:
        regexes[(height, suffix)] = re.compile(
            r"\b" + re.escape(height) + r"(?: (utca|u|ut|ter|korut|krt|rakpart|rkp|koz|setany|fasor|sor|park|lepcso))?"
            r" (\d{1,3})(?: ([a-z])\b)?(?: (\d{1,3})\b)?")
    name_index = defaultdict(list)
    for building_key, e in ep.items():
        for n in e["nevek"]:
            name_index[n].append(building_key)

    # grid for the "which building contains the photo's location" lookup
    grid = defaultdict(list)
    for building_key, e in ep.items():
        xs = [c[0] for c in e["gyuru"]]
        ys = [c[1] for c in e["gyuru"]]
        e["doboz"] = (min(xs), max(xs), min(ys), max(ys))
        for i in range(int(e["doboz"][0] / 0.001), int(e["doboz"][1] / 0.001) + 1):
            for j in range(int(e["doboz"][2] / 0.001), int(e["doboz"][3] / 0.001) + 1):
                grid[(i, j)].append(building_key)

    def where_has(lat, lon):
        best, small = None, None
        for building_key in grid.get((int(lon / 0.001), int(lat / 0.001)), ()):
            e = ep[building_key]
            d = e["doboz"]
            if d[0] <= lon <= d[1] and d[2] <= lat <= d[3] and _point_in_ring(lon, lat, e["gyuru"]):
                area_ = (d[1] - d[0]) * (d[3] - d[2])
                if small is None or area_ < small:
                    best, small = building_key, area_
        return best

    candidates = defaultdict(list)    # group key -> [(score, mode, file)]
    for f in files:
        address = f["title"].split(":", 1)[-1]
        address = re.sub(r"\.[A-Za-z0-9]{3,4}$", "", address)
        t = norm(address)
        if any(norm(x) in t for x in BANNED):
            continue
        # a detail photo (plaque, interior...) is better than nothing: it just ranks behind the facade photo
        bonus = (-40 if DETAIL.search(t) else 0) + (10 if "homlokzat" in t or "facade" in t else 0) - (15 if "fortepan" in t else 0)
        hit = {}                # key -> (score, mode)
        for (height, suffix), re_ in regexes.items():
            if height not in t:
                continue
            for m in re_.finditer(t):
                received = SUFFIX.get(m.group(1) or "", "")
                if received and suffix and received != suffix:
                    continue
                if not received and suffix and core_count[height] > 1:
                    continue
                n1 = int(m.group(2))
                n2 = int(m.group(4)) if m.group(4) else None
                numbers__ = {n1} if n2 is None or not (0 < n2 - n1 <= 30) else set(range(n1, n2 + 1))
                for n in numbers__:
                    for building_key in streets[(height, suffix)].get(n, []):
                        d = distance(f["lat"], f["lon"], ep[building_key]["lat"], ep[building_key]["lon"])
                        if d <= ADDRESS_DISTANCE:
                            point = 100 + (ADDRESS_DISTANCE - d) / 18 + bonus
                            if building_key not in hit or hit[building_key][0] < point:
                                hit[building_key] = (point, "cim")
        if not hit:
            for n, keys in name_index.items():
                if n in t and re.search(r"\b" + re.escape(n) + r"\b", t):     # the quick substring test first
                    for building_key in keys:
                        d = distance(f["lat"], f["lon"], ep[building_key]["lat"], ep[building_key]["lon"])
                        if d <= NAME_DISTANCE:
                            hit[building_key] = (60 + (NAME_DISTANCE - d) / 12 + bonus, "nev")
        if not hit and CITY:
            # no address or name in the file name: the building at the photo's location (in city mode only)
            building_key = where_has(f["lat"], f["lon"])
            if building_key:
                hit[building_key] = (30 + bonus, "hely")
        # if the file names several buildings, the nearest gets it
        if hit:
            building_key, (point, mode) = max(hit.items(), key=lambda kv: kv[1][0])
            candidates[ep[building_key]["kulcs"]].append((point, mode, f["title"], building_key))
    best = {}
    for group_, list_ in candidates.items():
        list_.sort(key=lambda x: -x[0])
        best[group_] = list_[:3]          # a fallback too: if the first has no free licence or is small
    return best


# ---------- 4. author, licence, size ----------
def text_(h):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", str(h or "")))).strip()


INFO_CACHE = DATA / "cache" / "commons_info.json"


def imageinfo(addresses):
    """Image data (size, author, licence); the ones already requested are taken from the cache."""
    result_ = json.loads(INFO_CACHE.read_text(encoding="utf-8")) if INFO_CACHE.exists() else {}
    addresses = sorted(c for c in set(addresses) if c not in result_)
    if not addresses:
        return result_
    for i in range(0, len(addresses), 40):
        detail = addresses[i:i + 40]
        j = get({"action": "query", "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
                 "titles": "|".join(detail)})
        for page in ((j.get("query") or {}).get("pages") or {}).values():
            ii = (page.get("imageinfo") or [None])[0]
            if ii:
                result_[page["title"]] = ii
        # Commons may normalise the titles (e.g. underscore -> space): we key them back the same way
        for rewritten in ((j.get("query") or {}).get("normalized") or []):
            if rewritten["to"] in result_:
                result_[rewritten["from"]] = result_[rewritten["to"]]
        INFO_CACHE.write_text(json.dumps(result_, ensure_ascii=False), encoding="utf-8")
        time.sleep(PAUSE)
        print(f"  képadatok: {min(i + 40, len(addresses))}/{len(addresses)}")
    return result_


# ---------- the whole city (called by download_budapest.py) ----------
CACHE_CITY = DATA / "cache" / "commons_geo_budapest.json"


def _point_in_ring(x, y, ring_):
    inside = False
    for (x1, y1), (x2, y2) in zip(ring_, ring_[1:] + ring_[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def fetch_city_files(rings, log=print):
    """Commons' geotagged files within the whole city boundary. The circle grid is the same as in the inner-city search
    (starting from DEL, NYUGAT), so the circles already downloaded (data/cache/commons_geo.json) are not downloaded again.
    The results are saved circle by circle: an interrupted download can be continued."""
    data_ = {"kesz": False, "cellak": {}}
    if CACHE_CITY.exists():
        data_ = json.loads(CACHE_CITY.read_text(encoding="utf-8"))
    if data_.get("kesz"):
        return
    if CACHE.exists():     # the circles of the inner-city search
        old = json.loads(CACHE.read_text(encoding="utf-8"))
        if isinstance(old, dict):
            for k, v in old.get("cellak", {}).items():
                la, lo = k.split("|")
                data_["cellak"].setdefault(f"{float(la):.4f}|{float(lo):.4f}", v)
    dlat = STEP / 111_000.0
    dlon = STEP / (111_320.0 * math.cos(math.radians((DEL + NORTH) / 2)))
    xs = [p[0] for g in rings for p in g]
    ys = [p[1] for g in rings for p in g]
    middles = []
    for i in range(math.floor((min(ys) - DEL) / dlat) - 1, math.ceil((max(ys) - DEL) / dlat) + 2):
        for j in range(math.floor((min(xs) - WEST) / dlon) - 1, math.ceil((max(xs) - WEST) / dlon) + 2):
            lat, lon = DEL + i * dlat, WEST + j * dlon
            # a circle is needed if its centre or the 8 points around it (about 450 m) lie within the city boundary
            points = [(lon, lat)] + [(lon + a * 450 / (111_320 * math.cos(math.radians(lat))), lat + b * 450 / 111_000)
                                     for a in (-1, 0, 1) for b in (-1, 0, 1) if a or b]
            if any(_point_in_ring(px, py, g) for (px, py) in points for g in rings):
                middles.append((lat, lon))
    log(f"Commons-keresés az egész városra: {len(middles)} kör, ebből {sum(1 for l, o in middles if f'{l:.4f}|{o:.4f}' in data_['cellak'])} már megvan")
    CACHE_CITY.parent.mkdir(parents=True, exist_ok=True)
    done = 0
    for n, (lat, lon) in enumerate(middles, 1):
        building_key = f"{lat:.4f}|{lon:.4f}"
        if building_key in data_["cellak"]:
            continue
        data_["cellak"][building_key] = [{"title": f["title"], "lat": f["lat"], "lon": f["lon"]}
                                 for f in era_walk(lat, lon, RADIUS)]
        done += 1
        if done % 5 == 0:
            CACHE_CITY.write_text(json.dumps(data_, ensure_ascii=False), encoding="utf-8")
        if done % 50 == 0:
            log(f"  Commons: {n}/{len(middles)} kör, eddig {len({f['title'] for l in data_['cellak'].values() for f in l})} fájl")
    data_["kesz"] = True
    CACHE_CITY.write_text(json.dumps(data_, ensure_ascii=False), encoding="utf-8")
    log(f"Commons: kész, {len({f['title'] for l in data_['cellak'].values() for f in l})} egyedi fájl az egész városban")


def city_files():
    """The Commons files of the whole city (saved by download_budapest.py / varos_fajlok_lekerese)."""
    if not CACHE_CITY.exists():
        raise SystemExit("Nincs data/cache/commons_geo_budapest.json - előbb a Commons-letöltés kell.")
    data_ = json.loads(CACHE_CITY.read_text(encoding="utf-8"))
    return list({f["title"]: f for list_ in data_["cellak"].values() for f in list_}.values())


CITY = len(sys.argv) > 1 and sys.argv[1] == "varos"      # py commons_images.py varos


def main():
    ep = read_buildings()
    print(f"Épületek: {len(ep)}")
    files = city_files() if CITY else fetch_files()
    print(f"Commons-fájlok a területen: {len(files)}")
    best = even(files, ep)
    print(f"Névvel vagy címmel párosított épületek: {len(best)}")
    ii = imageinfo([t for list_ in best.values() for (_, _, t, _) in list_])
    output = {}
    mode_count = defaultdict(int)
    for group_, list_ in best.items():
        for point, mode, address, building_key in list_:
            info = ii.get(address) or ii.get(address.replace("_", " "))
            if not info:
                continue
            if not str(info.get("mime", "")).startswith("image/") or info.get("mime") in ("image/svg+xml", "image/gif"):
                continue
            if info.get("width", 0) < MIN_WIDE:
                continue
            em = info.get("extmetadata") or {}
            licence = text_((em.get("LicenseShortName") or {}).get("value"))
            if not licence or "non-free" in licence.lower() or licence.lower().startswith("fair use"):
                continue
            output[group_] = {
                "f": address.split(":", 1)[-1].replace(" ", "_"),
                "a": text_((em.get("Artist") or {}).get("value"))[:90],
                "l": licence,
                "u": text_((em.get("LicenseUrl") or {}).get("value")),
                "m": mode,
                "r": 1 if DETAIL.search(norm(re.sub(r"\.[A-Za-z0-9]{3,4}$", "", address.split(":", 1)[-1]))) else 0,
            }
            mode_count[mode] += 1
            break
    output_path = DATA / ("varos/commons_kepek.json" if CITY else "commons_kepek.json")
    report_path = DATA / ("varos/commons_kepek_jelentes.md" if CITY else "commons_kepek_jelentes.md")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=0), encoding="utf-8")
    rows = ["# Commons-fotók az épületekhez", "",
             f"- Commons-fájl a területen: {len(files)}",
             f"- épület fotóval: {len(output)} (cím alapján: {mode_count['cim']}, név alapján: {mode_count['nev']}, helyadat alapján: {mode_count['hely']})", "",
             "## Példák az ellenőrzéshez (mód; épület; fájl)", ""]
    names = {e["kulcs"]: (e["nev"] or "") for e in ep.values()}
    for group_, k in list(output.items())[:60]:
        rows.append(f"- {k['m']}; {names.get(group_) or group_}; https://commons.wikimedia.org/wiki/File:{k['f']}")
    report_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"Kész: {len(output)} épületnek van fotója (cím: {mode_count['cim']}, név: {mode_count['nev']}, helyadat: {mode_count['hely']}).")
    print(f"Mentve: {output_path}, {report_path}  (most futtasd: py build_tiles.py)")


if __name__ == "__main__":
    main()
