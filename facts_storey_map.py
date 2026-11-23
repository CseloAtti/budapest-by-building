"""Data of the district storey-count map (forras/szintterkep.json) -> data/tenyek/szintterkep.csv"""
import json

from common import write_facts

DATA = "forras/szintterkep.json"
OUTPUT = "data/tenyek/szintterkep.csv"
MIN_VOTE = 0.5   # at least this proportion must vote for the same colour in the image


def main():
    with open(DATA, encoding="utf-8") as f:
        data_ = json.load(f)
    rows = []
    unique = 0
    for e in data_["epuletek"]:
        if e["bizt"] < MIN_VOTE:
            continue
        t, i = e["osm_tipus"], e["id"]
        rows.append((t, i, "szintterkep_osztaly", e["osztaly"], "szintterkep", ""))
        if e["szint"] is None:
            unique += 1      # "Egyedi magasság" (individual height): there is no storey count on the map
            continue
        rows.append((t, i, "szintek_kep", e["szint"], "szintterkep", ""))
        rows.append((t, i, "szintek", e["szint"], "szintterkep", f"{e['osztaly']}, szavazat {e['bizt']:.0%}"))
    write_facts(OUTPUT, rows)
    print(f"Tény-sorok: {len(rows)}, 'Egyedi magasság' (nincs szintszám): {unique}")
    print(f"Mentve: {OUTPUT}")


main()
