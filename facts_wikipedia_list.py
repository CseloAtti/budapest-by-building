"""Matching the street-by-street building lists of the Hungarian Wikipedia with the OSM buildings (by address), and writing out the facts.

Input:    data/wikipedia_lista/sorok.csv      (made by facts_wikipedia_list_download.py: street lists)
          data/wikipedia_lista/sorok_tema.csv (made by facts_wikipedia_topiclist_download.py: schools, hospitals ... - optional)
          data/varos/epuletek.geojson, data/varos/osm_cimek.csv
          forras/wikipedia_lista_kezi.csv     (YOU fill in THIS for the rows of the checking table, see below)
Output:   data/tenyek/wikipedia_lista.csv     - the facts of the rows matched with certainty (assemble.py reads it; source: wikipedia_lista)
          forras/wikipedia_lista_ellenorzes.csv - what was not unambiguous (rewritten on every run, do NOT edit this)

Run:       py facts_wikipedia_list.py varos      (afterwards: zones_refresh.bat)

Rules:
  - By the row's street and house number, an OSM building is matched if the street matches and the house number is among the building's OSM addresses
    (it also understands forms like '12-14', '2/a'). If the street runs through several districts, the page's section title (e.g. 'XIII. kerület') helps.
  - It is unambiguous if a single building (of at least 40 m²) comes into question. Several candidates, or several rows pointing to the same building with different
    data: it writes nothing, it goes into the checking table. It skips the rows of demolished/destroyed buildings.
  - Name: only if the building has no name yet (in OSM or from another source). Style: only if there is none yet. Year of construction and designer: the source
    is at the end in prioritas.json, so it never overwrites another source's data (assemble.py writes the discrepancies into data/varos/utkozesek.csv).
  - The remark always names the source: page and row.

Manual decision: forras/wikipedia_lista_kezi.csv  (utca;sor;osm_azonosito;megjegyzes). The 'osm_azonosito' can be:
  "nem"                     - skip this row
  "way 123|relation 456"    - tie the row to these buildings (several buildings with the '|' sign)
The script only creates the file (with a header), it does not touch its rows. 'utca' and 'sor' can be copied from the checking table.
"""
import collections
import csv
import json
import math
import re
from pathlib import Path

from common import write_facts

ROWS = "data/wikipedia_lista/sorok.csv"
ROWS_TOPIC = "data/wikipedia_lista/sorok_tema.csv"     # the topic lists (schools, hospitals ...), if downloaded
BUILDINGS = "data/varos/epuletek.geojson"
ADDRESSES = "data/varos/osm_cimek.csv"
FACTS = "data/tenyek"
MANUAL = "forras/wikipedia_lista_kezi.csv"
OUTPUT = "data/tenyek/wikipedia_lista.csv"
CHECK = "forras/wikipedia_lista_ellenorzes.csv"
RATIO = 3                   # the largest candidate is this many times larger than the second: that is the main building
MIN_AREA = 40            # m²: a smaller building (pantry, garage) is not regarded as a candidate
KX = 111000 * math.cos(math.radians(47.5))
GENERAL = re.compile(r"^(bérház|lakóház|ház|irodaház|lakó- és irodaház|üzletház|családi ház|villa|társasház|lakóépület|bérpalota)$", re.I)
DEMOLISHED = re.compile(r"elbont|lebont|elpusztult|megsemmis|már nem áll|nem áll fenn|nem létezik", re.I)
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12, "XIII": 13, "XIV": 14,
         "XV": 15, "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20, "XXI": 21, "XXII": 22, "XXIII": 23}


