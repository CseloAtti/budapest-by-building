"""Matching the so far unmatched value-register / Kataszter III. items based on the plot polygon (round 2).

Input:    forras/ertekleltar_telekadatok_kesz.xlsx  (collected by hand: pontos_cim + plot polygon in EOV)
          data/ertekleltar_kartyak.json              (data of the value-register cards: year, designer, style, protection)
          data/kataszter_III_nem_parositott.csv      (the items of the III. district Kataszter)
          forras/ertekleltar_telek2_parositas.csv    (the table of manual decisions; the 3D editor writes here; it does NOT touch the rows already filled in)
Output:   forras/ertekleltar_telek2_parositas.csv    (new rows: for the unambiguous cases an 'automatikus' decision goes in, for the others candidates)
          data/tenyek/ertekleltar_telek2.csv         (facts for assemble.py: for the building of every decided row)
          data/varos/ertekleltar_telek2_kozelito.csv (era data of the '1920-as évek' (1920s) kind)
Run: py facts_plots2.py   (afterwards zones_refresh.bat)
"""
import csv
import io
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import re as _re
import zipfile
import xml.etree.ElementTree as ET
import inventory_plots as E
import facts_corner as S
from common import write_facts
from century import text_year_range
from facts_oeny import clean_street

XLSX = Path("forras/ertekleltar_telekadatok_kesz.xlsx")
CARDS = Path("data/ertekleltar_kartyak.json")
REGISTER = Path("data/kataszter_III_nem_parositott.csv")
TABLE = Path("forras/ertekleltar_telek2_parositas.csv")
OUTPUT = "data/tenyek/ertekleltar_telek2.csv"
APPROXIMATE = "data/varos/ertekleltar_telek2_kozelito.csv"
COLUMNS = ["lista", "kerulet", "cim", "hrsz", "n", "mai_cim", "adat", "allapot", "javasolt_osm", "jeloltek", "osm_azonosito", "megjegyzes"]
OSM_ID = re.compile(r"(way|relation) (\d+)")


