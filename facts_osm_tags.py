"""
facts_osm_tags.py - further data that can be read out of the OSM tags (without Overpass).

Run (in the project folder, after budapest_pbf.py):
    py facts_osm_tags.py

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

DATA = Path("data")
RAW = DATA / "budapest_nyers"
CITY = DATA / "varos"
FACTS = DATA / "tenyek"

# the existing processor ("osm" source) already reads these
OLD_YEAR_LABELS = ["start_date", "building:start_date", "construction_date", "year_of_construction"]
# these are the new ones
NEW_YEAR_LABELS = ["year_built", "building:year_built", "building:year", "building:date", "construction_year",
                "built", "date_built", "start_date:year", "construction:date"]
STYLE_LABELS = ["building:architecture", "architecture"]
MIN_YEAR, MAX_YEAR = 1000, 2030
OLD_REGEX = re.compile(r"(?<!\d)(1[0-9]{3}|20[0-2][0-9])(?!\d)")     # what city_assembly.evszam uses


def year_valid(n):
    return MIN_YEAR <= n <= MAX_YEAR


def date(text_):
    """Date text -> (ev_tol, ev_ig, exact). None if it cannot be interpreted.
    exact=True: a single year (or a full date from which the year can be taken)."""
    s = " ".join((text_ or "").lower().replace("–", "-").replace("—", "-").split())
    if not s:
        return None
    m = re.fullmatch(r"(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?", s)          # 1890 / 1890-05 / 1890-05-12
    if m and year_valid(int(m.group(1))) and (m.group(2) is None or 1 <= int(m.group(2)) <= 12):
        n = int(m.group(1))
        return n, n, True
    m = re.fullmatch(r"(\d{3})0'?s|(\d{3})0-es(?: évek)?", s)                 # 1890s, 1890-es
    if m:
        n = int(m.group(1) or m.group(2)) * 10
        if year_valid(n):
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
            return a, min(b, MAX_YEAR), False
    m = re.fullmatch(r"(\d{4})\s*(?:\.\.|-|/|;|to|és|\bor\b)\s*(\d{4})", s)  # 1890..1910 / 1890-1910
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if year_valid(a) and year_valid(b) and a <= b and b - a <= 100:
            return a, b, a == b
    m = re.fullmatch(r"(?:~|c\.?|ca\.?|circa|about|kb\.?|körül)\s*(\d{4})", s)  # ~1890
    if m and year_valid(int(m.group(1))):
        n = int(m.group(1))
        return n - 5, n + 5, False
    m = re.fullmatch(r"(?:before|pre|előtt|<)\s*(\d{4})", s)
    if m and year_valid(int(m.group(1))):
        n = int(m.group(1))
        return max(MIN_YEAR, n - 80), n, False
    m = re.fullmatch(r"(?:after|post|után|>)\s*(\d{4})", s)
    if m and year_valid(int(m.group(1))):
        n = int(m.group(1))
        return n, min(MAX_YEAR, n + 60), False
    return None


def building_e(c):
    return ("building" in c and c["building"] != "roof") or ("building:part" in c and c["building:part"] != "roof")


def clean(x, length=100):
    x = " ".join(str(x).replace(";", ", ").split())
    return x if x and len(x) <= length and not re.search(r"[\x00-\x1f<>]", x) else None


def main(raw=RAW):
    files = sorted(Path(raw).glob("*.json.gz"))
    if not files:
        sys.exit("Nincs nyers adat a %s mappában. Előbb: py budapest_pbf.py" % raw)
    seen = set()
    count_ = Counter()
    facts, approximate, imprecise, protected = [], [], [], []
    unknown = Counter()
    for path_ in files:
        with gzip.open(path_, "rt", encoding="utf-8") as f:
            elements = json.load(f)
        for e in elements:
            if e.get("type") not in ("way", "relation"):
                continue
            k = (e["type"], e["id"])
            if k in seen:
                continue
            c = e.get("tags") or {}
            if not building_e(c):
                continue
            seen.add(k)
            count_["épület"] += 1
            for building_key in ("historic", "heritage", "wikidata", "wikipedia", "architect", "name", "start_date",
                          "building:start_date", "construction_date", "year_of_construction"):
                if c.get(building_key):
                    count_[building_key] += 1
            # --- dates
            old_year = None
            for t in OLD_YEAR_LABELS:
                v = c.get(t)
                if not v:
                    continue
                d = date(v)
                m = OLD_REGEX.search(v)
                if d is None:
                    count_["régi címke: nem értelmezhető"] += 1
                    unknown[v] += 1
                elif d[2]:
                    old_year = old_year or d[0]
                else:
                    count_["régi címke: pontatlan"] += 1
                    imprecise.append([k[0], k[1], t, v, d[0], d[1], m.group(1) if m else ""])
                    approximate.append([k[0], k[1], d[0], d[1], "%s=%s" % (t, v), "osm_cimke"])
            for t in NEW_YEAR_LABELS:
                v = c.get(t)
                if not v:
                    continue
                count_["új címke: " + t] += 1
                d = date(v)
                if d is None:
                    unknown[v] += 1
                    continue
                if d[2]:
                    if old_year is None or old_year == d[0]:
                        facts.append([k[0], k[1], "ev", d[0], "osm_cimke", t])
                    else:
                        count_["új címke eltér a régitől"] += 1
                else:
                    approximate.append([k[0], k[1], d[0], d[1], "%s=%s" % (t, v), "osm_cimke"])
            # --- architect, style
            ar = c.get("architect")
            if ar and clean(ar):
                facts.append([k[0], k[1], "tervezo", clean(ar), "osm_cimke", "architect"])
            for t in STYLE_LABELS:
                if c.get(t) and clean(c[t].replace("_", " ")):
                    facts.append([k[0], k[1], "stilus", clean(c[t].replace("_", " ")), "osm_cimke", t])
                    break
            # --- protection candidates
            if c.get("historic") or c.get("heritage"):
                protected.append([k[0], k[1], c.get("historic", ""), c.get("heritage", ""), c.get("heritage:operator", ""),
                               c.get("name", ""), c.get("wikidata", ""), c.get("ref:hu:muemlek", "")])

    # filtering out duplicates (one building, one field, one value)
    facts = [list(x) for x in dict.fromkeys(tuple(x) for x in facts)]
    approximate = [list(x) for x in dict.fromkeys(tuple(x) for x in approximate)]

    FACTS.mkdir(parents=True, exist_ok=True)
    CITY.mkdir(parents=True, exist_ok=True)
    with open(FACTS / "osm_cimke.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["osm_tipus", "id", "mezo", "ertek", "forras", "megjegyzes", "lat", "lon"])
        for s in facts:
            w.writerow(s + ["", ""])
    for path_, header, rows in (
            (CITY / "osm_kozelito.csv", ["osm_tipus", "id", "ev_tol", "ev_ig", "szoveg", "forras"], approximate),
            (CITY / "osm_pontatlan_ev.csv", ["osm_tipus", "id", "cimke", "ertek", "ev_tol", "ev_ig", "regi_feldolgozo_eve"], imprecise),
            (CITY / "osm_vedett_jeloltek.csv", ["osm_tipus", "id", "historic", "heritage", "heritage_operator", "nev", "wikidata", "muemlek_ref"], protected)):
        with open(path_, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(header)
            w.writerows(rows)

    year_new = sum(1 for s in facts if s[2] == "ev")
    rows = ["# OSM-címkék jelentése", "",
             "Épület (way/relation): %d" % count_["épület"], "",
             "## Címkék darabszáma", ""]
    for building_key in ("start_date", "building:start_date", "construction_date", "year_of_construction", "architect",
                  "historic", "heritage", "wikidata", "wikipedia", "name"):
        rows.append("- `%s`: %d" % (building_key, count_[building_key]))
    rows += ["", "## Új források", "",
              "- további pontos év (osm_cimke): %d" % year_new,
              "- tervező: %d" % sum(1 for s in facts if s[2] == "tervezo"),
              "- stílus: %d" % sum(1 for s in facts if s[2] == "stilus"),
              "- pontatlan dátum (közelítő tartomány): %d" % len(approximate),
              "- ebből a régi feldolgozó pontos évnek vette (hibásan): %d" % len(imprecise),
              "- védett-jelölt (historic/heritage): %d" % len(protected), "",
              "## Új évcímkék használata", ""]
    for t in NEW_YEAR_LABELS:
        if count_["új címke: " + t]:
            rows.append("- `%s`: %d" % (t, count_["új címke: " + t]))
    if count_["új címke eltér a régitől"]:
        rows.append("- az új címke éve eltér a régi címkééhez képest (a régi győz): %d" % count_["új címke eltér a régitől"])
    rows += ["", "## Nem értelmezhető dátumszövegek (leggyakoribbak)", ""]
    for v, n in unknown.most_common(25):
        rows.append("- `%s`: %d" % (v, n))
    (CITY / "osm_cimkek_jelentes.md").write_text("\n".join(rows) + "\n", encoding="utf-8")

    print("épület: %d" % count_["épület"])
    for building_key in ("start_date", "building:start_date", "construction_date", "year_of_construction", "architect",
                  "historic", "heritage", "wikidata", "wikipedia"):
        print("  %-24s %d" % (building_key, count_[building_key]))
    print("új pontos év: %d | tervező: %d | stílus: %d" % (
        year_new, sum(1 for s in facts if s[2] == "tervezo"), sum(1 for s in facts if s[2] == "stilus")))
    print("pontatlan dátum (tartomány): %d | ebből a régi feldolgozó pontos évnek vette: %d" % (len(approximate), len(imprecise)))
    print("védett-jelölt: %d | nem értelmezhető szöveg: %d" % (len(protected), sum(unknown.values())))
    print("-> data/tenyek/osm_cimke.csv, data/varos/osm_kozelito.csv, osm_pontatlan_ev.csv, osm_vedett_jeloltek.csv, osm_cimkek_jelentes.md")


if __name__ == "__main__":
    main()
