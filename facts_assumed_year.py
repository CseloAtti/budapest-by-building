"""Assumed era (APPROXIMATE data) for the locally protected (HV), non-monument buildings of the II. and XII. districts that have no year.

Input:     data/varos/epuletek_vegleges.geojson (the result of the previous assembly)
Output:    data/varos/veletlen_kozelito.csv   (approximate era data: 1890–1938, source: 'feltételezés' = assumption)
Run:       py facts_assumed_year.py varos     then zones_refresh.bat

Earlier this script wrote an INVENTED exact year (data/tenyek/veletlen_ev.csv) for every such building, which showed on the card as
a real year and also got into the training data of the era estimate. Now it becomes not a year but an approximate range:
the card shows it in the form "1890–1938, according to source", marking it as an assumption, and the estimate chooses an era only within this
range (does not learn from it). The script deletes the old data/tenyek/veletlen_ev.csv.
"""
import csv
import json
from pathlib import Path

BEMENET = Path("data/varos/epuletek_vegleges.geojson")
KIMENET = Path("data/varos/veletlen_kozelito.csv")
REGI = Path("data/tenyek/veletlen_ev.csv")
KERULETEK = {2, 12}
EV_TOL, EV_IG = 1890, 1938
SZOVEG = f"helyi védett épület, pontos építési éve nem ismert; feltételezés: {EV_TOL}–{EV_IG}"


def main():
    with open(BEMENET, encoding="utf-8") as f:
        feats = json.load(f)["features"]
    sorok, kerulet_db = [], {}
    for ft in feats:
        p = ft["properties"]
        if p.get("kerulet") not in KERULETEK or p.get("vedettseg") != "HV" or p.get("resz"):
            continue
        if p.get("ev") not in (None, "") and p.get("ev_forras") != "veletlen":
            continue          # it has a real year
        sorok.append((p.get("osm_tipus") or "way", int(p["id"]), EV_TOL, EV_IG, SZOVEG, "feltételezés"))
        kerulet_db[p["kerulet"]] = kerulet_db.get(p["kerulet"], 0) + 1
    sorok = sorted(set(sorok), key=lambda s: (s[0], s[1]))
    KIMENET.parent.mkdir(parents=True, exist_ok=True)
    with open(KIMENET, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["osm_tipus", "id", "ev_tol", "ev_ig", "szoveg", "forras"])
        w.writerows(sorok)
    print(f"Feltételezett korszakot (közelítő adat, {EV_TOL}–{EV_IG}) kapott: {len(sorok)} épület; kerületenként: {dict(sorted(kerulet_db.items()))}")
    print(f"Mentve: {KIMENET}")
    if REGI.exists():
        REGI.unlink()
        print(f"Törölve a régi, kitalált évszámokat tartalmazó fájl: {REGI}")


if __name__ == "__main__":
    main()
