"""Local server for the map, with an editing mode.

Start (in the project folder):   py editor_server.py
Open in the browser:             http://localhost:8000

It can do the same as `py -m http.server 8000`, but on the map the buildings' data can be corrected
in the popup with the "Edit" button. The corrections go into the forras/kezi_javitasok.csv
file (these always win). The "Rebuild map" button runs assemble.py.

Security: the server is reachable only from your own machine (127.0.0.1), writes only this one file,
and validates every value entered.
"""
import csv
import json
import math
import re
import unicodedata
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8000
MANUAL = Path("forras/kezi_javitasok.csv")
HEADER = ["osm_tipus", "id", "mezo", "ertek", "forras", "megjegyzes", "lat", "lon"]
NUMBERED = {"ev": (1000, 2100), "szintek": (1, 80), "magassag": (1, 500)}
TEXTUAL = {"tervezo", "iroda", "stilus"}
SINGLE_LINE = {"nev": 120}                      # the building's name
LONG_TEXT = {"about": 1500}              # free-text description (may have several paragraphs)
PROTECTION_CODES = {"M", "MJ", "VK", "MK", "MJT"}   # monument, monument-like, townscape, monument surroundings, area of monument significance
ALLOWED_ORIGIN = {f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}"}

# --- zones (polygons) from the zones.html editor ---
ZONES = Path("forras/zonak_poligon.geojson")
ZONE_TYPES = {"lakotelep", "telep", "kertvaros", "negyed", "lakopark", "ipar_kereskedelem", "egyeb", "muemlek"}
ZONE_STATES = {"helyismeret", "forrasolt", "ellenorizendo"}
ZONE_ORIGIN = {"kezi", "osm", "nominatim", "epuletbol", "lista"}
MAX_ZONE_SEARCH = 3_000_000
REJECTED = Path("forras/zona_elvetett.json")   # ids of zone-list items / candidates deleted for good in the editor


def save_rejected(data_):
    """{"ids": [...]} -> forras/zona_elvetett.json (the old state stays in .bak.json). Returns: (count, error)."""
    ids = data_.get("ids") if isinstance(data_, dict) else None
    if not isinstance(ids, list) or len(ids) > 5000:
        return None, "Hibás kérés."
    clean = []
    for x in ids:
        if not isinstance(x, str) or not x or len(x) > 120 or re.search(r"[\x00-\x1f<>]", x):
            return None, "Hibás azonosító."
        if x not in clean:
            clean.append(x)
    REJECTED.parent.mkdir(exist_ok=True)
    if REJECTED.exists():
        try:
            REJECTED.replace(REJECTED.with_suffix(".bak.json"))
        except OSError:
            pass
    time_ = REJECTED.with_suffix(".tmp")
    time_.write_text(json.dumps({"ids": sorted(clean)}, ensure_ascii=False, indent=1), encoding="utf-8")
    time_.replace(REJECTED)
    return len(clean), None



def clean_text(x, max_length):
    x = " ".join(str(x).split())          # remove line breaks, tabs, double spaces
    if not x or len(x) > max_length or re.search(r"[\x00-\x1f;]", str(x)):
        return None
    return x


def free_text(x, max_length, several_row):
    """Free text: control characters (except the line break) are forbidden; ';' is allowed (the CSV quotes it)."""
    x = str(x).replace("\r\n", "\n").replace("\r", "\n")
    if several_row:
        rows = [" ".join(s.split()) for s in x.split("\n")]
        x = "\n".join(rows).strip()
        while "\n\n\n" in x:
            x = x.replace("\n\n\n", "\n\n")
    else:
        x = " ".join(x.split())
    if not x or len(x) > max_length or re.search(r"[\x00-\x09\x0b-\x1f\x7f<>]", x):
        return None
    return x


def wikipedia_address(x):
    """Accepts: 'https://hu.wikipedia.org/wiki/Title' (also the mobile 'hu.m.' and the form without a scheme), 'hu:Title', 'en:Title',
    or a plain title ('Vécsey utcai lakótelep' -> hu:Vécsey utcai lakótelep). Output: 'hu:Title' (hu/en only)."""
    x = str(x).strip().strip("\"'“”„").strip()
    m = re.match(r"^(?:https?://)?(hu|en)(?:\.m)?\.wikipedia\.org/wiki/([^?#\s]+)(?:[#?].*)?$", x)
    if m:
        language, address = m.group(1), urllib.parse.unquote(m.group(2)).replace("_", " ")
    elif re.match(r"^(?:https?://)?(hu|en)(?:\.m)?\.wikipedia\.org/w/index\.php\?", x):
        # edit/permalink form: /w/index.php?title=Title&oldid=123 -> the title parameter
        m = re.match(r"^(?:https?://)?(hu|en)(?:\.m)?\.wikipedia\.org/w/index\.php\?(.*)$", x)
        t = urllib.parse.parse_qs(m.group(2).split("#")[0]).get("title")
        if not t:
            return None
        language, address = m.group(1), t[0].replace("_", " ")
    else:
        m = re.match(r"^(hu|en):(.+)$", x)
        if m:
            language, address = m.group(1), m.group(2).strip()
        elif re.match(r"^(?:https?://|www\.)", x, re.I) or re.search(r"\.(org|com|hu|net)\b", x, re.I):
            return None                      # a link to another page: not a Wikipedia article
        else:
            language, address = "hu", x             # a plain title: taken as a Hungarian article
    address = " ".join(address.split()).rstrip("/")
    if not address or len(address) > 150 or re.search(r"[\x00-\x1f;|<>\[\]{}]", address):
        return None
    return f"{language}:{address}"


def wikipedia_articles(x):
    """Several articles separated by '|' (at most 3); '-' = remove the field."""
    x = str(x).strip()
    if x == "-":
        return "-"
    parts = [wikipedia_address(r) for r in x.split("|") if r.strip()]
    if not parts or len(parts) > 3 or any(r is None for r in parts):
        return None
    return "|".join(dict.fromkeys(parts))


def url_clean(x, only_https=False):
    """Checks a web address (it goes into the CSV and onto the card): no space, quote, < > ; | or control character."""
    x = str(x).strip()
    if not 8 <= len(x) <= 400 or re.search(r"[\s<>\"'`;|\\\x00-\x1f\x7f]", x):
        return None
    if not re.match(r"^https://[^/]+\.[^/]+" if only_https else r"^https?://[^/]+\.[^/]+", x, re.I):
        return None
    return x


ARTWORK_BASE_ID = 3_000_000_000          # ids of the manually added works (OSM ids are much smaller than this)
MANUAL_BUILDINGS = Path("forras/kezi_epuletek.geojson")
DISTRICTS = Path("data/kerulethatarok.json")


