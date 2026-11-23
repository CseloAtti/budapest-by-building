"""Data of the district storey-count map (forras/szintterkep.json) -> data/tenyek/szintterkep.csv"""
import json

from common import tenyek_irasa

ADAT = "forras/szintterkep.json"
KIMENET = "data/tenyek/szintterkep.csv"
MIN_SZAVAZAT = 0.5   # at least this proportion must vote for the same colour in the image


def main():
    with open(ADAT, encoding="utf-8") as f:
        adat = json.load(f)
    sorok = []
    egyedi = 0
    for e in adat["epuletek"]:
        if e["bizt"] < MIN_SZAVAZAT:
            continue
        t, i = e["osm_tipus"], e["id"]
        sorok.append((t, i, "szintterkep_osztaly", e["osztaly"], "szintterkep", ""))
        if e["szint"] is None:
            egyedi += 1      # "Egyedi magasság" (individual height): there is no storey count on the map
            continue
        sorok.append((t, i, "szintek_kep", e["szint"], "szintterkep", ""))
        sorok.append((t, i, "szintek", e["szint"], "szintterkep", f"{e['osztaly']}, szavazat {e['bizt']:.0%}"))
    tenyek_irasa(KIMENET, sorok)
    print(f"Tény-sorok: {len(sorok)}, 'Egyedi magasság' (nincs szintszám): {egyedi}")
    print(f"Mentve: {KIMENET}")


main()
