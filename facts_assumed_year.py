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

INPUT = Path("data/varos/epuletek_vegleges.geojson")
OUTPUT = Path("data/varos/veletlen_kozelito.csv")
OLD = Path("data/tenyek/veletlen_ev.csv")
DISTRICTS = {2, 12}
YEAR_FROM, YEAR_TO = 1890, 1938
TEXT = f"helyi védett épület, pontos építési éve nem ismert; feltételezés: {YEAR_FROM}–{YEAR_TO}"


def main():
    with open(INPUT, encoding="utf-8") as f:
        feats = json.load(f)["features"]
    rows, district_count = [], {}
    for ft in feats:
        p = ft["properties"]
        if p.get("kerulet") not in DISTRICTS or p.get("vedettseg") != "HV" or p.get("resz"):
            continue
        if p.get("ev") not in (None, "") and p.get("ev_forras") != "veletlen":
            continue          # it has a real year
        rows.append((p.get("osm_tipus") or "way", int(p["id"]), YEAR_FROM, YEAR_TO, TEXT, "feltételezés"))
        district_count[p["kerulet"]] = district_count.get(p["kerulet"], 0) + 1
    rows = sorted(set(rows), key=lambda s: (s[0], s[1]))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["osm_tipus", "id", "ev_tol", "ev_ig", "szoveg", "forras"])
        w.writerows(rows)
    print(f"Feltételezett korszakot (közelítő adat, {YEAR_FROM}–{YEAR_TO}) kapott: {len(rows)} épület; kerületenként: {dict(sorted(district_count.items()))}")
    print(f"Mentve: {OUTPUT}")
    if OLD.exists():
        OLD.unlink()
        print(f"Törölve a régi, kitalált évszámokat tartalmazó fájl: {OLD}")


if __name__ == "__main__":
    main()
