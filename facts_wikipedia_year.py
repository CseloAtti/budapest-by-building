"""Reads the year of construction out of the text of Wikipedia articles -> data/tenyek/wikipedia_szoveg.csv (+ data/varos/wikipedia_kozelito.csv)

For which buildings: those that have their own Wikipedia article (the 'wikipedia' field; the 'wikipedia_zona' inherited from the zone does not count).
We output the year only for those that have no year of construction yet (or whose year has so far come from this source).
For the others we only compare the reading with the existing year: this gives the reliability indicator in the report.

What it reads out (from the article's introductory section, section 0):
  1. the infobox fields referring to construction ('építés ideje', 'építés éve', 'felszentelés' etc.);
  2. if there are none: the introductory sentence that contains 'épült / építették / felszentelték / átadták / megnyitották' (was built / they built / was consecrated / was handed over / was opened) and a year
     (it skips a sentence mentioning rebuilding, renovation, extension, demolition).
For a range ('1893–1896') it takes the first year (the original construction). If there is no year, but the text refers to a century / decade
('a 18. században', '1930-as évek'), it becomes an approximate range by the rules of century.py (data/varos/wikipedia_kozelito.csv).

Safeguards: if an article belongs to more than three buildings (estate, park, institutional article), we skip it; the year must be between 1000 and today.
The source's name: wikipedia_szoveg (in forras/prioritas.json in the 'ev' list, after wikidata_kozeli, before eubucco).

Run:       py facts_wikipedia_year.py varos        (the downloads stay in data/cache/wikipedia_szoveg.json, it does not ask again on a rerun)
Self-check (without network):  py facts_wikipedia_year.py teszt
"""
import csv
import json
import re
import sys
import time
import urllib.parse
from collections import Counter, defaultdict
from pathlib import Path

from common import http_json, write_facts
from century import text_year_range

CITY = len(sys.argv) > 1 and sys.argv[1] == "varos"
BUILDINGS = "data/varos/epuletek_vegleges.geojson" if CITY else "data/belvaros_epuletek_vegleges.geojson"
OUTPUT = "data/tenyek/wikipedia_szoveg.csv"
APPROXIMATE = "data/varos/wikipedia_kozelito.csv"
REPORT = "data/varos/wikipedia_ev_jelentes.md"
CACHE = Path("data/cache/wikipedia_szoveg.json")
API = "https://hu.wikipedia.org/w/api.php"
GROUP = 10
PAUSE_MP = 2
AT_MOST_BUILDING = 3
MA = 2026
SOURCE = "wikipedia_szoveg"

INFOBOX_FIELDS = ["építés ideje", "építés éve", "építési idő", "építés", "építési év", "építés kezdete", "épült",
                 "felszentelés", "felszentelés ideje", "felszentelés éve", "megnyitás", "megnyitás ideje", "átadás", "átadás ideje",
                 "befejezés", "elkészült", "avatás", "építtetés ideje", "alapkőletétel"]
WORDS_BUILT = re.compile(r"\b(épült|épített|építették|építtette|építtették|építette|emelték|emeltette|felszentelték|felépítették|"
                          r"felépült|átadták|megnyitották|elkészült|befejezték|avatták|alapkövét|alapkövét)\b", re.I)
EXCLUDING = re.compile(r"átépít|felújít|bővít|lebont|elpusztul|megsemmisül|restaurál|újjáépít|újjáépül|kibővít|helyreállít|"
                    r"megrongálód|lerombol|leég|kiég|romos|modernizál|átalakít|beépít", re.I)
YEAR = re.compile(r"(?<!\d)(1[0-9]{3}|20[0-2][0-9])(?!\d)(?!-?(?:as|es|os|ös)\b)")


def clean(s):
    """Wikitext -> plain text (without templates, links, markup)."""
    s = re.sub(r"<ref[^>/]*/>", " ", s)
    s = re.sub(r"<ref[^>]*>.*?</ref>", " ", s, flags=re.S)
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.S)
    for _ in range(4):                                   # nested templates from the outside in
        s = re.sub(r"\{\{[^{}]*\}\}", " ", s)
    s = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"\[https?://[^\s\]]+\s*([^\]]*)\]", r"\1", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace("'''", "").replace("''", "").replace("&nbsp;", " ").replace("&ndash;", "–")
    return re.sub(r"\s+", " ", s).strip()