def _in_ring(x, y, ring_):
    inside = False
    for (x1, y1), (x2, y2) in zip(ring_, ring_[1:]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def artwork_import(data_):
    """Adding a public artwork (not a building) from a point: a small, 3x3 m manual 'building' in forras/kezi_epuletek.geojson
    (assemble.py builds it in together with the other buildings), while the name/year/designer/description/photo/link go into
    forras/kezi_javitasok.csv as manual facts - so the architect highlighting, the card and the search work the same as for buildings."""
    name_ = free_text(data_.get("nev", ""), 120, False)
    if not name_:
        return None, "Add meg az alkotás nevét (legfeljebb 120 karakter)."
    designer = clean_text(data_.get("tervezo", ""), 100)
    if not designer:
        return None, "Add meg az alkotó nevét (pl. Szabó Levente; több alkotó: vesszővel)."
    try:
        year = int(str(data_.get("ev", "")).strip())
        lat, lon = float(data_.get("lat")), float(data_.get("lon"))
    except (TypeError, ValueError):
        return None, "Az év vagy a helyszín hibás."
    if not 1000 <= year <= 2100:
        return None, "Az év 1000 és 2100 között lehet."
    if not (18.7 <= lon <= 19.5 and 47.2 <= lat <= 47.8):
        return None, "A pont Budapesten kívül van."
    about = str(data_.get("about", "")).strip()
    if about:
        about = free_text(about, 1500, True)
        if about is None:
            return None, "A leírás legfeljebb 1500 karakter lehet, és nem tartalmazhat < > jelet."
    image = str(data_.get("kep_url", "")).strip()
    if image and not url_clean(image, True):
        return None, "A fotó címe egy https:// kezdetű, közvetlen képlink legyen."
    link = str(data_.get("link_url", "")).strip()
    if link and not url_clean(link):
        return None, "A link http:// vagy https:// kezdetű webcím legyen."
    gj = json.loads(MANUAL_BUILDINGS.read_text(encoding="utf-8")) if MANUAL_BUILDINGS.exists() else {"type": "FeatureCollection", "features": []}
    id_ = max([f["properties"]["id"] for f in gj["features"] if f["properties"].get("id", 0) >= ARTWORK_BASE_ID], default=ARTWORK_BASE_ID) + 1
    district_ = None
    try:
        for kn, rings in json.loads(DISTRICTS.read_text(encoding="utf-8")).items():
            if any(_in_ring(lon, lat, g) for g in rings):
                district_ = int(kn)
                break
    except (OSError, ValueError):
        pass
    dx, dy = 1.5 / (111320 * math.cos(math.radians(47.5))), 1.5 / 110574
    ring_ = [[round(lon - dx, 7), round(lat - dy, 7)], [round(lon + dx, 7), round(lat - dy, 7)], [round(lon + dx, 7), round(lat + dy, 7)],
             [round(lon - dx, 7), round(lat + dy, 7)], [round(lon - dx, 7), round(lat - dy, 7)]]
    gj["features"].append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring_]}, "properties": {
        "id": id_, "osm_tipus": "way", "nev": name_, "tipus": "yes", "resz": False, "szintek": None, "magassag": 3.0, "magassag_forras": "kezi",
        "ev": None, "ev_forras": None, "wikidata": None, "commons": None, "kerulet": district_, "pont_alapu": True, "alkotas": True}})
    tmp = MANUAL_BUILDINGS.with_suffix(".tmp")
    tmp.write_text(json.dumps(gj, ensure_ascii=False), encoding="utf-8")
    tmp.replace(MANUAL_BUILDINGS)
    remark = f"Köztéri alkotás (kézzel felvett pont): {name_}"[:200]
    for field, value in (("ev", year), ("tervezo", designer), ("magassag", 3), ("about", about), ("kep_url", image), ("link_url", link)):
        if value not in ("", None):
            add_row(["way", id_, field, value, "kezi", remark, "", ""])
    return {"id": id_, "kulcs": f"w{id_}", "kerulet": district_}, None


def check(data_):
    """Returns the CSV row or an error message."""
    type_ = data_.get("osm_tipus")
    if type_ not in ("way", "relation"):
        return None, "Ismeretlen épülettípus."
    try:
        id_ = int(data_.get("id"))
    except (TypeError, ValueError):
        return None, "Hibás azonosító."
    field = data_.get("mezo")
    if field in NUMBERED and str(data_.get("ertek", "")).strip() == "-":
        value = "-"                  # '-' = remove the number (assemble.py handles it as a deletion of the field)
    elif field in NUMBERED:
        try:
            v = float(str(data_.get("ertek")).replace(",", "."))
        except ValueError:
            return None, f"A(z) {field} értéke nem szám."
        lo, hi = NUMBERED[field]
        if not lo <= v <= hi:
            return None, f"A(z) {field} értéke {lo} és {hi} között lehet."
        value = int(v) if v == int(v) else round(v, 1)
    elif field in SINGLE_LINE or field in LONG_TEXT:
        if str(data_.get("ertek", "")).strip() == "-":
            value = "-"
        else:
            boundary = SINGLE_LINE.get(field) or LONG_TEXT[field]
            value = free_text(data_.get("ertek", ""), boundary, field in LONG_TEXT)
            if value is None:
                return None, f"A(z) {field} értéke üres, legfeljebb {boundary} karakter lehet, és nem tartalmazhat < > jelet."
    elif field == "vedettseg":
        value = str(data_.get("ertek", "")).strip()
        if value != "-" and value not in PROTECTION_CODES:
            return None, "A védettség csak M, MJ, VK, MK vagy MJT lehet (vagy '-' az eltávolításhoz)."
    elif field == "muemlek_torzsszam":
        value = str(data_.get("ertek", "")).strip()
        if value != "-":
            if not re.fullmatch(r"\d{1,6}", value):
                return None, "A műemléki törzsszám 1–6 jegyű szám (vagy '-' az eltávolításhoz)."
            value = int(value)
    elif field == "linkek":
        value = str(data_.get("ertek", "")).replace("\r\n", "\n").replace("\r", "\n").strip()
        if value != "-":
            rows = [x.strip() for x in value.split("\n") if x.strip()]
            done = []
            for row in rows:
                caption, _, url = row.rpartition("|")
                caption, url = caption.strip(), url.strip()
                url = url_clean(url)
                if url is None or len(caption) > 60 or re.search(r"[<>\"\x00-\x1f]", caption):
                    return None, "Linkek: soronként egy webcím (http:// vagy https://, szóköz nélkül), elé tetszés szerint „Felirat | ” (legfeljebb 60 karakter); '-' vagy üres = eltávolítás."
                done.append((caption + " | " if caption else "") + url)
            if not done or len(done) > 8:
                return None, "Linkek: legalább 1, legfeljebb 8 sor."
            value = "\n".join(done)
    elif field == "kepek_linkek":
        value = str(data_.get("ertek", "")).replace("\r\n", "\n").replace("\r", "\n").strip()
        if value != "-":
            done = []
            for row in [x.strip() for x in value.split("\n") if x.strip()]:
                caption, _, url = row.rpartition("|")
                caption, url = caption.strip(), url.strip()
                url = url_clean(url, True)
                if url is None or len(caption) > 80 or re.search(r"[<>\"\x00-\x1f]", caption):
                    return None, "Kép linkek: soronként egy közvetlen képlink (https:// kezdetű, szóköz nélkül), elé tetszés szerint „Forrás / szerző | ” (legfeljebb 80 karakter); '-' vagy üres = eltávolítás."
                done.append((caption + " | " if caption else "") + url)
            if not done or len(done) > 12:
                return None, "Kép linkek: legalább 1, legfeljebb 12 sor."
            value = "\n".join(done)
    elif field == "budapest100_url":
        value = str(data_.get("ertek", "")).strip()
        if value != "-":
            m_ = re.match(r"(?i)^(?:https?://)?(?:www\.)?(budapest100\.hu/[A-Za-z0-9._~%/\-]*)$", value)
            if not m_:
                return None, "A Budapest100-oldal a budapest100.hu teljes címe legyen (pl. https://budapest100.hu/house/…); '-' vagy üres = eltávolítás."
            value = "https://" + m_.group(1)
    elif field == "commons_kep":
        value = str(data_.get("ertek", "")).strip()
        if value.lower() in ("nincs", "nincs kép", "nincs kep"):
            value = "nincs"          # there is no photo on the card at all (this also disables the automatic matching)
        elif value != "-":
            m_ = re.match(r"(?i)^(?:https?://)?(?:[a-z]+\.)?(?:commons\.)?wikimedia\.org/wiki/(?:File|F%C3%A1jl|Fájl):([^?#\s]+)$", value)
            name_ = urllib.parse.unquote(m_.group(1)) if m_ else re.sub(r"(?i)^(?:File|Fájl):", "", value)
            name_ = name_.replace(" ", "_")
            if not re.fullmatch(r"[^/\\<>;|\x00-\x1f]{3,200}\.(?:jpe?g|png|gif|tiff?|webp|svg)", name_, flags=re.I):
                return None, "A Commons-fotó a Commons fájl-oldalának teljes linkje legyen (https://commons.wikimedia.org/wiki/File:…), vagy a fájl neve; '-' vagy üres = a kézi választás eltávolítása."
            value = "https://commons.wikimedia.org/wiki/File:" + urllib.parse.quote(name_, safe="_-.~()',!")
    elif field in ("kep_url", "link_url", "iroda_link"):
        value = str(data_.get("ertek", "")).strip()
        if value != "-":
            value = url_clean(value, field == "kep_url")
            if value is None:
                return None, ("A fotó címe egy https:// kezdetű, közvetlen képlink legyen (legfeljebb 400 karakter)." if field == "kep_url"
                              else "A link http:// vagy https:// kezdetű webcím legyen (legfeljebb 400 karakter); '-' vagy üres = eltávolítás.")
    elif field == "wikipedia":
        if re.match(r"(?i)^\s*(https?://)?(www\.)?budapest100\.hu/", str(data_.get("ertek", ""))):
            return None, "Ez egy Budapest100-link: írd a „Budapest100-oldal” mezőbe, ne a Wikipédia-mezőbe."
        value = wikipedia_articles(data_.get("ertek", ""))
        if value is None:
            return None, "A Wikipedia-oldal legyen hu.wikipedia.org vagy en.wikipedia.org cikk (link, vagy pl. 'hu:Vigadó'); több cikket | jellel válassz el."
    elif field in TEXTUAL:
        value = "-" if str(data_.get("ertek", "")).strip() == "-" else clean_text(data_.get("ertek", ""), 150 if field in ("stilus", "iroda") else 100)    # '-' = remove the field
        if value is None:
            return None, f"A(z) {field} értéke üres, túl hosszú, vagy tiltott karaktert tartalmaz."
    else:
        return None, "Ez a mező nem szerkeszthető."
    remark = clean_text(data_.get("megjegyzes", ""), 200)
    if remark is None:
        return None, "Add meg a forrást (rövid szöveg, pl. 'Időgép, 1944-es lakásív')."
    return [type_, id_, field, value, "kezi", remark, "", ""], None


