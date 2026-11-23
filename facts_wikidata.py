"""Wikidata -> fact table (data/tenyek/wikidata.csv).

We query the buildings that have a `wikidata` tag in OSM.
Data taken over: year of construction (P571), architect (P84), architectural style (P149), Wikidata name.
The content of Wikidata is CC0 (free to use).

Attention: sometimes the wikidata tag on an OSM building points not to the building, but to the
institution (then the 'year of founding' is the institution's). Therefore for the year Wikidata is a
weaker source than OSM and Lechner; the discrepancies are shown by data/utkozesek.csv.
"""
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from common import http_json, building_key, write_facts

import sys
CITY = len(sys.argv) > 1 and sys.argv[1] == "varos"      # py facts_wikidata.py varos  -> the whole city
OSM = "data/varos/epuletek_vegleges.geojson" if CITY else "data/belvaros_epuletek.geojson"
OUTPUT = "data/tenyek/wikidata.csv"
APPROXIMATE = "data/varos/wikidata_kozelito.csv"
CACHE = Path("data/cache")
API = "https://www.wikidata.org/w/api.php"
CLIENT = "budapest-by-building/1.0 (tanulasi projekt)"
BATCH = 50
PAUSE_MP = 2


def fetch(identifiers, props):
    """Fetching a batch of Wikidata elements (with a disk cache)."""
    name_ = "wd_" + hashlib.sha1((props + "|" + "|".join(identifiers)).encode()).hexdigest()[:16] + ".json"
    path_ = CACHE / name_
    if path_.exists():
        return json.loads(path_.read_text(encoding="utf-8"))
    params = {"action": "wbgetentities", "ids": "|".join(identifiers), "props": props,
              "languages": "hu|en", "format": "json"}
    if "sitelinks" in props:
        params["sitefilter"] = "huwiki|enwiki"
    url = API + "?" + urllib.parse.urlencode(params)
    data_ = http_json(url)
    CACHE.mkdir(parents=True, exist_ok=True)
    path_.write_text(json.dumps(data_, ensure_ascii=False), encoding="utf-8")
    time.sleep(PAUSE_MP)
    return data_


def wikipedia_article(entity):
    """The Wikipedia article, if there is one: 'hu:Title' (preferred) or 'en:Title'."""
    s = (entity or {}).get("sitelinks", {})
    for key_, language in (("huwiki", "hu"), ("enwiki", "en")):
        if key_ in s and s[key_].get("title"):
            return f"{language}:{s[key_]['title']}"
    return None


def in_batches(list_, n):
    for i in range(0, len(list_), n):
        yield list_[i:i + n]


def label(entity):
    c = (entity or {}).get("labels", {})
    for language in ("hu", "en"):
        if language in c:
            return c[language]["value"]
    return None


def elements_id(claims, prop):
    """The identifiers (Q...) of the value items of the given property."""
    out = []
    for c in claims.get(prop, []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(v, dict) and v.get("id"):
            out.append(v["id"])
    return out


def year_a_from_claims(claims):
    """Year of construction/founding, only if precise at least to the year (precision >= 9)."""
    for c in claims.get("P571", []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(v, dict) and v.get("precision", 0) >= 9:
            m = re.match(r"[+-](\d{4})-", v.get("time", ""))
            if m:
                return int(m.group(1))
    return None


def year_range(claims):
    """A P571 of decade (precision 8) or century (7) accuracy: (ev_tol, ev_ig, text), otherwise None."""
    for c in claims.get("P571", []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(v, dict) and v.get("precision") in (7, 8):
            m = re.match(r"[+-](\d{4})-", v.get("time", ""))
            if m:
                n = int(m.group(1))
                if v["precision"] == 8:
                    return n // 10 * 10, n // 10 * 10 + 9, "P571 évtized"
                return (n - 1) // 100 * 100, (n - 1) // 100 * 100 + 99, "P571 évszázad"
    return None


def main():
    with open(OSM, encoding="utf-8") as f:
        feats = [x for x in json.load(f)["features"] if x["properties"].get("tipus") != "roof"]
    building_qid = {}
    for ft in feats:
        for q in re.findall(r"Q\d+", ft["properties"].get("wikidata") or ""):
            building_qid.setdefault(building_key(ft["properties"]), []).append(q)
    qids_ = sorted({q for v in building_qid.values() for q in v})
    print(f"Wikidata-címkés épületek: {len(building_qid)}, különböző elemek: {len(qids_)}")
    if not qids_:
        return

    entities = {}
    for cs in in_batches(qids_, BATCH):
        entities.update(fetch(cs, "claims|labels|sitelinks").get("entities", {}))
    print(f"Letöltött elemek: {len(entities)}")

    # the names of the architects and styles
    secondary = set()
    for e in entities.values():
        cl = e.get("claims", {})
        secondary.update(elements_id(cl, "P84"))
        secondary.update(elements_id(cl, "P149"))
    names = {}
    for cs in in_batches(sorted(secondary), BATCH):
        for q, e in fetch(cs, "labels").get("entities", {}).items():
            names[q] = label(e)

    W = "wikidata"
    rows, year_count, designer_count, style_count = [], 0, 0, 0
    approximate = []
    for k, qk in building_qid.items():
        for q in qk:
            e = entities.get(q)
            if not e or "missing" in e:
                continue
            cl = e.get("claims", {})
            t, i = k
            if label(e):
                rows.append((t, i, "wikidata_nev", label(e), W, q))
            if wikipedia_article(e):
                rows.append((t, i, "wikipedia", wikipedia_article(e), W, q))
            year = year_a_from_claims(cl)
            if year:
                rows.append((t, i, "ev", year, W, f"{q}: P571"))
                year_count += 1
            else:
                hold = year_range(cl)
                if hold:
                    approximate.append((t, i, hold[0], hold[1], f"{q}: {hold[2]}", "wikidata"))
            architect = [names.get(x) for x in elements_id(cl, "P84") if names.get(x)]
            if architect:
                rows.append((t, i, "tervezo", ", ".join(architect), W, q))
                designer_count += 1
            style = [names.get(x) for x in elements_id(cl, "P149") if names.get(x)]
            if style:
                rows.append((t, i, "stilus", ", ".join(style), W, q))
                style_count += 1
    write_facts(OUTPUT, rows)
    if CITY:
        import csv
        Path(APPROXIMATE).parent.mkdir(parents=True, exist_ok=True)
        with open(APPROXIMATE, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["osm_tipus", "id", "ev_tol", "ev_ig", "szoveg", "forras"])
            w.writerows(approximate)
        print(f"Közelítő (évtized/évszázad) év: {len(approximate)} -> {APPROXIMATE}")
    print(f"Építési év: {year_count}, építész: {designer_count}, stílus: {style_count}")
    print(f"Mentve: {OUTPUT}")


if __name__ == "__main__":
    main()
