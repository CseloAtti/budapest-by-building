"""
facts_bp100.py - the houses of Budapest100 (budapest100.hu) -> data/tenyek/budapest100.csv

Input:    data/bp100/budapest100_teljes.csv   (clean_address, zip_code, building_name, building_type, built_year, era, year_source, url)
          data/varos/osm_cimek.csv            (osm_tipus;id;utca;hazszam)
          data/varos/epuletek_vegleges.geojson (only for the district: same-named streets in different districts)
          forras/utcanev_atnevezesek.csv      (old -> current street names)
Output:   data/tenyek/budapest100.csv         ('ev' facts, source: budapest100)
          data/bp100_nem_parositott.csv       what could not be tied to a building, and why

Run:        py facts_bp100.py      (afterwards: py assemble.py varos)

Matching: street name + house number against the OSM addresses; the district comes from the postcode (1052 -> V., 1196 -> XIX.), and only
the building there can be considered. Without a postcode we match only if the address exists in a single district in the whole city.
As year we take only the years extracted from the "exact expression" and the "introduction of the text"; the "year mentioned in the text" is weaker
(it may be a renovation), we leave it out, and the report counts it. A house-number range ("15-23") is taken as a single building complex:
the numbers of the same parity in the range also come into question (within a range at most 12 wide).
We take over only facts (year); not the text. The address of the house's page ('budapest100_url') and - if facts_bp100_images.py has already run - the
image's address ('budapest100_kep') are also recorded; the image is not copied, the card loads it from budapest100.hu, with a source link.
"""
import csv
import difflib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from common import write_facts

INPUT = Path("data/bp100/budapest100_teljes.csv")
ADDRESSES = Path("data/varos/osm_cimek.csv")
BUILDINGS = Path("data/varos/epuletek_vegleges.geojson")
RENAMING = Path("forras/utcanev_atnevezesek.csv")
OUTPUT = "data/tenyek/budapest100.csv"
NOT_PAIRED = Path("data/bp100_nem_parositott.csv")
IMAGES = Path("data/bp100/kepek.json")        # facts_bp100_images.py: {page_url: image_url}
SIMILARITY = 0.9
GOOD_SOURCE = ("Szövegből (pontos kifejezés)", "Szöveg bevezetőjéből")
MAX_BUILDING = 6
MAX_RANGE = 12


