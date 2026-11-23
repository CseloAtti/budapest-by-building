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

from common import write_facts
from facts_monuments import ROMAN, CITY, BUILDINGS, alt_addresses, address_split, norm, numbers_

REGISTER = "data/helyi_vedelem.json"
ADDRESSES = "data/varos/osm_cimek.csv" if "varos" in sys.argv[1:] else "data/osm_cimek.csv"   # py facts_local_protection.py varos: the addresses of the whole city
RENAMING = "forras/utcanev_atnevezesek.csv"
OUTPUT = "data/tenyek/helyi_vedelem.csv"
SIMILARITY = 0.9


def main():
    atn = {}
    try:
        with open(RENAMING, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                if r.get("regi") and r.get("uj"):
                    atn[norm(r["regi"])] = [norm(x) for x in r["uj"].split("|") if x.strip()]
    except FileNotFoundError:
        pass
    # In city mode we search within the district given in the list (otherwise the houses of a same-named street in another district would also match).
    district = {}
    if CITY:
        with open(BUILDINGS, encoding="utf-8") as f:
            for ft in json.load(f)["features"]:
                pr = ft["properties"]
                if pr.get("kerulet"):
                    district[(pr["osm_tipus"], int(pr["id"]))] = pr["kerulet"]
        if not district:
            raise SystemExit("Az épületeknél nincs kerület. Futtasd: py budapest_pbf.py, majd py city_assembly.py")
    streets_kn = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))   # district (0 = inner-city mode) -> street -> house number -> buildings
    with open(ADDRESSES, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            e = (r["osm_tipus"], int(r["id"]))
            if CITY and e not in district:
                continue
            for sz in numbers_(r["hazszam"]):
                streets_kn[district.get(e, 0)][norm(r["utca"])][sz].append(e)
    streets = streets_kn[0]
    osm_streets = list(streets)

    def candidates(street):
        n = norm(street)
        out = []
        for j in atn.get(n, [n]):
            if j in streets:
                out.append(j)
            else:
                good = difflib.get_close_matches(j, osm_streets, n=1, cutoff=SIMILARITY)
                if good:
                    out.append(good[0])
        return list(dict.fromkeys(out))

    with open(REGISTER, encoding="utf-8") as f:
        entries = json.load(f)["bejegyzesek"]

    done, paired, none_street, none_number, ambiguous, several = set(), 0, Counter(), 0, 0, 0
    for b in entries:
        addresses = []
        u, sz = address_split(b["cim"])
        if u and sz:
            addresses.append((u, sz))
        addresses += alt_addresses(b.get("alt_cimek", []))
        hit, was_street = set(), False
        kn = ROMAN.get(str(b.get("ker", "")).strip().upper(), 0) if CITY else 0
        if CITY and not kn:
            continue
        streets = streets_kn[kn]
        osm_streets = list(streets)
        for u, sz in addresses:
            jl = candidates(u)
            if not jl:
                none_street[u] += 1
                continue
            was_street = True
            hits = []
            for mu in jl:
                t = set()
                for n in sz:
                    t.update(streets[mu].get(n, []))
                if t:
                    hits.append(t)
            if len(hits) > 1:
                ambiguous += 1
            elif hits:
                hit.update(hits[0])
        if not hit:
            none_number += was_street
            continue
        paired += 1
        several += len(hit) > 1
        remark = "54/1993. Főv. Kgy. rendelet melléklete (2001)" + (", közelítő év" if b.get("ev_korul") else "")
        for t, i in hit:
            facts = [("vedettseg_helyi", "helyi védelem"), ("helyi_vedett_hrsz", b["hrsz"]),
                      ("helyi_vedett_megnevezes", b["megnevezes"]), ("tervezo", b["tervezo"]), ("ev", b["ev"])]
            for field, value in facts:
                if value not in (None, ""):
                    done.add((t, i, field, value, "helyi_vedelem", remark))
    write_facts(OUTPUT, sorted(done, key=lambda s: (s[0], s[1], s[2])))
    print(f"Bejegyzések a listán: {len(entries)}")
    print(f"OSM-épülethez párosítva: {paired} (ebből több OSM-épület: {several})")
    print(f"Az utca megvan, de a házszám nem (az OSM-épületen nincs cím): {none_number}")
    if ambiguous:
        print(f"Kétértelmű, kihagyva: {ambiguous}")
    if none_street:
        print(f"Nem található utcanevek: {len(none_street)} db (valószínűleg a területünkön kívül, vagy az OSM-ben nincs címük)")
        for u, n in none_street.most_common(15):
            print(f"  {u}  ({n})")
    print(f"Mentve: {OUTPUT}")


if __name__ == "__main__":
    main()
