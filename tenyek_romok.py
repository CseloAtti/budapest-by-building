"""A separate category of ancient and medieval ruins, archaeological remains -> data/tenyek/romok.csv (field: rom)

Only an element that has a footprint (a building polygon) can be included; we do not deal with linear elements (the line of a city wall etc.).
Decision file: forras/romok_kezi.csv   (osm_tipus;id;jelleg;kor;nev;megjegyzes)
  jelleg = rom            -> on the card and on the map it goes into the "Ancient and medieval ruins" category, with the text of the kor column
           nem_rom        -> a present-day ruined/abandoned building, it goes on to the normal estimate (this jelleg also counts as a "decision")
           ellenorizendo  -> you have not decided yet; until then we treat it by the normal estimate
The script adds every new building=ruins type OSM building to the file with the "ellenorizendo" (to be checked) jelleg (it does not touch the existing rows).
Run: py tenyek_romok.py   (afterwards py osszeepit.py varos, py ev_becsles.py varos, py osszeepit.py varos, py csempek_keszites.py varos)"""
import csv
import json
import sys
from pathlib import Path

from kozos import tenyek_irasa

DONTES = Path("forras/romok_kezi.csv")
EPULETEK = "data/varos/epuletek.geojson"
KIMENET = "data/tenyek/romok.csv"
OSZLOPOK = ["osm_tipus", "id", "jelleg", "kor", "nev", "megjegyzes"]


def main():
    sorok = []
    if DONTES.exists():
        with open(DONTES, encoding="utf-8-sig") as f:
            sorok = list(csv.DictReader(f, delimiter=";"))
    ismert = {(r["osm_tipus"], str(r["id"])) for r in sorok}
    uj = 0
    try:
        with open(EPULETEK, encoding="utf-8") as f:
            for ft in json.load(f)["features"]:
                p = ft["properties"]
                if p.get("resz") or p.get("tipus") != "ruins":
                    continue
                k = (p["osm_tipus"], str(p["id"]))
                if k in ismert:
                    continue
                ismert.add(k)
                sorok.append({"osm_tipus": k[0], "id": k[1], "jelleg": "ellenorizendo", "kor": "", "nev": p.get("nev") or "",
                              "megjegyzes": "új building=ruins épület"})
                uj += 1
    except FileNotFoundError:
        print(f"Figyelem: nincs {EPULETEK}, új romokat nem keresek.")
    if uj:
        with open(DONTES, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=OSZLOPOK, delimiter=";")
            w.writeheader()
            w.writerows(sorok)
    tenyek = [(r["osm_tipus"], int(r["id"]), "rom", (r["kor"] or "rom").strip(), "romok_kezi", (r.get("megjegyzes") or "").strip())
              for r in sorok if (r["jelleg"] or "").strip() == "rom"]
    tenyek_irasa(KIMENET, tenyek)
    szam = {}
    for r in sorok:
        szam[r["jelleg"]] = szam.get(r["jelleg"], 0) + 1
    print(f"Rom: {szam.get('rom', 0)}; nem rom: {szam.get('nem_rom', 0)}; még nem döntött: {szam.get('ellenorizendo', 0)}"
          f"{f' (új: {uj})' if uj else ''}. Mentve: {KIMENET}")


if __name__ == "__main__":
    main()
