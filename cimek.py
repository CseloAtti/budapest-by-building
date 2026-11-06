import json

with open("data/belvaros_epuletek.json", encoding="utf-8") as f:
    epuletek = json.load(f)

total = len(epuletek)
utca = sum(1 for e in epuletek if "addr:street" in e["tags"])
hazszam = sum(1 for e in epuletek if "addr:housenumber" in e["tags"])
teljes = sum(
    1 for e in epuletek
    if "addr:street" in e["tags"] and "addr:housenumber" in e["tags"]
)

print(f"Épületek: {total}")
print(f"Van utca: {utca} ({utca / total:.1%})")
print(f"Van házszám: {hazszam} ({hazszam / total:.1%})")
print(f"Teljes cím (utca + házszám): {teljes} ({teljes / total:.1%})")
print("Példa azonosító:", epuletek[0]["type"], epuletek[0]["id"])