"""
tenyek_osm_cimkek.py - further data that can be read out of the OSM tags (without Overpass).

Run (in the project folder, after budapest_pbf.py):
    py tenyek_osm_cimkek.py

Why is Overpass not needed? data/budapest_nyers/*.json.gz contains ALL the OSM tags of every building
(budapest_pbf.py does not filter on tags), so start_date, building:year_built, historic, wikidata... are all in it.

What it reads out:
  1. EXACT years from further tags (year_built, building:year_built, building:year, building:date, construction_year...)
     -> data/tenyek/osm_cimke.csv  (field: ev, source: osm_cimke)
  2. IMPRECISE dates ("1890s", "C19", "early C20", "1890..1910", "1890-1910", "~1890", "before 1900")
     -> data/varos/osm_kozelito.csv  (osm_tipus;id;ev_tol;ev_ig;szoveg;forras) - the estimator takes it as a label if the
        range falls into a single era. The old processor took the first 4-digit number of such a text
        as the exact year ("1890s" -> 1890): these are listed in data/varos/osm_pontatlan_ev.csv.
  3. architect -> tervezo, building:architecture / architecture -> stilus (fact-table rows, source: osm_cimke)
  4. counts of the historic / heritage / wikidata / wikipedia / name tags + the list of protected candidates
     -> data/varos/osm_vedett_jeloltek.csv
  Summary: data/varos/osm_cimkek_jelentes.md
"""
import csv
import gzip
import json
import re
import sys
from collections import Counter
from pathlib import Path

ADAT = Path("data")
NYERS = ADAT / "budapest_nyers"
VAROS = ADAT / "varos"
TENYEK = ADAT / "tenyek"

# the existing processor ("osm" source) already reads these
REGI_EV_CIMKEK = ["start_date", "building:start_date", "construction_date", "year_of_construction"]
# these are the new ones
UJ_EV_CIMKEK = ["year_built", "building:year_built", "building:year", "building:date", "construction_year",
                "built", "date_built", "start_date:year", "construction:date"]
STILUS_CIMKEK = ["building:architecture", "architecture"]
MIN_EV, MAX_EV = 1000, 2030
REGI_REGEX = re.compile(r"(?<!\d)(1[0-9]{3}|20[0-2][0-9])(?!\d)")     # what varos_osszeallitas.evszam uses


def evszam_ervenyes(n):
    return MIN_EV <= n <= MAX_EV


def datum(szoveg):
    """Date text -> (ev_tol, ev_ig, exact). None if it cannot be interpreted.
    exact=True: a single year (or a full date from which the year can be taken)."""
    s = " ".join((szoveg or "").lower().replace("–", "-").replace("—", "-").split())
    if not s:
        return None
    m = re.fullmatch(r"(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?", s)          # 1890 / 1890-05 / 1890-05-12
    if m and evszam_ervenyes(int(m.group(1))) and (m.group(2) is None or 1 <= int(m.group(2)) <= 12):
        n = int(m.group(1))
        return n, n, True
    m = re.fullmatch(r"(\d{3})0'?s|(\d{3})0-es(?: évek)?", s)                 # 1890s, 1890-es
    if m:
        n = int(m.group(1) or m.group(2)) * 10
        if evszam_ervenyes(n):
            return n, n + 9, False
    m = re.fullmatch(r"(?:(early|mid|late|első|második|közepe|vége|eleje)\s+)?(?:c|ca\.?\s*)?(\d{1,2})(?:th|st|nd|rd)?\s*(?:c|century|\. század|\.század)?", s)
    if m and ((m.group(0).startswith(("c", "early", "mid", "late"))) or "century" in s or "század" in s or re.fullmatch(r"\d{1,2}c", s)):
        k = int(m.group(2))
        if 10 <= k <= 21:
            a, b = (k - 1) * 100, k * 100 - 1
            if m.group(1) in ("early", "eleje", "első"):
                b = a + 33
            elif m.group(1) in ("mid", "közepe"):
                a, b = a + 33, a + 66
            elif m.group(1) in ("late", "vége", "második"):
                a = a + 66
            return a, min(b, MAX_EV), False
    m = re.fullmatch(r"(\d{4})\s*(?:\.\.|-|/|;|to|és|\bor\b)\s*(\d{4})", s)  # 1890..1910 / 1890-1910
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if evszam_ervenyes(a) and evszam_ervenyes(b) and a <= b and b - a <= 100:
            return a, b, a == b
    m = re.fullmatch(r"(?:~|c\.?|ca\.?|circa|about|kb\.?|körül)\s*(\d{4})", s)  # ~1890
    if m and evszam_ervenyes(int(m.group(1))):
        n = int(m.group(1))
        return n - 5, n + 5, False
    m = re.fullmatch(r"(?:before|pre|előtt|<)\s*(\d{4})", s)
    if m and evszam_ervenyes(int(m.group(1))):
        n = int(m.group(1))
        return max(MIN_EV, n - 80), n, False
    m = re.fullmatch(r"(?:after|post|után|>)\s*(\d{4})", s)
    if m and evszam_ervenyes(int(m.group(1))):
        n = int(m.group(1))
        return n, min(MAX_EV, n + 60), False
    return None