def zone_text(x, max_length):
    x = " ".join(str(x or "").split())
    if len(x) > max_length or re.search(r"[\x00-\x1f<>]", x):
        return None
    return x


def zones_check(data_):
    """Checks the whole zone FeatureCollection. Returns: (clean data, error)."""
    if not isinstance(data_, dict) or data_.get("type") != "FeatureCollection" or not isinstance(data_.get("features"), list):
        return None, "Hibás zóna-fájl."
    if len(data_["features"]) > 600:
        return None, "Legfeljebb 600 zóna menthető."
    out, ids_ = [], set()
    for f in data_["features"]:
        try:
            g, p = f["geometry"], f["properties"]
            if g["type"] != "Polygon" or len(g["coordinates"]) != 1:
                return None, "Csak egy külső gyűrűs sokszög (Polygon) menthető."
            ring_ = g["coordinates"][0]
            if not 4 <= len(ring_) <= 3000 or ring_[0] != ring_[-1]:
                return None, "A sokszög gyűrűje hibás (3–3000 csúcs, zárt)."
            clean_ring = []
            for lon, lat in ring_:
                lon, lat = float(lon), float(lat)
                if not (18.7 <= lon <= 19.5 and 47.2 <= lat <= 47.8):
                    return None, "A sokszög kilóg Budapestről."
                clean_ring.append([round(lon, 6), round(lat, 6)])
            id_ = zone_text(p.get("id"), 80)
            if not id_ or id_ in ids_:
                return None, "Hiányzó vagy ismétlődő zónaazonosító."
            ids_.add(id_)
            from_, to = int(p.get("ev_tol")), int(p.get("ev_ig"))
            if not (1 <= from_ <= to <= 2100):
                return None, f"A(z) {id_} évei hibásak (ev_tol <= ev_ig, 1–2100)."
            type_ = p.get("tipus") or "egyeb"
            state = p.get("allapot") or "helyismeret"
            origin_ = p.get("eredet") or "kezi"
            if type_ not in ZONE_TYPES or state not in ZONE_STATES or origin_ not in ZONE_ORIGIN:
                return None, f"A(z) {id_} típusa, állapota vagy eredete hibás."
            clean = {"id": id_, "tipus": type_, "allapot": state, "eredet": origin_, "ev_tol": from_, "ev_ig": to,
                      "mero": bool(p.get("mero")), "ig_hatar": bool(p.get("ig_hatar"))}
            if "zona_nev_hozzaad" in p:     # three-state: missing = the zone type decides (housing estate: yes)
                clean["zona_nev_hozzaad"] = bool(p["zona_nev_hozzaad"])
            for field, length in (("nev", 120), ("kerulet", 40), ("forras", 300), ("megjegyzes", 400), ("lista_id", 80), ("tervezo", 200)):
                v = zone_text(p.get(field), length)
                if v is None:
                    return None, f"A(z) {id_} {field} mezője túl hosszú vagy tiltott karaktert tartalmaz."
                clean[field] = v
            bp = str(p.get("budapest100") or "").strip()
            wiki = str(p.get("wikipedia") or "").strip()
            if re.match(r"(?i)^(https?://)?(www\.)?budapest100\.hu/", wiki):      # a Budapest100 link mistakenly written into the Wikipedia field is moved to its own field
                bp, wiki = bp or wiki, ""
            if bp:
                bp = bp.strip().strip("\"'")
                m = re.match(r"(?i)^(?:https?://)?(?:www\.)?(budapest100\.hu/[A-Za-z0-9._~%/\-]*)$", bp)
                if not m:
                    return None, (f"A(z) {id_} ({clean.get('nev') or 'névtelen'}) Budapest100-linkje hibás: „{bp[:80]}”. "
                                  "Írd be a budapest100.hu oldal teljes címét (https://budapest100.hu/...).")
                bp = "https://" + m.group(1)
            clean["budapest100"] = bp
            if wiki and wiki != "-":
                wiki = wikipedia_articles(wiki)
                if wiki is None:
                    return None, (f"A(z) {id_} ({clean.get('nev') or 'névtelen'}) Wikipedia-cikke hibás: „{str(p.get('wikipedia'))[:80]}”. "
                                  "Írj hu.wikipedia.org / en.wikipedia.org linket, vagy 'hu:Cím'-et (vagy csak a címet); legfeljebb 3 cikk, | jellel elválasztva.")
            else:
                wiki = ""
            clean["wikipedia"] = wiki
            out.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [clean_ring]}, "properties": clean})
        except (KeyError, TypeError, ValueError):
            return None, "Hibás zóna-bejegyzés."
    return {"type": "FeatureCollection", "features": out}, None


def save_zones(data_):
    ZONES.parent.mkdir(exist_ok=True)
    if ZONES.exists():
        try:
            ZONES.replace(ZONES.with_suffix(".bak.geojson"))
        except OSError:
            pass
    time_ = ZONES.with_suffix(".tmp")
    time_.write_text(json.dumps(data_, ensure_ascii=False), encoding="utf-8")
    time_.replace(ZONES)


