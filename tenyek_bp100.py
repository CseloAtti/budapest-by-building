"""
tenyek_bp100.py - Budapest100 (budapest100.hu) házai -> data/tenyek/budapest100.csv

Bemenet:  data/bp100/budapest100_teljes.csv   (clean_address, zip_code, building_name, building_type, built_year, era, year_source, url)
          data/varos/osm_cimek.csv            (osm_tipus;id;utca;hazszam)
          data/varos/epuletek_vegleges.geojson (csak a kerület miatt: azonos nevű utcák különböző kerületekben)
          forras/utcanev_atnevezesek.csv      (régi -> mai utcanevek)
Kimenet:  data/tenyek/budapest100.csv         ('ev' tények, forrás: budapest100)
          data/bp100_nem_parositott.csv       amit nem sikerült épülethez kötni, és miért

Futtatás:   py tenyek_bp100.py      (utána: py osszeepit.py varos)

Párosítás: utcanév + házszám az OSM-címekkel; az irányítószámból a kerület (1052 -> V., 1196 -> XIX.), és csak az ott lévő épület jöhet
szóba. Irányítószám nélkül csak akkor párosítunk, ha a cím az egész városban egyetlen kerületben létezik.
Évként csak a "pontos kifejezésből" és a "szöveg bevezetőjéből" kinyert éveket vesszük át; a "szövegben említett évszám" gyengébb
(lehet felújítás), azt kihagyjuk, és a jelentés számolja. A házszám-tartományt ("15-23") egyetlen épületegyüttesnek vesszük:
a tartomány azonos paritású számai is szóba jönnek (legfeljebb 12 széles tartományon belül).
Csak tényt (év) veszünk át; a szöveget nem. A ház oldalának címét ('budapest100_url') és - ha a tenyek_bp100_kepek.py már lefutott - a
kép címét ('budapest100_kep') is rögzítjük; a képet nem másoljuk, a kártya a budapest100.hu-ról tölti be, forrás-hivatkozással.
"""
import csv
import difflib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from kozos import tenyek_irasa

BEMENET = Path("data/bp100/budapest100_teljes.csv")
CIMEK = Path("data/varos/osm_cimek.csv")
EPULETEK = Path("data/varos/epuletek_vegleges.geojson")
ATNEVEZES = Path("forras/utcanev_atnevezesek.csv")
KIMENET = "data/tenyek/budapest100.csv"
NEM_PAROSITOTT = Path("data/bp100_nem_parositott.csv")
KEPEK = Path("data/bp100/kepek.json")        # tenyek_bp100_kepek.py: {oldal_url: kép_url}
HASONLOSAG = 0.9
JO_FORRAS = ("Szövegből (pontos kifejezés)", "Szöveg bevezetőjéből")
MAX_EPULET = 6
MAX_TARTOMANY = 12


