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

from common import write_facts

REGISTER = "data/muemlek_jegyzek.json"
ADDRESSES = "data/varos/osm_cimek.csv" if "varos" in sys.argv[1:] else "data/osm_cimek.csv"   # py facts_monuments.py varos: the addresses of the whole city
RENAMING = "forras/utcanev_atnevezesek.csv"
OUTPUT = "data/tenyek/muemlek.csv"
SIMILARITY = 0.9
CITY = "varos" in sys.argv[1:]
BUILDINGS = "data/varos/epuletek.geojson"
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12, "XIII": 13,
         "XIV": 14, "XV": 15, "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20, "XXI": 21, "XXII": 22, "XXIII": 23}


def norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\bu\.", "utca", s)
    s = re.sub(r"\bkrt\.", "korut", s)
    s = re.sub(r"\bkoerut\b", "korut", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(s.split())


def numbers_(text_):
    """House numbers: '11-13' -> {11, 13}, '15/A, B' -> {15}, '4;6' -> {4, 6}"""
    out = set()
    for a, b in re.findall(r"(\d+)\s*(?:[-–]\s*(\d+))?", text_ or ""):
        out.add(int(a))
        if b:
            out.add(int(b))
    return out


def address_split(address):
    """'Veres Pálné utca 15/A, B' -> ('Veres Pálné utca', {15})"""
    start_ = 0
    # 'Október 6. utca 3.': the number after the month name is part of the street name, not a house number
    h = re.search(r"\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+ \d+\.(?=\s+(?:utca|tér|út)\b)", address)
    if h:
        start_ = h.end()
    m = re.search(r"\d", address[start_:])
    if not m:
        return None, set()
    p = start_ + m.start()
    return address[:p].strip(" ,"), numbers_(address[p:])


def alt_addresses(list_):
    out = []
    for s in list_:
        s = s.strip().strip("()")
        for part in re.split(r"\.,\s*|;\s*", s):
            u, sz = address_split(part.strip())
            if u and sz:
                out.append((u, sz))
    return out


def main():
    atn = {}
    try:
        with open(RENAMING, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                if r.get("regi") and r.get("uj"):
                    atn[norm(r["regi"])] = norm(r["uj"])
    except FileNotFoundError:
        pass

    # In city mode we search for the address within the register's district (otherwise Király utca 12. in the VI. district would also get the Király utca 12. of Újpest).
    district = {}
    if CITY:
        with open(BUILDINGS, encoding="utf-8") as f:
            for ft in json.load(f)["features"]:
                pr = ft["properties"]
                if pr.get("kerulet"):
                    district[(pr["osm_tipus"], int(pr["id"]))] = pr["kerulet"]
        if not district:
            raise SystemExit("Az épületeknél nincs kerület. Futtasd: py budapest_pbf.py, majd py city_assembly.py")
    streets = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))   # district (0 = inner-city mode) -> street name -> house number -> [(type, id)]
    with open(ADDRESSES, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            e = (r["osm_tipus"], int(r["id"]))
            if CITY and e not in district:
                continue
            kn = district.get(e, 0)
            for sz in numbers_(r["hazszam"]):
                streets[kn][norm(r["utca"])][sz].append(e)
    osm_streets = {kn: list(v) for kn, v in streets.items()}

    def street_matching(street, kn):
        n = norm(street)
        n = atn.get(n, n)
        if n in streets[kn]:
            return n
        good = difflib.get_close_matches(n, osm_streets.get(kn, []), n=1, cutoff=SIMILARITY)
        return good[0] if good else None

    with open(REGISTER, encoding="utf-8") as f:
        entries = json.load(f)["bejegyzesek"]

    rows, paired, none_street, none_number, several = 0, 0, Counter(), 0, 0
    done = set()
    for b in entries:
        addresses = []
        u, sz = address_split(b["cim"])
        if u and sz:
            addresses.append((u, sz))
        addresses += alt_addresses(b.get("alt_cimek", []))
        hit = set()
        kn = ROMAN.get(str(b.get("ker", "")).strip().upper(), 0) if CITY else 0
        if CITY and not kn:
            continue
        for u, sz in addresses:
            mu = street_matching(u, kn)
            if not mu:
                none_street[u] += 1
                continue
            for n in sz:
                hit.update(streets[kn][mu].get(n, []))
        if not hit:
            if addresses and any(street_matching(u, kn) for u, _ in addresses):
                none_number += 1
            continue
        paired += 1
        several += len(hit) > 1
        remark = f"törzsszám {b['torzsszam']}" + (f", {len(hit)} OSM-épület" if len(hit) > 1 else "")
        for t, i in hit:
            F = "muemlek"
            rows_out = [("vedettseg", b["vedettseg"]), ("muemlek_torzsszam", b["torzsszam"]),
                        ("muemlek_hrsz", b["hrsz"]), ("stilus", b["stilus"])]
            if b["evek"]:
                rows_out.append(("ev", b["evek"][0][1]))
            if b["tervezo"]:
                rows_out.append(("tervezo", b["tervezo"]))
            if b["emelet"] is not None:
                rows_out.append(("szintek", b["emelet"] + 1))
            for field, value in rows_out:
                if value not in (None, ""):
                    done.add((t, i, field, value, F, remark))
    write_facts(OUTPUT, sorted(done, key=lambda s: (s[0], s[1], s[2])))
    print(f"Bejegyzések a jegyzékben: {len(entries)}")
    print(f"OSM-épülethez párosítva: {paired} (ebből több OSM-épület: {several})")
    print(f"Az utca megvan, de a házszám nem: {none_number}")
    if none_street:
        print(f"\nNem található utcanevek (valószínűleg régi nevek) – {len(none_street)} db:")
        for u, n in none_street.most_common():
            print(f"  {u}  ({n} bejegyzés)")
        print(f"\nA mai nevüket írd be ide: {RENAMING} (oszlopok: regi;uj)")
    print(f"Mentve: {OUTPUT}")


if __name__ == "__main__":
    main()
