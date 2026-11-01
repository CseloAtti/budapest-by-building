import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Több nyilvános Overpass szerver: ha az egyik nem válaszol, jön a következő
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

# Befoglaló téglalap: dél, nyugat, észak, kelet (kb. az V. kerület)
BBOX = "47.490,19.040,47.513,19.062"

query = f"""
[out:json][timeout:60];
way["building"]({BBOX});
out tags center;
"""

data = urllib.parse.urlencode({"data": query}).encode("utf-8")


def letolt():
    """Végigpróbálja a szervereket, szükség esetén többször is."""
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


print("Letöltés folyamatban...")
result = letolt()
buildings = result["elements"]

Path("data").mkdir(exist_ok=True)
with open("data/belvaros_epuletek.json", "w", encoding="utf-8") as f:
    json.dump(buildings, f, ensure_ascii=False)

total = len(buildings)
with_year = sum(1 for b in buildings if "start_date" in b["tags"])
with_levels = sum(1 for b in buildings if "building:levels" in b["tags"])
with_height = sum(1 for b in buildings if "height" in b["tags"])

print(f"Épületek száma: {total}")
print(f"Építési évvel (start_date): {with_year} ({with_year / total:.1%})")
print(f"Szintszámmal (building:levels): {with_levels} ({with_levels / total:.1%})")
print(f"Magassággal (height): {with_height} ({with_height / total:.1%})")