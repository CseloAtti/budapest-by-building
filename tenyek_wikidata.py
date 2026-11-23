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

from kozos import http_json, kulcs, tenyek_irasa

import sys
VAROS = len(sys.argv) > 1 and sys.argv[1] == "varos"      # py tenyek_wikidata.py varos  -> the whole city
OSM = "data/varos/epuletek_vegleges.geojson" if VAROS else "data/belvaros_epuletek.geojson"
KIMENET = "data/tenyek/wikidata.csv"
KOZELITO = "data/varos/wikidata_kozelito.csv"
CACHE = Path("data/cache")
API = "https://www.wikidata.org/w/api.php"
KLIENS = "budapest-by-building/1.0 (tanulasi projekt)"
CSOMAG = 50
SZUNET_MP = 2


def lekeres(azonositok, props):
    """Fetching a batch of Wikidata elements (with a disk cache)."""
    nev = "wd_" + hashlib.sha1((props + "|" + "|".join(azonositok)).encode()).hexdigest()[:16] + ".json"
    ut = CACHE / nev
    if ut.exists():
        return json.loads(ut.read_text(encoding="utf-8"))
    params = {"action": "wbgetentities", "ids": "|".join(azonositok), "props": props,
              "languages": "hu|en", "format": "json"}
    if "sitelinks" in props:
        params["sitefilter"] = "huwiki|enwiki"
    url = API + "?" + urllib.parse.urlencode(params)
    adat = http_json(url)
    CACHE.mkdir(parents=True, exist_ok=True)
    ut.write_text(json.dumps(adat, ensure_ascii=False), encoding="utf-8")
    time.sleep(SZUNET_MP)
    return adat


def wikipedia_cikk(entitas):
    """The Wikipedia article, if there is one: 'hu:Title' (preferred) or 'en:Title'."""
    s = (entitas or {}).get("sitelinks", {})
    for kulcs_, nyelv in (("huwiki", "hu"), ("enwiki", "en")):
        if kulcs_ in s and s[kulcs_].get("title"):
            return f"{nyelv}:{s[kulcs_]['title']}"
    return None


def csomagokban(lista, n):
    for i in range(0, len(lista), n):
        yield lista[i:i + n]


def cimke(entitas):
    c = (entitas or {}).get("labels", {})
    for nyelv in ("hu", "en"):
        if nyelv in c:
            return c[nyelv]["value"]
    return None


def elemek_id(claims, prop):
    """The identifiers (Q...) of the value items of the given property."""
    ki = []
    for c in claims.get(prop, []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(v, dict) and v.get("id"):
            ki.append(v["id"])
    return ki


def ev_a_claimekbol(claims):
    """Year of construction/founding, only if precise at least to the year (precision >= 9)."""
    for c in claims.get("P571", []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(v, dict) and v.get("precision", 0) >= 9:
            m = re.match(r"[+-](\d{4})-", v.get("time", ""))
            if m:
                return int(m.group(1))
    return None


def ev_tartomany(claims):
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
    epulet_qid = {}
    for ft in feats:
        for q in re.findall(r"Q\d+", ft["properties"].get("wikidata") or ""):
            epulet_qid.setdefault(kulcs(ft["properties"]), []).append(q)
    qidok = sorted({q for v in epulet_qid.values() for q in v})
    print(f"Wikidata-címkés épületek: {len(epulet_qid)}, különböző elemek: {len(qidok)}")
    if not qidok:
        return

    entitasok = {}
    for cs in csomagokban(qidok, CSOMAG):
        entitasok.update(lekeres(cs, "claims|labels|sitelinks").get("entities", {}))
    print(f"Letöltött elemek: {len(entitasok)}")

    # the names of the architects and styles
    masodlagos = set()
    for e in entitasok.values():
        cl = e.get("claims", {})
        masodlagos.update(elemek_id(cl, "P84"))
        masodlagos.update(elemek_id(cl, "P149"))
    nevek = {}
    for cs in csomagokban(sorted(masodlagos), CSOMAG):
        for q, e in lekeres(cs, "labels").get("entities", {}).items():
            nevek[q] = cimke(e)

    W = "wikidata"
    sorok, ev_db, tervezo_db, stilus_db = [], 0, 0, 0
    kozelito = []
    for k, qk in epulet_qid.items():
        for q in qk:
            e = entitasok.get(q)
            if not e or "missing" in e:
                continue
            cl = e.get("claims", {})
            t, i = k
            if cimke(e):
                sorok.append((t, i, "wikidata_nev", cimke(e), W, q))
            if wikipedia_cikk(e):
                sorok.append((t, i, "wikipedia", wikipedia_cikk(e), W, q))
            ev = ev_a_claimekbol(cl)
            if ev:
                sorok.append((t, i, "ev", ev, W, f"{q}: P571"))
                ev_db += 1
            else:
                tart = ev_tartomany(cl)
                if tart:
                    kozelito.append((t, i, tart[0], tart[1], f"{q}: {tart[2]}", "wikidata"))
            epitesz = [nevek.get(x) for x in elemek_id(cl, "P84") if nevek.get(x)]
            if epitesz:
                sorok.append((t, i, "tervezo", ", ".join(epitesz), W, q))
                tervezo_db += 1
            stilus = [nevek.get(x) for x in elemek_id(cl, "P149") if nevek.get(x)]
            if stilus:
                sorok.append((t, i, "stilus", ", ".join(stilus), W, q))
                stilus_db += 1
    tenyek_irasa(KIMENET, sorok)
    if VAROS:
        import csv
        Path(KOZELITO).parent.mkdir(parents=True, exist_ok=True)
        with open(KOZELITO, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["osm_tipus", "id", "ev_tol", "ev_ig", "szoveg", "forras"])
            w.writerows(kozelito)
        print(f"Közelítő (évtized/évszázad) év: {len(kozelito)} -> {KOZELITO}")
    print(f"Építési év: {ev_db}, építész: {tervezo_db}, stílus: {stilus_db}")
    print(f"Mentve: {KIMENET}")


if __name__ == "__main__":
    main()