def norm(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\bu\.", "utca", s)
    s = re.sub(r"\bkrt\.", "korut", s)
    s = re.sub(r"\bkoerut\b", "korut", s)
    s = re.sub(r"\butca\b", "utca", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(s.split())


def haz_szamok(szoveg):
    """'11-13' -> {11,12,13 azonos paritásúak: 11, 13}; '15/A, B' -> {15}; '4;6' -> {4, 6}"""
    ki = set()
    for a, b in re.findall(r"(\d+)\s*(?:[-–]\s*(\d+))?", szoveg or ""):
        a = int(a)
        ki.add(a)
        if b:
            b = int(b)
            ki.add(b)
            if a < b <= a + MAX_TARTOMANY and (b - a) % 2 == 0:
                ki.update(range(a, b + 1, 2))
    return ki


def cim_felbontas(cim):
    """'Károly körút 22.' -> ('Károly körút', {22}); 'Október 6. utca 3.' kezelve."""
    kezdet = 0
    h = re.search(r"\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+ \d+\.(?=\s+(?:utca|tér|út)\b)", cim)
    if h:
        kezdet = h.end()
    m = re.search(r"\d", cim[kezdet:])
    if not m:
        return None, set()
    p = kezdet + m.start()
    return cim[:p].strip(" ,"), haz_szamok(cim[p:])


def kerulet_irszambol(zip_kod):
    try:
        z = int(float(zip_kod))
    except (TypeError, ValueError):
        return None
    if 1011 <= z <= 1239:
        k = (z // 10) % 100
        return k if 1 <= k <= 23 else None
    return None


def kerulet_szam(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        pass
    romai = {"I": 1, "V": 5, "X": 10}
    s = str(x or "").strip().rstrip(".").upper()
    if s and all(c in romai for c in s):
        t = 0
        for c, n in zip(s, s[1:] + " "):
            v = romai[c]
            t += -v if n in romai and romai[n] > v else v
        return t
    return None


def kerulet_terkep():
    """(osm_tipus, id) -> kerület száma, az épületfájlból."""
    if not EPULETEK.exists():
        return {}
    with open(EPULETEK, encoding="utf-8") as f:
        g = json.load(f)
    ki = {}
    for ft in g["features"]:
        p = ft["properties"]
        k = kerulet_szam(p.get("kerulet"))
        if k:
            ki[(p.get("osm_tipus") or "way", int(p["id"]))] = k
    return ki


def main():
    if not BEMENET.exists():
        sys.exit("Nincs " + str(BEMENET))
    atn = {}
    if ATNEVEZES.exists():
        for r in csv.DictReader(open(ATNEVEZES, encoding="utf-8-sig", newline=""), delimiter=";"):
            if r.get("regi") and r.get("uj"):
                atn[norm(r["regi"])] = [norm(x) for x in r["uj"].split("|") if x.strip()]
    kerulet = kerulet_terkep()
    print("Épület a kerület-térképen:", len(kerulet))
    utcak = defaultdict(lambda: defaultdict(list))
    for r in csv.DictReader(open(CIMEK, encoding="utf-8-sig", newline=""), delimiter=";"):
        for sz in haz_szamok(r["hazszam"]):
            utcak[norm(r["utca"])][sz].append((r["osm_tipus"], int(r["id"])))
    osm_utcak = list(utcak)

    def utca_jeloltek(utca):
        n = norm(utca)
        ki = []
        for j in atn.get(n, [n]):
            if j in utcak:
                ki.append(j)
            else:
                jo = difflib.get_close_matches(j, osm_utcak, n=1, cutoff=HASONLOSAG)
                if jo:
                    ki.append(jo[0])
        return list(dict.fromkeys(ki))

    sorok = list(csv.DictReader(open(BEMENET, encoding="utf-8-sig", newline="")))
    stat = Counter()
    kepek = json.load(open(KEPEK, encoding="utf-8")) if KEPEK.exists() else {}
    kesz, kimaradt = set(), []
    for r in sorok:
        ev = (r.get("built_year") or "").strip()
        # év nélkül is párosítunk (a link miatt), de évet csak megbízható forrásból veszünk át
        if not ev:
            stat["nincs év a forrásban"] += 1
            ev = None
        elif r.get("year_source") not in JO_FORRAS:
            stat["gyenge évforrás (évet nem veszünk át)"] += 1
            ev = None
        else:
            try:
                ev = int(float(ev))
            except ValueError:
                stat["hibás év"] += 1
                ev = None
            else:
                if not 1000 <= ev <= 2030:
                    stat["hihetetlen év"] += 1
                    ev = None
        cim = (r.get("clean_address") or "").strip()
        u, sz = cim_felbontas(cim)
        if not u or not sz:
            kimaradt.append([cim, ev, "nincs házszám"])
            stat["nincs házszám a címben"] += 1
            continue
        jeloltek = utca_jeloltek(u)
        if not jeloltek:
            kimaradt.append([cim, ev, "ismeretlen utcanév"])
            stat["ismeretlen utcanév"] += 1
            continue
        talalat = set()
        for mu in jeloltek:
            for n in sz:
                talalat.update(utcak[mu].get(n, []))
        if not talalat:
            kimaradt.append([cim, ev, "az utcán nincs ilyen házszámú OSM-épület"])
            stat["nincs ilyen házszám"] += 1
            continue
        ker = kerulet_irszambol(r.get("zip_code"))
        if kerulet:
            if ker:
                talalat = {t for t in talalat if kerulet.get(t) == ker}
                if not talalat:
                    kimaradt.append([cim, ev, "a megadott kerületben (%s.) nincs ilyen című épület" % ker])
                    stat["nincs ilyen című épület a kerületben"] += 1
                    continue
            else:
                kerek = {kerulet.get(t) for t in talalat}
                if len(kerek) > 1:
                    kimaradt.append([cim, ev, "irányítószám nélkül több kerületben is van ilyen cím"])
                    stat["kétértelmű (nincs irányítószám)"] += 1
                    continue
        if len(talalat) > MAX_EPULET:
            kimaradt.append([cim, ev, "túl sok (%d) lehetséges épület" % len(talalat)])
            stat["túl sok jelölt"] += 1
            continue
        stat["párosítva"] += 1
        stat["párosított OSM-épület"] += len(talalat)
        megj = f"Budapest100: {cim}" + (f" ({len(talalat)} OSM-épület)" if len(talalat) > 1 else "") + f" {r.get('url', '')}"
        url = (r.get("url") or "").strip()
        if not re.fullmatch(r"https://budapest100\.hu/house/[A-Za-z0-9_%\-]+/?", url):
            url = ""
        for t, i in talalat:
            if ev:
                kesz.add((t, i, "ev", ev, "budapest100", megj.strip()))
            if url:
                kesz.add((t, i, "budapest100_url", url, "budapest100", megj.strip()))
                kep = kepek.get(url) or kepek.get(url.rstrip("/") + "/") or kepek.get(url.rstrip("/")) or {}
                if isinstance(kep, str):
                    kep = {"kep": kep, "foto": ""}
                if kep.get("kep"):
                    kesz.add((t, i, "budapest100_kep", kep["kep"], "budapest100", megj.strip()))
                    if kep.get("foto"):
                        kesz.add((t, i, "budapest100_foto", kep["foto"], "budapest100", megj.strip()))
    tenyek_irasa(KIMENET, sorted(kesz, key=lambda s: (s[0], s[1], s[2])))
    with open(NEM_PAROSITOTT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["cim", "ev", "miert"])
        w.writerows(kimaradt)
    print(f"Bejegyzés: {len(sorok)}")
    for k, v in stat.most_common():
        print(f"  {k}: {v}")
    print(f"Tények: {len(kesz)} sor -> {KIMENET}; nem párosított: {NEM_PAROSITOTT}")


if __name__ == "__main__":
    main()
