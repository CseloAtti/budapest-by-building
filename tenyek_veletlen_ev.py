"""Feltételezett korszak (KÖZELÍTŐ adat) a II. és XII. kerület azon helyi védett (HV), nem műemléki épületeire, amelyeknek nincs évszámuk.

Bemenet:   data/varos/epuletek_vegleges.geojson (az előző összeépítés eredménye)
Kimenet:   data/varos/veletlen_kozelito.csv   (közelítő korszakadat: 1890–1938, forrás: 'feltételezés')
Futtatás:  py tenyek_veletlen_ev.py varos     utána zona_frissit.bat

Korábban ez a szkript minden ilyen épületre egy KITALÁLT pontos évet írt (data/tenyek/veletlen_ev.csv), amely a kártyán
valódi évként látszott, és a korszakbecslés tanítóadatába is bekerült. Most nem évszám, hanem közelítő tartomány lesz belőle:
a kártya "1890–1938, forrás szerint" formában, a feltételezés megjelölésével mutatja, a becslés pedig csak ezen a
tartományon belül választ korszakot (nem tanul belőle). A régi data/tenyek/veletlen_ev.csv-t a szkript törli.
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
            continue          # van valódi évszáma
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
