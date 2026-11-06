import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

BBOX = "47.490,19.040,47.513,19.062"

# Most "out tags geom": a körvonal koordinátáit is kérjük
query = f"""
[out:json][timeout:60];
way["building"]({BBOX});
out tags geom;
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
                with urllib.request.urlopen(request, timeout=90) as response:
                    return json.load(response)
            except (urllib.error.URLError, TimeoutError) as hiba:
                print(f"  Nem sikerült: {hiba}")
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


print("Letöltés folyamatban...")
elemek = letolt()["elements"]

features = []
for e in elemek:
    pontok = e.get("geometry")
    if not pontok or len(pontok) < 3:
        continue
    gyuru = [[p["lon"], p["lat"]] for p in pontok]
    if gyuru[0] != gyuru[-1]:
        gyuru.append(gyuru[0])
    tags = e["tags"]
    ev, ev_forras = evszam(tags)
    mag, mag_forras = magassag(tags)
    features.append({
        "type": "Feature",
        "properties": {
            "id": e["id"],
            "nev": tags.get("name"),
            "tipus": tags.get("building"),
            "szintek": szam(tags.get("building:levels")),
            "magassag": mag,
            "magassag_forras": mag_forras,
            "ev": ev,
            "ev_forras": ev_forras,
            "wikidata": tags.get("wikidata"),
        },
        "geometry": {"type": "Polygon", "coordinates": [gyuru]},
    })

geojson = {"type": "FeatureCollection", "features": features}
Path("data").mkdir(exist_ok=True)
with open("data/belvaros_epuletek.geojson", "w", encoding="utf-8") as fajl:
    json.dump(geojson, fajl, ensure_ascii=False)

print(f"Mentett épületek: {len(features)}")
for forras in ("height", "szintszam", "alapertelmezett"):
    db = sum(1 for ft in features if ft["properties"]["magassag_forras"] == forras)
    print(f"  magasság forrása '{forras}': {db}")
evvel = sum(1 for ft in features if ft["properties"]["ev"])
print(f"  építési évvel: {evvel}")