def add_row(row):
    MANUAL.parent.mkdir(exist_ok=True)
    new = not MANUAL.exists() or MANUAL.stat().st_size == 0
    if not new:
        with open(MANUAL, "rb") as f:
            f.seek(-1, 2)
            end_newline = f.read(1) in (b"\n", b"\r")
    else:
        end_newline = True
    with open(MANUAL, "a", encoding="utf-8-sig" if new else "utf-8", newline="") as f:
        if not end_newline:
            f.write("\r\n")
        w = csv.writer(f, delimiter=";")
        if new:
            w.writerow(HEADER)
        w.writerow(row)


OENY_EXCLUDED = Path("forras/oeny_kizart.csv")


VALUE_TABLE = Path("forras/ertekleltar_kezi_parositas.csv")
VALUE_COLUMNS = ["kerulet", "cim", "hrsz", "epites_ideje", "tervezo", "allapot", "javasolt_osm", "jeloltek", "osm_azonosito", "megjegyzes"]


def value_read():
    if not VALUE_TABLE.exists():
        return []
    with open(VALUE_TABLE, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def value_decision(data_):
    """A decision for one row of the heritage-inventory manual pairing table: osm_azonosito (way/relation id) or a 'not pairable' remark.
    The row is identified by the serial number + the (district, address, lot number) key; the file is rewritten whole, atomically (BOM, CRLF)."""
    rows = value_read()
    building_key = (str(data_.get("kerulet", "")), str(data_.get("cim", "")).strip(), str(data_.get("hrsz", "")).strip())
    try:
        i = int(data_.get("index"))
    except (TypeError, ValueError):
        i = -1
    matches = lambda r: (r.get("kerulet", ""), r.get("cim", "").strip(), r.get("hrsz", "").strip()) == building_key
    if not (0 <= i < len(rows) and matches(rows[i])):
        found = [j for j, r in enumerate(rows) if matches(r)]
        if len(found) != 1:
            return None, "A sor nem található (a tábla közben megváltozott?). Töltsd újra a listát."
        i = found[0]
    osm = re.sub(r"\s+", " ", str(data_.get("osm_azonosito") or "")).strip()
    if osm and not re.fullmatch(r"(way|relation) \d{3,}", osm):
        return None, "Hibás OSM-azonosító (way 123456 vagy relation 123 alakban)."
    remark = re.sub(r"\s+", " ", str(data_.get("megjegyzes") or "")).strip()[:200]
    rows[i]["osm_azonosito"] = osm
    rows[i]["megjegyzes"] = remark
    try:
        tmp = VALUE_TABLE.with_suffix(".csv.tmp")
        with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=VALUE_COLUMNS, delimiter=";", extrasaction="ignore", lineterminator="\r\n")
            w.writeheader()
            w.writerows(rows)
        try:
            tmp.replace(VALUE_TABLE)
        except OSError:                   # on Windows the replacement may fail (something keeps the target file open): write directly
            with open(VALUE_TABLE, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=VALUE_COLUMNS, delimiter=";", extrasaction="ignore", lineterminator="\r\n")
                w.writeheader()
                w.writerows(rows)
            try:
                tmp.unlink()
            except OSError:
                pass
    except OSError as error_:
        return None, f"A forras/ertekleltar_kezi_parositas.csv nem írható ({error_.__class__.__name__}): valószínűleg meg van nyitva Excelben vagy más programban. Zárd be, és próbáld újra."
    return i, None


# ---- manual decision tables (Budapest100 corner houses, Wikipedia conflicts) and the rejected architect items ----
TABLES = {
    "bp100": {"ut": Path("forras/bp100_kezi_parositas.csv"),
              "oszlopok": ["cim", "ev", "url", "allapot", "javasolt_osm", "mod", "jeloltek", "osm_azonosito", "megjegyzes"],
              "kulcs": ("cim",)},
    "telek2": {"ut": Path("forras/ertekleltar_telek2_parositas.csv"),
               "oszlopok": ["lista", "kerulet", "cim", "hrsz", "n", "mai_cim", "adat", "allapot", "javasolt_osm", "jeloltek", "osm_azonosito", "megjegyzes"],
               "kulcs": ("lista", "kerulet", "cim", "hrsz", "n")},
    "konfliktus": {"ut": Path("forras/wikipedia_konfliktus_dontes.csv"),
                   "oszlopok": ["id", "epitesz", "tetel", "mod", "osm", "db_nev", "db_tervezo", "db_ev", "wiki_ev", "ok", "dontes", "megjegyzes"],
                   "kulcs": ("id",)},
}
ARCHITECT_PAIRED = Path("forras/epitesz_parositott.csv")    # epitesz;tetel;osm - pairings already done in the pairing list (they disappear from the list in every browser)
ARCHITECT_REJECTED = Path("forras/epitesz_elvetett.csv")      # epitesz;tetel - items removed from the pairing list (demolished, plan only)
OSM_ID = re.compile(r"(?:way|relation) \d{3,}(?: \| (?:way|relation) \d{3,})*")


