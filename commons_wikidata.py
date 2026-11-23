"""
commons_wikidata.py - Photos for the buildings based on Wikidata (P18 image, P373 Commons category) and the OSM
`wikidata` / `wikimedia_commons` tags. For the whole city.

Run (in the project folder; first: py city_assembly.py and py assemble.py varos, as well as
py commons_images.py varos, so that data/varos/commons_kepek.json exists):
    py commons_wikidata.py

What does it do?
  1. The buildings' OSM tags: the `wikidata` tag (Q id) and the `wikimedia_commons` tag (File: or Category:).
  2. Fetching the Wikidata items: the P18/P373 data of the tagged items + a SPARQL query for all items of Budapest
     that have a coordinate and an image or a Commons category. These are fitted into the buildings' outlines.
  3. From the members of the Commons categories it selects the best facade photo.
  4. It queries the images' licence/author (only a free licence, an image at least 600 px wide).
  5. It merges the results with the data/varos/commons_kepek.json file. The order (good -> weaker):
       wd (Wikidata image) > cim (file name with address) > nev (file name containing the name) > kat (Commons category) > hely (location data)
     It does not overwrite an existing better match.
Every step is cached (data/cache/), and can be resumed after an interruption. The log is on the console and in the
data/varos/commons_wikidata_jelentes.md file.
"""
import json
import math
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

import commons_images as ck

DATA = Path("data")
CACHE = DATA / "cache"
WD_API = "https://www.wikidata.org/w/api.php"
SPARQL = "https://query.wikidata.org/sparql"
UA = ck.UA
PAUSE = 1.2
RANK = {"wd": 5, "cim": 4, "nev": 3, "kat": 2, "hely": 1}
CITY_BOX = (47.34, 18.92, 47.62, 19.35)          # south, west, north, east (slightly larger than the city boundary)


# ---------- network ----------
def request_(url, params, header=None, timeout=120):
    for attempt in range(8):
        try:
            u = url + "?" + urllib.parse.urlencode(params)
            with urllib.request.urlopen(urllib.request.Request(u, headers={**UA, **(header or {})}), timeout=timeout) as v:
                return json.load(v)
        except urllib.error.HTTPError as h:
            var = h.headers.get("Retry-After")
            var = int(var) if var and var.isdigit() else 30 * (attempt + 1)
            print(f"    HTTP {h.code}, várok {var} s", flush=True)
            time.sleep(var)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as h:
            print(f"    újrapróbálom ({type(h).__name__}: {h})", flush=True)
            time.sleep(2 ** attempt * 2)
    raise SystemExit("A szerver nem válaszol. Futtasd újra később, onnan folytatja, ahol abbamaradt.")


def cache_in(name_, base):
    path_ = CACHE / name_
    if path_.exists():
        return json.loads(path_.read_text(encoding="utf-8"))
    return base


def cache_out(name_, data_):
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / name_).write_text(json.dumps(data_, ensure_ascii=False), encoding="utf-8")


def file_address(name_):
    """'Some_file.jpg' or the Special:FilePath URL -> 'File:Some file.jpg'."""
    name_ = urllib.parse.unquote(str(name_))
    name_ = name_.rsplit("Special:FilePath/", 1)[-1]
    name_ = re.sub(r"^(?:File|Fájl):", "", name_, flags=re.I)
    return "File:" + name_.replace("_", " ").strip()


