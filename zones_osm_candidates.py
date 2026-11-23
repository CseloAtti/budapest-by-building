"""
zones_osm_candidates.py - for the zones of forras/zona_lista.csv, searches for a polygon by name in the OSM extract.

Run (in the project folder, where budapest_pbf.py is too):
    py zones_osm_candidates.py                 # only from the data/pbf/*.osm.pbf file, without network
    py zones_osm_candidates.py --nominatim     # it also asks Nominatim for the missing ones (1 request/s)

Output:
    data/zonak_jeloltek.geojson   the polygons found (WGS84, lon/lat), with the year and the source
    data/zonak_jeloltek.csv       per zone: type of match, OSM id, OSM name
    data/zonak_hianyzo.csv        what we did not find (these have to be drawn by hand)

Of the housing estates (lt_*) and rule rows (sz_*) it searches only for the housing estates, and the estates (ze_*) too.
A match is 'pontos' (exact) if the words of the OSM name equal the zone name, and 'reszleges' (partial) if the words of the zone name
are all contained in the OSM name. It does NOT check the district: review the matches on the map!
"""
import csv
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

from budapest_pbf import (blokkok, blokk_olvasas, mezok, csomagolt, delta, cikcakk, cimkek,
                          gyurukke_fuz, pont, EGYSEG, UA)

ADAT = Path("data")
PBF_MAPPA = ADAT / "pbf"
CSV_BE = Path("forras") / "zona_lista.csv"
TIPUS_KULCSOK = ("landuse", "place", "leisure", "boundary", "residential", "building:use")
LEHETSEGES_LANDUSE = {"residential", "commercial", "retail", "industrial", "garages", "allotments"}
LEHETSEGES_PLACE = {"quarter", "neighbourhood", "suburb", "city_block", "locality", "borough"}
STOP = {"lakotelep", "telep", "telepe", "utcai", "utca", "uti", "ut", "u", "ter", "teri", "kertvaros",
        "negyed", "i", "ii", "iii", "utem", "varoskozpont", "varos", "park", "lakopark", "tisztviselotelep"}


def norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return s


def szavak(s):
    return {w for w in norm(s).split() if w not in STOP and not w.isdigit()}


