"""Ókori és középkori romok, régészeti maradványok külön kategóriája -> data/tenyek/romok.csv (mező: rom)

Csak olyan elem lehet, amelynek alapterülete (épület-sokszöge) van; vonalas elemekkel (városfal vonala stb.) nem foglalkozunk.
Döntési fájl: forras/romok_kezi.csv   (osm_tipus;id;jelleg;kor;nev;megjegyzes)
  jelleg = rom            -> a kártyán és a térképen az "Ókori és középkori romok" kategóriába kerül, a kor oszlop szövegével
           nem_rom        -> mai romos/elhagyott épület, megy tovább a rendes becslésre (ez a jelleg számít "döntésnek" is)
           ellenorizendo  -> még nem döntöttél; addig a rendes becslés szerint kezeljük
A szkript minden új, building=ruins típusú OSM-épületet felvesz a fájlba "ellenorizendo" jelleggel (a meglévő sorokat nem bántja).
Futtatás: py tenyek_romok.py   (utána py osszeepit.py varos, py ev_becsles.py varos, py osszeepit.py varos, py csempek_keszites.py varos)"""
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
