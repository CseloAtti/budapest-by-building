"""Műemlékjegyzék (data/muemlek_jegyzek.json) -> data/tenyek/muemlek.csv

A bejegyzések címét az OSM-épületek címéhez (data/osm_cimek.csv) párosítjuk.
A könyv a 80-as évek utcaneveit használja; a régi -> mai neveket a
forras/utcanev_atnevezesek.csv adja meg (régi;új). A nem párosítható utcaneveket kiírjuk.
Csak tényeket veszünk át: védettség, törzsszám, helyrajzi szám, szintszám, stílus, év, tervező.
"""
import csv
import difflib
import json
import re
import unicodedata
from collections import Counter, defaultdict

from kozos import tenyek_irasa

JEGYZEK = "data/muemlek_jegyzek.json"
CIMEK = "data/osm_cimek.csv"
ATNEVEZES = "forras/utcanev_atnevezesek.csv"
KIMENET = "data/tenyek/muemlek.csv"
HASONLOSAG = 0.9


def norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\bu\.", "utca", s)
    s = re.sub(r"\bkrt\.", "korut", s)
    s = re.sub(r"\bkoerut\b", "korut", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(s.split())


def szamok(szoveg):
    """Házszámok: '11-13' -> {11, 13}, '15/A, B' -> {15}, '4;6' -> {4, 6}"""
    ki = set()
    for a, b in re.findall(r"(\d+)\s*(?:[-–]\s*(\d+))?", szoveg or ""):
        ki.add(int(a))
        if b:
            ki.add(int(b))
    return ki


def cim_felbontas(cim):
    """'Veres Pálné utca 15/A, B' -> ('Veres Pálné utca', {15})"""
    kezdet = 0
    # 'Október 6. utca 3.': a hónapnév utáni szám az utcanév része, nem házszám
    h = re.search(r"\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+ \d+\.(?=\s+(?:utca|tér|út)\b)", cim)
    if h:
        kezdet = h.end()
    m = re.search(r"\d", cim[kezdet:])
    if not m:
        return None, set()
    p = kezdet + m.start()
    return cim[:p].strip(" ,"), szamok(cim[p:])


def alt_cimek(lista):
    ki = []
    for s in lista:
        s = s.strip().strip("()")
        for resz in re.split(r"\.,\s*|;\s*", s):
            u, sz = cim_felbontas(resz.strip())
            if u and sz:
                ki.append((u, sz))
    return ki


def main():
    atn = {}
    try:
        with open(ATNEVEZES, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                if r.get("regi") and r.get("uj"):
                    atn[norm(r["regi"])] = norm(r["uj"])
    except FileNotFoundError:
        pass

    utcak = defaultdict(lambda: defaultdict(list))   # utcanév -> házszám -> [(tipus, id)]
    with open(CIMEK, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            for sz in szamok(r["hazszam"]):
                utcak[norm(r["utca"])][sz].append((r["osm_tipus"], int(r["id"])))
    osm_utcak = list(utcak)

    def utca_megfelelo(utca):
        n = norm(utca)
        n = atn.get(n, n)
        if n in utcak:
            return n
        jo = difflib.get_close_matches(n, osm_utcak, n=1, cutoff=HASONLOSAG)
        return jo[0] if jo else None

    with open(JEGYZEK, encoding="utf-8") as f:
        bejegyzesek = json.load(f)["bejegyzesek"]

    sorok, parositva, nincs_utca, nincs_szam, tobb = 0, 0, Counter(), 0, 0
    kesz = set()
    for b in bejegyzesek:
        cimek = []
        u, sz = cim_felbontas(b["cim"])
        if u and sz:
            cimek.append((u, sz))
        cimek += alt_cimek(b.get("alt_cimek", []))
        talalat = set()
        for u, sz in cimek:
            mu = utca_megfelelo(u)
            if not mu:
                nincs_utca[u] += 1
                continue
            for n in sz:
                talalat.update(utcak[mu].get(n, []))
        if not talalat:
            if cimek and any(utca_megfelelo(u) for u, _ in cimek):
                nincs_szam += 1
            continue
        parositva += 1
        tobb += len(talalat) > 1
        megj = f"törzsszám {b['torzsszam']}" + (f", {len(talalat)} OSM-épület" if len(talalat) > 1 else "")
        for t, i in talalat:
            F = "muemlek"
            sorok_ki = [("vedettseg", b["vedettseg"]), ("muemlek_torzsszam", b["torzsszam"]),
                        ("muemlek_hrsz", b["hrsz"]), ("stilus", b["stilus"])]
            if b["evek"]:
                sorok_ki.append(("ev", b["evek"][0][1]))
            if b["tervezo"]:
                sorok_ki.append(("tervezo", b["tervezo"]))
            if b["emelet"] is not None:
                sorok_ki.append(("szintek", b["emelet"] + 1))
            for mezo, ertek in sorok_ki:
                if ertek not in (None, ""):
                    kesz.add((t, i, mezo, ertek, F, megj))
    tenyek_irasa(KIMENET, sorted(kesz, key=lambda s: (s[0], s[1], s[2])))
    print(f"Bejegyzések a jegyzékben: {len(bejegyzesek)}")
    print(f"OSM-épülethez párosítva: {parositva} (ebből több OSM-épület: {tobb})")
    print(f"Az utca megvan, de a házszám nem: {nincs_szam}")
    if nincs_utca:
        print(f"\nNem található utcanevek (valószínűleg régi nevek) – {len(nincs_utca)} db:")
        for u, n in nincs_utca.most_common():
            print(f"  {u}  ({n} bejegyzés)")
        print(f"\nA mai nevüket írd be ide: {ATNEVEZES} (oszlopok: regi;uj)")
    print(f"Mentve: {KIMENET}")


if __name__ == "__main__":
    main()
