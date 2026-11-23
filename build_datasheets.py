"""Data sheets of key buildings -> terkep3d/adatlapok.json

Run (in the project folder):   py build_datasheets.py
Input:    forras/adatlapok.json                 (text, sources, the per-style list of houses)
          terkep3d/kepek/<image_folder>/kepek.csv   (per image: fajl;szerzo;forras_url;licenc;megjegyzes) and the image files themselves
Output:   terkep3d/adatlapok.json               (read by the 3D view; the rebuild does not touch it)
Check:    prints which image lacks its author, source or licence, and which file is not in the csv / the folder.
Before going public the goal is a state with no warnings: every image should have an author, a source and a licence (or a permission).
"""
import csv
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

BE = Path("forras/adatlapok.json")
KEPEK = Path("terkep3d/kepek")
KI = Path("terkep3d/adatlapok.json")
KEPEK_KIT = {".jpg", ".jpeg", ".png", ".webp"}
TABLA = Path("forras/budapest_stilusok_final.xlsx")      # per style: period, key designers, houses (the 'Stílus' and 'Tervezők' columns are needed)
JAVITASOK = {"Skardelli Gyögy": "Skardelli György"}        # typos of the table
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def tabla_olvas():
    """Reads the style table (xlsx) with only the Python standard library. -> {style: {"ido": ..., "tervezok": [...], "hazak": ...}}"""
    if not TABLA.exists():
        print(f"  Nincs {TABLA}: a meghatározó építészek a régi lista szerint maradnak.")
        return {}
    z = zipfile.ZipFile(TABLA)
    ss = ["".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])) for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS)]
    ki = {}
    for sor in ET.fromstring(z.read("xl/worksheets/sheet1.xml")).iter("{%s}row" % NS["m"]):
        v = {}
        for c in sor.findall("m:c", NS):
            x = c.find("m:v", NS)
            if x is None:
                continue
            v[re.match(r"[A-Z]+", c.get("r")).group(0)] = ss[int(x.text)] if c.get("t") == "s" else x.text
        nev = (v.get("B") or "").strip()
        if not nev or nev in ("Stílus", "#"):
            continue
        tervezok = []
        for n in re.split(r"[,;]", v.get("D", "")):
            n = re.sub(r"\s+", " ", n).strip()
            n = JAVITASOK.get(n, n)
            if n and n not in tervezok:
                tervezok.append(n)
        ki[nev] = {"ido": (v.get("C") or "").strip(), "tervezok": tervezok, "hazak": (v.get("E") or "").strip()}
    return ki


def main():
    adat = json.loads(BE.read_text(encoding="utf-8"))
    ki = {"adatlapok": {}, "stilusok": adat.get("stilusok", {}), "tabla": tabla_olvas()}
    figy = 0
    for azon, a in adat["adatlapok"].items():
        mappa = KEPEK / a.get("kepmappa", "")
        kepek = []
        csv_fajlok = set()
        ut = mappa / "kepek.csv"
        if a.get("kepmappa") and ut.exists():
            for r in csv.DictReader(open(ut, encoding="utf-8-sig", newline=""), delimiter=";"):
                f = (r.get("fajl") or "").strip()
                if not f:
                    continue
                csv_fajlok.add(f)
                if not (mappa / f).exists():
                    print(f"  FIGYELEM {azon}: a kepek.csv-ben szerepel, de nincs a mappában: {f}")
                    figy += 1
                    continue
                hiany = [k for k in ("szerzo", "forras_url", "licenc") if not (r.get(k) or "").strip()]
                if hiany:
                    print(f"  FIGYELEM {azon}: {f} - hiányzik: {', '.join(hiany)}")
                    figy += 1
                kepek.append({"f": f"kepek/{a['kepmappa']}/{f}", "szerzo": (r.get("szerzo") or "").strip(),
                              "forras": (r.get("forras_url") or "").strip(), "licenc": (r.get("licenc") or "").strip()})
        if mappa.exists():
            for p in sorted(mappa.iterdir()):
                if p.suffix.lower() in KEPEK_KIT and p.name not in csv_fajlok:
                    print(f"  FIGYELEM {azon}: {p.name} nincs a kepek.csv-ben (nem kerül be)")
                    figy += 1
        ki["adatlapok"][azon] = {"szoveg": a.get("szoveg", ""), "forrasok": a.get("forrasok", []), "kepek": kepek}
        if a.get("kiemel"):
            ki["adatlapok"][azon]["kiemel"] = a["kiemel"]
        print(f"{azon}: {len(kepek)} kép, {len(a.get('szoveg', ''))} karakter szöveg")
    KI.write_text(json.dumps(ki, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Stílus-táblázat: {len(ki['tabla'])} stílus, {sum(len(v['tervezok']) for v in ki['tabla'].values())} meghatározó építész")
    print(f"Kész: {len(ki['adatlapok'])} adatlap -> {KI}" + (f" ({figy} figyelmeztetés)" if figy else ""))


if __name__ == "__main__":
    main()
