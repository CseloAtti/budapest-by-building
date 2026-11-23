"""Budapest100: filling in the addresses not matched by facts_bp100.py (missing house number -> interpolation / OSM address point / corner-house rule).

Input:    data/bp100_nem_parositott.csv, data/bp100/budapest100_teljes.csv, data/bp100/kepek.json,
          data/varos/epuletek.geojson, data/varos/osm_cimek.csv, data/ertekleltar_cimpontok*.csv, forras/utcanev_atnevezesek.csv
Output:   data/tenyek/budapest100_sarok.csv   - the facts of the unambiguous (~95%) matches (ev, budapest100_url, kep)
          data/bp100_sarok_javaslat.csv       - every unmatched item: status + candidates (for manual checking)
Method: the same as in the inventory-based facts_corner.py (the same Terkep class and automatic rule).
Run:      py facts_bp100.py   then   py facts_bp100_corner.py
"""
import csv
import json
import re
import collections
from pathlib import Path

import facts_corner as S
from facts_inventory import cim_felbontas
from facts_oeny import tisztit_utca
from facts_bp100 import JO_FORRAS, kerulet_irszambol
from common import tenyek_irasa

BEMENET = Path("data/bp100/budapest100_teljes.csv")
KEPEK = Path("data/bp100/kepek.json")
NEM = Path("data/bp100_nem_parositott.csv")
KIMENET = "data/tenyek/budapest100_sarok.csv"
JAVASLAT = "data/bp100_sarok_javaslat.csv"
CIMPONT_FAJLOK = ["data/ertekleltar_cimpontok.csv", "data/ertekleltar_cimpontok_wiki.csv", "data/bp100_cimpontok.csv"]


def jelolt(T, kn, u, hsz):
    """-> (auto, valoszinu, mod, [(tav, e, sarok, ter)]) or (None, None, status, [])"""
    n = int(re.match(r"\d+", hsz).group(0))
    cp = T.cimpont(kn, u, hsz)
    if cp:
        return len(cp) == 1, False, "OSM címpont alapján", cp
    u2, megj = T.utca_feloldas(u, kn)
    if not u2:
        return None, None, "ismeretlen utca az OSM-címek között", []
    p, mod, c = T.jeloltek(kn, u2, n)
    if not c:
        return None, None, f"nincs jelölt ({mod})", []
    elso = c[0]
    res = 99 if len(c) == 1 else c[1][0] - elso[0]
    auto = mod == "interpolált" and ((elso[0] < 5 and res >= 15) or (elso[0] < 1 and res >= 8))
    valoszinu = False
    if not auto and mod == "interpolált":
        sarkok = [y for y in c if y[2]]
        if sarkok and sarkok[0][0] < 5:
            tobbi = [y for y in c if y is not sarkok[0]]
            r2 = 99 if not tobbi else tobbi[0][0] - sarkok[0][0]
            if r2 >= 8:
                c, auto = [sarkok[0]] + tobbi, True
            elif sarkok[0][0] < 4 and r2 >= 4:
                c, valoszinu = [sarkok[0]] + tobbi, True
        elif elso[0] < 4 and res >= 4:
            valoszinu = True
    return auto, valoszinu, mod + (", " + megj if megj else ""), c


