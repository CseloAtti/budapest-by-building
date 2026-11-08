import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

# Sorrend: a most túlterhelt overpass-api.de a végére került
OVERPASS_URLS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

BBOX = "47.490,19.040,47.513,19.062"

query = f"""
[out:json][timeout:180];
way["building"]["building"!="roof"]({BBOX});
out tags geom;
relation["building"]["building"!="roof"]({BBOX});
out body geom;
way["building:part"]["building:part"!="roof"]({BBOX});
out tags geom;
relation["building:part"]["building:part"!="roof"]({BBOX});
out body geom;
"""

data = urllib.parse.urlencode({"data": query}).encode("utf-8")


def letolt():
    for kor in range(3):
        for url in OVERPASS_URLS:
            print(f"Próbálkozás: {url}")
            request = urllib.request.Request(
                url,
                data=data,
                headers={"User-Agent": "budapest-by-building-tanulas/0.1"},
            )
            try:
                with urllib.request.urlopen(request, timeout=200) as response:
                    eredmeny = json.load(response)
            except (urllib.error.URLError, TimeoutError) as hiba:
                print(f"  Nem sikerült: {hiba}")
                continue
            if eredmeny.get("remark"):
                print("  A szerver figyelmeztet:", eredmeny["remark"])
                continue
            tipusok = Counter(e["type"] for e in eredmeny["elements"])
            print("  Letöltött elemek:", dict(tipusok))
            return eredmeny
        print("Minden szerver hibázott, 20 másodperc várakozás...")
        time.sleep(20)
    raise SystemExit("Nem sikerült letölteni. Próbáld meg később.")


def szam(ertek):
    """Kiveszi az első számot egy szövegből ('12 m' -> 12.0). Ha nincs szám: None."""
    if ertek is None:
        return None
    talalat = re.search(r"\d+(?:[.,]\d+)?", ertek)
    if talalat:
        return float(talalat.group().replace(",", "."))
    return None


EV_CIMKEK = ["start_date", "building:start_date", "construction_date", "year_of_construction"]


def evszam(tags):
    """Visszaadja az építési évet és azt a címkét, amelyből származik."""
    for cimke in EV_CIMKEK:
        ertek = tags.get(cimke)
        if ertek:
            talalat = re.search(r"(?<!\d)(1[0-9]{3}|20[0-2][0-9])(?!\d)", ertek)
            if talalat:
                return int(talalat.group(1)), cimke
    return None, None


def magassag(tags):
    """Magasság méterben, és hogy honnan tudjuk."""
    h = szam(tags.get("height"))
    if h:
        return h, "height"
    szintek = szam(tags.get("building:levels"))
    if szintek:
        return szintek * 3.0, "szintszam"
    return 15.0, "alapertelmezett"


def gyurukke_fuz(szakaszok):
    """Szétdarabolt körvonal-szakaszokat fűz össze zárt gyűrűkké."""
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
                break  # ez a gyűrű nem zárható be
        if gyuru[0] == gyuru[-1] and len(gyuru) >= 4:
            gyuruk.append(gyuru)
    return gyuruk


def kozeppont(gyuru):
    """A gyűrű pontjainak átlaga (közelítő középpont)."""
    return [
        sum(p[0] for p in gyuru) / len(gyuru),
        sum(p[1] for p in gyuru) / len(gyuru),
    ]


def pont_gyuruben(pont, gyuru):
    """Igaz, ha a pont a gyűrűn belül van."""
    x, y = pont
    bent = False
    for (x1, y1), (x2, y2) in zip(gyuru, gyuru[1:]):
        if (y1 > y) != (y2 > y):
            if x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                bent = not bent
    return bent


def resz_e(tags):
    """Igaz, ha az elem csak épületrész (building:part), nem önálló épületkörvonal."""
    return "building" not in tags and "building:part" in tags


def lebego_e(tags):
    """Az alapjától elemelt rész (kiugró, áthidaló stb.): ezt nem tudjuk helyesen kirajzolni."""
    for cimke in ("min_height", "building:min_level", "min_level"):
        v = szam(tags.get(cimke))
        if v:
            return True
    return False