def epulet_e(c):
    return ("building" in c and c["building"] != "roof") or ("building:part" in c and c["building:part"] != "roof")


def tiszta(x, hossz=100):
    x = " ".join(str(x).replace(";", ", ").split())
    return x if x and len(x) <= hossz and not re.search(r"[\x00-\x1f<>]", x) else None


def main(nyers=NYERS):
    fajlok = sorted(Path(nyers).glob("*.json.gz"))
    if not fajlok:
        sys.exit("Nincs nyers adat a %s mappában. Előbb: py budapest_pbf.py" % nyers)
    lattam = set()
    db = Counter()
    tenyek, kozelito, pontatlan, vedett = [], [], [], []
    ismeretlen = Counter()
    for ut in fajlok:
        with gzip.open(ut, "rt", encoding="utf-8") as f:
            elemek = json.load(f)
        for e in elemek:
            if e.get("type") not in ("way", "relation"):
                continue
            k = (e["type"], e["id"])
            if k in lattam:
                continue
            c = e.get("tags") or {}
            if not epulet_e(c):
                continue
            lattam.add(k)
            db["épület"] += 1
            for kulcs in ("historic", "heritage", "wikidata", "wikipedia", "architect", "name", "start_date",
                          "building:start_date", "construction_date", "year_of_construction"):
                if c.get(kulcs):
                    db[kulcs] += 1
            # --- dates
            regi_ev = None
            for t in REGI_EV_CIMKEK:
                v = c.get(t)
                if not v:
                    continue
                d = datum(v)
                m = REGI_REGEX.search(v)
                if d is None:
                    db["régi címke: nem értelmezhető"] += 1
                    ismeretlen[v] += 1
                elif d[2]:
                    regi_ev = regi_ev or d[0]
                else:
                    db["régi címke: pontatlan"] += 1
                    pontatlan.append([k[0], k[1], t, v, d[0], d[1], m.group(1) if m else ""])
                    kozelito.append([k[0], k[1], d[0], d[1], "%s=%s" % (t, v), "osm_cimke"])
            for t in UJ_EV_CIMKEK:
                v = c.get(t)
                if not v:
                    continue
                db["új címke: " + t] += 1
                d = datum(v)
                if d is None:
                    ismeretlen[v] += 1
                    continue
                if d[2]:
                    if regi_ev is None or regi_ev == d[0]:
                        tenyek.append([k[0], k[1], "ev", d[0], "osm_cimke", t])
                    else:
                        db["új címke eltér a régitől"] += 1
                else:
                    kozelito.append([k[0], k[1], d[0], d[1], "%s=%s" % (t, v), "osm_cimke"])
            # --- architect, style
            ar = c.get("architect")
            if ar and tiszta(ar):
                tenyek.append([k[0], k[1], "tervezo", tiszta(ar), "osm_cimke", "architect"])
            for t in STILUS_CIMKEK:
                if c.get(t) and tiszta(c[t].replace("_", " ")):
                    tenyek.append([k[0], k[1], "stilus", tiszta(c[t].replace("_", " ")), "osm_cimke", t])
                    break
            # --- protection candidates
            if c.get("historic") or c.get("heritage"):
                vedett.append([k[0], k[1], c.get("historic", ""), c.get("heritage", ""), c.get("heritage:operator", ""),
                               c.get("name", ""), c.get("wikidata", ""), c.get("ref:hu:muemlek", "")])

    # filtering out duplicates (one building, one field, one value)
    tenyek = [list(x) for x in dict.fromkeys(tuple(x) for x in tenyek)]
    kozelito = [list(x) for x in dict.fromkeys(tuple(x) for x in kozelito)]

    TENYEK.mkdir(parents=True, exist_ok=True)
    VAROS.mkdir(parents=True, exist_ok=True)
    with open(TENYEK / "osm_cimke.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["osm_tipus", "id", "mezo", "ertek", "forras", "megjegyzes", "lat", "lon"])
        for s in tenyek:
            w.writerow(s + ["", ""])
    for ut, fejlec, sorok in (
            (VAROS / "osm_kozelito.csv", ["osm_tipus", "id", "ev_tol", "ev_ig", "szoveg", "forras"], kozelito),
            (VAROS / "osm_pontatlan_ev.csv", ["osm_tipus", "id", "cimke", "ertek", "ev_tol", "ev_ig", "regi_feldolgozo_eve"], pontatlan),
            (VAROS / "osm_vedett_jeloltek.csv", ["osm_tipus", "id", "historic", "heritage", "heritage_operator", "nev", "wikidata", "muemlek_ref"], vedett)):
        with open(ut, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(fejlec)
            w.writerows(sorok)

    ev_uj = sum(1 for s in tenyek if s[2] == "ev")
    sorok = ["# OSM-címkék jelentése", "",
             "Épület (way/relation): %d" % db["épület"], "",
             "## Címkék darabszáma", ""]
    for kulcs in ("start_date", "building:start_date", "construction_date", "year_of_construction", "architect",
                  "historic", "heritage", "wikidata", "wikipedia", "name"):
        sorok.append("- `%s`: %d" % (kulcs, db[kulcs]))
    sorok += ["", "## Új források", "",
              "- további pontos év (osm_cimke): %d" % ev_uj,
              "- tervező: %d" % sum(1 for s in tenyek if s[2] == "tervezo"),
              "- stílus: %d" % sum(1 for s in tenyek if s[2] == "stilus"),
              "- pontatlan dátum (közelítő tartomány): %d" % len(kozelito),
              "- ebből a régi feldolgozó pontos évnek vette (hibásan): %d" % len(pontatlan),
              "- védett-jelölt (historic/heritage): %d" % len(vedett), "",
              "## Új évcímkék használata", ""]
    for t in UJ_EV_CIMKEK:
        if db["új címke: " + t]:
            sorok.append("- `%s`: %d" % (t, db["új címke: " + t]))
    if db["új címke eltér a régitől"]:
        sorok.append("- az új címke éve eltér a régi címkééhez képest (a régi győz): %d" % db["új címke eltér a régitől"])
    sorok += ["", "## Nem értelmezhető dátumszövegek (leggyakoribbak)", ""]
    for v, n in ismeretlen.most_common(25):
        sorok.append("- `%s`: %d" % (v, n))
    (VAROS / "osm_cimkek_jelentes.md").write_text("\n".join(sorok) + "\n", encoding="utf-8")

    print("épület: %d" % db["épület"])
    for kulcs in ("start_date", "building:start_date", "construction_date", "year_of_construction", "architect",
                  "historic", "heritage", "wikidata", "wikipedia"):
        print("  %-24s %d" % (kulcs, db[kulcs]))
    print("új pontos év: %d | tervező: %d | stílus: %d" % (
        ev_uj, sum(1 for s in tenyek if s[2] == "tervezo"), sum(1 for s in tenyek if s[2] == "stilus")))
    print("pontatlan dátum (tartomány): %d | ebből a régi feldolgozó pontos évnek vette: %d" % (len(kozelito), len(pontatlan)))
    print("védett-jelölt: %d | nem értelmezhető szöveg: %d" % (len(vedett), sum(ismeretlen.values())))
    print("-> data/tenyek/osm_cimke.csv, data/varos/osm_kozelito.csv, osm_pontatlan_ev.csv, osm_vedett_jeloltek.csv, osm_cimkek_jelentes.md")


if __name__ == "__main__":
    main()
