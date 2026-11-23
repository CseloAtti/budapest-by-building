"""Manual matching for the E-Örökség (OENY) monuments that facts_oeny.py could not tie to an OSM building.

Input:    data/oeny_nem_parositott.csv         (made by facts_oeny.py: what was not matched)
          forras/oeny_kezi_parositas.csv       (YOU fill in THIS: write the OSM building's identifier into the 'osm_azonosito' column)
          data/oeny_epuletek.json, data/muemlek_jegyzek.json   (the OENY cards and the register of monuments)
Output:   data/tenyek/oeny_kezi.csv            - the facts of the manually matched monuments for assemble.py

Run:       py facts_oeny_manual.py       (afterwards the usual: py assemble.py varos ... or zones_refresh.bat)

The table is created on the first run. Later the script appends to the end only the (new) unmatched entries not yet in it;
if there is no new row, it does not touch the file. Formatting (conditional formatting, hidden columns) is not stored in CSV anyway; save the Excel file (.xlsx) separately for that. The 'terbeli_biztonsag' and 'terbeli_javaslat' columns were filled in from the coordinates (ArcGIS): where the confidence is 'magas' (high),
osm_azonosito is already filled in (check it), for the others copy the right one from the suggestions.
Accepted forms of 'osm_azonosito': "way 123456", "123456" (way), "relation 123",
the link of the OSM page; several buildings separated by '|' (e.g. a monument consists of several buildings).
If the building cannot or need not be matched, write it into the 'megjegyzes' column (e.g. "nincs már meg" = no longer exists), and leave osm_azonosito empty.
Facts taken over: the monument serial number, protection (according to the register; if it is not in it: M, for those named "területe" (area of ...) MJT),
the OENY sheet's identifier, from the register the year of construction, designer, style, number of storeys, and the year/designer read out of the OENY description.
"""
import collections
import csv
import json
import re
import urllib.parse
from pathlib import Path

from common import tenyek_irasa

NEM_PAROSITOTT = "data/oeny_nem_parositott.csv"
TABLA = "forras/oeny_kezi_parositas.csv"
KARTYAK = "data/oeny_epuletek.json"
JEGYZEK = "data/muemlek_jegyzek.json"
KIMENET = "data/tenyek/oeny_kezi.csv"
OSZLOPOK = ["torzsszam", "megnevezes", "cim", "miert_nem_parosult", "kiolvasott_tervezo", "kiolvasott_ev",
            "lehetseges_epuletek_a_tobbi_cim_alapjan", "oeny_oldal", "osm_kereses", "arcgis_lat", "arcgis_lon",
            "terbeli_biztonsag", "terbeli_javaslat", "osm_azonosito", "megjegyzes"]


