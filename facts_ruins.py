"""A separate category of ancient and medieval ruins, archaeological remains -> data/tenyek/romok.csv (field: rom)

Only an element that has a footprint (a building polygon) can be included; we do not deal with linear elements (the line of a city wall etc.).
Decision file: forras/romok_kezi.csv   (osm_tipus;id;jelleg;kor;nev;megjegyzes)
  jelleg = rom            -> on the card and on the map it goes into the "Ancient and medieval ruins" category, with the text of the kor column
           nem_rom        -> a present-day ruined/abandoned building, it goes on to the normal estimate (this jelleg also counts as a "decision")
           ellenorizendo  -> you have not decided yet; until then we treat it by the normal estimate
The script adds every new building=ruins type OSM building to the file with the "ellenorizendo" (to be checked) jelleg (it does not touch the existing rows).
Run: py facts_ruins.py   (afterwards py assemble.py varos, py year_estimate.py varos, py assemble.py varos, py build_tiles.py varos)"""
import csv
import json
import sys
from pathlib import Path

from common import write_facts

DECISION = Path("forras/romok_kezi.csv")
BUILDINGS = "data/varos/epuletek.geojson"
OUTPUT = "data/tenyek/romok.csv"
COLUMNS = ["osm_tipus", "id", "jelleg", "kor", "nev", "megjegyzes"]


def main():
    rows = []
    if DECISION.exists():
        with open(DECISION, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f, delimiter=";"))
    known = {(r["osm_tipus"], str(r["id"])) for r in rows}
    new = 0
    try:
        with open(BUILDINGS, encoding="utf-8") as f:
            for ft in json.load(f)["features"]:
                p = ft["properties"]
                if p.get("resz") or p.get("tipus") != "ruins":
                    continue
                k = (p["osm_tipus"], str(p["id"]))
                if k in known:
                    continue
                known.add(k)
                rows.append({"osm_tipus": k[0], "id": k[1], "jelleg": "ellenorizendo", "kor": "", "nev": p.get("nev") or "",
                              "megjegyzes": "új building=ruins épület"})
                new += 1
    except FileNotFoundError:
        print(f"Figyelem: nincs {BUILDINGS}, új romokat nem keresek.")
    if new:
        with open(DECISION, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS, delimiter=";")
            w.writeheader()
            w.writerows(rows)
    facts = [(r["osm_tipus"], int(r["id"]), "rom", (r["kor"] or "rom").strip(), "romok_kezi", (r.get("megjegyzes") or "").strip())
              for r in rows if (r["jelleg"] or "").strip() == "rom"]
    write_facts(OUTPUT, facts)
    number = {}
    for r in rows:
        number[r["jelleg"]] = number.get(r["jelleg"], 0) + 1
    print(f"Rom: {number.get('rom', 0)}; nem rom: {number.get('nem_rom', 0)}; még nem döntött: {number.get('ellenorizendo', 0)}"
          f"{f' (új: {new})' if new else ''}. Mentve: {OUTPUT}")


if __name__ == "__main__":
    main()