def zonak_beolvasasa():
    zonak = []
    with open(CSV_BE, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r["id"].startswith("sz_"):
                continue
            nev = re.sub(r"\(.*?\)", " ", r["nev"])
            r["_szavak"] = szavak(nev)
            r["_nev_norm"] = " ".join(sorted(r["_szavak"]))
            if r["_szavak"]:
                zonak.append(r)
    return zonak


def egyezes(zona, osm_nev):
    """pontos / reszleges / None"""
    o = szavak(osm_nev)
    z = zona["_szavak"]
    if not o:
        return None
    if o == z:
        return "pontos"
    if z <= o and len(" ".join(z)) >= 5:
        return "reszleges"
    return None


def jelolt_e(cimke):
    if "name" not in cimke:
        return False
    if cimke.get("place") in LEHETSEGES_PLACE:
        return True
    if cimke.get("landuse") in LEHETSEGES_LANDUSE:
        return True
    if cimke.get("boundary") in ("administrative", "place", "census") and cimke.get("admin_level", "9") in ("9", "10", "11", "12"):
        return True
    if "residential" in cimke or cimke.get("leisure") == "park":
        return False
    return False


def tobb_zona_egyezik(cimke, zonak):
    talalatok = []
    for nev_kulcs in ("name", "alt_name", "old_name"):
        nev = cimke.get(nev_kulcs)
        if not nev:
            continue
        for z in zonak:
            e = egyezes(z, nev)
            if e:
                talalatok.append((z, e, nev))
    return talalatok


def pbf_keresese():
    fajlok = sorted(PBF_MAPPA.glob("*.pbf"))
    if not fajlok:
        sys.exit("Nincs PBF a data/pbf mappában. Előbb futtasd: py budapest_pbf.py")
    return max(fajlok, key=lambda p: p.stat().st_size)


def menet_kapcsolatok_es_vonalak(ut, zonak):
    """Pass 1: the named, tagged ways and relations. Pass 2: the member ways of the relations."""
    vonal_talalat = {}      # vonal azon -> (cimke, hivatkozasok, [(zona, tipus, nev)])
    kapcs_talalat = {}      # kapcsolat azon -> (cimke, [(tagvonal, szerep)], talalatok)
    for tipus, adat in blokkok(ut):
        if tipus != "OSMData":
            continue
        szotar, gran, lat0, lon0, csoportok = blokk_olvasas(adat)
        for cs in csoportok:
            for sz, t, v in mezok(cs):
                if sz == 3:                                   # vonal
                    azon = 0
                    kulcsok = ertekek = []
                    hiv = b""
                    for s2, t2, x in mezok(v):
                        if s2 == 1:
                            azon = x
                        elif s2 == 2:
                            kulcsok = csomagolt(x)
                        elif s2 == 3:
                            ertekek = csomagolt(x)
                        elif s2 == 8:
                            hiv = x
                    if not kulcsok:
                        continue
                    c = cimkek(szotar, kulcsok, ertekek)
                    if jelolt_e(c):
                        tl = tobb_zona_egyezik(c, zonak)
                        if tl:
                            vonal_talalat[azon] = (c, delta(csomagolt(hiv)), tl)
                elif sz == 4:                                 # kapcsolat
                    azon = 0
                    kulcsok = ertekek = szerepek = azonok = tipusok = []
                    for s2, t2, x in mezok(v):
                        if s2 == 1:
                            azon = x
                        elif s2 == 2:
                            kulcsok = csomagolt(x)
                        elif s2 == 3:
                            ertekek = csomagolt(x)
                        elif s2 == 8:
                            szerepek = csomagolt(x)
                        elif s2 == 9:
                            azonok = delta(csomagolt(x))
                        elif s2 == 10:
                            tipusok = csomagolt(x)
                    if not kulcsok:
                        continue
                    c = cimkek(szotar, kulcsok, ertekek)
                    if c.get("type") in ("multipolygon", "boundary") and jelolt_e(c):
                        tl = tobb_zona_egyezik(c, zonak)
                        if tl:
                            tagok = [(mid, szotar[sid]) for sid, mid, mt in zip(szerepek, azonok, tipusok) if mt == 1]
                            kapcs_talalat[azon] = (c, tagok, tl)
    # the member ways of the relations
    kell = {mid for _, tagok, _ in kapcs_talalat.values() for mid, _ in tagok}
    tag_vonalak = {}
    if kell:
        for tipus, adat in blokkok(ut):
            if tipus != "OSMData":
                continue
            szotar, gran, lat0, lon0, csoportok = blokk_olvasas(adat)
            for cs in csoportok:
                for sz, t, v in mezok(cs):
                    if sz != 3:
                        continue
                    azon = 0
                    hiv = b""
                    for s2, t2, x in mezok(v):
                        if s2 == 1:
                            azon = x
                        elif s2 == 8:
                            hiv = x
                    if azon in kell:
                        tag_vonalak[azon] = delta(csomagolt(hiv))
    return vonal_talalat, kapcs_talalat, tag_vonalak


def csomopontok_olvasasa(ut, kellek):
    """Coordinates of only the requested node ids: {id: (lon, lat)}."""
    ki = {}
    maradt = set(kellek)
    for tipus, adat in blokkok(ut):
        if tipus != "OSMData":
            continue
        szotar, gran, lat0, lon0, csoportok = blokk_olvasas(adat)
        for cs in csoportok:
            for sz, t, v in mezok(cs):
                if sz == 2:
                    azonok = lat = lon = None
                    for s2, t2, x in mezok(v):
                        if s2 == 1:
                            azonok = delta(csomagolt(x))
                        elif s2 == 8:
                            lat = delta(csomagolt(x))
                        elif s2 == 9:
                            lon = delta(csomagolt(x))
                    if azonok is None:
                        continue
                    for a, la, lo in zip(azonok, lat, lon):
                        if a in maradt:
                            ki[a] = ((lon0 + gran * lo) / 1e9, (lat0 + gran * la) / 1e9)
                            maradt.discard(a)
                elif sz == 1:
                    azon = la = lo = 0
                    for s2, t2, x in mezok(v):
                        if s2 == 1:
                            azon = cikcakk(x)
                        elif s2 == 8:
                            la = cikcakk(x)
                        elif s2 == 9:
                            lo = cikcakk(x)
                    if azon in maradt:
                        ki[azon] = ((lon0 + gran * lo) / 1e9, (lat0 + gran * la) / 1e9)
                        maradt.discard(azon)
    return ki


def terulet(gyuru):
    s = 0.0
    for (x1, y1), (x2, y2) in zip(gyuru, gyuru[1:]):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def geometria(vonalak, csomagok):
    """ways: [lists of refs] -> GeoJSON Polygon/MultiPolygon (outer rings, without holes)."""
    gyuruk = gyurukke_fuz([list(v) for v in vonalak])
    ki = []
    for g in gyuruk:
        koord = [csomagok[r] for r in g if r in csomagok]
        if len(koord) >= 4 and koord[0] == koord[-1]:
            ki.append(koord)
    if not ki:
        return None
    if len(ki) == 1:
        return {"type": "Polygon", "coordinates": [ki[0]]}
    return {"type": "MultiPolygon", "coordinates": [[g] for g in ki]}


def nominatim_kerdes(q, bounded):
    parameterek = {"q": q, "format": "jsonv2", "polygon_geojson": 1, "limit": 5, "countrycodes": "hu"}
    if bounded:
        parameterek.update({"viewbox": "18.90,47.62,19.35,47.35", "bounded": 1})
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(parameterek)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def nominatim(zona):
    """Several query variants; returns the hit that gives the first polygon. It logs what it got."""
    nev = re.sub(r"\(.*?\)", " ", zona["nev"]).strip()
    mag = re.sub(r"\b(lakótelep|telep)\b", " ", nev, flags=re.I).strip()
    valtozatok = [(nev + ", Budapest", True), (nev + ", Budapest", False), (mag + ", Budapest", True)]
    latott = []
    for q, bounded in valtozatok:
        time.sleep(1.1)
        adat = nominatim_kerdes(q, bounded)
        latott.append("%s%s: %s" % (q, "" if bounded else " [nincs doboz]",
                      ",".join((e.get("geojson") or {}).get("type", "-") + ":" + e.get("class", "?") for e in adat) or "0 találat"))
        for e in adat:
            g = e.get("geojson")
            if g and g.get("type") in ("Polygon", "MultiPolygon"):
                return g, e, latott
    return None, None, latott


def main():
    nominatim_kell = "--nominatim" in sys.argv[1:]
    zonak = zonak_beolvasasa()
    ut = pbf_keresese()
    print("PBF:", ut, "| zónák:", len(zonak))
    vonal_t, kapcs_t, tag_v = menet_kapcsolatok_es_vonalak(ut, zonak)
    print("nevesített vonal-jelölt:", len(vonal_t), "| kapcsolat-jelölt:", len(kapcs_t))
    kellek = set()
    for c, hiv, tl in vonal_t.values():
        kellek.update(hiv)
    for refs in tag_v.values():
        kellek.update(refs)
    csomagok = csomopontok_olvasasa(ut, kellek)

    jeloltek = {}   # zone id -> list (accuracy, source, geometry, osm name, osm id)
    rang = {"pontos": 0, "reszleges": 1}
    for azon, (c, hiv, tl) in vonal_t.items():
        g = geometria([hiv], csomagok)
        if not g:
            continue
        for z, e, nev in tl:
            jeloltek.setdefault(z["id"], []).append((e, "way/%d" % azon, g, nev))
    for azon, (c, tagok, tl) in kapcs_t.items():
        kulso = [tag_v[mid] for mid, szerep in tagok if mid in tag_v and szerep in ("outer", "")]
        g = geometria(kulso, csomagok)
        if not g:
            continue
        for z, e, nev in tl:
            jeloltek.setdefault(z["id"], []).append((e, "relation/%d" % azon, g, nev))

    jellemzok = []
    sorok = []
    hianyzo = []
    for z in zonak:
        lista = sorted(jeloltek.get(z["id"], []), key=lambda x: (rang[x[0]],
                       -max((terulet(r) for r in ([x[2]["coordinates"][0]] if x[2]["type"] == "Polygon" else [p[0] for p in x[2]["coordinates"]])), default=0)))
        mod = None
        if lista:
            e, osm_id, g, nev = lista[0]
            mod = "osm_" + e
        elif nominatim_kell:
            try:
                g, ent, napl = nominatim(z)
                print("Nominatim:", z["nev"], "->", "TALÁLAT" if g else "nincs poligon", "|", " || ".join(napl)[:300], flush=True)
                if g:
                    osm_id = "%s/%s" % (ent.get("osm_type"), ent.get("osm_id"))
                    nev = ent.get("display_name", "")[:80]
                    mod = "nominatim"
            except Exception as ex:
                print("Nominatim hiba:", z["nev"], ex)
        if not mod:
            hianyzo.append([z["id"], z["nev"], z["kerulet"], z["ev_tol"], z["ev_ig"], z["allapot"]])
            continue
        jellemzok.append({"type": "Feature", "geometry": g, "properties": {
            "id": z["id"], "nev": z["nev"], "tipus": z["tipus"], "kerulet": z["kerulet"],
            "ev_tol": int(z["ev_tol"]), "ev_ig": int(z["ev_ig"]), "allapot": z["allapot"],
            "forras": z["forras"], "egyezes": mod, "osm": osm_id, "osm_nev": nev,
            "tobb_jelolt": len(lista)}})
        sorok.append([z["id"], z["nev"], z["kerulet"], mod, osm_id, nev, len(lista)])

    with open(ADAT / "zonak_jeloltek.geojson", "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": jellemzok}, f, ensure_ascii=False)
    with open(ADAT / "zonak_jeloltek.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["id", "nev", "kerulet", "egyezes", "osm", "osm_nev", "jeloltek_szama"])
        w.writerows(sorok)
    with open(ADAT / "zonak_hianyzo.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["id", "nev", "kerulet", "ev_tol", "ev_ig", "allapot"])
        w.writerows(hianyzo)
    print("Megtalált: %d / %d zóna; hiányzik: %d" % (len(jellemzok), len(zonak), len(hianyzo)))
    print("-> data/zonak_jeloltek.geojson, data/zonak_jeloltek.csv, data/zonak_hianyzo.csv")


if __name__ == "__main__":
    main()