def infobox_values(wt):
    """{field: raw value} from the rows of the infobox template (only the fields referring to construction)."""
    out = {}
    for m in re.finditer(r"^\s*\|\s*([^=|\n]+?)\s*=\s*(.*?)(?=^\s*\||^\s*\}\}|\Z)", wt, flags=re.M | re.S):
        field = m.group(1).strip().lower()
        if field in INFOBOX_FIELDS and field not in out:
            value = clean(m.group(2))
            if value:
                out[field] = value
    return out


def sentences(wt):
    """The plain text of the introductory section split into sentences (skipping the infobox template)."""
    s = clean(wt)
    s = re.sub(r"^=+[^=]+=+", " ", s, flags=re.M)
    return [x.strip() for x in re.split(r"(?<=[a-záéíóöőúüű\)\]])\.\s+(?=[A-ZÁÉÍÓÖŐÚÜŰ])", s) if x.strip()]


def read_out(wt):
    """-> (ev, ev_tol, ev_ig, source, quote) or None. For an exact year ev_tol = ev_ig = ev, for an approximate one ev = None."""
    # 1. infobox
    for field, value in infobox_values(wt).items():
        e = YEAR.findall(value)
        if e:
            return int(e[0]), int(e[0]), int(e[0]), f"infobox: {field}", value[:120]
        r = text_year_range(value)
        if r:
            return None, r[0], r[1], f"infobox: {field}", value[:120]
    # 2. introductory sentences
    clauses = [k for m in sentences(wt)[:12] for k in re.split(r"[;,]\s+|\s+(?:de|majd|ám|azonban)\s+", m)]
    for m in clauses:
        if not WORDS_BUILT.search(m) or EXCLUDING.search(m):
            continue
        e = YEAR.findall(m)
        e = [int(x) for x in e if 1000 <= int(x) <= MA]
        if e:
            return e[0], e[0], e[0], "bevezető mondat", m[:160]
        r = text_year_range(m)
        if r:
            return None, r[0], r[1], "bevezető mondat", m[:160]
    return None


def addresses_list(wikipedia):
    """'hu:Title|hu:Other title|en:Title' -> the Hungarian titles (at most 3)."""
    out = []
    for x in str(wikipedia or "").split("|"):
        x = x.strip()
        if x.startswith("hu:"):
            out.append(x[3:].strip())
        elif ":" not in x[:4] and x:
            out.append(x)
    return out[:3]


