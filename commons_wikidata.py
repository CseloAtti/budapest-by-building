"""
commons_wikidata.py - Fotók az épületekhez a Wikidata (P18 kép, P373 Commons-kategória) és az OSM
`wikidata` / `wikimedia_commons` címkéi alapján. Az egész városra.

Futtatás (a projekt mappájában; előtte: py varos_osszeallitas.py és py osszeepit.py varos, valamint a
py commons_kepek.py varos, hogy legyen data/varos/commons_kepek.json):
    py commons_wikidata.py

Mit csinál?
  1. Az épületek OSM-címkéi: a `wikidata` címke (Q-azonosító) és a `wikimedia_commons` címke (File: vagy Category:).
  2. A Wikidata-elemek lekérése: a címkézett elemek P18/P373 adata + egy SPARQL-lekérdezés Budapest összes olyan
     elemére, amelynek van koordinátája és képe vagy Commons-kategóriája. Ezeket az épületek körvonalába illeszti.
  3. A Commons-kategóriák tagjaiból a legjobb homlokzati fotót választja.
  4. A képek licencét/szerzőjét lekérdezi (csak szabad licenc, legalább 600 px széles kép).
  5. A találatokat összefésüli a data/varos/commons_kepek.json fájllal. A sorrend (jó -> gyengébb):
       wd (Wikidata-kép) > cim (címes fájlnév) > nev (nevet tartalmazó fájlnév) > kat (Commons-kategória) > hely (helyadat)
     Meglévő jobb találatot nem ír felül.
Minden lépés gyorsítótárazott (data/cache/), megszakítás után folytatható. A napló a konzolon és a
data/varos/commons_wikidata_jelentes.md fájlban van.
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

import commons_kepek as ck

ADAT = Path("data")
CACHE = ADAT / "cache"
WD_API = "https://www.wikidata.org/w/api.php"
SPARQL = "https://query.wikidata.org/sparql"
UA = ck.UA
SZUNET = 1.2
RANG = {"wd": 5, "cim": 4, "nev": 3, "kat": 2, "hely": 1}
VAROS_DOBOZ = (47.34, 18.92, 47.62, 19.35)          # dél, nyugat, észak, kelet (a városhatárnál kicsit nagyobb)


# ---------- hálózat ----------
def kerj(url, params, fejlec=None, timeout=120):
    for kiserlet in range(8):
        try:
            u = url + "?" + urllib.parse.urlencode(params)
            with urllib.request.urlopen(urllib.request.Request(u, headers={**UA, **(fejlec or {})}), timeout=timeout) as v:
                return json.load(v)
        except urllib.error.HTTPError as h:
            var = h.headers.get("Retry-After")
            var = int(var) if var and var.isdigit() else 30 * (kiserlet + 1)
            print(f"    HTTP {h.code}, várok {var} s", flush=True)
            time.sleep(var)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as h:
            print(f"    újrapróbálom ({type(h).__name__}: {h})", flush=True)
            time.sleep(2 ** kiserlet * 2)
    raise SystemExit("A szerver nem válaszol. Futtasd újra később, onnan folytatja, ahol abbamaradt.")


def cache_be(nev, alap):
    ut = CACHE / nev
    if ut.exists():
        return json.loads(ut.read_text(encoding="utf-8"))
    return alap


def cache_ki(nev, adat):
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / nev).write_text(json.dumps(adat, ensure_ascii=False), encoding="utf-8")


def fajl_cim(nev):
    """'Valami_fájl.jpg' vagy a Special:FilePath URL -> 'File:Valami fájl.jpg'."""
    nev = urllib.parse.unquote(str(nev))
    nev = nev.rsplit("Special:FilePath/", 1)[-1]
    nev = re.sub(r"^(?:File|Fájl):", "", nev, flags=re.I)
    return "File:" + nev.replace("_", " ").strip()


# ---------- 2. Wikidata ----------
def entitasok(qidek):
    """{Q: {"p18": [fájlcímek], "p373": kategória|None}} a címkézett elemekre (wbgetentities, 50/kérés)."""
    ered = cache_be("wd_entitasok.json", {})
    kell = sorted(q for q in set(qidek) if re.fullmatch(r"Q\d+", q) and q not in ered)
    print(f"Wikidata-elemek lekérése: {len(kell)} új ({len(ered)} már megvan)", flush=True)
    for i in range(0, len(kell), 50):
        resz = kell[i:i + 50]
        j = kerj(WD_API, {"action": "wbgetentities", "ids": "|".join(resz), "props": "claims", "format": "json"})
        for q in resz:
            e = (j.get("entities") or {}).get(q) or {}
            cl = e.get("claims") or {}
            p18 = [c["mainsnak"]["datavalue"]["value"] for c in cl.get("P18", [])
                   if c.get("mainsnak", {}).get("datavalue")]
            p373 = next((c["mainsnak"]["datavalue"]["value"] for c in cl.get("P373", [])
                         if c.get("mainsnak", {}).get("datavalue")), None)
            ered[q] = {"p18": [fajl_cim(x) for x in p18], "p373": p373}
        cache_ki("wd_entitasok.json", ered)
        time.sleep(SZUNET)
        if (i // 50) % 20 == 0:
            print(f"  {min(i + 50, len(kell))}/{len(kell)}", flush=True)
    return ered


def sparql_elemek():
    """Budapest összes Wikidata-eleme, amelynek van koordinátája és (P18 vagy P373): 3x3-as rácsban, időkorlát ellen."""
    ered = cache_be("wd_budapest.json", {"kesz": [], "elemek": {}})
    d, ny, e, k = VAROS_DOBOZ
    n = 3
    for a in range(n):
        for b in range(n):
            kulcs = f"{a}_{b}"
            if kulcs in ered["kesz"]:
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
            j = kerj(SPARQL, {"query": q, "format": "json"}, {"Accept": "application/sparql-results+json"}, timeout=180)
            for r in j["results"]["bindings"]:
                qid = r["item"]["value"].rsplit("/", 1)[-1]
                m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", r["coord"]["value"])
                if not m:
                    continue
                el = ered["elemek"].setdefault(qid, {"lon": float(m.group(1)), "lat": float(m.group(2)),
                                                     "p18": [], "p373": None, "cimke": ""})
                if "img" in r:
                    c = fajl_cim(r["img"]["value"])
                    if c not in el["p18"]:
                        el["p18"].append(c)
                if "cat" in r:
                    el["p373"] = r["cat"]["value"]
                if "label" in r:
                    el["cimke"] = r["label"]["value"]
            ered["kesz"].append(kulcs)
            cache_ki("wd_budapest.json", ered)
            time.sleep(5)
    print(f"  {len(ered['elemek'])} Wikidata-elem koordinátával és képpel/kategóriával", flush=True)
    return ered["elemek"]


# ---------- 3. kategóriák ----------
def kategoria_tagjai(kategoriak):
    """{kategória: [fájlcímek]} (legfeljebb 100 fájl kategóriánként)."""
    ered = cache_be("commons_kategoriak.json", {})
    kell = sorted(k for k in set(kategoriak) if k not in ered)
    print(f"Commons-kategóriák: {len(kell)} új ({len(ered)} már megvan)", flush=True)
    for i, kat in enumerate(kell, 1):
        j = kerj(ck.API, {"action": "query", "list": "categorymembers", "cmtitle": "Category:" + kat,
                          "cmtype": "file", "cmlimit": 100, "format": "json"})
        if "error" in j:
            print(f"    a Commons hibát jelzett: {str(j['error'])[:120]}", flush=True)
            time.sleep(20)
            continue
        ered[kat] = [m["title"] for m in (j.get("query") or {}).get("categorymembers", [])]
        time.sleep(SZUNET)
        if i % 25 == 0:
            cache_ki("commons_kategoriak.json", ered)
            print(f"  kategóriák: {i}/{len(kell)}", flush=True)
    cache_ki("commons_kategoriak.json", ered)
    return ered


def cimpont(fajl):
    """Fájlnév alapján pontszám a kategóriában: homlokzati kép előre, részletfotó hátra."""
    t = ck.norm(re.sub(r"\.[A-Za-z0-9]{3,4}$", "", fajl.split(":", 1)[-1]))
    if any(ck.norm(x) in t for x in ck.TILTOTT):
        return None
    return (-40 if ck.RESZLET.search(t) else 0) + (10 if "homlokzat" in t or "facade" in t else 0) \
        - (15 if "fortepan" in t else 0)


def legjobb_fajlok(tagok, db=3):
    jel = [(cimpont(f), f) for f in tagok]
    jel = [x for x in jel if x[0] is not None and re.search(r"\.(jpe?g|png|tiff?|webp)$", x[1], re.I)]
    jel.sort(key=lambda x: -x[0])
    return [f for _, f in jel[:db]]


# ---------- épületkeresés koordináta szerint ----------
def racs_epitese(ep):
    racs = defaultdict(list)
    for kulcs, e in ep.items():
        xs = [c[0] for c in e["gyuru"]]
        ys = [c[1] for c in e["gyuru"]]
        e["doboz"] = (min(xs), max(xs), min(ys), max(ys))
        for i in range(int(e["doboz"][0] / 0.001), int(e["doboz"][1] / 0.001) + 1):
            for j in range(int(e["doboz"][2] / 0.001), int(e["doboz"][3] / 0.001) + 1):
                racs[(i, j)].append(kulcs)
    return racs


def hol_van(ep, racs, lat, lon):
    legjobb, kis = None, None
    for kulcs in racs.get((int(lon / 0.001), int(lat / 0.001)), ()):
        e = ep[kulcs]
        d = e["doboz"]
        if d[0] <= lon <= d[1] and d[2] <= lat <= d[3] and ck._pont_gyuruben(lon, lat, e["gyuru"]):
            ter = (d[1] - d[0]) * (d[3] - d[2])
            if kis is None or ter < kis:
                legjobb, kis = kulcs, ter
    return legjobb


# ---------- fő ----------
def main():
    ck.VAROS = True
    ep = ck.epuletek_beolvasasa()
    print(f"Épületek: {len(ep)}", flush=True)
    meglevo_ut = ADAT / "varos" / "commons_kepek.json"
    meglevo = json.loads(meglevo_ut.read_text(encoding="utf-8")) if meglevo_ut.exists() else {}

    # 1. az OSM-címkék
    csoport_qid = defaultdict(set)          # csoportkulcs -> {Q}
    csoport_fajl = defaultdict(list)        # csoportkulcs -> [(mód, fájlcím)]
    csoport_kat = defaultdict(list)         # csoportkulcs -> [(mód, kategória)]
    osm_wd = osm_commons = 0
    for e in ep.values():
        if e.get("wikidata"):
            csoport_qid[e["kulcs"]].add(str(e["wikidata"]).split(";")[0].strip())
            osm_wd += 1
        c = (e.get("commons") or "").strip()
        if c:
            osm_commons += 1
            if re.match(r"(File|Fájl):", c, re.I):
                csoport_fajl[e["kulcs"]].append(("wd", fajl_cim(c)))
            else:
                csoport_kat[e["kulcs"]].append(("kat", re.sub(r"^(Category|Kategória):", "", c, flags=re.I).strip()))
    print(f"OSM-címkék: wikidata {osm_wd}, wikimedia_commons {osm_commons}", flush=True)

    # 2. Wikidata
    ent = entitasok([q for qs in csoport_qid.values() for q in qs])
    sp = sparql_elemek()
    racs = racs_epitese(ep)
    koord_db = 0
    for qid, el in sp.items():
        kulcs = hol_van(ep, racs, el["lat"], el["lon"])
        if kulcs:
            csoport_qid[ep[kulcs]["kulcs"]].add(qid)
            ent.setdefault(qid, {"p18": el["p18"], "p373": el["p373"]})
            koord_db += 1
    print(f"  koordináta szerint épületbe illesztett Wikidata-elem: {koord_db}", flush=True)
    for csoport, qs in csoport_qid.items():
        for q in sorted(qs):
            e = ent.get(q) or {}
            for f in e.get("p18", [])[:2]:
                csoport_fajl[csoport].append(("wd", f))
            if e.get("p373"):
                csoport_kat[csoport].append(("kat", e["p373"]))

    # 3. kategóriák
    tagok = kategoria_tagjai([k for lista in csoport_kat.values() for _, k in lista])
    jeloltek = defaultdict(list)            # csoport -> [(mód, fájlcím)] sorrendben
    for csoport in set(csoport_fajl) | set(csoport_kat):
        lista = list(csoport_fajl.get(csoport, []))
        for mod, kat in csoport_kat.get(csoport, []):
            for f in legjobb_fajlok(tagok.get(kat, [])):
                lista.append(("kat", f))
        lista = [x for i, x in enumerate(lista) if x not in lista[:i]]
        jeloltek[csoport] = lista[:6]

    # 4. képadatok
    ii = ck.imageinfo([f for lista in jeloltek.values() for _, f in lista])

    # 5. összefésülés
    uj = dict(meglevo)
    stat = defaultdict(int)
    for csoport, lista in jeloltek.items():
        for mod, cim in lista:
            info = ii.get(cim) or ii.get(cim.replace("_", " "))
            if not info:
                continue
            if not str(info.get("mime", "")).startswith("image/") or info.get("mime") in ("image/svg+xml", "image/gif"):
                continue
            if info.get("width", 0) < ck.MIN_SZELES:
                continue
            em = info.get("extmetadata") or {}
            licenc = ck.szoveg((em.get("LicenseShortName") or {}).get("value"))
            if not licenc or "non-free" in licenc.lower() or licenc.lower().startswith("fair use"):
                continue
            reszlet = 1 if ck.RESZLET.search(ck.norm(re.sub(r"\.[A-Za-z0-9]{3,4}$", "", cim.split(":", 1)[-1]))) else 0
            regi = uj.get(csoport)
            if regi:
                # jobb módú találat győz; azonos módnál a nem részletfotó
                if RANG.get(regi.get("m"), 0) > RANG[mod] or (RANG.get(regi.get("m"), 0) == RANG[mod] and (regi.get("r", 0) <= reszlet)):
                    break
            uj[csoport] = {"f": cim.split(":", 1)[-1].replace(" ", "_"),
                           "a": ck.szoveg((em.get("Artist") or {}).get("value"))[:90], "l": licenc,
                           "u": ck.szoveg((em.get("LicenseUrl") or {}).get("value")), "m": mod, "r": reszlet}
            stat[mod] += 1
            break
    meglevo_ut.parent.mkdir(parents=True, exist_ok=True)
    meglevo_ut.write_text(json.dumps(uj, ensure_ascii=False, indent=0), encoding="utf-8")
    jel = ["# Commons-fotók a Wikidata és az OSM-címkék alapján", "",
           f"- OSM `wikidata` címkével: {osm_wd} épület, `wikimedia_commons` címkével: {osm_commons} épület",
           f"- koordináta szerint épületbe illesztett Wikidata-elem (képpel vagy kategóriával): {koord_db}",
           f"- új vagy lecserélt fotó: Wikidata-kép {stat['wd']}, Commons-kategória {stat['kat']}",
           f"- épület fotóval összesen: {len(uj)}", "", "## Példák az ellenőrzéshez", ""]
    nevek = {e["kulcs"]: (e["nev"] or "") for e in ep.values()}
    pelda = [(c, k) for c, k in uj.items() if k.get("m") in ("wd", "kat")][:60]
    for c, k in pelda:
        jel.append(f"- {k['m']}; {nevek.get(c) or c}; https://commons.wikimedia.org/wiki/File:{k['f']}")
    (ADAT / "varos" / "commons_wikidata_jelentes.md").write_text("\n".join(jel) + "\n", encoding="utf-8")
    print(f"Kész: {len(uj)} épületnek van fotója (új/lecserélt: Wikidata {stat['wd']}, kategória {stat['kat']}).")
    print("Mentve: data/varos/commons_kepek.json, data/varos/commons_wikidata_jelentes.md  (most futtasd: py csempek_keszites.py)")


if __name__ == "__main__":
    main()