def read_(path_):
    with open(path_, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def street_key(s):
    s = s.lower().replace(".", "").strip()
    s = re.sub(r"\b(utca|u)\b$", "u", s)
    s = re.sub(r"\b(körút|krt)\b$", "krt", s)
    s = re.sub(r"\b(út)\b$", "ut", s)
    return re.sub(r"\s+", " ", s)


def numbers_(h):
    out = set()
    for a, b in re.findall(r"(\d+)\s*[a-zA-Z]?(?:\s*[-–]\s*(\d+))?", h or ""):
        a = int(a)
        out.add(a)
        if b and a < int(b) < a + 60:
            out.update(range(a, int(b) + 1, 2) if (int(b) - a) % 2 == 0 else range(a, int(b) + 1))
    return out


def tokens(h):
    """[(number, suffix)]: '89/c' -> (89, 'c'); '1-5' -> (1,''), (3,''), (5,''); the elements of the range have no suffix."""
    out = []
    for a, sa, b in re.findall(r"(\d+)\s*(?:/?\s*([a-zA-Z])\b)?(?:\s*[-–]\s*(\d+))?", h or ""):
        a = int(a)
        if b and a < int(b) < a + 60:
            out += [(n, "") for n in (range(a, int(b) + 1, 2) if (int(b) - a) % 2 == 0 else range(a, int(b) + 1))]
        else:
            out.append((a, sa.lower()))
            if b:
                out.append((int(b), ""))
    return list(dict.fromkeys(out))


def area(g):
    r = g[0]
    return abs(sum(r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1] for i in range(len(r) - 1))) / 2 * KX * 111000


def osm_id(s):
    out = []
    for part in re.split(r"[|;,\n]+", s or ""):
        m = re.search(r"(?:(way|relation|node)[/ :]*)?(\d{3,})", part.strip(), flags=re.I)
        if m:
            out.append(((m.group(1) or "way").lower(), int(m.group(2))))
    return out


def year_value(s):
    if re.search(r"évek|század|\bvagy\b", s or ""):          # '1880-as évek' (the 1880s), '19. század' (19th century): not an exact year
        return None
    m = re.search(r"\b(1[0-9]{3}|20[0-2][0-9])\b", s or "")
    return int(m.group(1)) if m else None