def main():
    atn = {}
    try:
        with open(S.ATNEVEZES, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                if r.get("regi") and r.get("uj") and "|" not in r["uj"]:
                    atn[tisztit_utca(r["regi"])] = tisztit_utca(r["uj"])
    except FileNotFoundError:
        pass
    T = S.Terkep(S.geometria(), S.CIMEK, atn)
    # we merge the address-point files (Terkep loads only one at a time)
    egyesitett = Path("data/_bp100_cimpontok_egyesitett.csv")
    sorok_p = []
    for ut in CIMPONT_FAJLOK:
        if Path(ut).exists():
            with open(ut, encoding="utf-8-sig", newline="") as f:
                sorok_p += list(csv.DictReader(f, delimiter=";"))
    with open(egyesitett, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["osm_tipus", "osm_id", "lat", "lon", "utca", "hazszam"], delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows(sorok_p)
    T.pontok_betoltese(str(egyesitett))
    egyesitett.unlink()

    forras = collections.defaultdict(list)
    for r in csv.DictReader(open(BEMENET, encoding="utf-8-sig", newline="")):
        forras[r["clean_address"].strip()].append(r)
    kepek = json.load(open(KEPEK, encoding="utf-8")) if KEPEK.exists() else {}
    nem = list(csv.DictReader(open(NEM, encoding="utf-8-sig", newline=""), delimiter=";"))
    utca_kerek = collections.defaultdict(set)
    for u, l in T.utca.items():
        for k, _, _ in l:
            utca_kerek[u].add(k)

    kesz, javaslat, stat = set(), [], collections.Counter()
    # a building that facts_bp100.py has already given Budapest100 data (typically the other address of a corner house) is not overwritten / not made to collide
    van = set()
    ut = Path("data/tenyek/budapest100.csv")
    if ut.exists():
        with open(ut, encoding="utf-8-sig", newline="") as f:
            van = {(r["osm_tipus"], int(r["id"])) for r in csv.DictReader(f, delimiter=";")}
    for n in nem:
        cim = n["cim"].strip()
        if n["miert"] == "nincs házszám":
            stat["nincs házszám (kihagyva)"] += 1
            continue
        r = (forras.get(cim) or [{}])[0]
        ev = None
        try:
            if r.get("built_year") and r.get("year_source") in JO_FORRAS and 1000 <= int(float(r["built_year"])) <= 2030:
                ev = int(float(r["built_year"]))
        except ValueError:
            pass
        url = (r.get("url") or "").strip()
        if not re.fullmatch(r"https://budapest100\.hu/house/[A-Za-z0-9_%\-]+/?", url):
            url = ""
        kn0 = kerulet_irszambol(r.get("zip_code"))
        u, hszok = cim_felbontas(cim)
        allapot, ered = "nincs házszám / utca", None
        if u and hszok:
            u = atn.get(u, u)
            for hsz in hszok:
                if not re.fullmatch(r"\d+[a-z]?(?:/[a-z0-9]+)?", hsz):
                    continue
                kerek = [kn0] if kn0 else sorted(utca_kerek.get(u, set()) or {k for k in utca_kerek.get(T.utca_feloldas(u, None)[0] or "", set())}, key=str)
                talalatok = []
                for kn in kerek:
                    a, v, mod, c = jelolt(T, kn, u, hsz)
                    if a is None:
                        allapot = mod
                        continue
                    talalatok.append((kn, a, v, mod, c))
                if not talalatok:
                    continue
                if not kn0 and len([t for t in talalatok if t[1] or t[2]]) > 1:
                    allapot = "több kerületben is lehetséges"
                    continue
                kn, a, v, mod, c = sorted(talalatok, key=lambda t: (not t[1], not t[2]))[0]
                ered = (kn, a, v, mod, c, hsz)
                break
        if not ered:
            stat[allapot] += 1
            javaslat.append([cim, ev or "", url, allapot, "", "", ""])
            continue
        kn, a, v, mod, c, hsz = ered
        jel = " | ".join(f"{e[0]} {e[1]} ({d:.0f} m{', saroképület' if sa else ''})" for d, e, sa, _ in c[:4])
        if a and c[0][1] in van:
            stat["már van Budapest100-adata (sarokház?), kézi döntés"] += 1
            javaslat.append([cim, ev or "", url, "már van Budapest100-adata (sarokház?), kézi döntés", f"{c[0][1][0]} {c[0][1][1]}", mod, jel])
        elif a:
            stat["automatikusan párosítva"] += 1
            e = c[0][1]
            megj = f"Budapest100: {cim} (hiányzó cím: {mod} párosítva) {url}".strip()
            if ev:
                kesz.add((e[0], e[1], "ev", ev, "budapest100", megj))
            if url:
                kesz.add((e[0], e[1], "budapest100_url", url, "budapest100", megj))
                kep = kepek.get(url) or kepek.get(url.rstrip("/") + "/") or kepek.get(url.rstrip("/")) or {}
                if isinstance(kep, str):
                    kep = {"kep": kep, "foto": ""}
                if kep.get("kep"):
                    kesz.add((e[0], e[1], "budapest100_kep", kep["kep"], "budapest100", megj))
                    if kep.get("foto"):
                        kesz.add((e[0], e[1], "budapest100_foto", kep["foto"], "budapest100", megj))
            javaslat.append([cim, ev or "", url, "automatikusan párosítva", f"{e[0]} {e[1]}", mod, jel])
        else:
            st = "valószínű (kézi megerősítés kell)" if v else "bizonytalan, jelöltekkel"
            stat[st] += 1
            javaslat.append([cim, ev or "", url, st, "", mod, jel])
    # manual decisions (3D editor, forras/bp100_kezi_parositas.csv): a filled-in osm_azonosito overrides the suggestion
    kezi_ut = Path("forras/bp100_kezi_parositas.csv")
    if kezi_ut.exists():
        with open(kezi_ut, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                m = re.fullmatch(r"(way|relation)\s+(\d+)", (r.get("osm_azonosito") or "").strip())
                if not m:
                    continue
                e = (m.group(1), int(m.group(2)))
                cim, url = r["cim"].strip(), (r.get("url") or "").strip()
                megj = f"Budapest100: {cim} (kézi párosítás) {url}".strip()
                try:
                    ev = int(float(r["ev"])) if r.get("ev") else None
                except ValueError:
                    ev = None
                if ev:
                    kesz.add((e[0], e[1], "ev", ev, "budapest100", megj))
                if url:
                    kesz.add((e[0], e[1], "budapest100_url", url, "budapest100", megj))
                    kep = kepek.get(url) or kepek.get(url.rstrip("/") + "/") or kepek.get(url.rstrip("/")) or {}
                    if isinstance(kep, str):
                        kep = {"kep": kep, "foto": ""}
                    if kep.get("kep"):
                        kesz.add((e[0], e[1], "budapest100_kep", kep["kep"], "budapest100", megj))
                        if kep.get("foto"):
                            kesz.add((e[0], e[1], "budapest100_foto", kep["foto"], "budapest100", megj))
                stat["kézi párosítás beépítve"] += 1
    tenyek_irasa(KIMENET, sorted(kesz, key=lambda s: (s[0], s[1], s[2])))
    with open(JAVASLAT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["cim", "ev", "url", "allapot", "javasolt_osm", "mod", "jeloltek"])
        w.writerows(javaslat)
    for k, v in stat.most_common():
        print(f"  {k}: {v}")
    print(f"Tények: {len(kesz)} sor -> {KIMENET}; javaslat: {JAVASLAT}")


if __name__ == "__main__":
    main()