def olvas(ut):
    with open(ut, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def oeny_azonositok():
    try:
        return {int(k["torzsszam"]): k.get("azonositok", []) for k in json.loads(Path(KARTYAK).read_text(encoding="utf-8"))}
    except (FileNotFoundError, ValueError, KeyError):
        return {}


def tabla_szinkron():
    """Creates or extends the manual table with the unmatched entries (it does not touch the filled-in rows)."""
    if not Path(NEM_PAROSITOTT).exists():
        raise SystemExit(f"Hiányzik: {NEM_PAROSITOTT}. Előbb futtasd: py facts_oeny.py varos")
    # Several rows can belong to one serial number. We append a new row only if the table has fewer rows for the given
    # serial number than the unmatched list (you may correct the address in the table, that does not count as new).
    sorok = olvas(TABLA) if Path(TABLA).exists() else []
    van = collections.Counter(r["torzsszam"].strip() for r in sorok)
    azon = oeny_azonositok()
    uj = 0
    for r in olvas(NEM_PAROSITOTT):
        tsz = r["torzsszam"].strip()
        if van[tsz] > 0:
            van[tsz] -= 1
            continue
        a = azon.get(int(tsz), []) if tsz.isdigit() else []
        cim = r["cim"].split(",")[0].strip()
        sorok.append({
            **{k: r.get(k, "") for k in OSZLOPOK[:7]}, "arcgis_lat": "", "arcgis_lon": "", "terbeli_biztonsag": "", "terbeli_javaslat": "",
            "oeny_oldal": f"https://www.oeny.hu/oeny/eorok/public/monument/{a[0]}" if a else "",
            "osm_kereses": "https://www.openstreetmap.org/search?query=" + urllib.parse.quote(f"{cim}, Budapest"),
            "osm_azonosito": "", "megjegyzes": "",
        })
        uj += 1
    if not uj:
        return sorok, 0            # no new row: we do NOT rewrite the table's file (everything you set up in Excel stays)
    if Path(TABLA).exists():
        # we append the new rows only to the end, and do not touch the existing rows, order or columns
        with open(TABLA, "rb") as f:
            adat = f.read()
        with open(TABLA, encoding="utf-8-sig", newline="") as f:
            fej = next(csv.reader(f, delimiter=";"))
        sorvege = "\r\n" if b"\r\n" in adat else "\n"
        with open(TABLA, "a", encoding="utf-8", newline="") as f:
            if not adat.endswith((b"\n", b"\r")):
                f.write(sorvege)
            w = csv.DictWriter(f, fieldnames=fej, delimiter=";", extrasaction="ignore", lineterminator=sorvege)
            w.writerows(sorok[-uj:])
    else:
        Path(TABLA).parent.mkdir(parents=True, exist_ok=True)
        with open(TABLA, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=OSZLOPOK, delimiter=";", extrasaction="ignore")
            w.writeheader()
            w.writerows(sorok)
    return sorok, uj


def main():
    sorok, uj = tabla_szinkron()
    konyv = {}
    try:
        for b in json.loads(Path(JEGYZEK).read_text(encoding="utf-8"))["bejegyzesek"]:
            konyv[int(b["torzsszam"])] = b
    except (FileNotFoundError, ValueError, KeyError):
        pass
    azon = oeny_azonositok()
    kesz = set()
    kitoltott = hianyzo = 0
    for r in sorok:
        osm = []
        for resz in re.split(r"[|;,\n]+", r.get("osm_azonosito") or ""):
            m = re.search(r"(?:(way|relation|node)[/ :]*)?(\d{3,})", resz.strip(), flags=re.I)
            if m:
                osm.append(((m.group(1) or "way").lower(), int(m.group(2))))
        if not osm:
            hianyzo += 1
            continue
        kitoltott += 1
        tsz = int(r["torzsszam"])
        b = konyv.get(tsz)
        megj = f"E-Örökség, törzsszám {tsz}, kézi párosítás"
        sorok_ki = [("muemlek_torzsszam", tsz, "oeny")]
        for az in azon.get(tsz, [])[:3]:
            sorok_ki.append(("oeny_azonosito", az, "oeny"))
        if b:
            sorok_ki += [("vedettseg", b["vedettseg"], "muemlek"), ("muemlek_hrsz", b["hrsz"], "muemlek"), ("stilus", b["stilus"], "muemlek")]
            if b["evek"]:
                sorok_ki.append(("ev", b["evek"][0][1], "muemlek"))
            if b["tervezo"]:
                sorok_ki.append(("tervezo", b["tervezo"], "muemlek"))
            if b["emelet"] is not None:
                sorok_ki.append(("szintek", b["emelet"] + 1, "muemlek"))
        else:
            sorok_ki.append(("vedettseg", "MJT" if "területe" in r["megnevezes"].lower() else "M", "oeny"))
        mev = re.match(r"\s*(\d{4})(?:\.0)?\s*$", r.get("kiolvasott_ev") or "")   # Excel may convert it to "1934.0"
        if mev:
            sorok_ki.append(("ev", int(mev.group(1)), "oeny"))
        if (r.get("kiolvasott_tervezo") or "").strip():
            sorok_ki.append(("tervezo", r["kiolvasott_tervezo"].strip(), "oeny"))
        for t, i in osm:
            for mezo, ertek, forras in sorok_ki:
                if ertek not in (None, ""):
                    kesz.add((t, i, mezo, ertek, forras, megj))
    tenyek_irasa(KIMENET, sorted(kesz, key=lambda s: (s[0], s[1], s[2], str(s[3]))))
    print(f"Táblázat: {TABLA} ({len(sorok)} sor, ebből új: {uj})")
    print(f"OSM-hez kötve: {kitoltott}; még kitöltendő: {hianyzo}")
    print(f"Tények: {len(kesz)} sor -> {KIMENET}")


if __name__ == "__main__":
    main()
