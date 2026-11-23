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
IMAGES = Path("terkep3d/kepek")
OUT = Path("terkep3d/adatlapok.json")
IMAGES_OUT = {".jpg", ".jpeg", ".png", ".webp"}
TABLE = Path("forras/budapest_stilusok_final.xlsx")      # per style: period, key designers, houses (the 'Stílus' and 'Tervezők' columns are needed)
FIXES = {"Skardelli Gyögy": "Skardelli György"}        # typos of the table
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def table_read():
    """Reads the style table (xlsx) with only the Python standard library. -> {style: {"ido": ..., "tervezok": [...], "hazak": ...}}"""
    if not TABLE.exists():
        print(f"  Nincs {TABLE}: a meghatározó építészek a régi lista szerint maradnak.")
        return {}
    z = zipfile.ZipFile(TABLE)
    ss = ["".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])) for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS)]
    out = {}
    for row in ET.fromstring(z.read("xl/worksheets/sheet1.xml")).iter("{%s}row" % NS["m"]):
        v = {}
        for c in row.findall("m:c", NS):
            x = c.find("m:v", NS)
            if x is None:
                continue
            v[re.match(r"[A-Z]+", c.get("r")).group(0)] = ss[int(x.text)] if c.get("t") == "s" else x.text
        name_ = (v.get("B") or "").strip()
        if not name_ or name_ in ("Stílus", "#"):
            continue
        designers = []
        for n in re.split(r"[,;]", v.get("D", "")):
            n = re.sub(r"\s+", " ", n).strip()
            n = FIXES.get(n, n)
            if n and n not in designers:
                designers.append(n)
        out[name_] = {"ido": (v.get("C") or "").strip(), "tervezok": designers, "hazak": (v.get("E") or "").strip()}
    return out


def main():
    data_ = json.loads(BE.read_text(encoding="utf-8"))
    out = {"adatlapok": {}, "stilusok": data_.get("stilusok", {}), "tabla": table_read()}
    warn = 0
    for id_, a in data_["adatlapok"].items():
        folder = IMAGES / a.get("kepmappa", "")
        images = []
        csv_files = set()
        path_ = folder / "kepek.csv"
        if a.get("kepmappa") and path_.exists():
            for r in csv.DictReader(open(path_, encoding="utf-8-sig", newline=""), delimiter=";"):
                f = (r.get("fajl") or "").strip()
                if not f:
                    continue
                csv_files.add(f)
                if not (folder / f).exists():
                    print(f"  FIGYELEM {id_}: a kepek.csv-ben szerepel, de nincs a mappában: {f}")
                    warn += 1
                    continue
                missing = [k for k in ("szerzo", "forras_url", "licenc") if not (r.get(k) or "").strip()]
                if missing:
                    print(f"  FIGYELEM {id_}: {f} - hiányzik: {', '.join(missing)}")
                    warn += 1
                images.append({"f": f"kepek/{a['kepmappa']}/{f}", "szerzo": (r.get("szerzo") or "").strip(),
                              "forras": (r.get("forras_url") or "").strip(), "licenc": (r.get("licenc") or "").strip()})
        if folder.exists():
            for p in sorted(folder.iterdir()):
                if p.suffix.lower() in IMAGES_OUT and p.name not in csv_files:
                    print(f"  FIGYELEM {id_}: {p.name} nincs a kepek.csv-ben (nem kerül be)")
                    warn += 1
        out["adatlapok"][id_] = {"szoveg": a.get("szoveg", ""), "forrasok": a.get("forrasok", []), "kepek": images}
        if a.get("kiemel"):
            out["adatlapok"][id_]["kiemel"] = a["kiemel"]
        print(f"{id_}: {len(images)} kép, {len(a.get('szoveg', ''))} karakter szöveg")
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Stílus-táblázat: {len(out['tabla'])} stílus, {sum(len(v['tervezok']) for v in out['tabla'].values())} meghatározó építész")
    print(f"Kész: {len(out['adatlapok'])} adatlap -> {OUT}" + (f" ({warn} figyelmeztetés)" if warn else ""))


if __name__ == "__main__":
    main()
