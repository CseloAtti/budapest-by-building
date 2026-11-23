"""Wikidata, by coordinate -> data/tenyek/wikidata_terulet.csv

It queries all the Wikidata buildings in our area that have a year of construction
(no wikidata tag is needed in OSM), and matches them to our building outlines:
  - if the coordinate falls into the building: source = "wikidata"
  - if the nearest building is at most 10 m away: source = "wikidata_kozeli"
The content of Wikidata is CC0 (free to use).
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from common import building_key, nearest_vertex_m, point_in_any, polygons, write_facts

OSM = "data/belvaros_epuletek.geojson"
OUTPUT = "data/tenyek/wikidata_terulet.csv"
CACHE = Path("data/cache/wdqs_terulet.json")
DEL, WEST, NORTH, EAST = 47.490, 19.040, 47.513, 19.062
NEARBY_METER = 10
CLIENT = "budapest-by-building/1.0 (tanulasi projekt)"
SPARQL = "https://query.wikidata.org/sparql"

QUERY = f"""
SELECT ?item ?itemLabel ?coord ?ev ?epiteszLabel ?stilusLabel WHERE {{
  SERVICE wikibase:box {{
    ?item wdt:P625 ?coord .
    bd:serviceParam wikibase:cornerSouthWest "Point({WEST} {DEL})"^^geo:wktLiteral .
    bd:serviceParam wikibase:cornerNorthEast "Point({EAST} {NORTH})"^^geo:wktLiteral .
  }}
  ?item wdt:P31/wdt:P279* wd:Q41176 .
  ?item p:P571/psv:P571 ?v .
  ?v wikibase:timeValue ?ev ; wikibase:timePrecision ?pontossag .
  FILTER(?pontossag >= 9)
  OPTIONAL {{ ?item wdt:P84 ?epitesz . }}
  OPTIONAL {{ ?item wdt:P149 ?stilus . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "hu,en". }}
}}
"""


def fetch():
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    url = SPARQL + "?" + urllib.parse.urlencode({"query": QUERY, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": CLIENT, "Accept": "application/sparql-results+json"})
    data_ = None
    for attempt in range(1, 6):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data_ = json.load(r)
            break
        except urllib.error.HTTPError as error_:
            if error_.code not in (429, 500, 502, 503, 504) or attempt == 5:
                raise
            wait = 70
            try:
                wait = max(wait, int(error_.headers.get("Retry-After", 0)) + 5)
            except (TypeError, ValueError):
                pass
            print(f"A Wikidata szervere most nem fogad ({error_.code}), {attempt}/5. próba. "
                  f"Várok {wait} másodpercet...")
            time.sleep(wait)
        except urllib.error.URLError as error_:
            if attempt == 5:
                raise
            print(f"Hálózati hiba ({error_.reason}), {attempt}/5. próba. Várok 30 másodpercet...")
            time.sleep(30)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(data_, ensure_ascii=False), encoding="utf-8")
    return data_


def point_wkt(s):
    # "Point(19.05 47.5)"
    x, y = s[s.index("(") + 1:s.index(")")].split()
    return float(x), float(y)


def main():
    rows_wd = fetch()["results"]["bindings"]
    elements = {}
    for r in rows_wd:
        q = r["item"]["value"].rsplit("/", 1)[-1]
        e = elements.setdefault(q, {"nev": None, "pont": None, "ev": None, "epitesz": [], "stilus": []})
        e["nev"] = r.get("itemLabel", {}).get("value")
        e["pont"] = point_wkt(r["coord"]["value"])
        e["ev"] = int(r["ev"]["value"].lstrip("+")[:4])
        for key_name, field in (("epiteszLabel", "epitesz"), ("stilusLabel", "stilus")):
            v = r.get(key_name, {}).get("value")
            if v and not v.startswith("http") and v not in e[field]:
                e[field].append(v)
    print(f"Wikidata-épületek a területen (építési évvel): {len(elements)}")

    with open(OSM, encoding="utf-8") as f:
        feats = [x for x in json.load(f)["features"] if x["properties"].get("tipus") != "roof"]
    polys = [(ft, polygons(ft["geometry"])) for ft in feats]

    rows, inside_, nearby, none = [], 0, 0, 0
    best = {}   # building -> (distance from the inner point, data)
    for q, e in elements.items():
        x, y = e["pont"]
        hit, mode = None, None
        for ft, pl in polys:
            if pl and point_in_any(x, y, pl):
                hit, mode = ft, "wikidata"
                break
        if hit is None:
            distance = NEARBY_METER
            for ft, pl in polys:
                if not pl:
                    continue
                d = nearest_vertex_m(x, y, pl[0][0])
                if d < distance:
                    hit, distance = ft, d
            mode = "wikidata_kozeli" if hit else None
        if hit is None:
            none += 1
            continue
        inside_ += mode == "wikidata"
        nearby += mode == "wikidata_kozeli"
        k = building_key(hit["properties"])
        previous = best.get(k)
        # if several elements fall into a building, the "inside" hit wins
        if previous is None or (mode == "wikidata" and previous[0] != "wikidata"):
            best[k] = (mode, q, e)

    for (t, i), (mode, q, e) in best.items():
        rows.append((t, i, "wikidata_id", q, mode, ""))
        if e["nev"]:
            rows.append((t, i, "wikidata_nev", e["nev"], mode, q))
        rows.append((t, i, "ev", e["ev"], mode, f"{q}: P571"))
        if e["epitesz"]:
            rows.append((t, i, "tervezo", ", ".join(e["epitesz"]), mode, q))
        if e["stilus"]:
            rows.append((t, i, "stilus", ", ".join(e["stilus"]), mode, q))
    write_facts(OUTPUT, rows)
    print(f"Épületbe esik: {inside_}, közeli (≤{NEARBY_METER} m): {nearby}, nem párosítható: {none}")
    print(f"Épület, amelyhez adat került: {len(best)}")
    print(f"Mentve: {OUTPUT}")


if __name__ == "__main__":
    main()
