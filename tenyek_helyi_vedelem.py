"""Capital's local protection list (data/helyi_vedelem.json) -> data/tenyek/helyi_vedelem.csv

Source: annex of Decree 54/1993 (1 Feb 1994) of the General Assembly of Budapest,
as of 1 June 2001 (V., VI., VII. districts). The street names already use
today's names. We take over only facts: protection, lot number, designation, designer, year.
"""
import csv
import difflib
import json
import sys
from collections import Counter, defaultdict

from kozos import tenyek_irasa
from tenyek_muemlek import ROMAI, VAROS, EPULETEK, alt_cimek, cim_felbontas, norm, szamok

JEGYZEK = "data/helyi_vedelem.json"
CIMEK = "data/varos/osm_cimek.csv" if "varos" in sys.argv[1:] else "data/osm_cimek.csv"   # py tenyek_helyi_vedelem.py varos: the addresses of the whole city
ATNEVEZES = "forras/utcanev_atnevezesek.csv"
KIMENET = "data/tenyek/helyi_vedelem.csv"
HASONLOSAG = 0.9


def main():
    atn = {}
    try:
        with open(ATNEVEZES, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                if r.get("regi") and r.get("uj"):
                    atn[norm(r["regi"])] = [norm(x) for x in r["uj"].split("|") if x.strip()]
    except FileNotFoundError:
        pass
    # In city mode we search within the district given in the list (otherwise the houses of a same-named street in another district would also match).
    kerulete = {}
    if VAROS:
        with open(EPULETEK, encoding="utf-8") as f:
            for ft in json.load(f)["features"]:
                pr = ft["properties"]
                if pr.get("kerulet"):
                    kerulete[(pr["osm_tipus"], int(pr["id"]))] = pr["kerulet"]
        if not kerulete:
            raise SystemExit("Az épületeknél nincs kerület. Futtasd: py budapest_pbf.py, majd py varos_osszeallitas.py")
    utcak_kn = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))   # district (0 = inner-city mode) -> street -> house number -> buildings
    with open(CIMEK, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            e = (r["osm_tipus"], int(r["id"]))
            if VAROS and e not in kerulete:
                continue
            for sz in szamok(r["hazszam"]):
                utcak_kn[kerulete.get(e, 0)][norm(r["utca"])][sz].append(e)
    utcak = utcak_kn[0]
    osm_utcak = list(utcak)

    def jeloltek(utca):
        n = norm(utca)
        ki = []
        for j in atn.get(n, [n]):
            if j in utcak:
                ki.append(j)
            else:
                jo = difflib.get_close_matches(j, osm_utcak, n=1, cutoff=HASONLOSAG)
                if jo:
                    ki.append(jo[0])
        return list(dict.fromkeys(ki))

    with open(JEGYZEK, encoding="utf-8") as f:
        bejegyzesek = json.load(f)["bejegyzesek"]

    kesz, parositva, nincs_utca, nincs_szam, ketertelmu, tobb = set(), 0, Counter(), 0, 0, 0
    for b in bejegyzesek:
        cimek = []
        u, sz = cim_felbontas(b["cim"])
        if u and sz:
            cimek.append((u, sz))
        cimek += alt_cimek(b.get("alt_cimek", []))
        talalat, volt_utca = set(), False
        kn = ROMAI.get(str(b.get("ker", "")).strip().upper(), 0) if VAROS else 0
        if VAROS and not kn:
            continue
        utcak = utcak_kn[kn]
        osm_utcak = list(utcak)
        for u, sz in cimek:
            jl = jeloltek(u)
            if not jl:
                nincs_utca[u] += 1
                continue
            volt_utca = True
            talalatok = []
            for mu in jl:
                t = set()
                for n in sz:
                    t.update(utcak[mu].get(n, []))
                if t:
                    talalatok.append(t)
            if len(talalatok) > 1:
                ketertelmu += 1
            elif talalatok:
                talalat.update(talalatok[0])
        if not talalat:
            nincs_szam += volt_utca
            continue
        parositva += 1
        tobb += len(talalat) > 1
        megj = "54/1993. Főv. Kgy. rendelet melléklete (2001)" + (", közelítő év" if b.get("ev_korul") else "")
        for t, i in talalat:
            tenyek = [("vedettseg_helyi", "helyi védelem"), ("helyi_vedett_hrsz", b["hrsz"]),
                      ("helyi_vedett_megnevezes", b["megnevezes"]), ("tervezo", b["tervezo"]), ("ev", b["ev"])]
            for mezo, ertek in tenyek:
                if ertek not in (None, ""):
                    kesz.add((t, i, mezo, ertek, "helyi_vedelem", megj))
    tenyek_irasa(KIMENET, sorted(kesz, key=lambda s: (s[0], s[1], s[2])))
    print(f"Bejegyzések a listán: {len(bejegyzesek)}")
    print(f"OSM-épülethez párosítva: {parositva} (ebből több OSM-épület: {tobb})")
    print(f"Az utca megvan, de a házszám nem (az OSM-épületen nincs cím): {nincs_szam}")
    if ketertelmu:
        print(f"Kétértelmű, kihagyva: {ketertelmu}")
    if nincs_utca:
        print(f"Nem található utcanevek: {len(nincs_utca)} db (valószínűleg a területünkön kívül, vagy az OSM-ben nincs címük)")
        for u, n in nincs_utca.most_common(15):
            print(f"  {u}  ({n})")
    print(f"Mentve: {KIMENET}")


if __name__ == "__main__":
    main()
