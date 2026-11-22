"""Wikidata, koordináta alapján -> data/tenyek/wikidata_terulet.csv

Lekérdezi a területünkön lévő összes Wikidata-épületet, amelynek van építési éve
(nem kell hozzá OSM-ben wikidata-címke), és az épületkörvonalainkhoz párosítja őket:
  - ha a koordináta az épületbe esik: forrás = "wikidata"
  - ha legfeljebb 10 m-re van a legközelebbi épülettől: forrás = "wikidata_kozeli"
A Wikidata tartalma CC0 (szabadon felhasználható).
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from kozos import kulcs, legkozelebbi_csucs_m, pont_barmelyikben, poligonok, tenyek_irasa

OSM = "data/belvaros_epuletek.geojson"
KIMENET = "data/tenyek/wikidata_terulet.csv"
CACHE = Path("data/cache/wdqs_terulet.json")
DEL, NYUGAT, ESZAK, KELET = 47.490, 19.040, 47.513, 19.062
KOZELI_METER = 10
KLIENS = "budapest-by-building/1.0 (tanulasi projekt)"
SPARQL = "https://query.wikidata.org/sparql"

LEKERDEZES = f"""
SELECT ?item ?itemLabel ?coord ?ev ?epiteszLabel ?stilusLabel WHERE {{
  SERVICE wikibase:box {{
    ?item wdt:P625 ?coord .
    bd:serviceParam wikibase:cornerSouthWest "Point({NYUGAT} {DEL})"^^geo:wktLiteral .
    bd:serviceParam wikibase:cornerNorthEast "Point({KELET} {ESZAK})"^^geo:wktLiteral .
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


def lekeres():
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    url = SPARQL + "?" + urllib.parse.urlencode({"query": LEKERDEZES, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": KLIENS, "Accept": "application/sparql-results+json"})
    adat = None
    for probalkozas in range(1, 6):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                adat = json.load(r)
            break
        except urllib.error.HTTPError as hiba:
            if hiba.code not in (429, 500, 502, 503, 504) or probalkozas == 5:
                raise
            varakozas = 70
            try:
                varakozas = max(varakozas, int(hiba.headers.get("Retry-After", 0)) + 5)
            except (TypeError, ValueError):
                pass
            print(f"A Wikidata szervere most nem fogad ({hiba.code}), {probalkozas}/5. próba. "
                  f"Várok {varakozas} másodpercet...")
            time.sleep(varakozas)
        except urllib.error.URLError as hiba:
            if probalkozas == 5:
                raise
            print(f"Hálózati hiba ({hiba.reason}), {probalkozas}/5. próba. Várok 30 másodpercet...")
            time.sleep(30)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(adat, ensure_ascii=False), encoding="utf-8")
    return adat


def pont_wkt(s):
    # "Point(19.05 47.5)"
    x, y = s[s.index("(") + 1:s.index(")")].split()
    return float(x), float(y)


def main():
    sorok_wd = lekeres()["results"]["bindings"]
    elemek = {}
    for r in sorok_wd:
        q = r["item"]["value"].rsplit("/", 1)[-1]
        e = elemek.setdefault(q, {"nev": None, "pont": None, "ev": None, "epitesz": [], "stilus": []})
        e["nev"] = r.get("itemLabel", {}).get("value")
        e["pont"] = pont_wkt(r["coord"]["value"])
        e["ev"] = int(r["ev"]["value"].lstrip("+")[:4])
        for kulcsnev, mezo in (("epiteszLabel", "epitesz"), ("stilusLabel", "stilus")):
            v = r.get(kulcsnev, {}).get("value")
            if v and not v.startswith("http") and v not in e[mezo]:
                e[mezo].append(v)
    print(f"Wikidata-épületek a területen (építési évvel): {len(elemek)}")

    with open(OSM, encoding="utf-8") as f:
        feats = [x for x in json.load(f)["features"] if x["properties"].get("tipus") != "roof"]
    polik = [(ft, poligonok(ft["geometry"])) for ft in feats]

    sorok, belul, kozeli, nincs = [], 0, 0, 0
    legjobb = {}   # épület -> (távolság a belső ponttól, adatok)
    for q, e in elemek.items():
        x, y = e["pont"]
        talalat, mod = None, None
        for ft, pl in polik:
            if pl and pont_barmelyikben(x, y, pl):
                talalat, mod = ft, "wikidata"
                break
        if talalat is None:
            tav = KOZELI_METER
            for ft, pl in polik:
                if not pl:
                    continue
                d = legkozelebbi_csucs_m(x, y, pl[0][0])
                if d < tav:
                    talalat, tav = ft, d
            mod = "wikidata_kozeli" if talalat else None
        if talalat is None:
            nincs += 1
            continue
        belul += mod == "wikidata"
        kozeli += mod == "wikidata_kozeli"
        k = kulcs(talalat["properties"])
        elozo = legjobb.get(k)
        # ha egy épületbe több elem esik, a "belül" találat győz
        if elozo is None or (mod == "wikidata" and elozo[0] != "wikidata"):
            legjobb[k] = (mod, q, e)

    for (t, i), (mod, q, e) in legjobb.items():
        sorok.append((t, i, "wikidata_id", q, mod, ""))
        if e["nev"]:
            sorok.append((t, i, "wikidata_nev", e["nev"], mod, q))
        sorok.append((t, i, "ev", e["ev"], mod, f"{q}: P571"))
        if e["epitesz"]:
            sorok.append((t, i, "tervezo", ", ".join(e["epitesz"]), mod, q))
        if e["stilus"]:
            sorok.append((t, i, "stilus", ", ".join(e["stilus"]), mod, q))
    tenyek_irasa(KIMENET, sorok)
    print(f"Épületbe esik: {belul}, közeli (≤{KOZELI_METER} m): {kozeli}, nem párosítható: {nincs}")
    print(f"Épület, amelyhez adat került: {len(legjobb)}")
    print(f"Mentve: {KIMENET}")


if __name__ == "__main__":
    main()
