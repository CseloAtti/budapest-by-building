"""Round 2: checking and pairing the manually collected lot data (forras/ertekleltar_telekadatok_kesz.xlsx).
The 362 items are the heritage inventory's (279) and the Kataszter III's (83) items not paired so far. For every row: the lot's polygon
(EOV -> WGS84), the OSM buildings falling on the lot, a decision (auto / probable / uncertain / none) and check remarks.
Output: data/ertekleltar_telek2_jelentes.csv (it does not write to the source tables).
Run: py inventory_plots2.py"""
import csv, json, re
from collections import Counter
from pathlib import Path
import openpyxl
import eov
import facts_corner as S
from facts_oeny import clean_street
import inventory_plots as E

XLSX = Path("forras/ertekleltar_telekadatok_kesz.xlsx")
OUT = Path("data/ertekleltar_telek2_jelentes.csv")


def main():
    atn = {}
    try:
        for r in csv.DictReader(open(S.RENAMING, encoding="utf-8-sig", newline=""), delimiter=";"):
            if r.get("regi") and r.get("uj") and "|" not in r["uj"]:
                atn[clean_street(r["regi"])] = clean_street(r["uj"])
    except FileNotFoundError:
        pass
    T = S.Map(S.geometry(), S.ADDRESSES, atn)
    ws = openpyxl.load_workbook(XLSX, read_only=True, data_only=True).active
    rows = list(ws.iter_rows(values_only=True))
    head = [str(c or "").strip() for c in rows[0]]
    stat, out = Counter(), []
    for r in rows[1:]:
        d = dict(zip(head, r))
        if not d.get("cim"):
            continue
        list_, district, address, lot_number = (str(d.get(k) or "").strip() for k in ("forras_lista", "kerulet", "cim", "hrsz"))
        lot_number = E.lot_number_fix(lot_number)
        current = str(d.get("pontos_cim") or "")
        geom = str(d.get("Geometria (GeoJSON)") or "").strip()
        remark = []
        if not geom.startswith("{"):
            stat[list_ + ": nincs geometria"] += 1
            out.append([list_, district, address, lot_number, current[:90], "nincs geometria", "", "", "nincs telekpoligon", ""])
            continue
        try:
            rings = E.polygons(geom)
        except Exception as e:
            stat[list_ + ": hibás geometria"] += 1
            out.append([list_, district, address, lot_number, current[:90], "hibás geometria", "", "", f"{e.__class__.__name__}", ""])
            continue
        ov, middle = E.overlap(T, rings)
        addresses = E.new_addresses(current)
        if "Nincs találat" in current or not addresses:
            remark.append("nincs mai cím")
        state, buildings, reason = E.decision(T, ov, addresses)
        # check: is the lot in the requested district (the district key of the nearest buildings)
        district_b = Counter(str(T.b[e].get("ker") or T.b[e].get("kn") or "") for e in ov if ov[e] >= .3)
        id_ = " | ".join(f"{e[0]} {e[1]}" for e in buildings)
        candidate = " | ".join(f"{e[0]} {e[1]} ({round(((T.b[e]['c'][0]-middle[0])**2+(T.b[e]['c'][1]-middle[1])**2)**.5)} m)" for e in buildings[:6])
        stat[f"{list_}: {state}"] += 1
        out.append([list_, district, address, lot_number, current[:90], state, id_, candidate, reason + ("; " + "; ".join(remark) if remark else ""), ""])
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["forras_lista", "kerulet", "cim", "hrsz", "mai_cim", "dontes", "osm", "jeloltek", "indok", "megjegyzes"])
        w.writerows(out)
    for a, v in sorted(stat.items()):
        print(f"  {a}: {v}")


if __name__ == "__main__":
    main()
