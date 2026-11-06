import json
import urllib.error
import urllib.parse
import urllib.request

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

BBOX = "47.490,19.040,47.513,19.062"

# Csak megszámoltatjuk az épületeket, nem töltjük le őket
query = f"""
[out:json][timeout:90];
(
  way["building"]({BBOX});
  relation["building"]({BBOX});
);
out count;
"""
data = urllib.parse.urlencode({"data": query}).encode("utf-8")

for url in OVERPASS_URLS:
    print(f"\nSzerver: {url}")
    request = urllib.request.Request(
        url, data=data, headers={"User-Agent": "budapest-by-building-tanulas/0.1"}
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            eredmeny = json.load(response)
    except (urllib.error.URLError, TimeoutError) as hiba:
        print(f"  Nem sikerült: {hiba}")
        continue
    print("  Figyelmeztetés (remark):", eredmeny.get("remark", "nincs"))
    print("  Adatok frissessége:", eredmeny.get("osm3s", {}).get("timestamp_osm_base", "?"))
    for elem in eredmeny["elements"]:
        print("  Darabszámok:", elem.get("tags"))

# A már elkészült GeoJSON kiterjedése
with open("data/belvaros_epuletek.geojson", encoding="utf-8") as f:
    gj = json.load(f)
lonok, latok = [], []
for ft in gj["features"]:
    for lon, lat in ft["geometry"]["coordinates"][0]:
        lonok.append(lon)
        latok.append(lat)
print("\nAz adatok kiterjedése:")
print(f"  szélesség (lat): {min(latok):.4f} – {max(latok):.4f}")
print(f"  hosszúság (lon): {min(lonok):.4f} – {max(lonok):.4f}")