"""From the manual era assignments of forras/kezi_korszak.csv (osm_tipus;id;korszak;megjegyzes) -> data/varos/kezi_kozelito.csv.

Use it when you do not know a building's exact year, but do know which era it falls into. The era (0-6, in the order of the map's
eras) goes among the approximate era data, like the "the 1930s" type data of the value registers:
 - assemble.py writes it onto the card as ev_kozelito_* fields (it does not touch the 'ev' field),
 - year_estimate.py treats it as a label (puts the building into this era with high confidence, and it also counts as
   known data in the estimate for its neighbours), so the map colour will be this too.
It affects only buildings without a year (like every *_kozelito.csv).
Run: py facts_manual_era.py   (the editor server runs it by itself on saving; so does zones_refresh.bat)
"""
import csv
from pathlib import Path

FORRAS = Path("forras/kezi_korszak.csv")
KIMENET = Path("data/varos/kezi_kozelito.csv")
# (year_from, year_to, label) - the same as the map's eras (year_estimate.py KORSZAKOK); the lower bound of the first era is the map's year axis
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