# ---------- 2. Wikidata ----------
def entities(qids):
    """{Q: {"p18": [file titles], "p373": category|None}} for the tagged items (wbgetentities, 50 per request)."""
    result = cache_in("wd_entitasok.json", {})
    needed = sorted(q for q in set(qids) if re.fullmatch(r"Q\d+", q) and q not in result)
    print(f"Wikidata-elemek lekérése: {len(needed)} új ({len(result)} már megvan)", flush=True)
    for i in range(0, len(needed), 50):
        part = needed[i:i + 50]
        j = request_(WD_API, {"action": "wbgetentities", "ids": "|".join(part), "props": "claims", "format": "json"})
        for q in part:
            e = (j.get("entities") or {}).get(q) or {}
            cl = e.get("claims") or {}
            p18 = [c["mainsnak"]["datavalue"]["value"] for c in cl.get("P18", [])
                   if c.get("mainsnak", {}).get("datavalue")]
            p373 = next((c["mainsnak"]["datavalue"]["value"] for c in cl.get("P373", [])
                         if c.get("mainsnak", {}).get("datavalue")), None)
            result[q] = {"p18": [file_address(x) for x in p18], "p373": p373}
        cache_out("wd_entitasok.json", result)
        time.sleep(PAUSE)
        if (i // 50) % 20 == 0:
            print(f"  {min(i + 50, len(needed))}/{len(needed)}", flush=True)
    return result


def sparql_elements():
    """All of Budapest's Wikidata items that have a coordinate and (P18 or P373): in a 3x3 grid, against the timeout."""
    result = cache_in("wd_budapest.json", {"kesz": [], "elemek": {}})
    d, ny, e, k = CITY_BOX
    n = 3
    for a in range(n):
        for b in range(n):
            building_key = f"{a}_{b}"
            if building_key in result["kesz"]:
                continue
            s0, s1 = d + (e - d) * a / n, d + (e - d) * (a + 1) / n
            w0, w1 = ny + (k - ny) * b / n, ny + (k - ny) * (b + 1) / n
            q = f"""SELECT ?item ?coord ?img ?cat ?label WHERE {{
  SERVICE wikibase:box {{ ?item wdt:P625 ?coord .
    bd:serviceParam wikibase:cornerSouthWest "Point({w0} {s0})"^^geo:wktLiteral .
    bd:serviceParam wikibase:cornerNorthEast "Point({w1} {s1})"^^geo:wktLiteral . }}
  OPTIONAL {{ ?item wdt:P18 ?img }} OPTIONAL {{ ?item wdt:P373 ?cat }}
  FILTER(BOUND(?img) || BOUND(?cat))
  OPTIONAL {{ ?item rdfs:label ?label . FILTER(LANG(?label) = "hu") }}
}}"""
            print(f"Wikidata SPARQL: {a * n + b + 1}/{n * n}", flush=True)
            j = request_(SPARQL, {"query": q, "format": "json"}, {"Accept": "application/sparql-results+json"}, timeout=180)
            for r in j["results"]["bindings"]:
                qid = r["item"]["value"].rsplit("/", 1)[-1]
                m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", r["coord"]["value"])
                if not m:
                    continue
                el = result["elemek"].setdefault(qid, {"lon": float(m.group(1)), "lat": float(m.group(2)),
                                                     "p18": [], "p373": None, "cimke": ""})
                if "img" in r:
                    c = file_address(r["img"]["value"])
                    if c not in el["p18"]:
                        el["p18"].append(c)
                if "cat" in r:
                    el["p373"] = r["cat"]["value"]
                if "label" in r:
                    el["cimke"] = r["label"]["value"]
            result["kesz"].append(building_key)
            cache_out("wd_budapest.json", result)
            time.sleep(5)
    print(f"  {len(result['elemek'])} Wikidata-elem koordinátával és képpel/kategóriával", flush=True)
    return result["elemek"]


# ---------- 3. categories ----------
def category_members_of(categories):
    """{category: [file titles]} (at most 100 files per category)."""
    result = cache_in("commons_kategoriak.json", {})
    needed = sorted(k for k in set(categories) if k not in result)
    print(f"Commons-kategóriák: {len(needed)} új ({len(result)} már megvan)", flush=True)
    for i, category in enumerate(needed, 1):
        j = request_(ck.API, {"action": "query", "list": "categorymembers", "cmtitle": "Category:" + category,
                          "cmtype": "file", "cmlimit": 100, "format": "json"})
        if "error" in j:
            print(f"    a Commons hibát jelzett: {str(j['error'])[:120]}", flush=True)
            time.sleep(20)
            continue
        result[category] = [m["title"] for m in (j.get("query") or {}).get("categorymembers", [])]
        time.sleep(PAUSE)
        if i % 25 == 0:
            cache_out("commons_kategoriak.json", result)
            print(f"  kategóriák: {i}/{len(needed)}", flush=True)
    cache_out("commons_kategoriak.json", result)
    return result


def address_point(file):
    """A score within the category by file name: facade image first, detail photo last."""
    t = ck.norm(re.sub(r"\.[A-Za-z0-9]{3,4}$", "", file.split(":", 1)[-1]))
    if any(ck.norm(x) in t for x in ck.BANNED):
        return None
    return (-40 if ck.DETAIL.search(t) else 0) + (10 if "homlokzat" in t or "facade" in t else 0) \
        - (15 if "fortepan" in t else 0)


def best_files(members, count_=3):
    sign = [(address_point(f), f) for f in members]
    sign = [x for x in sign if x[0] is not None and re.search(r"\.(jpe?g|png|tiff?|webp)$", x[1], re.I)]
    sign.sort(key=lambda x: -x[0])
    return [f for _, f in sign[:count_]]


# ---------- finding buildings by coordinate ----------
def grid_construction(ep):
    grid = defaultdict(list)
    for building_key, e in ep.items():
        xs = [c[0] for c in e["gyuru"]]
        ys = [c[1] for c in e["gyuru"]]
        e["doboz"] = (min(xs), max(xs), min(ys), max(ys))
        for i in range(int(e["doboz"][0] / 0.001), int(e["doboz"][1] / 0.001) + 1):
            for j in range(int(e["doboz"][2] / 0.001), int(e["doboz"][3] / 0.001) + 1):
                grid[(i, j)].append(building_key)
    return grid


def where_has(ep, grid, lat, lon):
    best, small = None, None
    for building_key in grid.get((int(lon / 0.001), int(lat / 0.001)), ()):
        e = ep[building_key]
        d = e["doboz"]
        if d[0] <= lon <= d[1] and d[2] <= lat <= d[3] and ck._point_in_ring(lon, lat, e["gyuru"]):
            area_ = (d[1] - d[0]) * (d[3] - d[2])
            if small is None or area_ < small:
                best, small = building_key, area_
    return best


# ---------- main ----------
def main():
    ck.CITY = True
    ep = ck.read_buildings()
    print(f"Épületek: {len(ep)}", flush=True)
    existing_path = DATA / "varos" / "commons_kepek.json"
    existing = json.loads(existing_path.read_text(encoding="utf-8")) if existing_path.exists() else {}

    # 1. the OSM tags
    group_qid = defaultdict(set)          # csoportkulcs -> {Q}
    group_file = defaultdict(list)        # group key -> [(mode, file title)]
    group_category = defaultdict(list)         # group key -> [(mode, category)]
    osm_wd = osm_commons = 0
    for e in ep.values():
        if e.get("wikidata"):
            group_qid[e["kulcs"]].add(str(e["wikidata"]).split(";")[0].strip())
            osm_wd += 1
        c = (e.get("commons") or "").strip()
        if c:
            osm_commons += 1
            if re.match(r"(File|Fájl):", c, re.I):
                group_file[e["kulcs"]].append(("wd", file_address(c)))
            else:
                group_category[e["kulcs"]].append(("kat", re.sub(r"^(Category|Kategória):", "", c, flags=re.I).strip()))
    print(f"OSM-címkék: wikidata {osm_wd}, wikimedia_commons {osm_commons}", flush=True)

    # 2. Wikidata
    ent = entities([q for qs in group_qid.values() for q in qs])
    sp = sparql_elements()
    grid = grid_construction(ep)
    coord_count = 0
    for qid, el in sp.items():
        building_key = where_has(ep, grid, el["lat"], el["lon"])
        if building_key:
            group_qid[ep[building_key]["kulcs"]].add(qid)
            ent.setdefault(qid, {"p18": el["p18"], "p373": el["p373"]})
            coord_count += 1
    print(f"  koordináta szerint épületbe illesztett Wikidata-elem: {coord_count}", flush=True)
    for group_, qs in group_qid.items():
        for q in sorted(qs):
            e = ent.get(q) or {}
            for f in e.get("p18", [])[:2]:
                group_file[group_].append(("wd", f))
            if e.get("p373"):
                group_category[group_].append(("kat", e["p373"]))

    # 3. categories
    members = category_members_of([k for list_ in group_category.values() for _, k in list_])
    candidates = defaultdict(list)            # group -> [(mode, file title)] in order
    for group_ in set(group_file) | set(group_category):
        list_ = list(group_file.get(group_, []))
        for mode, category in group_category.get(group_, []):
            for f in best_files(members.get(category, [])):
                list_.append(("kat", f))
        list_ = [x for i, x in enumerate(list_) if x not in list_[:i]]
        candidates[group_] = list_[:6]

    # 4. image data
    ii = ck.imageinfo([f for list_ in candidates.values() for _, f in list_])

    # 5. merging
    new = dict(existing)
    stat = defaultdict(int)
    for group_, list_ in candidates.items():
        for mode, address in list_:
            info = ii.get(address) or ii.get(address.replace("_", " "))
            if not info:
                continue
            if not str(info.get("mime", "")).startswith("image/") or info.get("mime") in ("image/svg+xml", "image/gif"):
                continue
            if info.get("width", 0) < ck.MIN_WIDE:
                continue
            em = info.get("extmetadata") or {}
            licence = ck.text_((em.get("LicenseShortName") or {}).get("value"))
            if not licence or "non-free" in licence.lower() or licence.lower().startswith("fair use"):
                continue
            detail = 1 if ck.DETAIL.search(ck.norm(re.sub(r"\.[A-Za-z0-9]{3,4}$", "", address.split(":", 1)[-1]))) else 0
            old = new.get(group_)
            if old:
                # a better-mode match wins; with the same mode, the non-detail photo
                if RANK.get(old.get("m"), 0) > RANK[mode] or (RANK.get(old.get("m"), 0) == RANK[mode] and (old.get("r", 0) <= detail)):
                    break
            new[group_] = {"f": address.split(":", 1)[-1].replace(" ", "_"),
                           "a": ck.text_((em.get("Artist") or {}).get("value"))[:90], "l": licence,
                           "u": ck.text_((em.get("LicenseUrl") or {}).get("value")), "m": mode, "r": detail}
            stat[mode] += 1
            break
    existing_path.parent.mkdir(parents=True, exist_ok=True)
    existing_path.write_text(json.dumps(new, ensure_ascii=False, indent=0), encoding="utf-8")
    sign = ["# Commons-fotók a Wikidata és az OSM-címkék alapján", "",
           f"- OSM `wikidata` címkével: {osm_wd} épület, `wikimedia_commons` címkével: {osm_commons} épület",
           f"- koordináta szerint épületbe illesztett Wikidata-elem (képpel vagy kategóriával): {coord_count}",
           f"- új vagy lecserélt fotó: Wikidata-kép {stat['wd']}, Commons-kategória {stat['kat']}",
           f"- épület fotóval összesen: {len(new)}", "", "## Példák az ellenőrzéshez", ""]
    names = {e["kulcs"]: (e["nev"] or "") for e in ep.values()}
    example = [(c, k) for c, k in new.items() if k.get("m") in ("wd", "kat")][:60]
    for c, k in example:
        sign.append(f"- {k['m']}; {names.get(c) or c}; https://commons.wikimedia.org/wiki/File:{k['f']}")
    (DATA / "varos" / "commons_wikidata_jelentes.md").write_text("\n".join(sign) + "\n", encoding="utf-8")
    print(f"Kész: {len(new)} épületnek van fotója (új/lecserélt: Wikidata {stat['wd']}, kategória {stat['kat']}).")
    print("Mentve: data/varos/commons_kepek.json, data/varos/commons_wikidata_jelentes.md  (most futtasd: py build_tiles.py)")


if __name__ == "__main__":
    main()
