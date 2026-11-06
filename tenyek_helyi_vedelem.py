"""Fővárosi helyi védelmi lista (data/helyi_vedelem.json) -> data/tenyek/helyi_vedelem.csv

Forrás: Budapest Főváros Közgyűlésének 54/1993. (1994. II. 1.) rendelete melléklete,
a 2001. június 1-jei állapot szerint (V., VI., VII. kerület). Az utcanevek már a mai neveket
használják. Csak tényeket veszünk át: védettség, helyrajzi szám, megnevezés, tervező, év.
"""
import csv
import difflib
import json
from collections import Counter, defaultdict

from kozos import tenyek_irasa
from tenyek_muemlek import alt_cimek, cim_felbontas, norm, szamok

JEGYZEK = "data/helyi_vedelem.json"
CIMEK = "data/osm_cimek.csv"
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
    utcak = defaultdict(lambda: defaultdict(list))
    with open(CIMEK, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            for sz in szamok(r["hazszam"]):
                utcak[norm(r["utca"])][sz].append((r["osm_tipus"], int(r["id"])))
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