def main():
    for path_ in (ROWS, BUILDINGS, ADDRESSES):
        if not Path(path_).exists():
            raise SystemExit(f"Hiányzik: {path_}" + (" - előbb futtasd: py facts_wikipedia_list_download.py" if path_ == ROWS else ""))
    rows = read_(ROWS) + (read_(ROWS_TOPIC) if Path(ROWS_TOPIC).exists() else [])
    # buildings: area, district, OSM name; addresses
    ep = {}
    for f in json.load(open(BUILDINGS, encoding="utf-8"))["features"]:
        p = f["properties"]
        if p.get("tipus") == "roof":
            continue
        k = (p["osm_tipus"], int(p["id"]))
        area_ = area(f["geometry"]["coordinates"])
        if k not in ep or area_ > ep[k]["ter"]:
            ep[k] = {"ter": area_, "ker": p.get("kerulet"), "nev": p.get("nev")}
    address = collections.defaultdict(list)
    for r in read_(ADDRESSES):
        address[(r["osm_tipus"], int(r["id"]))].append((street_key(r["utca"]), numbers_(r["hazszam"])))
    street_number = collections.defaultdict(dict)          # (street key, number) -> {building key: {suffixes}}
    osm_addresses_text = collections.defaultdict(set)
    for r_ in read_(ADDRESSES):
        k = (r_["osm_tipus"], int(r_["id"]))
        if k not in ep:
            continue
        u = street_key(r_["utca"])
        osm_addresses_text[k].add((u, r_["hazszam"].strip().lower()))
        for n, suf in tokens(r_["hazszam"]):
            street_number[(u, n)].setdefault(k, set()).add(suf)
    # name / style already present from another source
    has_name, has_style = set(), set()
    for path_ in sorted(Path(FACTS).glob("*.csv")):
        if path_.name == Path(OUTPUT).name:
            continue
        for r in read_(path_):
            k = (r.get("osm_tipus") or "way", int(r["id"])) if (r.get("id") or "").isdigit() else None
            if k and (r.get("ertek") or "").strip():
                if r["mezo"] == "nev":
                    has_name.add(k)
                elif r["mezo"] == "stilus":
                    has_style.add(k)
    # manual decisions
    manual = {}
    if Path(MANUAL).exists():
        for r in read_(MANUAL):
            if (r.get("utca") or "").strip() and (r.get("sor") or "").strip():
                manual[(r["utca"].strip(), r["sor"].strip())] = (r.get("osm_azonosito") or "").strip()
    else:
        Path(MANUAL).parent.mkdir(parents=True, exist_ok=True)
        with open(MANUAL, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f, delimiter=";").writerow(["utca", "sor", "osm_azonosito", "megjegyzes"])

    def candidates(uk, n, suf):
        """Buildings bearing the (street, house number[, suffix]) address and of at least MIN_TERULET m²; the suffix (89/c) makes it more precise."""
        everything = [k for k in street_number.get((uk, n), {}) if ep[k]["ter"] >= MIN_AREA]
        if suf:
            exact = [k for k in everything if suf in street_number[(uk, n)][k]]
        else:
            exact = [k for k in everything if "" in street_number[(uk, n)][k]]
        return exact or everything

    def keywords(sz):
        return {w for w in re.findall(r"[a-záéíóöőúüű]{5,}", sz.lower()) if w not in ("bérház", "bérpalota", "lakóház", "épület", "lakóépület", "irodaház")}

    # pass 1: in which districts the street runs (based on the unambiguous hits)
    round_ = collections.defaultdict(collections.Counter)
    for r in rows:
        for n, suf in tokens(r["szam"]):
            j = candidates(street_key(r["utca"]), n, suf)
            if len(j) == 1:
                round_[r["utca"]][ep[j[0]]["ker"]] += 1
    fo_district = {u: {k for k, v in c.items() if v >= max(3, 0.1 * sum(c.values()))} for u, c in round_.items()}

    even = []                     # (row, [building keys])
    check, stat = [], collections.Counter()
    for r in rows:
        sz = r["szam"]
        base = {"lap": r["lap"], "utca": r["utca"], "sor": r["sor"], "szam": sz, "nev": r["nev"], "ev": r["ev"], "tervezo": r["tervezo"],
                "szakasz": r["szakasz"], "megjegyzes_wikipedia": r["megjegyzes"]}
        if DEMOLISHED.search(" ".join((r["nev"], r["megjegyzes"], r["ev"]))):
            stat["elbontott: kihagyva"] += 1
            continue
        decide = manual.get((r["utca"], r["sor"]), "")
        if decide.lower() == "nem":
            stat["kézi: nem"] += 1
            continue
        if decide and osm_id(decide):
            even.append((r, osm_id(decide)))
            stat["kézi: megadott épület"] += 1
            continue
        toks = tokens(sz)
        if not toks:
            stat["nincs használható házszám"] += 1
            continue
        uk = street_key(r["utca"])
        district = int(r["kerulet"]) if (r["kerulet"] or "").isdigit() else None
        m = re.search(r"\b([IVX]+)\.\s*kerület", r["szakasz"] or "")
        district = district or (ROMAN.get(m.group(1)) if m else None)
        found, missing, several = [], [], []
        kw = keywords(r["nev"])
        for n, suf in toks:
            sign = candidates(uk, n, suf)
            if district:
                sign = [k for k in sign if ep[k]["ker"] == district] or sign
            fk = fo_district.get(r["utca"])
            if fk and len(sign) > 1:
                sign = [k for k in sign if ep[k]["ker"] in fk] or sign
            if len(sign) > 1:                                  # match by name: the OSM name or type has a word in common
                named = [k for k in sign if kw and keywords(ep[k]["nev"] or "") & kw]
                if len(named) == 1:
                    sign = named
            if len(sign) > 1:
                sign.sort(key=lambda k: -ep[k]["ter"])
                addresses_ = [frozenset(osm_addresses_text[k]) for k in sign]
                if ep[sign[0]]["ter"] >= RATIO * ep[sign[1]]["ter"]:          # the largest is the main building, the rest are outbuildings
                    sign = sign[:1]
                elif len(set(addresses_)) == 1 and ep[sign[0]]["ter"] <= RATIO * ep[sign[-1]]["ter"] and len({ep[k]["ker"] for k in sign}) == 1:
                    pass                                          # sibling buildings with the same title and similar size: all of them get it
                else:
                    several.append((n, sign))
                    continue
            if len(sign) >= 1:
                found += sign
            else:
                missing.append(n)
        found = list(dict.fromkeys(found))
        if found and not several:
            even.append((r, found))
            stat["párosítva" if not missing else "párosítva (néhány házszám hiányzik az OSM-ben)"] += 1
        else:
            if several:
                category = "több jelölt (több épület viseli ezt a címet)"
                suggestion = " | ".join(f"{t} {i}" for _, sign in several[:2] for t, i in sign[:3])
            else:
                category = "nincs OSM-épület ezzel a címmel"
                suggestion = ""
            stat[category[:20]] += 1
            check.append({**base, "kategoria": category, "javasolt_osm": suggestion, "hianyzo_hazszam": " ".join(map(str, missing))})

    # rows pointing to the same building: if they carry different data, we write nothing
    building_rows = collections.defaultdict(list)
    for r, ks in even:
        for k in ks:
            building_rows[k].append(r)
    done, checked_rows = set(), set()
    for k, list_ in building_rows.items():
        years = {year_value(x["ev"]) for x in list_ if year_value(x["ev"])}
        names = {x["nev"] for x in list_ if x["nev"]}
        if len(list_) > 1 and years and max(years) - min(years) > 2:      # a difference in names is no obstacle (a corner house in the lists of two streets): there we write no name
            for x in list_:
                if (x["utca"], x["sor"]) not in checked_rows:
                    checked_rows.add((x["utca"], x["sor"]))
                    check.append({"lap": x["lap"], "utca": x["utca"], "sor": x["sor"], "szam": x["szam"], "nev": x["nev"], "ev": x["ev"],
                                       "tervezo": x["tervezo"], "szakasz": x["szakasz"], "megjegyzes_wikipedia": x["megjegyzes"],
                                       "kategoria": "több sor mutat ugyanarra az épületre, eltérő adattal",
                                       "javasolt_osm": f"{k[0]} {k[1]}", "hianyzo_hazszam": ""})
            stat["több sor, eltérő adat"] += 1
    def matching(k, field_fn):
        vals = {field_fn(x) for x in building_rows[k]}
        vals.discard(None)
        vals.discard("")
        return vals

    for r, ks in even:
        if (r["utca"], r["sor"]) in checked_rows:
            continue
        remark = f"hu.wikipedia.org {r['lap']}, {r['sor']}. sor ({r['utca']} {r['szam']})"
        year = year_value(r["ev"])
        designer = re.sub(r"\s+", " ", r["tervezo"]).strip()
        if designer.lower() in ("", "?", "ismeretlen", "-", "–", "nem ismert", "n. a.", "n.a.") or "?" in designer or re.search(r"\bvagy\b", designer):
            designer = ""
        for k in ks:
            if len(building_rows[k]) > 1:      # several lists mention it: only the consistent data goes out
                if year and len(matching(k, lambda x: year_value(x["ev"]))) > 1:
                    year = None
                if designer and len(matching(k, lambda x: re.sub(r"\s+", " ", x["tervezo"]).strip())) > 1:
                    designer = ""
                name_ok = len(matching(k, lambda x: x["nev"].strip())) <= 1
            else:
                name_ok = True
            if year:
                done.add((k[0], k[1], "ev", year, "wikipedia_lista", remark))
            if designer:
                done.add((k[0], k[1], "tervezo", designer, "wikipedia_lista", remark))
            if name_ok and r["nev"] and not GENERAL.match(r["nev"].strip()) and r["nev"].strip()[0].isupper() and k not in has_name and not ep[k]["nev"]:
                done.add((k[0], k[1], "nev", r["nev"].strip(), "wikipedia_lista", remark))
            if r["stilus"] and k not in has_style:
                done.add((k[0], k[1], "stilus", r["stilus"].strip(), "wikipedia_lista", remark))
    write_facts(OUTPUT, sorted(done, key=lambda s: (s[0], s[1], s[2], str(s[3]))))

    fields = ["kategoria", "lap", "utca", "sor", "szam", "nev", "ev", "tervezo", "szakasz", "megjegyzes_wikipedia", "javasolt_osm", "hianyzo_hazszam"]
    check.sort(key=lambda x: (x["kategoria"], x["utca"], int(x["sor"]) if str(x["sor"]).isdigit() else 0))
    with open(CHECK, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows(check)
    print(f"Wikipedia-sorok: {len(rows)}")
    for k, v in sorted(stat.items()):
        print(f"  {k}: {v}")
    print(f"Tények: {len(done)} sor -> {OUTPUT} ({len(building_rows)} épület)")
    print(f"Ellenőrizendő: {len(check)} sor -> {CHECK}")


if __name__ == "__main__":
    main()
