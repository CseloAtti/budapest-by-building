"""Register of monuments (data/muemlek_jegyzek.json) -> data/tenyek/muemlek.csv

We match the entries' addresses to the addresses of the OSM buildings (data/osm_cimek.csv).
The book uses the street names of the 1980s; the old -> current names are given by
forras/utcanev_atnevezesek.csv (old;new). The street names that cannot be matched are printed.
We take over only facts: protection, serial number, lot number, number of storeys, style, year, designer.
"""
import csv
import difflib
import json
import sys
import re
import unicodedata
from collections import Counter, defaultdict

from common import tenyek_irasa

JEGYZEK = "data/muemlek_jegyzek.json"
CIMEK = "data/varos/osm_cimek.csv" if "varos" in sys.argv[1:] else "data/osm_cimek.csv"   # py facts_monuments.py varos: the addresses of the whole city
ATNEVEZES = "forras/utcanev_atnevezesek.csv"
KIMENET = "data/tenyek/muemlek.csv"
HASONLOSAG = 0.9
VAROS = "varos" in sys.argv[1:]
EPULETEK = "data/varos/epuletek.geojson"
ROMAI = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12, "XIII": 13,
         "XIV": 14, "XV": 15, "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20, "XXI": 21, "XXII": 22, "XXIII": 23}


def norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\bu\.", "utca", s)
    s = re.sub(r"\bkrt\.", "korut", s)
    s = re.sub(r"\bkoerut\b", "korut", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(s.split())


def szamok(szoveg):
    """House numbers: '11-13' -> {11, 13}, '15/A, B' -> {15}, '4;6' -> {4, 6}"""
    ki = set()
    for a, b in re.findall(r"(\d+)\s*(?:[-–]\s*(\d+))?", szoveg or ""):
        ki.add(int(a))
        if b:
            ki.add(int(b))
    return ki


def cim_felbontas(cim):
    """'Veres Pálné utca 15/A, B' -> ('Veres Pálné utca', {15})"""
    kezdet = 0
    # 'Október 6. utca 3.': the number after the month name is part of the street name, not a house number
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

    # In city mode we search for the address within the register's district (otherwise Király utca 12. in the VI. district would also get the Király utca 12. of Újpest).
    kerulete = {}
    if VAROS:
        with open(EPULETEK, encoding="utf-8") as f:
            for ft in json.load(f)["features"]:
                pr = ft["properties"]
                if pr.get("kerulet"):
                    kerulete[(pr["osm_tipus"], int(pr["id"]))] = pr["kerulet"]
        if not kerulete:
            raise SystemExit("Az épületeknél nincs kerület. Futtasd: py budapest_pbf.py, majd py city_assembly.py")
    utcak = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))   # district (0 = inner-city mode) -> street name -> house number -> [(type, id)]
    with open(CIMEK, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            e = (r["osm_tipus"], int(r["id"]))
            if VAROS and e not in kerulete:
                continue
            kn = kerulete.get(e, 0)
            for sz in szamok(r["hazszam"]):
                utcak[kn][norm(r["utca"])][sz].append(e)
    osm_utcak = {kn: list(v) for kn, v in utcak.items()}

    def utca_megfelelo(utca, kn):
        n = norm(utca)
        n = atn.get(n, n)
        if n in utcak[kn]:
            return n
        jo = difflib.get_close_matches(n, osm_utcak.get(kn, []), n=1, cutoff=HASONLOSAG)
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
        kn = ROMAI.get(str(b.get("ker", "")).strip().upper(), 0) if VAROS else 0
        if VAROS and not kn:
            continue
        for u, sz in cimek:
            mu = utca_megfelelo(u, kn)
            if not mu:
                nincs_utca[u] += 1
                continue
            for n in sz:
                talalat.update(utcak[kn][mu].get(n, []))
        if not talalat:
            if cimek and any(utca_megfelelo(u, kn) for u, _ in cimek):
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