def table_read(name_):
    t = TABLES.get(name_)
    if not t or not t["ut"].exists():
        return []
    with open(t["ut"], encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def csv_atomic_write(path_, columns, rows):
    """BOM + CRLF, via a temporary file; on Windows the replacement may fail: then a direct write. Raises OSError if the file cannot be written."""
    def ir(target):
        with open(target, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=columns, delimiter=";", extrasaction="ignore", lineterminator="\r\n")
            w.writeheader()
            w.writerows(rows)
    tmp = path_.with_suffix(path_.suffix + ".tmp")
    ir(tmp)
    try:
        tmp.replace(path_)
    except OSError:
        ir(path_)
        try:
            tmp.unlink()
        except OSError:
            pass


def several_designer(old, new):
    """The existing designer(s) + the new one: 'A; B'; parentheses with years (Hild József (1789-1867)) are removed, a duplicate is not written."""
    def ground(x):
        return re.sub(r"[^a-z]", "", unicodedata.normalize("NFD", str(x).lower()).encode("ascii", "ignore").decode())
    names = [re.sub(r"\s*\(\d{4}[^)]*\)", "", r).strip() for r in re.split(r"[;,]", old or "") if r.strip()]
    if ground(new) not in [ground(n) for n in names]:
        names.append(new.strip())
    return "; ".join(names)


def table_decision(data_):
    """A decision for one row: bp100: osm_azonosito / megjegyzes; conflict: dontes (hozzaad / felulir / elvet) + megjegyzes.
    The conflict's 'hozzaad' (add) and 'felulir' (overwrite) decision also writes a tervezo row to forras/kezi_javitasok.csv for every building of the item."""
    name_ = data_.get("tabla")
    t = TABLES.get(name_)
    if not t:
        return None, "Ismeretlen tábla."
    rows = table_read(name_)
    building_key = {k: str(data_.get(k, "")).strip() for k in t["kulcs"]}
    matches = lambda r: all(str(r.get(k, "")).strip() == v for k, v in building_key.items())
    try:
        i = int(data_.get("index"))
    except (TypeError, ValueError):
        i = -1
    if not (0 <= i < len(rows) and matches(rows[i])):
        found = [j for j, r in enumerate(rows) if matches(r)]
        if len(found) != 1:
            return None, "A sor nem található (a tábla közben megváltozott?). Töltsd újra a listát."
        i = found[0]
    row = rows[i]
    remark = re.sub(r"\s+", " ", str(data_.get("megjegyzes") or "")).strip()[:200]
    if name_ in ("bp100", "telek2"):
        osm = re.sub(r"\s*[|;,]\s*", " | ", re.sub(r"\s+", " ", str(data_.get("osm_azonosito") or "")).strip())
        if osm and not OSM_ID.fullmatch(osm):
            return None, "Hibás OSM-azonosító (way 123456 vagy relation 123 alakban, több esetén | jellel)."
        row["osm_azonosito"], row["megjegyzes"] = osm, remark
    else:
        decision = str(data_.get("dontes") or "").strip()
        if decision not in ("hozzaad", "felulir", "elvet", ""):
            return None, "Ismeretlen döntés."
        if decision in ("hozzaad", "felulir"):
            architect = re.sub(r"\s+", " ", row.get("epitesz", "")).strip()
            value = architect if decision == "felulir" else several_designer(row.get("db_tervezo", ""), architect)
            if not architect or len(value) > 200 or ";" in value.replace("; ", ""):
                return None, "Hibás tervező-érték."
            ids_ = [x.split() for x in str(row.get("osm", "")).split("|") if x.strip()][:8]
            if not ids_ or any(len(x) != 2 or x[0] not in ("way", "relation") or not x[1].isdigit() for x in ids_):
                return None, "A tételhez nincs érvényes OSM-azonosító."
            if row.get("dontes") in ("hozzaad", "felulir"):
                return None, "Erre a tételre már született döntés (a forras/kezi_javitasok.csv-ben a sor megvan). Módosítsd ott."
            for kind, id_ in ids_:
                add_row([kind, int(id_), "tervezo", value, "kezi", "Wikipédia művek-lista (konfliktus-döntés): " + row.get("tetel", "")[:100], "", ""])
        row["dontes"], row["megjegyzes"] = decision, remark
    try:
        csv_atomic_write(t["ut"], t["oszlopok"], rows)
    except OSError as error_:
        return None, f"A {t['ut']} nem írható ({error_.__class__.__name__}): valószínűleg meg van nyitva Excelben. Zárd be, és próbáld újra."
    return i, None


def rejected_read():
    """The rejected AND the already paired items (both disappear from the pairing list)."""
    out = []
    for path_ in (ARCHITECT_REJECTED, ARCHITECT_PAIRED):
        if path_.exists():
            with open(path_, encoding="utf-8-sig", newline="") as f:
                out += [{"a": r["epitesz"], "t": r["tetel"]} for r in csv.DictReader(f, delimiter=";")]
    return out


def architect_paired_pin(architect, item, osm):
    a = re.sub(r"\s+", " ", str(architect or "")).strip()[:120]
    tt = re.sub(r"\s+", " ", str(item or "")).strip()[:400]
    if not a or not tt:
        return
    rows = []
    if ARCHITECT_PAIRED.exists():
        with open(ARCHITECT_PAIRED, encoding="utf-8-sig", newline="") as f:
            rows = [{"epitesz": r["epitesz"], "tetel": r["tetel"], "osm": r.get("osm", "")} for r in csv.DictReader(f, delimiter=";")]
    for x in rows:
        if x["epitesz"] == a and x["tetel"] == tt:
            x["osm"] = osm
            break
    else:
        rows.append({"epitesz": a, "tetel": tt, "osm": osm})
    try:
        csv_atomic_write(ARCHITECT_PAIRED, ["epitesz", "tetel", "osm"], rows)
    except OSError:
        pass       # the pairing itself (kezi_javitasok.csv) already exists; hiding it from the list is only for convenience


def architect_rejection(data_):
    a = re.sub(r"\s+", " ", str(data_.get("epitesz") or "")).strip()[:120]
    tt = re.sub(r"\s+", " ", str(data_.get("tetel") or "")).strip()[:400]
    if not a or not tt:
        return None, "Hiányzó építész vagy tétel."
    rows = [{"epitesz": x["a"], "tetel": x["t"]} for x in rejected_read()]
    if not any(x["epitesz"] == a and x["tetel"] == tt for x in rows):
        rows.append({"epitesz": a, "tetel": tt})
    try:
        csv_atomic_write(ARCHITECT_REJECTED, ["epitesz", "tetel"], rows)
    except OSError as error_:
        return None, f"A {ARCHITECT_REJECTED} nem írható ({error_.__class__.__name__}): zárd be, ha meg van nyitva."
    return len(rows), None


def oeny_removal(data_):
    """Removing the E-Örökség (OENY) data from a building: one row in forras/oeny_kizart.csv (assemble.py drops
    all oeny/oeny_koord facts of the building). Returns: (status, error); the status is "uj" (new) or "mar_szerepelt" (already listed)."""
    type_ = data_.get("osm_tipus")
    if type_ not in ("way", "relation"):
        return None, "Ismeretlen épülettípus."
    try:
        id_ = int(data_.get("id"))
    except (TypeError, ValueError):
        return None, "Hibás azonosító."
    remark = "kézzel kivéve az E-Örökség (OENY) adatokból"
    serial = str(data_.get("torzsszam") or "").strip()
    if re.fullmatch(r"\d{1,6}", serial):
        remark += f" (törzsszám {serial})"
    one = bool(data_.get("egy"))          # take off only this one data sheet (register number), leave the others
    if one and not re.fullmatch(r"\d{1,6}", serial):
        return None, "Az egyedi levételhez törzsszám kell."
    building_key = f"{type_};{id_};"
    new = not OENY_EXCLUDED.exists() or OENY_EXCLUDED.stat().st_size == 0
    if not new:
        text_ = OENY_EXCLUDED.read_text(encoding="utf-8-sig")
        rows = text_.splitlines()
        # a full exclusion (no register-number column) already exists -> every data sheet is removed; an individual row for the same register number
        if any(row.startswith(building_key) and (row.count(";") < 3 or not row.split(";")[3].strip()) for row in rows if not row.startswith("osm_tipus")):
            return "mar_szerepelt", None
        if one and any(row.startswith(building_key) and row.rstrip().endswith(";" + serial) for row in rows):
            return "mar_szerepelt", None
        if not one and any(row.startswith(building_key) for row in rows):
            return "mar_szerepelt", None
        end_newline = text_.endswith(("\n", "\r"))
        # extending the header with the torzsszam column (the old rows may stay with 3 fields)
        if one and "torzsszam" not in rows[0]:
            text_ = text_.replace(rows[0], rows[0].rstrip() + ";torzsszam", 1)
            OENY_EXCLUDED.write_text(text_, encoding="utf-8-sig", newline="")
    else:
        end_newline = True
    OENY_EXCLUDED.parent.mkdir(exist_ok=True)
    with open(OENY_EXCLUDED, "a", encoding="utf-8-sig" if new else "utf-8", newline="") as f:
        if new:
            f.write("osm_tipus;id;megjegyzes;torzsszam\r\n")
        elif not end_newline:
            f.write("\r\n")
        f.write(f"{type_};{id_};{remark}" + (f";{serial}" if one else "") + "\r\n")
    return "uj", None


OENY_MANUAL = Path("forras/oeny_kezi_parositas.csv")
# The register numbers of suspicious automatic OENY pairings (the OSM address's street does not match the OENY address), and the address-based suggestion
OENY_SUSPICIOUS = ["15003", "15114", "15115", "15116", "15118", "15134", "15229", "15643", "15809", "15984", "16061",
               "16068", "16137", "16164", "16165", "16182", "16189", "16250", "16283"]
OENY_SUGGESTION = {"15003": "way 323479222", "15114": "way 1308611895", "15115": "relation 3361170", "15116": "way 250065364",
                 "15643": "way 1086635486", "16068": "relation 19132", "16182": "way 249857122"}
OENY_MANUAL_COLUMN = ["torzsszam", "megnevezes", "cim", "miert_nem_parosult", "kiolvasott_tervezo", "kiolvasott_ev",
                    "lehetseges_epuletek_a_tobbi_cim_alapjan", "oeny_oldal", "osm_kereses", "arcgis_lat", "arcgis_lon",
                    "terbeli_biztonsag", "terbeli_javaslat", "osm_azonosito", "megjegyzes"]


def oeny_suspicious_list():
    with open(OENY_MANUAL, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    out = []
    for r in rows:
        t = r.get("torzsszam", "")
        if t not in OENY_SUSPICIOUS or not (r.get("osm_azonosito") or "").strip():
            continue
        remark = r.get("megjegyzes", "")
        if not (remark.startswith("automatikus") or remark.startswith("kézzel")):
            continue
        state = "ok" if remark.startswith("kézzel ellenőrizve") else "atrakva" if remark.startswith("kézzel átrakva") else "levetel" if remark.startswith("kézzel levéve") else ""
        fix = OENY_SUGGESTION.get(t, "")
        out.append({"t": t, "nev": r.get("megnevezes", ""), "cim": r.get("cim", ""), "oeny": r.get("oeny_oldal", ""),
                   "akt": [x.strip() for x in re.split(r"[|;,]+", r["osm_azonosito"]) if x.strip()],
                   "javaslat": fix if fix and fix != r["osm_azonosito"].strip() else "", "allapot": state})
    out.sort(key=lambda x: (OENY_SUSPICIOUS.index(x["t"]), x["cim"]))
    return out


def oeny_reassign(data_):
    """A decision on one suspicious OENY pairing: 'ok' (stays), 'levetel' (removal mark; the removal is done by /api/oeny_levetel) or a new OSM id."""
    t = str(data_.get("t") or "").strip()
    address = str(data_.get("cim") or "")
    new = str(data_.get("uj") or "").strip()
    if t not in OENY_SUSPICIOUS:
        return None, "Ismeretlen törzsszám."
    if new not in ("ok", "levetel") and not re.fullmatch(r"(way|relation) \d{1,12}", new):
        return None, "Hibás új azonosító."
    with open(OENY_MANUAL, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    found = False
    for r in rows:
        if r.get("torzsszam") == t and r.get("cim") == address and (r.get("osm_azonosito") or "").strip():
            if new == "ok":
                r["megjegyzes"] = "kézzel ellenőrizve (marad)"
            elif new == "levetel":
                r["megjegyzes"] = "kézzel levéve az OENY-adatokból"
            else:
                r["osm_azonosito"] = new
                r["megjegyzes"] = "kézzel átrakva (gyanús párosítás ellenőrzése)"
            found = True
            break
    if not found:
        return None, "A sor nem található."
    try:
        csv_atomic_write(OENY_MANUAL, OENY_MANUAL_COLUMN, rows)
    except OSError as error_:
        return None, f"A {OENY_MANUAL} nem írható ({error_.__class__.__name__}): zárd be, ha meg van nyitva."
    return True, None


LEGEND_MANUAL = Path("forras/legenda_kezi_parositas.csv")
LEGEND_IMAGES = Path("forras/legenda_kepek.csv")


def legend_list():
    with open(LEGEND_MANUAL, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    images = {}
    if LEGEND_IMAGES.exists():
        with open(LEGEND_IMAGES, encoding="utf-8-sig", newline="") as f:
            images = {(k.get("url") or "").strip(): (k.get("kep_url") or "").strip() for k in csv.DictReader(f, delimiter=";")}
    out = []
    for r in rows:
        lnk = (r.get("legenda_link") or "").strip()
        out.append({"id": r.get("legenda_id", ""), "nev": r.get("nev", ""), "ev": r.get("ev", ""), "tervezo": r.get("tervezo", ""),
                   "link": lnk, "uj": r.get("uj_epulet", ""), "allapot": r.get("allapot", ""), "epforum": r.get("epforum_egyezes", ""),
                   "javaslat": r.get("osm_javaslat", ""), "keres": r.get("osm_kereses", ""), "megj": r.get("megjegyzes", ""),
                   "osm": [x.strip() for x in re.split(r"[|;,]+", r.get("osm_azonosito") or "") if x.strip()],
                   "kep": (r.get("kep_url") or images.get(lnk, "")).strip()})
    return out


def legend_decision(data_):
    """Pairing one Legenda row: hozzaad (OSM building), torol (all pairings), nincs (not pairable), nyitott (clear the mark)."""
    id_ = str(data_.get("id") or "").strip()
    operation = data_.get("muvelet")
    if operation not in ("hozzaad", "torol", "nincs", "nyitott"):
        return None, "Ismeretlen művelet."
    with open(LEGEND_MANUAL, encoding="utf-8-sig", newline="") as f:
        read_ = csv.DictReader(f, delimiter=";")
        columns = list(read_.fieldnames or [])
        rows = list(read_)
    target = next((r for r in rows if r.get("legenda_id") == id_), None)
    if target is None:
        return None, "A sor nem található."
    current = [x.strip() for x in re.split(r"[|;,]+", target.get("osm_azonosito") or "") if x.strip()]
    if operation == "hozzaad":
        type_ = data_.get("osm_tipus")
        try:
            oid = int(data_.get("osm_id"))
        except (TypeError, ValueError):
            return None, "Hibás OSM-azonosító."
        if type_ not in ("way", "relation"):
            return None, "Ismeretlen épülettípus."
        new = f"{type_} {oid}"
        if new not in current:
            current.append(new)
        target["osm_azonosito"] = " | ".join(current)
        if (target.get("megjegyzes") or "").startswith("kézzel: nem párosítható"):
            target["megjegyzes"] = ""
    elif operation == "torol":
        target["osm_azonosito"] = ""
    elif operation == "nincs":
        target["osm_azonosito"] = ""
        target["megjegyzes"] = "kézzel: nem párosítható"
    else:
        if (target.get("megjegyzes") or "").startswith("kézzel: nem párosítható"):
            target["megjegyzes"] = ""
    try:
        csv_atomic_write(LEGEND_MANUAL, columns, rows)
    except OSError as error_:
        return None, f"A {LEGEND_MANUAL} nem írható ({error_.__class__.__name__}): zárd be, ha meg van nyitva."
    return target["osm_azonosito"], None


MANUAL_ERA = Path("forras/kezi_korszak.csv")


def era_save(data_):
    """Manual era assignment for one building (0-6, in the order of the map's eras; empty = delete): forras/kezi_korszak.csv,
    then regenerating data/varos/kezi_kozelito.csv (see facts_manual_era.py)."""
    type_ = data_.get("osm_tipus")
    try:
        id_ = int(data_.get("id"))
    except (TypeError, ValueError):
        return "Hibás épületazonosító."
    if type_ not in ("way", "relation"):
        return "Ismeretlen épülettípus."
    era = str(data_.get("korszak", "")).strip()
    if era != "" and not (era.isdigit() and 0 <= int(era) <= 6):
        return "Hibás korszak."
    remark = re.sub(r"\s+", " ", str(data_.get("megjegyzes") or "")).strip()[:200].replace(";", ",")
    if era != "" and not remark:
        return "Add meg a forrást / indoklást."
    rows = []
    if MANUAL_ERA.exists():
        with open(MANUAL_ERA, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f, delimiter=";"))
    rows = [r for r in rows if not (r.get("osm_tipus") == type_ and str(r.get("id")) == str(id_))]
    if era != "":
        rows.append({"osm_tipus": type_, "id": str(id_), "korszak": era, "megjegyzes": remark})
    try:
        csv_atomic_write(MANUAL_ERA, ["osm_tipus", "id", "korszak", "megjegyzes"], rows)
        import facts_manual_era
        facts_manual_era.generation()
    except OSError as error_:
        return f"A {MANUAL_ERA} nem írható ({error_.__class__.__name__}): zárd be, ha meg van nyitva."
    return None


ARCHITECT_OFFICES = Path("forras/epitesz_irodak.csv")
ARCHITECT_TYPES = ("iroda", "intezmeny", "tobb_szemely", "nem_nev", "szemely")
ARCHITECT_OFFICES_COLUMN = ["kulcs", "nev", "tipus", "forras", "megjegyzes"]


def architect_types_read():
    """Classification of the names occurring in the Designer field (forras/epitesz_irodak.csv): iroda (office) / intezmeny (institution) / tobb_szemely (several persons) / nem_nev (not a name); 'szemely' = marked by hand as a person."""
    if not ARCHITECT_OFFICES.exists():
        return []
    with open(ARCHITECT_OFFICES, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def architect_type_save(data_):
    """Manual entry of a name's classification; it overwrites the automatic row (forras=kezi)."""
    building_key = re.sub(r"\s+", " ", str(data_.get("kulcs") or "")).strip()
    name_ = re.sub(r"\s+", " ", str(data_.get("nev") or "")).strip().replace(";", ",")
    type_ = str(data_.get("tipus") or "")
    if not building_key or len(building_key) > 150 or not name_ or len(name_) > 150:
        return "Hibás név."
    if type_ not in ARCHITECT_TYPES:
        return "Ismeretlen típus."
    rows = architect_types_read()
    old = next((r for r in rows if r.get("kulcs") == building_key), None)
    rows = [r for r in rows if r.get("kulcs") != building_key]
    rows.append({"kulcs": building_key, "nev": name_, "tipus": type_, "forras": "kezi", "megjegyzes": (old or {}).get("megjegyzes", "")})
    rows.sort(key=lambda r: (r.get("nev") or "").lower())
    try:
        csv_atomic_write(ARCHITECT_OFFICES, ARCHITECT_OFFICES_COLUMN, rows)
    except OSError as error_:
        return f"A {ARCHITECT_OFFICES} nem írható ({error_.__class__.__name__}): zárd be, ha meg van nyitva."
    return None


def oeny_list(type_, id_):
    """The OENY data sheets tied to the building (grouped by register number), so that they can be removed one by one."""
    grp_ = {}
    for fn in ("oeny", "oeny_koord", "oeny_kezi"):
        path_ = Path("data/tenyek") / f"{fn}.csv"
        if not path_.exists():
            continue
        with open(path_, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                if r.get("osm_tipus") != type_ or r.get("id") != str(id_):
                    continue
                m = re.search(r"törzsszám (\d+)", r.get("megjegyzes") or "")
                serial_no = m.group(1) if m else (str(r.get("ertek")).strip() if r.get("mezo") == "muemlek_torzsszam" else "")
                if not serial_no:
                    continue
                c = grp_.setdefault(serial_no, {"torzsszam": serial_no, "adatlap": set(), "ev": set(), "tervezo": set()})
                if r["mezo"] == "oeny_azonosito":
                    c["adatlap"].add(str(r["ertek"]))
                elif r["mezo"] in ("ev", "tervezo"):
                    c[r["mezo"]].add(str(r["ertek"]))
    out = []
    for c in sorted(grp_.values(), key=lambda c: int(c["torzsszam"])):
        out.append({k: (sorted(v) if isinstance(v, set) else v) for k, v in c.items()})
    return out


def fortepan_data(url):
    """From a Fortepan image link (...fortepan_<id>...) reads the year, the author and the donor: it queries fortepan.hu's own search service (the same one the site uses)."""
    m = re.search(r"fortepan_(\d+)", url or "")
    if not m or not re.match(r"^https://(?:[a-z0-9-]+\.)?fortepan\.(?:hu|download)/", url):
        return {"ok": False, "hiba": "Csak Fortepan képlinkből olvasható ki."}
    try:
        serial = json.dumps({"query": {"term": {"mid": int(m.group(1))}}, "size": 1}).encode()
        request_ = urllib.request.Request("https://fortepan.hu/api/elastic/prod/media/_search", data=serial,
                                       headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (budapest-by-building szerkeszto)"})
        with urllib.request.urlopen(request_, timeout=12) as r:
            hit = json.loads(r.read(2_000_000).decode("utf-8", "replace"))["hits"]["hits"]
    except Exception as exception:
        return {"ok": False, "hiba": f"A fortepan.hu nem érhető el ({exception.__class__.__name__}) – írd be kézzel."}
    if not hit:
        return {"ok": False, "hiba": "Ezt a fotót nem találtam a Fortepanon."}
    f = hit[0].get("_source", {})
    one = lambda k: str((f.get(k) or [""])[0]).strip()
    year, author, donor = one("year"), one("szerzo_name"), one("adomanyozo_name")
    if not (year or author or donor):
        return {"ok": False, "hiba": "A fotónál nincs kiolvasható adat – írd be kézzel."}
    return {"ok": True, "ev": year, "szerzo": author, "adomanyozo": donor, "leiras": one("description")}


WRITE_CLOSE = threading.Lock()    # only one save at a time: the endpoints that read, modify and write back the file lost each other's changes on parallel requests


class Handler(SimpleHTTPRequestHandler):
    timeout = 30                # if the client sends less data than it announced, the thread must not wait forever
    def _json(self, code_, data_):
        serial = json.dumps(data_, ensure_ascii=False).encode("utf-8")
        self.send_response(code_)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(serial)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(serial)

    def end_headers(self):
        if self.path.split("?")[0].endswith((".geojson", ".json", ".html", ".js", ".css", ".bin", ".png")):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _local_host(self):
        """Only requests meant for the local machine are served. Without checking the 'Host' header a malicious web page
        (DNS rebinding: its own domain points to 127.0.0.1) could read every file of the project (.git, forras/, data/) through your browser."""
        port = self.server.server_address[1]
        return (self.headers.get("Host") or "").lower() in {f"localhost:{port}", f"127.0.0.1:{port}", "localhost", "127.0.0.1"}

    def do_HEAD(self):
        if not self._local_host():
            return self._json(403, {"ok": False, "hiba": "Csak helyi kérés engedélyezett."})
        return super().do_HEAD()

    def do_GET(self):
        if not self._local_host():
            return self._json(403, {"ok": False, "hiba": "Csak helyi kérés engedélyezett."})
        if self.path.startswith("/api/kep_adat?"):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            return self._json(200, fortepan_data((q.get("url") or [""])[0]))
        if self.path == "/api/ping":
            return self._json(200, {"szerkeszto": True})
        if self.path.startswith("/api/oeny_lista"):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            try:
                return self._json(200, {"ok": True, "adatlapok": oeny_list((q.get("tipus") or ["way"])[0], int((q.get("id") or ["0"])[0]))})
            except Exception as exception:
                return self._json(500, {"ok": False, "hiba": f"{exception.__class__.__name__}: {exception}"})
        if self.path == "/api/oeny_gyanus":
            try:
                return self._json(200, {"ok": True, "tetelek": oeny_suspicious_list()})
            except Exception as exception:
                return self._json(500, {"ok": False, "hiba": f"{exception.__class__.__name__}: {exception}"})
        if self.path == "/api/epitesz_tipusok":
            try:
                return self._json(200, {"ok": True, "sorok": architect_types_read()})
            except Exception as exception:
                return self._json(500, {"ok": False, "hiba": f"{exception.__class__.__name__}: {exception}"})
        if self.path == "/api/legenda_lista":
            try:
                return self._json(200, {"ok": True, "sorok": legend_list()})
            except Exception as exception:
                return self._json(500, {"ok": False, "hiba": f"{exception.__class__.__name__}: {exception}"})
        if self.path == "/api/ertekleltar_lista":
            try:
                return self._json(200, {"ok": True, "sorok": value_read()})
            except Exception as exception:
                return self._json(500, {"ok": False, "hiba": f"{exception.__class__.__name__}: {exception}"})
        if self.path.startswith("/api/tabla?"):
            name_ = self.path.split("nev=", 1)[-1].split("&", 1)[0]
            try:
                return self._json(200, {"ok": True, "sorok": table_read(name_)})
            except Exception as exception:
                return self._json(500, {"ok": False, "hiba": f"{exception.__class__.__name__}: {exception}"})
        if self.path == "/api/epitesz_elvetett":
            try:
                return self._json(200, {"ok": True, "tetelek": rejected_read()})
            except Exception as exception:
                return self._json(500, {"ok": False, "hiba": f"{exception.__class__.__name__}: {exception}"})
        return super().do_GET()

    def _allowed(self):
        origin = self.headers.get("Origin")
        return self.headers.get("X-Szerkeszto") == "1" and (origin is None or origin in ALLOWED_ORIGIN)

    def do_POST(self):
        if not self._local_host() or not self._allowed():
            return self._json(403, {"ok": False, "hiba": "Nem engedélyezett kérés."})
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0:          # with a negative length the read would wait until the connection ends (the thread would hang)
            return self._json(400, {"ok": False, "hiba": "Hibás kérés."})
        if length > (MAX_ZONE_SEARCH if self.path == "/api/zonak" else 20_000):
            return self._json(413, {"ok": False, "hiba": "Túl nagy kérés."})
        try:
            data_ = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, RecursionError):
            return self._json(400, {"ok": False, "hiba": "Hibás kérés."})
        if not isinstance(data_, dict):          # e.g. '[]': previously the server dropped the connection without a response
            return self._json(400, {"ok": False, "hiba": "Hibás kérés."})
        if self.path == "/api/ujraepit":         # a long run: it does not hold up the saves
            return self._post(data_)
        with WRITE_CLOSE:
            return self._post(data_)

    def _post(self, data_):
        if self.path == "/api/zonak":
            clean, error_ = zones_check(data_)
            if error_:
                return self._json(400, {"ok": False, "hiba": error_})
            save_zones(clean)
            return self._json(200, {"ok": True, "db": len(clean["features"])})
        if self.path == "/api/zona_elvetett":
            count_, error_ = save_rejected(data_)
            if error_:
                return self._json(400, {"ok": False, "hiba": error_})
            return self._json(200, {"ok": True, "db": count_})
        if self.path == "/api/uj_alkotas":
            try:
                v, error_ = artwork_import(data_ if isinstance(data_, dict) else {})
            except Exception as exception:
                return self._json(500, {"ok": False, "hiba": f"Szerverhiba: {exception}"})
            if error_:
                return self._json(400, {"ok": False, "hiba": error_})
            return self._json(200, {"ok": True, **v})
        if self.path == "/api/korszak":
            error_ = era_save(data_ if isinstance(data_, dict) else {})
            if error_:
                return self._json(400, {"ok": False, "hiba": error_})
            return self._json(200, {"ok": True})
        if self.path == "/api/javitas":
            row, error_ = check(data_)
            if error_:
                return self._json(400, {"ok": False, "hiba": error_})
            add_row(row)
            return self._json(200, {"ok": True})
        if self.path == "/api/ertekleltar_dontes":
            try:
                i, error_ = value_decision(data_ if isinstance(data_, dict) else {})
            except Exception as exception:          # the connection must not break: the error should reach the interface as a message
                i, error_ = None, f"Szerverhiba: {exception.__class__.__name__}: {exception}"
                print(error_)
            if error_:
                return self._json(400, {"ok": False, "hiba": error_})
            return self._json(200, {"ok": True, "index": i})
        if self.path in ("/api/tabla_dontes", "/api/epitesz_elvetes"):
            try:
                if self.path == "/api/tabla_dontes":
                    i, error_ = table_decision(data_ if isinstance(data_, dict) else {})
                else:
                    i, error_ = architect_rejection(data_ if isinstance(data_, dict) else {})
            except Exception as exception:
                i, error_ = None, f"Szerverhiba: {exception.__class__.__name__}: {exception}"
                print(error_)
            if error_:
                return self._json(400, {"ok": False, "hiba": error_})
            return self._json(200, {"ok": True, "index": i})
        if self.path == "/api/epitesz_parositas":
            a = data_ if isinstance(data_, dict) else {}
            type_ = a.get("osm_tipus")
            value = re.sub(r"\s+", " ", str(a.get("ertek") or "")).strip()
            item = re.sub(r"\s+", " ", str(a.get("tetel") or "")).strip()[:120]
            try:
                id_ = int(a.get("id"))
            except (TypeError, ValueError):
                id_ = None
            if type_ not in ("way", "relation") or id_ is None or not value or len(value) > 200 or ";" in value.replace("; ", ""):
                return self._json(400, {"ok": False, "hiba": "Hibás párosítási adat."})
            add_row([type_, id_, "tervezo", value, "kezi", "Wikipédia művek-lista (kézi párosítás): " + item, "", ""])
            architect_paired_pin(a.get("epitesz"), a.get("tetel_teljes"), f"{type_} {id_}")
            return self._json(200, {"ok": True})
        if self.path == "/api/epitesz_tipus":
            error_ = architect_type_save(data_ if isinstance(data_, dict) else {})
            if error_:
                return self._json(400, {"ok": False, "hiba": error_})
            return self._json(200, {"ok": True})
        if self.path == "/api/legenda_dontes":
            osm, error_ = legend_decision(data_ if isinstance(data_, dict) else {})
            if error_:
                return self._json(400, {"ok": False, "hiba": error_})
            return self._json(200, {"ok": True, "osm": osm})
        if self.path == "/api/oeny_atrak":
            ok, error_ = oeny_reassign(data_ if isinstance(data_, dict) else {})
            if error_:
                return self._json(400, {"ok": False, "hiba": error_})
            return self._json(200, {"ok": True})
        if self.path == "/api/oeny_levetel":
            state, error_ = oeny_removal(data_ if isinstance(data_, dict) else {})
            if error_:
                return self._json(400, {"ok": False, "hiba": error_})
            return self._json(200, {"ok": True, "allapot": state})
        if self.path == "/api/ujraepit":
            city = ["varos"] if isinstance(data_, dict) and data_.get("varos") else []   # from the 3D (whole city) view
            try:
                result_ = subprocess.run([sys.executable, "assemble.py", *city], capture_output=True,
                                          text=True, encoding="utf-8", errors="replace", timeout=1800)
            except subprocess.TimeoutExpired:
                return self._json(500, {"ok": False, "hiba": "Az újraépítés túl sokáig tartott."})
            if result_.returncode != 0:
                return self._json(500, {"ok": False, "hiba": (result_.stderr or "")[-400:]})
            # the 3D view's data is rebuilt too (if this fails, the 2D map is still refreshed)
            three_d = "ok"
            try:
                e3 = subprocess.run([sys.executable, "build_tiles.py", *city], capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=1800)
                if e3.returncode != 0:
                    three_d = "hiba: " + ((e3.stderr or e3.stdout or "")[-300:])
            except (subprocess.TimeoutExpired, OSError) as error_:
                three_d = f"hiba: {error_}"
            print(f"  3D adatok: {three_d}")
            try:      # the zone list of the 3D Housing estates tab (type, district, years)
                subprocess.run([sys.executable, "build_zones_json.py"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
            except (subprocess.TimeoutExpired, OSError):
                pass
            return self._json(200, {"ok": True, "harom_d": three_d})
        return self._json(404, {"ok": False, "hiba": "Ismeretlen kérés."})

    def log_message(self, fmt, *args):
        if "/api/" in str(args[0] if args else ""):     # str(): the first argument of error messages (e.g. 404) is a number, which previously made the server drop the connection without a response
            super().log_message(fmt, *args)


if __name__ == "__main__":
    print(f"A térkép: http://localhost:{PORT}   (leállítás: Ctrl+C)")
    print("Szerkesztési mód aktív: a javítások a forras/kezi_javitasok.csv fájlba kerülnek.")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
