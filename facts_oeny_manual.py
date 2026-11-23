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

from common import write_facts

NOT_PAIRED = "data/oeny_nem_parositott.csv"
TABLE = "forras/oeny_kezi_parositas.csv"
CARDS = "data/oeny_epuletek.json"
REGISTER = "data/muemlek_jegyzek.json"
OUTPUT = "data/tenyek/oeny_kezi.csv"
COLUMNS = ["torzsszam", "megnevezes", "cim", "miert_nem_parosult", "kiolvasott_tervezo", "kiolvasott_ev",
            "lehetseges_epuletek_a_tobbi_cim_alapjan", "oeny_oldal", "osm_kereses", "arcgis_lat", "arcgis_lon",
            "terbeli_biztonsag", "terbeli_javaslat", "osm_azonosito", "megjegyzes"]


def read_(path_):
    with open(path_, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def oeny_identifiers():
    try:
        return {int(k["torzsszam"]): k.get("azonositok", []) for k in json.loads(Path(CARDS).read_text(encoding="utf-8"))}
    except (FileNotFoundError, ValueError, KeyError):
        return {}


def table_sync():
    """Creates or extends the manual table with the unmatched entries (it does not touch the filled-in rows)."""
    if not Path(NOT_PAIRED).exists():
        raise SystemExit(f"Hiányzik: {NOT_PAIRED}. Előbb futtasd: py facts_oeny.py varos")
    # Several rows can belong to one serial number. We append a new row only if the table has fewer rows for the given
    # serial number than the unmatched list (you may correct the address in the table, that does not count as new).
    rows = read_(TABLE) if Path(TABLE).exists() else []
    has = collections.Counter(r["torzsszam"].strip() for r in rows)
    id_ = oeny_identifiers()
    new = 0
    for r in read_(NOT_PAIRED):
        serial_no = r["torzsszam"].strip()
        if has[serial_no] > 0:
            has[serial_no] -= 1
            continue
        a = id_.get(int(serial_no), []) if serial_no.isdigit() else []
        address = r["cim"].split(",")[0].strip()
        rows.append({
            **{k: r.get(k, "") for k in COLUMNS[:7]}, "arcgis_lat": "", "arcgis_lon": "", "terbeli_biztonsag": "", "terbeli_javaslat": "",
            "oeny_oldal": f"https://www.oeny.hu/oeny/eorok/public/monument/{a[0]}" if a else "",
            "osm_kereses": "https://www.openstreetmap.org/search?query=" + urllib.parse.quote(f"{address}, Budapest"),
            "osm_azonosito": "", "megjegyzes": "",
        })
        new += 1
    if not new:
        return rows, 0            # no new row: we do NOT rewrite the table's file (everything you set up in Excel stays)
    if Path(TABLE).exists():
        # we append the new rows only to the end, and do not touch the existing rows, order or columns
        with open(TABLE, "rb") as f:
            data_ = f.read()
        with open(TABLE, encoding="utf-8-sig", newline="") as f:
            head = next(csv.reader(f, delimiter=";"))
        line_end = "\r\n" if b"\r\n" in data_ else "\n"
        with open(TABLE, "a", encoding="utf-8", newline="") as f:
            if not data_.endswith((b"\n", b"\r")):
                f.write(line_end)
            w = csv.DictWriter(f, fieldnames=head, delimiter=";", extrasaction="ignore", lineterminator=line_end)
            w.writerows(rows[-new:])
    else:
        Path(TABLE).parent.mkdir(parents=True, exist_ok=True)
        with open(TABLE, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS, delimiter=";", extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    return rows, new


def main():
    rows, new = table_sync()
    book = {}
    try:
        for b in json.loads(Path(REGISTER).read_text(encoding="utf-8"))["bejegyzesek"]:
            book[int(b["torzsszam"])] = b
    except (FileNotFoundError, ValueError, KeyError):
        pass
    id_ = oeny_identifiers()
    done = set()
    filled = missing = 0
    for r in rows:
        osm = []
        for part in re.split(r"[|;,\n]+", r.get("osm_azonosito") or ""):
            m = re.search(r"(?:(way|relation|node)[/ :]*)?(\d{3,})", part.strip(), flags=re.I)
            if m:
                osm.append(((m.group(1) or "way").lower(), int(m.group(2))))
        if not osm:
            missing += 1
            continue
        filled += 1
        serial_no = int(r["torzsszam"])
        b = book.get(serial_no)
        remark = f"E-Örökség, törzsszám {serial_no}, kézi párosítás"
        rows_out = [("muemlek_torzsszam", serial_no, "oeny")]
        for az in id_.get(serial_no, [])[:3]:
            rows_out.append(("oeny_azonosito", az, "oeny"))
        if b:
            rows_out += [("vedettseg", b["vedettseg"], "muemlek"), ("muemlek_hrsz", b["hrsz"], "muemlek"), ("stilus", b["stilus"], "muemlek")]
            if b["evek"]:
                rows_out.append(("ev", b["evek"][0][1], "muemlek"))
            if b["tervezo"]:
                rows_out.append(("tervezo", b["tervezo"], "muemlek"))
            if b["emelet"] is not None:
                rows_out.append(("szintek", b["emelet"] + 1, "muemlek"))
        else:
            rows_out.append(("vedettseg", "MJT" if "területe" in r["megnevezes"].lower() else "M", "oeny"))
        mev = re.match(r"\s*(\d{4})(?:\.0)?\s*$", r.get("kiolvasott_ev") or "")   # Excel may convert it to "1934.0"
        if mev:
            rows_out.append(("ev", int(mev.group(1)), "oeny"))
        if (r.get("kiolvasott_tervezo") or "").strip():
            rows_out.append(("tervezo", r["kiolvasott_tervezo"].strip(), "oeny"))
        for t, i in osm:
            for field, value, source in rows_out:
                if value not in (None, ""):
                    done.add((t, i, field, value, source, remark))
    write_facts(OUTPUT, sorted(done, key=lambda s: (s[0], s[1], s[2], str(s[3]))))
    print(f"Táblázat: {TABLE} ({len(rows)} sor, ebből új: {new})")
    print(f"OSM-hez kötve: {filled}; még kitöltendő: {missing}")
    print(f"Tények: {len(done)} sor -> {OUTPUT}")


if __name__ == "__main__":
    main()
