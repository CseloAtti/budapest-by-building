"""Az OSM-épületek címe (utca, házszám) -> data/osm_cimek.csv (csak a címkék, geometria nélkül).
Egyetlen lekérdezés az egész területre."""
import csv
import time
import urllib.error
import urllib.parse
from pathlib import Path

from kozos import http_json

SZERVEREK = ["https://overpass.kumi.systems/api/interpreter",
             "https://overpass.private.coffee/api/interpreter",
             "https://overpass-api.de/api/interpreter"]
DEL, NYUGAT, ESZAK, KELET = 47.490, 19.040, 47.513, 19.062
KIMENET = "data/osm_cimek.csv"


def main():
    bbox = f"{DEL},{NYUGAT},{ESZAK},{KELET}"
    q = (f'[out:json][timeout:90];(way["building"]["building"!="roof"]["addr:housenumber"]({bbox});'
         f'relation["building"]["building"!="roof"]["addr:housenumber"]({bbox}););out tags;')
    adat = None
    for kor in range(3):
        for szerver in SZERVEREK:
            print(f"Próbálkozás: {szerver}")
            try:
                adat = http_json(szerver + "?" + urllib.parse.urlencode({"data": q}), probak=1, timeout=120)
                if adat.get("elements") is not None and not adat.get("remark"):
                    break
            except (urllib.error.URLError, OSError, ValueError) as hiba:
                print(f"  nem sikerült: {type(hiba).__name__}")
            adat = None
        if adat:
            break
        time.sleep(10)
    if not adat:
        raise SystemExit("Egyik szerver sem válaszolt. Próbáld később újra.")
    sorok = []
    for e in adat["elements"]:
        t = e.get("tags", {})
        sorok.append((e["type"], e["id"], t.get("addr:street", ""), t.get("addr:housenumber", "")))
    Path(KIMENET).parent.mkdir(exist_ok=True)
    with open(KIMENET, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["osm_tipus", "id", "utca", "hazszam"])
        w.writerows(sorok)
    print(f"Címmel rendelkező épületek: {len(sorok)}")
    print(f"Mentve: {KIMENET}")


if __name__ == "__main__":
    main()
