"""Matching the so far unmatched value-register / Kataszter III. items based on the plot polygon (round 2).

Input:    forras/ertekleltar_telekadatok_kesz.xlsx  (collected by hand: pontos_cim + plot polygon in EOV)
          data/ertekleltar_kartyak.json              (data of the value-register cards: year, designer, style, protection)
          data/kataszter_III_nem_parositott.csv      (the items of the III. district Kataszter)
          forras/ertekleltar_telek2_parositas.csv    (the table of manual decisions; the 3D editor writes here; it does NOT touch the rows already filled in)
Output:   forras/ertekleltar_telek2_parositas.csv    (new rows: for the unambiguous cases an 'automatikus' decision goes in, for the others candidates)
          data/tenyek/ertekleltar_telek2.csv         (facts for osszeepit.py: for the building of every decided row)
          data/varos/ertekleltar_telek2_kozelito.csv (era data of the '1920-as évek' (1920s) kind)
Run: py tenyek_telek2.py   (afterwards zona_frissit.bat)
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
import ertekleltar_telek as E
import tenyek_sarok as S
from kozos import tenyek_irasa
from szazad import szoveg_evtartomany
from tenyek_oeny import tisztit_utca

XLSX = Path("forras/ertekleltar_telekadatok_kesz.xlsx")
KARTYAK = Path("data/ertekleltar_kartyak.json")
KATASZTER = Path("data/kataszter_III_nem_parositott.csv")
TABLA = Path("forras/ertekleltar_telek2_parositas.csv")
KIMENET = "data/tenyek/ertekleltar_telek2.csv"
KOZELITO = "data/varos/ertekleltar_telek2_kozelito.csv"
OSZLOPOK = ["lista", "kerulet", "cim", "hrsz", "n", "mai_cim", "adat", "allapot", "javasolt_osm", "jeloltek", "osm_azonosito", "megjegyzes"]
OSM_AZON = re.compile(r"(way|relation) (\d+)")


def xlsx_sorok(ut):
    """The rows of the first worksheet (lists), without an external package (an xlsx is a zip + XML)."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(ut) as z:
        kozos = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
                kozos.append("".join(t.text or "" for t in si.iter("{%s}t" % ns["m"])))
        nevek = sorted(n for n in z.namelist() if _re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
        try:
            wb = ET.fromstring(z.read("xl/workbook.xml"))
            rel = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
            elso = wb.find("m:sheets", ns)[0].get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            cel = next(r.get("Target") for r in rel if r.get("Id") == elso)
            nev = "xl/" + cel.lstrip("/").replace("xl/", "", 1)
        except Exception:
            nev = nevek[0]
        sorok = []
        for sor in ET.fromstring(z.read(nev)).iter("{%s}row" % ns["m"]):
            ertekek = {}
            for c in sor.findall("m:c", ns):
                oszlop = 0
                for ch in _re.match(r"[A-Z]+", c.get("r")).group(0):
                    oszlop = oszlop * 26 + ord(ch) - 64
                t = c.get("t")
                if t == "s":
                    v = c.find("m:v", ns)
                    ertek = kozos[int(v.text)] if v is not None and v.text else None
                elif t == "inlineStr":
                    ertek = "".join(x.text or "" for x in c.iter("{%s}t" % ns["m"]))
                else:
                    v = c.find("m:v", ns)
                    ertek = v.text if v is not None else None
                ertekek[oszlop - 1] = ertek
            sorok.append([ertekek.get(i) for i in range(max(ertekek) + 1)] if ertekek else [])
        return sorok


def meglevo_torzsszamok():
    """The serial numbers already written onto the building by OENY / the register of monuments: {(osm_tipus, id): {serial number}} (without the fully removed OENY rows)."""
    ki = defaultdict(set)
    kiz = set()
    try:
        for r in csv.DictReader(open("forras/oeny_kizart.csv", encoding="utf-8-sig", newline=""), delimiter=";"):
            if (r.get("id") or "").strip().isdigit() and not (r.get("torzsszam") or "").strip():
                kiz.add(((r.get("osm_tipus") or "way").strip(), int(r["id"])))
    except FileNotFoundError:
        pass
    for fn in ("oeny", "oeny_kezi", "oeny_koord", "muemlek"):
        ut = Path("data/tenyek") / f"{fn}.csv"
        if ut.exists():
            for r in csv.DictReader(open(ut, encoding="utf-8-sig", newline=""), delimiter=";"):
                if r["mezo"] == "muemlek_torzsszam" and (r["osm_tipus"], int(r["id"])) not in kiz:
                    ki[(r["osm_tipus"], int(r["id"]))].add(str(r["ertek"]).strip())
    return ki


def adat_szoveg(k, lista):
    if lista == "kataszter III.":
        return " · ".join(x for x in (k.get("nev", "").title(), k.get("epites_eve_vagy_kora", ""), k.get("vedelem", ""), ("törzsszám " + k["torzsszam_azon"]) if k.get("torzsszam_azon") else "") if x)
    return " · ".join(str(x) for x in (k.get("ev_szoveg") or k.get("ev") or "", k.get("tervezo") or "", k.get("stilus") or "", k.get("vedelem") or "") if x)


def main():
    kartyak = defaultdict(list)
    for k in json.load(open(KARTYAK, encoding="utf-8")):
        kartyak[(str(k["kerulet"]), k["cim"].strip(), E.hrsz_javit(k.get("hrsz") or ""))].append(k)
    katasz = defaultdict(list)
    if KATASZTER.exists():
        for r in csv.DictReader(open(KATASZTER, encoding="utf-8-sig", newline=""), delimiter=";"):
            katasz[(r["cim"].strip(), E.hrsz_javit(r["hrsz"]))].append(r)
    atn = {}
    try:
        for r in csv.DictReader(open(S.ATNEVEZES, encoding="utf-8-sig", newline=""), delimiter=";"):
            if r.get("regi") and r.get("uj") and "|" not in r["uj"]:
                atn[tisztit_utca(r["regi"])] = tisztit_utca(r["uj"])
    except FileNotFoundError:
        pass
    T = S.Terkep(S.geometria(), S.CIMEK, atn)

    regi = {}
    if TABLA.exists():
        for r in csv.DictReader(open(TABLA, encoding="utf-8-sig", newline=""), delimiter=";"):
            regi[(r["lista"], r["kerulet"], r["cim"], r["hrsz"], r["n"])] = r
    sorok_x = xlsx_sorok(XLSX)
    fej = [str(c or "").strip() for c in sorok_x[0]]
    szamlalo, tabla, stat = Counter(), [], Counter()
    for r in sorok_x[1:]:
        d = dict(zip(fej, r))
        if not d.get("cim"):
            continue
        lista, ker, cim = (str(d.get(k) or "").strip() for k in ("forras_lista", "kerulet", "cim"))
        hrsz = E.hrsz_javit(str(d.get("hrsz") or ""))
        szamlalo[(lista, ker, cim, hrsz)] += 1
        n = str(szamlalo[(lista, ker, cim, hrsz)])
        mai = str(d.get("pontos_cim") or "")
        geom = str(d.get("Geometria (GeoJSON)") or "").strip()
        forras_k = (kartyak.get((ker, cim, hrsz)) or [None])[0] if lista != "kataszter III." else (katasz.get((cim, hrsz)) or [None])[0]
        sor = regi.get((lista, ker, cim, hrsz, n)) or {}
        uj = {"lista": lista, "kerulet": ker, "cim": cim, "hrsz": hrsz, "n": n, "mai_cim": mai[:120],
              "adat": adat_szoveg(forras_k or {}, lista), "allapot": "", "javasolt_osm": "", "jeloltek": "",
              "osm_azonosito": sor.get("osm_azonosito", ""), "megjegyzes": sor.get("megjegyzes", "")}
        nyitott = not (uj["osm_azonosito"].strip() or uj["megjegyzes"].strip())
        if not geom.startswith("{"):
            uj["allapot"] = "nincs telekpoligon"
        else:
            try:
                gyuruk = E.poligonok(geom)
            except Exception:
                gyuruk = None
            if not gyuruk:
                uj["allapot"] = "hibás telekpoligon"
            else:
                ov, kozep = E.atfedes(T, gyuruk)
                allapot, epuletek, indok = E.dontes(T, ov, E.uj_cimek(mai))
                azon = " | ".join(f"{e[0]} {e[1]}" for e in epuletek)
                uj["jeloltek"] = " | ".join(f"{e[0]} {e[1]} ({round(((T.b[e]['c'][0]-kozep[0])**2+(T.b[e]['c'][1]-kozep[1])**2)**.5)} m)" for e in epuletek[:6])
                if allapot == "auto":
                    uj["allapot"] = "automatikus (telek alapján)"
                    if nyitott:
                        uj["osm_azonosito"], uj["megjegyzes"] = azon, "automatikus (telek): " + indok
                elif allapot == "valoszinu":
                    uj["allapot"], uj["javasolt_osm"] = "valószínű (telek alapján, kézi megerősítés kell)", f"{epuletek[0][0]} {epuletek[0][1]}"
                elif allapot == "bizonytalan":
                    uj["allapot"] = "bizonytalan, jelöltekkel (telek alapján)"
                else:
                    uj["allapot"] = "a telekre nem esik épület"
        stat[uj["allapot"]] += 1
        tabla.append(uj)
    b = io.StringIO(newline="")
    w = csv.DictWriter(b, fieldnames=OSZLOPOK, delimiter=";", lineterminator="\r\n")
    w.writeheader()
    w.writerows(tabla)
    TABLA.parent.mkdir(exist_ok=True)
    tmp = TABLA.with_suffix(".csv.tmp")
    tmp.write_bytes(b.getvalue().encode("utf-8-sig"))
    tmp.replace(TABLA)

    # ---- facts from the decided rows ----
    kesz, kozelito = set(), set()
    van_tsz = meglevo_torzsszamok()
    for u in tabla:
        epuletek = [(a, int(b)) for a, b in OSM_AZON.findall(u["osm_azonosito"])]
        if not epuletek:
            continue
        lista = u["lista"]
        if lista == "kataszter III.":
            k = (katasz.get((u["cim"], u["hrsz"])) or [None])[0]
            if not k:
                continue
            megj = f"III. kerületi Értékkataszter, {k.get('oldal', '')}. oldal, hrsz {u['hrsz']} (telek alapján párosítva)"
            for t, i in epuletek:
                ved = (k.get("vedelem") or "").strip()
                kt, mar = (k.get("torzsszam_azon") or ""), van_tsz.get((t, i), set())
                if mar and kt not in mar:
                    # the building already has another serial number (from OENY): we do not write a second one next to it
                    stat["törzsszám kihagyva (az épületen már más van)"] += 1
                else:
                    if kt.isdigit():
                        kesz.add((t, i, "muemlek_torzsszam", kt, "muemlek", megj))
                    if ved.lower().startswith("műemlék"):
                        kesz.add((t, i, "vedettseg", "M", "muemlek", megj))
                if not ved.lower().startswith("műemlék") and ved and ved not in ("E", "Mk", "Mk / E", "-") and "javasolt" not in ved:
                    kesz.add((t, i, "vedettseg_helyi", ved, "ertekleltar", megj))
                m = re.fullmatch(r"\s*(1[5-9]\d\d|20[0-2]\d)\s*", k.get("epites_eve_vagy_kora") or "")
                if m:
                    kesz.add((t, i, "ev", int(m.group(1)), "ertekleltar", megj))
                if k.get("stilus"):
                    kesz.add((t, i, "stilus", k["stilus"], "ertekleltar", megj))
            continue
        k = (kartyak.get((u["kerulet"], u["cim"], u["hrsz"])) or [None])[0]
        if not k:
            continue
        megj = f"{k['forras']}, hrsz {k['hrsz']} (telek alapján párosítva)"
        for t, i in epuletek:
            if k["ev"]:
                kesz.add((t, i, "ev", k["ev"], "ertekleltar", megj))
            elif k.get("korszak"):
                kozelito.add((t, i, k["korszak"][0], k["korszak"][1], k["ev_szoveg"], k["forras"]))
            else:
                tart = szoveg_evtartomany(k.get("ev_szoveg"))
                if tart:
                    kozelito.add((t, i, tart[0], tart[1], k["ev_szoveg"], k["forras"]))
            if k["tervezo"]:
                kesz.add((t, i, "tervezo", k["tervezo"], "ertekleltar", megj))
            if k["stilus"]:
                kesz.add((t, i, "stilus", k["stilus"], "ertekleltar", megj))
            ved = k["vedelem"]
            if ved and ved not in ("E", "Mk", "Mk / E", "-") and "javasolt" not in ved:
                kesz.add((t, i, "vedettseg_helyi", ved, "ertekleltar", megj))
    tenyek_irasa(KIMENET, sorted(kesz, key=lambda s: (s[0], s[1], s[2], str(s[3]))))
    with open(KOZELITO, "w", encoding="utf-8-sig", newline="") as f:
        w2 = csv.writer(f, delimiter=";")
        w2.writerow(["osm_tipus", "id", "ev_tol", "ev_ig", "szoveg", "forras"])
        w2.writerows(sorted(kozelito, key=lambda r: (r[0], r[1])))
    for a, v in stat.most_common():
        print(f"  {a}: {v}")
    print(f"Tábla: {len(tabla)} sor -> {TABLA}; tények: {len(kesz)} -> {KIMENET}; közelítő: {len(kozelito)} -> {KOZELITO}")


if __name__ == "__main__":
    main()