def feature_keszit(elem, koordinatak):
    tags = elem["tags"]
    ev, ev_forras = evszam(tags)
    mag, mag_forras = magassag(tags)
    return {
        "type": "Feature",
        "properties": {
            "id": elem["id"],
            "osm_tipus": elem["type"],
            "nev": tags.get("name"),
            "tipus": tags.get("building") or tags.get("building:part"),
            "resz": resz_e(tags),
            "szintek": szam(tags.get("building:levels")),
            "magassag": mag,
            "magassag_forras": mag_forras,
            "ev": ev,
            "ev_forras": ev_forras,
            "wikidata": tags.get("wikidata"),
        },
        "geometry": {"type": "Polygon", "coordinates": koordinatak},
    }


print("Letöltés folyamatban...")
elemek = letolt()["elements"]

rel = [e for e in elemek if e["type"] == "relation"]
print("Relation-ök tagokkal:", sum(1 for e in rel if e.get("members")), "/", len(rel))

# Az összetett épületek tag-körvonalait nem rajzoljuk ki külön,
# mert az épület egésze (az udvarral együtt) már megvan
relacio_tagok = set()
for e in elemek:
    if e["type"] == "relation":
        for m in e.get("members", []):
            if m["type"] == "way":
                relacio_tagok.add(m["ref"])

features = []
reszek = []
latott = set()
lebego = 0
for e in elemek:
    kulcs_ = (e["type"], e["id"])
    if kulcs_ in latott:          # az épület és az épületrész lekérdezése is visszaadhatja
        continue
    latott.add(kulcs_)
    if resz_e(e.get("tags", {})) and lebego_e(e["tags"]):
        lebego += 1
        continue
    cel = reszek if resz_e(e.get("tags", {})) else features
    if e["type"] == "way":
        if e["id"] in relacio_tagok:
            continue
        pontok = e.get("geometry")
        if not pontok or len(pontok) < 3:
            continue
        gyuru = [[p["lon"], p["lat"]] for p in pontok]
        if gyuru[0] != gyuru[-1]:
            gyuru.append(gyuru[0])
        cel.append(feature_keszit(e, [gyuru]))

    elif e["type"] == "relation":
        kulso, belso = [], []
        for m in e.get("members", []):
            if m["type"] != "way" or not m.get("geometry"):
                continue
            vonal = [[p["lon"], p["lat"]] for p in m["geometry"]]
            if m.get("role") == "inner":
                belso.append(vonal)
            else:
                kulso.append(vonal)
        kulso_gyuruk = gyurukke_fuz(kulso)
        belso_gyuruk = gyurukke_fuz(belso)
        for k in kulso_gyuruk:
            lyukak = [b for b in belso_gyuruk if pont_gyuruben(kozeppont(b), k)]
            cel.append(feature_keszit(e, [k] + lyukak))

geojson = {"type": "FeatureCollection", "features": features}
Path("data").mkdir(exist_ok=True)
with open("data/belvaros_epuletek.geojson", "w", encoding="utf-8") as fajl:
    json.dump(geojson, fajl, ensure_ascii=False)

with open("data/belvaros_reszek.geojson", "w", encoding="utf-8") as fajl:
    json.dump({"type": "FeatureCollection", "features": reszek}, fajl, ensure_ascii=False)
print(f"Mentett épületrészek (building:part): {len(reszek)}  -> data/belvaros_reszek.geojson")
if lebego:
    print(f"  kihagyva {lebego} elemelt rész (min_height / min_level)")
print(f"Mentett épületek: {len(features)}")
for tipus in ("way", "relation"):
    db = sum(1 for ft in features if ft["properties"]["osm_tipus"] == tipus)
    print(f"  OSM-típus '{tipus}': {db}")
for forras in ("height", "szintszam", "alapertelmezett"):
    db = sum(1 for ft in features if ft["properties"]["magassag_forras"] == forras)
    print(f"  magasság forrása '{forras}': {db}")
evvel = sum(1 for ft in features if ft["properties"]["ev"])
print(f"  építési évvel: {evvel}")