"""
facts_ghsl.py - GHSL built-up time series (GHS-BUILT-S R2023A, 100 m) -> data/varos/ghsl.csv

What does it give? For every building: how many m2 were built up in the building's 100 m cell in 1975, 1990, 2000, 2010, 2020.
If a cell was still empty in 1990 and built up by 2000, the building standing there was very probably built after 1990.
The estimator (year_estimate.py varos) uses this as "G" evidence.

Download (once, by hand): the tile covering Budapest for all 5 years (R4_C20); the zip does NOT need to be unpacked:
  https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_BUILT_S_GLOBE_R2023A/GHS_BUILT_S_E1975_GLOBE_R2023A_54009_100/V1-0/tiles/GHS_BUILT_S_E1975_GLOBE_R2023A_54009_100_V1_0_R4_C20.zip
  (the same with the E1990, E2000, E2010, E2020 folder and file name)
  Put the files into the data/ghsl folder (the zips can stay zips, the .tif is also fine).

Run:        py facts_ghsl.py
Licence: the GHSL data is CC BY 4.0 (European Commission, JRC). Citation: Pesaresi et al., GHS-BUILT-S R2023A.
"""
import csv
import json
import math
import re
import sys
import zipfile
from pathlib import Path

from geotiff_reader import GeoTiff

ADAT = Path("data")
MAPPA = ADAT / "ghsl"
VAROS = ADAT / "varos"
R = 6378137.0       # the spherical radius of the Mollweide projection (ESRI:54009)


def mollweide(lon, lat):
    fi = math.radians(lat)
    th = fi
    for _ in range(60):
        d = 2 + 2 * math.cos(2 * th)
        if abs(d) < 1e-12:
            break
        dt = (2 * th + math.sin(2 * th) - math.pi * math.sin(fi)) / d
        th -= dt
        if abs(dt) < 1e-12:
            break
    return 2 * math.sqrt(2) / math.pi * R * math.radians(lon) * math.cos(th), math.sqrt(2) * R * math.sin(th)


def fajlok():
    """{year: [GeoTiff, ...]} from the data/ghsl folder."""
    ki = {}
    for ut in sorted(MAPPA.glob("*")):
        m = re.search(r"_E(\d{4})_", ut.name)
        if not m or ut.suffix.lower() not in (".zip", ".tif", ".tiff"):
            continue
        ev = int(m.group(1))
        if ut.suffix.lower() == ".zip":
            with zipfile.ZipFile(ut) as z:
                nev = next((n for n in z.namelist() if n.lower().endswith((".tif", ".tiff"))), None)
                if not nev:
                    print("  nincs .tif a zip-ben:", ut.name)
                    continue
                adat = z.read(nev)
        else:
            adat = ut.read_bytes()
        try:
            ki.setdefault(ev, []).append(GeoTiff(adat))
        except Exception as hiba:
            print("  nem olvasható:", ut.name, "-", hiba)
    return ki


def kozeppontok():
    g = json.load(open(VAROS / "epuletek_vegleges.geojson", encoding="utf-8"))
    ki = []
    for f in g["features"]:
        p = f["properties"]
        if p.get("resz"):
            continue
        geo = f["geometry"]
        gy = geo["coordinates"][0] if geo["type"] == "Polygon" else geo["coordinates"][0][0] if geo["type"] == "MultiPolygon" else None
        if not gy:
            continue
        lon = sum(x for x, _ in gy) / len(gy)
        lat = sum(y for _, y in gy) / len(gy)
        ki.append((p.get("osm_tipus") or "way", int(p["id"]), lon, lat))
    return ki


def main():
    if not MAPPA.exists():
        sys.exit("Nincs data/ghsl mappa. Töltsd le a csempéket (lásd a fájl elejét).")
    tif = fajlok()
    if not tif:
        sys.exit("A data/ghsl mappában nincs GHS_BUILT_S_E<évszám>_...zip vagy .tif fájl.")
    evek = sorted(tif)
    print("Évszámok:", evek)
    ep = kozeppontok()
    print("Épület:", len(ep))
    pontok = [mollweide(lon, lat) for _, _, lon, lat in ep]
    oszlopok = {}
    for ev in evek:
        ertek = [None] * len(ep)
        for t in tif[ev]:
            r = t.ertekek(pontok)
            ertek = [a if a is not None else b for a, b in zip(ertek, r)]
        oszlopok[ev] = ertek
        ok = sum(1 for v in ertek if v is not None)
        print("  %d: %d épületnek van értéke (%.1f%%), átlag %.0f m2/cella" % (
            ev, ok, 100 * ok / len(ep), sum(v for v in ertek if v is not None) / max(ok, 1)))
    if not any(v is not None for ev in evek for v in oszlopok[ev]):
        sys.exit("Egyetlen épületnek sincs értéke: nem írom meg a ghsl.csv-t. Ellenőrizd, hogy a letöltött csempe (R4_C20) fedi-e Budapestet.")
    VAROS.mkdir(parents=True, exist_ok=True)
    with open(VAROS / "ghsl.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["osm_tipus", "id"] + ["m2_%d" % ev for ev in evek])
        for n, (t, i, _, _) in enumerate(ep):
            w.writerow([t, i] + ["" if oszlopok[ev][n] is None else oszlopok[ev][n] for ev in evek])
    print("-> data/varos/ghsl.csv")


if __name__ == "__main__":
    main()