def xlsx_rows(path_):
    """The rows of the first worksheet (lists), without an external package (an xlsx is a zip + XML)."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path_) as z:
        common_ = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
                common_.append("".join(t.text or "" for t in si.iter("{%s}t" % ns["m"])))
        names = sorted(n for n in z.namelist() if _re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
        try:
            wb = ET.fromstring(z.read("xl/workbook.xml"))
            rel = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
            first = wb.find("m:sheets", ns)[0].get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            target = next(r.get("Target") for r in rel if r.get("Id") == first)
            name_ = "xl/" + target.lstrip("/").replace("xl/", "", 1)
        except Exception:
            name_ = names[0]
        rows = []
        for row in ET.fromstring(z.read(name_)).iter("{%s}row" % ns["m"]):
            values_ = {}
            for c in row.findall("m:c", ns):
                column = 0
                for ch in _re.match(r"[A-Z]+", c.get("r")).group(0):
                    column = column * 26 + ord(ch) - 64
                t = c.get("t")
                if t == "s":
                    v = c.find("m:v", ns)
                    value = common_[int(v.text)] if v is not None and v.text else None
                elif t == "inlineStr":
                    value = "".join(x.text or "" for x in c.iter("{%s}t" % ns["m"]))
                else:
                    v = c.find("m:v", ns)
                    value = v.text if v is not None else None
                values_[column - 1] = value
            rows.append([values_.get(i) for i in range(max(values_) + 1)] if values_ else [])
        return rows


def existing_serial_numbers():
    """The serial numbers already written onto the building by OENY / the register of monuments: {(osm_tipus, id): {serial number}} (without the fully removed OENY rows)."""
    out = defaultdict(set)
    exclude = set()
    try:
        for r in csv.DictReader(open("forras/oeny_kizart.csv", encoding="utf-8-sig", newline=""), delimiter=";"):
            if (r.get("id") or "").strip().isdigit() and not (r.get("torzsszam") or "").strip():
                exclude.add(((r.get("osm_tipus") or "way").strip(), int(r["id"])))
    except FileNotFoundError:
        pass
    for fn in ("oeny", "oeny_kezi", "oeny_koord", "muemlek"):
        path_ = Path("data/tenyek") / f"{fn}.csv"
        if path_.exists():
            for r in csv.DictReader(open(path_, encoding="utf-8-sig", newline=""), delimiter=";"):
                if r["mezo"] == "muemlek_torzsszam" and (r["osm_tipus"], int(r["id"])) not in exclude:
                    out[(r["osm_tipus"], int(r["id"]))].add(str(r["ertek"]).strip())
    return out


def data_text(k, list_):
    if list_ == "kataszter III.":
        return " · ".join(x for x in (k.get("nev", "").title(), k.get("epites_eve_vagy_kora", ""), k.get("vedelem", ""), ("törzsszám " + k["torzsszam_azon"]) if k.get("torzsszam_azon") else "") if x)
    return " · ".join(str(x) for x in (k.get("ev_szoveg") or k.get("ev") or "", k.get("tervezo") or "", k.get("stilus") or "", k.get("vedelem") or "") if x)


def main():
    cards = defaultdict(list)
    for k in json.load(open(CARDS, encoding="utf-8")):
        cards[(str(k["kerulet"]), k["cim"].strip(), E.lot_number_fix(k.get("hrsz") or ""))].append(k)
    register = defaultdict(list)
    if REGISTER.exists():
        for r in csv.DictReader(open(REGISTER, encoding="utf-8-sig", newline=""), delimiter=";"):
            register[(r["cim"].strip(), E.lot_number_fix(r["hrsz"]))].append(r)
    atn = {}
    try:
        for r in csv.DictReader(open(S.RENAMING, encoding="utf-8-sig", newline=""), delimiter=";"):
            if r.get("regi") and r.get("uj") and "|" not in r["uj"]:
                atn[clean_street(r["regi"])] = clean_street(r["uj"])
    except FileNotFoundError:
        pass
    T = S.Map(S.geometry(), S.ADDRESSES, atn)

    old = {}
    if TABLE.exists():
        for r in csv.DictReader(open(TABLE, encoding="utf-8-sig", newline=""), delimiter=";"):
            old[(r["lista"], r["kerulet"], r["cim"], r["hrsz"], r["n"])] = r
    rows_x = xlsx_rows(XLSX)
    head = [str(c or "").strip() for c in rows_x[0]]
    counter, table, stat = Counter(), [], Counter()
    for r in rows_x[1:]:
        d = dict(zip(head, r))
        if not d.get("cim"):
            continue
        list_, district, address = (str(d.get(k) or "").strip() for k in ("forras_lista", "kerulet", "cim"))
        lot_number = E.lot_number_fix(str(d.get("hrsz") or ""))
        counter[(list_, district, address, lot_number)] += 1
        n = str(counter[(list_, district, address, lot_number)])
        current = str(d.get("pontos_cim") or "")
        geom = str(d.get("Geometria (GeoJSON)") or "").strip()
        source_k = (cards.get((district, address, lot_number)) or [None])[0] if list_ != "kataszter III." else (register.get((address, lot_number)) or [None])[0]
        row = old.get((list_, district, address, lot_number, n)) or {}
        new = {"lista": list_, "kerulet": district, "cim": address, "hrsz": lot_number, "n": n, "mai_cim": current[:120],
              "adat": data_text(source_k or {}, list_), "allapot": "", "javasolt_osm": "", "jeloltek": "",
              "osm_azonosito": row.get("osm_azonosito", ""), "megjegyzes": row.get("megjegyzes", "")}
        open_ = not (new["osm_azonosito"].strip() or new["megjegyzes"].strip())
        if not geom.startswith("{"):
            new["allapot"] = "nincs telekpoligon"
        else:
            try:
                rings = E.polygons(geom)
            except Exception:
                rings = None
            if not rings:
                new["allapot"] = "hibás telekpoligon"
            else:
                ov, middle = E.overlap(T, rings)
                state, buildings, reason = E.decision(T, ov, E.new_addresses(current))
                id_ = " | ".join(f"{e[0]} {e[1]}" for e in buildings)
                new["jeloltek"] = " | ".join(f"{e[0]} {e[1]} ({round(((T.b[e]['c'][0]-middle[0])**2+(T.b[e]['c'][1]-middle[1])**2)**.5)} m)" for e in buildings[:6])
                if state == "auto":
                    new["allapot"] = "automatikus (telek alapján)"
                    if open_:
                        new["osm_azonosito"], new["megjegyzes"] = id_, "automatikus (telek): " + reason
                elif state == "valoszinu":
                    new["allapot"], new["javasolt_osm"] = "valószínű (telek alapján, kézi megerősítés kell)", f"{buildings[0][0]} {buildings[0][1]}"
                elif state == "bizonytalan":
                    new["allapot"] = "bizonytalan, jelöltekkel (telek alapján)"
                else:
                    new["allapot"] = "a telekre nem esik épület"
        stat[new["allapot"]] += 1
        table.append(new)
    b = io.StringIO(newline="")
    w = csv.DictWriter(b, fieldnames=COLUMNS, delimiter=";", lineterminator="\r\n")
    w.writeheader()
    w.writerows(table)
    TABLE.parent.mkdir(exist_ok=True)
    tmp = TABLE.with_suffix(".csv.tmp")
    tmp.write_bytes(b.getvalue().encode("utf-8-sig"))
    tmp.replace(TABLE)

    # ---- facts from the decided rows ----
    done, approximate = set(), set()
    has_serial_no = existing_serial_numbers()
    for u in table:
        buildings = [(a, int(b)) for a, b in OSM_ID.findall(u["osm_azonosito"])]
        if not buildings:
            continue
        list_ = u["lista"]
        if list_ == "kataszter III.":
            k = (register.get((u["cim"], u["hrsz"])) or [None])[0]
            if not k:
                continue
            remark = f"III. kerületi Értékkataszter, {k.get('oldal', '')}. oldal, hrsz {u['hrsz']} (telek alapján párosítva)"
            for t, i in buildings:
                protect = (k.get("vedelem") or "").strip()
                kt, already = (k.get("torzsszam_azon") or ""), has_serial_no.get((t, i), set())
                if already and kt not in already:
                    # the building already has another serial number (from OENY): we do not write a second one next to it
                    stat["törzsszám kihagyva (az épületen már más van)"] += 1
                else:
                    if kt.isdigit():
                        done.add((t, i, "muemlek_torzsszam", kt, "muemlek", remark))
                    if protect.lower().startswith("műemlék"):
                        done.add((t, i, "vedettseg", "M", "muemlek", remark))
                if not protect.lower().startswith("műemlék") and protect and protect not in ("E", "Mk", "Mk / E", "-") and "javasolt" not in protect:
                    done.add((t, i, "vedettseg_helyi", protect, "ertekleltar", remark))
                m = re.fullmatch(r"\s*(1[5-9]\d\d|20[0-2]\d)\s*", k.get("epites_eve_vagy_kora") or "")
                if m:
                    done.add((t, i, "ev", int(m.group(1)), "ertekleltar", remark))
                if k.get("stilus"):
                    done.add((t, i, "stilus", k["stilus"], "ertekleltar", remark))
            continue
        k = (cards.get((u["kerulet"], u["cim"], u["hrsz"])) or [None])[0]
        if not k:
            continue
        remark = f"{k['forras']}, hrsz {k['hrsz']} (telek alapján párosítva)"
        for t, i in buildings:
            if k["ev"]:
                done.add((t, i, "ev", k["ev"], "ertekleltar", remark))
            elif k.get("korszak"):
                approximate.add((t, i, k["korszak"][0], k["korszak"][1], k["ev_szoveg"], k["forras"]))
            else:
                hold = text_year_range(k.get("ev_szoveg"))
                if hold:
                    approximate.add((t, i, hold[0], hold[1], k["ev_szoveg"], k["forras"]))
            if k["tervezo"]:
                done.add((t, i, "tervezo", k["tervezo"], "ertekleltar", remark))
            if k["stilus"]:
                done.add((t, i, "stilus", k["stilus"], "ertekleltar", remark))
            protect = k["vedelem"]
            if protect and protect not in ("E", "Mk", "Mk / E", "-") and "javasolt" not in protect:
                done.add((t, i, "vedettseg_helyi", protect, "ertekleltar", remark))
    write_facts(OUTPUT, sorted(done, key=lambda s: (s[0], s[1], s[2], str(s[3]))))
    with open(APPROXIMATE, "w", encoding="utf-8-sig", newline="") as f:
        w2 = csv.writer(f, delimiter=";")
        w2.writerow(["osm_tipus", "id", "ev_tol", "ev_ig", "szoveg", "forras"])
        w2.writerows(sorted(approximate, key=lambda r: (r[0], r[1])))
    for a, v in stat.most_common():
        print(f"  {a}: {v}")
    print(f"Tábla: {len(table)} sor -> {TABLE}; tények: {len(done)} -> {OUTPUT}; közelítő: {len(approximate)} -> {APPROXIMATE}")


if __name__ == "__main__":
    main()
