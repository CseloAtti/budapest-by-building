"""A forras/kezi_korszak.csv (osm_tipus;id;korszak;megjegyzes) kézi korszak-megadásaiból data/varos/kezi_kozelito.csv.

Akkor használd, ha egy épület pontos évét nem tudod, de azt igen, melyik korszakba esik. A korszak (0-6, a térkép
korszakainak sorrendjében) a közelítő korszakadatok közé kerül, mint az értékleltárak "az 1930-as évek" jellegű adata:
 - az osszeepit.py ev_kozelito_* mezőkként írja a kártyára (az 'ev' mezőhöz nem nyúl),
 - az ev_becsles.py címkének tekinti (magas bizonyossággal ebbe a korszakba teszi, és a szomszédai becslésénél is
   ismert adatként számít), így a térkép színe is ez lesz.
Csak az évszám nélküli épületekre hat (mint minden *_kozelito.csv).
Futtatás: py tenyek_kezi_korszak.py   (a szerkesztő szerver mentéskor magától lefuttatja; a zona_frissit.bat is)
"""
import csv
from pathlib import Path

FORRAS = Path("forras/kezi_korszak.csv")
KIMENET = Path("data/varos/kezi_kozelito.csv")
# (ev_tol, ev_ig, felirat) - azonos a térkép korszakaival (ev_becsles.py KORSZAKOK); az első korszak alsó határa a térkép évtengelye
KORSZAKOK = [(1700, 1866, "1867 előtt"), (1867, 1918, "1867–1918"), (1919, 1944, "1919–1944"), (1945, 1956, "1945–1956"),
             (1957, 1989, "1957–1989"), (1990, 2010, "1990–2010"), (2011, 2026, "2011-től")]


def generalas():
    sorok = []
    if FORRAS.exists():
        with open(FORRAS, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                try:
                    tol, ig, nev = KORSZAKOK[int(r["korszak"])]
                    sorok.append((r["osm_tipus"].strip() or "way", int(r["id"]), tol, ig, nev, (r.get("megjegyzes") or "").strip()))
                except (KeyError, ValueError, IndexError):
                    continue
    KIMENET.parent.mkdir(parents=True, exist_ok=True)
    with open(KIMENET, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["osm_tipus", "id", "ev_tol", "ev_ig", "szoveg", "forras"])
        for t, i, tol, ig, nev, megj in sorok:
            w.writerow([t, i, tol, ig, "kézi korszak: " + nev + (" – " + megj if megj else ""), "kezi"])
    return len(sorok)


if __name__ == "__main__":
    print(f"Kézi korszak-megadás: {generalas()} épület -> {KIMENET}")
