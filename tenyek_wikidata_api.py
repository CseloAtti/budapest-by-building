"""Wikidata, koordináta alapján, a normál API-n keresztül (nem a lekérdező szerveren)
-> data/tenyek/wikidata_terulet.csv   (ugyanaz a kimenet, mint a tenyek_wikidata_terulet.py-é)

Lépések: 1) földrajzi keresés rácsonként, 2) az elemek adatainak lekérése,
3) csak az épület-jellegű elemek megtartása (P31 -> P279 lánc a 'building' osztályig),
4) párosítás az épületkörvonalainkhoz.
A Wikidata tartalma CC0 (szabadon felhasználható).
"""
import hashlib
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

from kozos import http_json, kulcs, legkozelebbi_csucs_m, pont_barmelyikben, poligonok, tenyek_irasa
from tenyek_wikidata import (API, CACHE, KLIENS, SZUNET_MP, cimke, csomagokban, elemek_id,
                             ev_a_claimekbol, lekeres, wikipedia_cikk)

OSM = "data/belvaros_epuletek.geojson"
KIMENET = "data/tenyek/wikidata_terulet.csv"
DEL, NYUGAT, ESZAK, KELET = 47.490, 19.040, 47.513, 19.062
RACS = 4                # a területet RACS x RACS darabra osztjuk (egy keresés max. 500 találatot ad)
KOZELI_METER = 10
EPULET = "Q41176"       # building
MAX_MELYSEG = 7


def geokeres(d0, w0, d1, w1):
    nev = "wdgeo_" + hashlib.sha1(f"{d0}{w0}{d1}{w1}".encode()).hexdigest()[:12] + ".json"
    ut = CACHE / nev
    if ut.exists():
        return json.loads(ut.read_text(encoding="utf-8"))
    url = API + "?" + urllib.parse.urlencode({
        "action": "query", "list": "geosearch", "gsbbox": f"{d1}|{w0}|{d0}|{w1}",
        "gslimit": 500, "format": "json"})
    adat = http_json(url)
    CACHE.mkdir(parents=True, exist_ok=True)
    ut.write_text(json.dumps(adat, ensure_ascii=False), encoding="utf-8")
    time.sleep(SZUNET_MP)
    return adat


def epulet_osztalyok(osztalyok):
    """Melyik osztály éri el a 'building' osztályt az alosztály-láncon (P279)."""
    szulok, kesz = {}, set()
    ma = set(osztalyok)
    for _ in range(MAX_MELYSEG):
        uj = [q for q in ma if q not in kesz]
        if not uj:
            break
        for cs in csomagokban(sorted(uj), 50):
            for q, e in lekeres(cs, "claims").get("entities", {}).items():
                szulok[q] = elemek_id(e.get("claims", {}), "P279")
                kesz.add(q)
        ma = {p for q in uj for p in szulok.get(q, [])}
    eredmeny = {}

    def eler(q, latott=()):
        if q == EPULET:
            return True
        if q in eredmeny:
            return eredmeny[q]
        if q in latott:
            return False
        ok = any(eler(p, latott + (q,)) for p in szulok.get(q, []))
        eredmeny[q] = ok
        return ok
    return {q for q in osztalyok if eler(q)}


def main():
    # 1) földrajzi keresés
    talalatok = {}
    for i in range(RACS):
        for j in range(RACS):
            d0 = DEL + (ESZAK - DEL) * i / RACS
            d1 = DEL + (ESZAK - DEL) * (i + 1) / RACS
            w0 = NYUGAT + (KELET - NYUGAT) * j / RACS
            w1 = NYUGAT + (KELET - NYUGAT) * (j + 1) / RACS
            lista = geokeres(d0, w0, d1, w1).get("query", {}).get("geosearch", [])
            if len(lista) >= 500:
                print(f"Figyelem: a rács ({i},{j}) cellájában elérte a 500-as korlátot, adat hiányozhat.")
            for r in lista:
                if str(r.get("title", "")).startswith("Q"):
                    talalatok[r["title"]] = (r["lon"], r["lat"])
    print(f"Koordinátás Wikidata-elemek a területen: {len(talalatok)}")

    # 2) az elemek adatai
    entitasok = {}
    for cs in csomagokban(sorted(talalatok), 50):
        entitasok.update(lekeres(cs, "claims|labels|sitelinks").get("entities", {}))

    # 3) csak épületek, építési évvel
    jeloltek = {}
    for q, e in entitasok.items():
        cl = e.get("claims", {})
        if ev_a_claimekbol(cl):
            jeloltek[q] = e
    osztalyok = {c for e in jeloltek.values() for c in elemek_id(e.get("claims", {}), "P31")}
    epulet_cl = epulet_osztalyok(osztalyok)
    epuletek = {q: e for q, e in jeloltek.items()
                if any(c in epulet_cl for c in elemek_id(e.get("claims", {}), "P31"))}
    print(f"Építési évvel: {len(jeloltek)}, ebből épület-jellegű: {len(epuletek)}")

    masodlagos = set()
    for e in epuletek.values():
        masodlagos.update(elemek_id(e.get("claims", {}), "P84"))
        masodlagos.update(elemek_id(e.get("claims", {}), "P149"))
    nevek = {}
    for cs in csomagokban(sorted(masodlagos), 50):
        for q, e in lekeres(cs, "labels").get("entities", {}).items():
            nevek[q] = cimke(e)

    # 4) párosítás
    with open(OSM, encoding="utf-8") as f:
        feats = [x for x in json.load(f)["features"] if x["properties"].get("tipus") != "roof"]
    polik = [(ft, poligonok(ft["geometry"])) for ft in feats]
    legjobb, belul, kozeli, nincs = {}, 0, 0, 0
    for q, e in epuletek.items():
        x, y = talalatok[q]
        talalat, mod = None, None
        for ft, pl in polik:
            if pl and pont_barmelyikben(x, y, pl):
                talalat, mod = ft, "wikidata"
                break
        if talalat is None:
            tav = KOZELI_METER
            for ft, pl in polik:
                if pl:
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
        if elozo is None or (mod == "wikidata" and elozo[0] != "wikidata"):
            legjobb[k] = (mod, q, e)

    sorok = []
    for (t, i), (mod, q, e) in legjobb.items():
        cl = e.get("claims", {})
        sorok.append((t, i, "wikidata_id", q, mod, ""))
        if cimke(e):
            sorok.append((t, i, "wikidata_nev", cimke(e), mod, q))
        if wikipedia_cikk(e):
            sorok.append((t, i, "wikipedia", wikipedia_cikk(e), mod, q))
        sorok.append((t, i, "ev", ev_a_claimekbol(cl), mod, f"{q}: P571"))
        epitesz = [nevek.get(x) for x in elemek_id(cl, "P84") if nevek.get(x)]
        if epitesz:
            sorok.append((t, i, "tervezo", ", ".join(epitesz), mod, q))
        stilus = [nevek.get(x) for x in elemek_id(cl, "P149") if nevek.get(x)]
        if stilus:
            sorok.append((t, i, "stilus", ", ".join(stilus), mod, q))
    tenyek_irasa(KIMENET, sorok)
    print(f"Épületbe esik: {belul}, közeli (≤{KOZELI_METER} m): {kozeli}, nem párosítható: {nincs}")
    print(f"Épület, amelyhez adat került: {len(legjobb)}")
    print(f"Mentve: {KIMENET}")


if __name__ == "__main__":
    main()
