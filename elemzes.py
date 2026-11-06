import json
import re
from collections import Counter

with open("data/belvaros_epuletek.json", encoding="utf-8") as f:
    epuletek = json.load(f)

# 1. Milyen formátumúak a start_date értékek?
peldak = []
evek = []
for e in epuletek:
    ertek = e["tags"].get("start_date")
    if ertek is None:
        continue
    if len(peldak) < 15:
        peldak.append(ertek)
    talalat = re.search(r"\b(1[0-9]{3}|20[0-2][0-9])\b", ertek)
    if talalat:
        evek.append(int(talalat.group(1)))

print("Példák a start_date értékekre:", peldak)
print(f"Értelmezhető évszám: {len(evek)}")

# 2. Évtizedek szerinti eloszlás (egyszerű szöveges oszlopdiagram)
evtizedek = Counter((ev // 10) * 10 for ev in evek)
print("\nÉvtizedek szerinti eloszlás:")
for evtized in sorted(evtizedek):
    db = evtizedek[evtized]
    print(f"{evtized}-es évek: {'#' * db} ({db})")

# 3. Más, korra utaló címkék?
kulcsok = Counter()
for e in epuletek:
    for kulcs in e["tags"]:
        if any(szo in kulcs.lower() for szo in ("date", "year", "built", "age")):
            kulcsok[kulcs] += 1
print("\nKorra utaló címkék (név: darabszám):")
for kulcs, db in kulcsok.most_common():
    print(f"  {kulcs}: {db}")

# 4. Egyéb hasznos címkék
print("\nEgyéb címkék:")
print("  wikidata:", sum(1 for e in epuletek if "wikidata" in e["tags"]))
print("  name:", sum(1 for e in epuletek if "name" in e["tags"]))
print("  heritage:", sum(1 for e in epuletek if "heritage" in e["tags"]))
print("  épülettípus (building):",
      Counter(e["tags"].get("building") for e in epuletek).most_common(5))