def norm(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\bu\.", "utca", s)
    s = re.sub(r"\bkrt\.", "korut", s)
    s = re.sub(r"\bkoerut\b", "korut", s)
    s = re.sub(r"\butca\b", "utca", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(s.split())


def house_numbers(text_):
    """'11-13' -> {11,12,13 of the same parity: 11, 13}; '15/A, B' -> {15}; '4;6' -> {4, 6}"""
    out = set()
    for a, b in re.findall(r"(\d+)\s*(?:[-–]\s*(\d+))?", text_ or ""):
        a = int(a)
        out.add(a)
        if b:
            b = int(b)
            out.add(b)
            if a < b <= a + MAX_RANGE and (b - a) % 2 == 0:
                out.update(range(a, b + 1, 2))
    return out


def address_split(address):
    """'Károly körút 22.' -> ('Károly körút', {22}); 'Október 6. utca 3.' handled."""
    start_ = 0
    h = re.search(r"\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+ \d+\.(?=\s+(?:utca|tér|út)\b)", address)
    if h:
        start_ = h.end()
    m = re.search(r"\d", address[start_:])
    if not m:
        return None, set()
    p = start_ + m.start()
    return address[:p].strip(" ,"), house_numbers(address[p:])


def district_from_postcode(zip_code):
    try:
        z = int(float(zip_code))
    except (TypeError, ValueError):
        return None
    if 1011 <= z <= 1239:
        k = (z // 10) % 100
        return k if 1 <= k <= 23 else None
    return None


def district_number(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        pass
    roman = {"I": 1, "V": 5, "X": 10}
    s = str(x or "").strip().rstrip(".").upper()
    if s and all(c in roman for c in s):
        t = 0
        for c, n in zip(s, s[1:] + " "):
            v = roman[c]
            t += -v if n in roman and roman[n] > v else v
        return t
    return None


def district_map():
    """(osm_tipus, id) -> district number, from the building file."""
    if not BUILDINGS.exists():
        return {}
    with open(BUILDINGS, encoding="utf-8") as f:
        g = json.load(f)
    out = {}
    for ft in g["features"]:
        p = ft["properties"]
        k = district_number(p.get("kerulet"))
        if k:
            out[(p.get("osm_tipus") or "way", int(p["id"]))] = k
    return out


def main():
    if not INPUT.exists():
        sys.exit("Nincs " + str(INPUT))
    atn = {}
    if RENAMING.exists():
        for r in csv.DictReader(open(RENAMING, encoding="utf-8-sig", newline=""), delimiter=";"):
            if r.get("regi") and r.get("uj"):
                atn[norm(r["regi"])] = [norm(x) for x in r["uj"].split("|") if x.strip()]
    district_ = district_map()
    print("Épület a kerület-térképen:", len(district_))
    streets = defaultdict(lambda: defaultdict(list))
    for r in csv.DictReader(open(ADDRESSES, encoding="utf-8-sig", newline=""), delimiter=";"):
        for sz in house_numbers(r["hazszam"]):
            streets[norm(r["utca"])][sz].append((r["osm_tipus"], int(r["id"])))
    osm_streets = list(streets)

    def street_candidates(street):
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

    rows = list(csv.DictReader(open(INPUT, encoding="utf-8-sig", newline="")))
    stat = Counter()
    images = json.load(open(IMAGES, encoding="utf-8")) if IMAGES.exists() else {}
    done, left_out = set(), []
    for r in rows:
        year = (r.get("built_year") or "").strip()
        # we match even without a year (because of the link), but take a year only from a reliable source
        if not year:
            stat["nincs év a forrásban"] += 1
            year = None
        elif r.get("year_source") not in GOOD_SOURCE:
            stat["gyenge évforrás (évet nem veszünk át)"] += 1
            year = None
        else:
            try:
                year = int(float(year))
            except ValueError:
                stat["hibás év"] += 1
                year = None
            else:
                if not 1000 <= year <= 2030:
                    stat["hihetetlen év"] += 1
                    year = None
        address = (r.get("clean_address") or "").strip()
        u, sz = address_split(address)
        if not u or not sz:
            left_out.append([address, year, "nincs házszám"])
            stat["nincs házszám a címben"] += 1
            continue
        candidates = street_candidates(u)
        if not candidates:
            left_out.append([address, year, "ismeretlen utcanév"])
            stat["ismeretlen utcanév"] += 1
            continue
        hit = set()
        for mu in candidates:
            for n in sz:
                hit.update(streets[mu].get(n, []))
        if not hit:
            left_out.append([address, year, "az utcán nincs ilyen házszámú OSM-épület"])
            stat["nincs ilyen házszám"] += 1
            continue
        district = district_from_postcode(r.get("zip_code"))
        if district_:
            if district:
                hit = {t for t in hit if district_.get(t) == district}
                if not hit:
                    left_out.append([address, year, "a megadott kerületben (%s.) nincs ilyen című épület" % district])
                    stat["nincs ilyen című épület a kerületben"] += 1
                    continue
            else:
                round_ = {district_.get(t) for t in hit}
                if len(round_) > 1:
                    left_out.append([address, year, "irányítószám nélkül több kerületben is van ilyen cím"])
                    stat["kétértelmű (nincs irányítószám)"] += 1
                    continue
        if len(hit) > MAX_BUILDING:
            left_out.append([address, year, "túl sok (%d) lehetséges épület" % len(hit)])
            stat["túl sok jelölt"] += 1
            continue
        stat["párosítva"] += 1
        stat["párosított OSM-épület"] += len(hit)
        remark = f"Budapest100: {address}" + (f" ({len(hit)} OSM-épület)" if len(hit) > 1 else "") + f" {r.get('url', '')}"
        url = (r.get("url") or "").strip()
        if not re.fullmatch(r"https://budapest100\.hu/house/[A-Za-z0-9_%\-]+/?", url):
            url = ""
        for t, i in hit:
            if year:
                done.add((t, i, "ev", year, "budapest100", remark.strip()))
            if url:
                done.add((t, i, "budapest100_url", url, "budapest100", remark.strip()))
                image = images.get(url) or images.get(url.rstrip("/") + "/") or images.get(url.rstrip("/")) or {}
                if isinstance(image, str):
                    image = {"kep": image, "foto": ""}
                if image.get("kep"):
                    done.add((t, i, "budapest100_kep", image["kep"], "budapest100", remark.strip()))
                    if image.get("foto"):
                        done.add((t, i, "budapest100_foto", image["foto"], "budapest100", remark.strip()))
    write_facts(OUTPUT, sorted(done, key=lambda s: (s[0], s[1], s[2])))
    with open(NOT_PAIRED, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["cim", "ev", "miert"])
        w.writerows(left_out)
    print(f"Bejegyzés: {len(rows)}")
    for k, v in stat.most_common():
        print(f"  {k}: {v}")
    print(f"Tények: {len(done)} sor -> {OUTPUT}; nem párosított: {NOT_PAIRED}")


if __name__ == "__main__":
    main()