def download(addresses):
    """{title: the wikitext of the article's section 0 or None}; it uses the cache."""
    try:
        cache = json.loads(CACHE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        cache = {}
    missing = [c for c in addresses if c not in cache]
    print(f"Cikkek: {len(addresses)}, ebből letöltendő: {len(missing)}")
    for i in range(0, len(missing), GROUP):
        group_ = missing[i:i + GROUP]
        url = API + "?" + urllib.parse.urlencode({
            "action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main", "rvsection": 0,
            "titles": "|".join(group_), "redirects": 1, "format": "json", "formatversion": 2})
        data_ = http_json(url).get("query", {})
        redirect = {x["from"]: x["to"] for x in data_.get("redirects", [])}
        redirect.update({x["from"]: x["to"] for x in data_.get("normalized", []) if x["from"] not in redirect})
        texts = {}
        for p in data_.get("pages", []):
            rev = p.get("revisions") or []
            texts[p.get("title")] = rev[0]["slots"]["main"]["content"] if rev else None
        for c in group_:
            target = c
            for _ in range(3):
                target = redirect.get(target, target)
            cache[c] = texts.get(target)
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        print(f"  letöltve: {min(i + GROUP, len(missing))}/{len(missing)}")
        time.sleep(PAUSE_MP)
    return cache


def main():
    print("Épületek beolvasása...")
    with open(BUILDINGS, encoding="utf-8") as f:
        feats = json.load(f)["features"]
    buildings = []                       # (osm_tipus, id, [titles], year, year_source, name)
    for ft in feats:
        p = ft["properties"]
        if p.get("wikipedia") and not p.get("wikipedia_zona") and not p.get("rom"):
            addresses = addresses_list(p["wikipedia"])
            if addresses:
                buildings.append((p["osm_tipus"], p["id"], addresses, p.get("ev"), p.get("ev_forras"), p.get("nev") or ""))
    del feats
    print(f"Saját Wikipédia-cikkes épület: {len(buildings)}")

    article_buildings = defaultdict(set)
    for t, i, addresses, *_ in buildings:
        for c in addresses:
            article_buildings[c].add((t, i))
    cache = download(sorted(article_buildings))

    read_out_ = {c: (read_out(sz) if sz else None) for c, sz in cache.items() if c in article_buildings}

    rows, approximate = [], []
    stat = Counter()
    match = []                       # compared with the existing year: (difference)
    skipped_many = []
    for t, i, addresses, year, year_source, name_ in buildings:
        hit = None
        for c in addresses:
            if len(article_buildings[c]) > AT_MOST_BUILDING:
                stat["kihagyva: a cikk túl sok épülethez tartozik"] += 1
                if c not in skipped_many:
                    skipped_many.append(c)
                continue
            k = read_out_.get(c)
            if k:
                hit = (c, k)
                break
        if not hit:
            stat["nincs kiolvasható építési idő"] += 1
            continue
        c, (year_k, from_, to, origin_from, quote) = hit
        has_year = year not in (None, "") and year_source != SOURCE
        if has_year:
            if year_k is not None:
                try:
                    match.append(abs(int(year) - year_k))
                except (TypeError, ValueError):
                    pass
            stat["van már évük (csak összevetés)"] += 1
            continue
        remark = f"Wikipédia: {c} ({origin_from}): „{quote}”"
        if year_k is not None and 1000 <= year_k <= MA:
            rows.append((t, i, "ev", year_k, SOURCE, remark))
            stat["új pontos év" + (" (infoboxból)" if origin_from.startswith("infobox") else " (mondatból)")] += 1
        elif year_k is None:
            approximate.append([t, i, from_, to, quote[:80], "Wikipédia-cikk szövege: " + c])
            stat["új közelítő évtartomány"] += 1
    write_facts(OUTPUT, sorted(rows, key=lambda s: (s[0], s[1])))
    Path(APPROXIMATE).parent.mkdir(parents=True, exist_ok=True)
    with open(APPROXIMATE, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["osm_tipus", "id", "ev_tol", "ev_ig", "szoveg", "forras"])
        w.writerows(approximate)

    good2 = sum(1 for x in match if x <= 2)
    row = [f"# Wikipédia-szövegből kiolvasott építési évek\n",
           f"Saját cikkes épület: {len(buildings)}; letöltött cikk: {len(article_buildings)}\n"]
    for k, v in sorted(stat.items()):
        row.append(f"- {k}: {v}\n")
    if match:
        row.append(f"\n**Megbízhatóság:** a már évvel rendelkező épületeknél a kiolvasás {len(match)} esetben ért össze "
                   f"a meglévő évvel, ebből {good2} ({good2 / len(match):.0%}) esett ±2 éven belülre.\n")
    if skipped_many:
        row.append("\nKihagyott cikkek (több mint %d épületre mutatnak): %s\n" % (AT_MOST_BUILDING, "; ".join(skipped_many[:40])))
    Path(REPORT).write_text("".join(row), encoding="utf-8")
    print("".join(row))
    print(f"Mentve: {OUTPUT}, {APPROXIMATE}, {REPORT}")
    print("Következő lépés:  py assemble.py varos  ->  py year_estimate.py varos  ->  py assemble.py varos  ->  py build_tiles.py varos")


def test():
    sample = """{{Templom infobox
| név = Teszt-templom
| építés ideje = 1893–1896<ref>valami</ref>
| felszentelés = [[1897]]
}}
A '''Teszt-templom''' [[Budapest]] [[XIX. kerülete|XIX. kerületében]] áll. A templom 1850-ben épült, de 1944-ben lebombázták.
"""
    assert read_out(sample)[:3] == (1893, 1893, 1893), read_out(sample)
    m2 = """{{Infobox
| név = X
}}
A '''X-kápolna''' Budapesten található. A kápolnát 1759-ben építették, 1810-ben felújították. A XIX. század végén bővítették.
"""
    assert read_out(m2)[:3] == (1759, 1759, 1759), read_out(m2)
    m3 = """{{Infobox
| építés ideje = XIX. század második fele
}}
Valami."""
    r = read_out(m3)
    assert r[0] is None and r[1:3] == (1851, 1900), r
    m4 = """A '''Y-ház''' ma múzeum. A felújítás 1990-ben fejeződött be. Az épület az 1930-as évek elején épült."""
    r = read_out(m4)
    assert r and r[0] is None and r[1:3] == (1930, 1933), r
    m5 = "A '''Z''' egy intézmény. 1860-ban alapították. Az épületet 1902-ben avatták fel."
    assert read_out(m5)[:3] == (1902, 1902, 1902), read_out(m5)
    assert read_out("Semmi évszám itt.") is None
    assert addresses_list("hu:A|en:B|hu:C (Kispest)") == ["A", "C (Kispest)"]
    print("Önellenőrzés rendben.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "teszt":
        test()
    else:
        main()
