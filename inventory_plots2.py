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
from facts_oeny import tisztit_utca
import inventory_plots as E

XLSX = Path("forras/ertekleltar_telekadatok_kesz.xlsx")
KI = Path("data/ertekleltar_telek2_jelentes.csv")


def main():
    atn = {}
    try:
        for r in csv.DictReader(open(S.ATNEVEZES, encoding="utf-8-sig", newline=""), delimiter=";"):
            if r.get("regi") and r.get("uj") and "|" not in r["uj"]:
                atn[tisztit_utca(r["regi"])] = tisztit_utca(r["uj"])
    except FileNotFoundError:
        pass
    T = S.Terkep(S.geometria(), S.CIMEK, atn)
    ws = openpyxl.load_workbook(XLSX, read_only=True, data_only=True).active
    sorok = list(ws.iter_rows(values_only=True))
    fej = [str(c or "").strip() for c in sorok[0]]
    stat, ki = Counter(), []
    for r in sorok[1:]:
        d = dict(zip(fej, r))
        if not d.get("cim"):
            continue
        lista, ker, cim, hrsz = (str(d.get(k) or "").strip() for k in ("forras_lista", "kerulet", "cim", "hrsz"))
        hrsz = E.hrsz_javit(hrsz)
        mai = str(d.get("pontos_cim") or "")
        geom = str(d.get("Geometria (GeoJSON)") or "").strip()
        megj = []
        if not geom.startswith("{"):
            stat[lista + ": nincs geometria"] += 1
            ki.append([lista, ker, cim, hrsz, mai[:90], "nincs geometria", "", "", "nincs telekpoligon", ""])
            continue
        try:
            gyuruk = E.poligonok(geom)
        except Exception as e:
            stat[lista + ": hibás geometria"] += 1
            ki.append([lista, ker, cim, hrsz, mai[:90], "hibás geometria", "", "", f"{e.__class__.__name__}", ""])
            continue
        ov, kozep = E.atfedes(T, gyuruk)
        cimek = E.uj_cimek(mai)
        if "Nincs találat" in mai or not cimek:
            megj.append("nincs mai cím")
        allapot, epuletek, indok = E.dontes(T, ov, cimek)
        # check: is the lot in the requested district (the district key of the nearest buildings)
        ker_b = Counter(str(T.b[e].get("ker") or T.b[e].get("kn") or "") for e in ov if ov[e] >= .3)
        azon = " | ".join(f"{e[0]} {e[1]}" for e in epuletek)
        jelolt = " | ".join(f"{e[0]} {e[1]} ({round(((T.b[e]['c'][0]-kozep[0])**2+(T.b[e]['c'][1]-kozep[1])**2)**.5)} m)" for e in epuletek[:6])
        stat[f"{lista}: {allapot}"] += 1
        ki.append([lista, ker, cim, hrsz, mai[:90], allapot, azon, jelolt, indok + ("; " + "; ".join(megj) if megj else ""), ""])
    with open(KI, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["forras_lista", "kerulet", "cim", "hrsz", "mai_cim", "dontes", "osm", "jeloltek", "indok", "megjegyzes"])
        w.writerows(ki)
    for a, v in sorted(stat.items()):
        print(f"  {a}: {v}")


if __name__ == "__main__":
    main()
