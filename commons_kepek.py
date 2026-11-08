"""
commons_kepek.py - fotók a Wikimedia Commonsból az épületekhez (a kártya képéhez).

Futtatás (a projekt mappájában):   py commons_kepek.py
Kimenet:  data/commons_kepek.json        (épületenként a legjobb fotó: fájlnév, szerző, licenc)
          data/commons_kepek_jelentes.md (összesítés és példák az ellenőrzéshez)
Utána:    py csempek_keszites.py          (a 3D nézet a képeket innen veszi)

A módszer az amszterdami projekt s10_commons.py lépésének mintájára működik:
1. A vizsgált területet 300 m sugarú körökkel járja be, és a Commons helyadatos fájljait kéri le (geosearch).
2. A fájlnévből kiolvassa a címet (utca + házszám) vagy az épület nevét.
3. Egy fotó csak akkor kerül egy épülethez, ha a fájlnév ezt az épületet nevezi meg ÉS a fotó helye közel van hozzá
   (cím alapján 180 m, név alapján 120 m). Ez kizárja, hogy másik városrész azonos nevű utcájának fotója kerüljön ide.
4. Épületenként a legjobb találat marad (a cím erősebb a névnél, a közelebbi erősebb a távolabbinál).
5. A kiválasztott fájlok szerzőjét és licencét a Commons adja meg; csak a szabad licencű, kellően nagy képek maradnak.

Csak a Python alap könyvtárát használja. Az első futás pár percig tart, a letöltött nyers adatot elmenti
(data/cache/commons_geo.json), így az ismételt futás gyors.
"""
import csv
import html
import json
import math
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "budapest-by-building/0.1 (https://github.com/CseloAtti/budapest-by-building; oktatasi projekt)"}
SZUNET = 1.2         # s, két kérés között (a Wikimedia kéri, hogy ne terheljük)
ADAT = Path("data")
CACHE = ADAT / "cache" / "commons_geo.json"
DEL, NYUGAT, ESZAK, KELET = 47.488, 19.038, 47.515, 19.064      # az épületterületnél kicsit nagyobb
SUGAR = 300           # m, egy lekérdezés sugara
LEPES = 400           # m, a körök középpontjainak távolsága
CIM_TAV = 180.0       # m: címes találatnál a fotó és az épület legnagyobb távolsága
NEV_TAV = 120.0       # m: névvel találatnál
MIN_SZELES = 600      # képpont: ennél kisebb képet nem használunk
TILTOTT = ("terkep", "térkép", "map", "plan", "alaprajz", "logo", "címer", "cimer", "coat of arms", "diagram",
           "plakat", "poster", "stamp", "bélyeg")
# részletfotók (emléktábla, oltár, lépcsőház...): ezek nem az épületet mutatják, hanem egy részletét vagy belsejét
RESZLET = re.compile(r"\b(?:emlektabl|emlekhely|emlekmu|emlekmuv|plaque|stolperstein|oltar|szoszek|olvasoterem|"
                     r"lepcsohaz|lifthaz|bejarat|kapu|kapualj|udvar|erkely|detail|reszlet|szobor|statue|kut|fountain|"
                     r"freskó|mennyezet|csillar|ablak|ajto|kilincs|folyoso|terem|aula|nagyterem|kupola|sirko|koporso|"
                     r"mellekoltar|orgona|keresztut|stalla|interior|lobby|room|stairs|staircase|ceiling|window|door|"
                     r"gazcso|atepites alatt|haztartasi|elelmiszer|vendeglo|etterem teraszan|belso|inside)\w*\b")
ALTALANOS_NEV = {"budapest", "irodahaz", "iroda", "lakohaz", "haz", "epulet", "szallo", "hotel", "templom",
                 "iskola", "bank", "uzlet", "garazs", "parkolo", "ovoda", "szekhaz", "palota"}

SZUFFIX = {"utca": "utca", "u": "utca", "ut": "ut", "ter": "ter", "korut": "korut", "krt": "korut",
           "rakpart": "rakpart", "rkp": "rakpart", "koz": "koz", "setany": "setany", "fasor": "fasor",
           "sor": "sor", "park": "park", "lepcso": "lepcso"}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def tavolsag(lat1, lon1, lat2, lon2):
    dy = (lat2 - lat1) * 111_000.0
    dx = (lon2 - lon1) * 111_320.0 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


def get(params):
    for kiserlet in range(8):
        try:
            kerés = urllib.request.Request(API + "?" + urllib.parse.urlencode(dict(params, format="json")), headers=UA)
            with urllib.request.urlopen(kerés, timeout=60) as v:
                return json.load(v)
        except urllib.error.HTTPError as hiba:
            if hiba.code in (429, 503):
                var = hiba.headers.get("Retry-After")
                var = int(var) if var and var.isdigit() else 30 * (kiserlet + 1)
                print(f"    a Commons lassítást kér ({hiba.code}), várok {var} másodpercet...")
                time.sleep(var)
            else:
                print(f"    újrapróbálom ({hiba})")
                time.sleep(2 ** kiserlet)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as hiba:
            print(f"    újrapróbálom ({hiba})")
            time.sleep(2 ** kiserlet)
    raise SystemExit("A Commons nem válaszol. Futtasd újra később: a program onnan folytatja, ahol abbamaradt.")


# ---------- 1. a Commons helyadatos fájljai ----------
def kor_lekerdez(lat, lon, sugar):
    """Egy kör találatai. Ha a Commons hibaüzenetet ad (ez is 200-as válasz lehet), várunk és újrapróbáljuk:
    hibás választ soha nem szabad üres találatként elmenteni."""
    for kiserlet in range(6):
        j = get({"action": "query", "list": "geosearch", "gscoord": f"{lat}|{lon}", "gsradius": int(round(sugar)),
                 "gsnamespace": 6, "gslimit": 500})
        if "error" in j or "query" not in j:
            print(f"    a Commons hibát jelzett: {str(j.get('error') or j)[:200]} - várok és újrapróbálom")
            time.sleep(20 * (kiserlet + 1))
            continue
        return j["query"].get("geosearch", [])
    raise SystemExit("A Commons hibát ad a kérésekre. Futtasd újra később: a program onnan folytatja, ahol abbamaradt.")


def kor_bejar(lat, lon, sugar, melyseg=0):
    talalatok = kor_lekerdez(lat, lon, sugar)
    time.sleep(SZUNET)
    if len(talalatok) >= 500 and melyseg < 3:          # megtelt: négy kisebb körre bontjuk
        ki = []
        d = sugar / 2 / 111_000.0
        dl = d / math.cos(math.radians(lat))
        for a, b in ((d, dl), (d, -dl), (-d, dl), (-d, -dl)):
            ki += kor_bejar(lat + a, lon + b, max(10, int(round(sugar / 1.5))), melyseg + 1)
        return ki
    return talalatok


def fajlok_lekerese():
    """A körök találatai körönként mentve (CACHE), így egy megszakadt futás folytatható."""
    adat = {"kesz": False, "cellak": {}}
    if CACHE.exists():
        regi = json.loads(CACHE.read_text(encoding="utf-8"))
        if isinstance(regi, dict):
            adat = regi
    egyedi = lambda: {f["title"]: f for lista in adat["cellak"].values() for f in lista}
    if adat.get("kesz"):
        return list(egyedi().values())
    dlat = LEPES / 111_000.0
    dlon = LEPES / (111_320.0 * math.cos(math.radians((DEL + ESZAK) / 2)))
    kozepek = []
    lat = DEL
    while lat <= ESZAK + dlat / 2:
        lon = NYUGAT
        while lon <= KELET + dlon / 2:
            kozepek.append((lat, lon))
            lon += dlon
        lat += dlat
    print(f"Commons-keresés: {len(kozepek)} kör ({len(adat['cellak'])} már megvan)")
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    for i, (lat, lon) in enumerate(kozepek, 1):
        kulcs = f"{lat:.5f}|{lon:.5f}"
        if kulcs in adat["cellak"]:
            continue
        adat["cellak"][kulcs] = [{"title": f["title"], "lat": f["lat"], "lon": f["lon"]}
                                 for f in kor_bejar(lat, lon, SUGAR)]
        CACHE.write_text(json.dumps(adat, ensure_ascii=False), encoding="utf-8")
        print(f"  {i}/{len(kozepek)} kör kész ({len(adat['cellak'][kulcs])} találat a körben), eddig {len(egyedi())} egyedi fájl")
    adat["kesz"] = True
    CACHE.write_text(json.dumps(adat, ensure_ascii=False), encoding="utf-8")
    return list(egyedi().values())


# ---------- 2. az épületek: címek, nevek, hely ----------
def epuletek_beolvasasa():
    cimek = defaultdict(list)       # (tipus, id) -> [(utca, [házszámok])]
    ut = ADAT / "osm_cimek.csv"
    if ut.exists():
        with open(ut, encoding="utf-8-sig", newline="") as f:
            for sor in csv.DictReader(f, delimiter=";"):
                cimek[(sor["osm_tipus"], str(sor["id"]))].append((sor["utca"], szamok(sor["hazszam"])))
    g = json.load(open(ADAT / "belvaros_epuletek_vegleges.geojson", encoding="utf-8"))
    ep = {}
    for ft in g["features"]:
        p = ft["properties"]
        gy = ft["geometry"]
        kulso = gy["coordinates"][0][0] if gy["type"] == "MultiPolygon" else gy["coordinates"][0]
        lon = sum(c[0] for c in kulso) / len(kulso)
        lat = sum(c[1] for c in kulso) / len(kulso)
        tip, az = p.get("osm_tipus") or "way", str(p.get("id"))
        kulcs = (tip, az)
        if p.get("resz") and p.get("szulo_id"):
            kulcs_cim = (p.get("szulo_tipus") or "way", str(p["szulo_id"]))
        else:
            kulcs_cim = kulcs
        nevek = set()
        for n in (p.get("nev"), (p.get("lechner_nev") or "").split("/")[0], ):
            if n:
                nevek.add(norm(n))
        for c in str(p.get("wikipedia") or "").split("|"):
            if ":" in c:
                nevek.add(norm(re.sub(r"\s*\(.*\)$", "", c.split(":", 1)[1])))
        nevek = {n for n in nevek if nev_hasznalhato(n)}
        # a fotó az épületcsoport (szülő) kulcsa alá kerül, így a részek is megkapják
        csoport = kulcs_cim if p.get("resz") and p.get("szulo_id") else kulcs
        ep[kulcs] = {"kulcs": f"{csoport[0]}:{csoport[1]}", "lat": lat, "lon": lon,
                     "cimek": cimek.get(kulcs_cim, []), "nevek": nevek, "nev": p.get("nev")}
    return ep


def szamok(h):
    ki = set()
    for m in re.finditer(r"(\d+)\s*[-–]\s*(\d+)|(\d+)", str(h)):
        if m.group(1):
            a, b = int(m.group(1)), int(m.group(2))
            if 0 < b - a <= 30:
                ki.update(range(a, b + 1, 2))
                ki.add(b)
            else:
                ki.update((a, b))
        else:
            ki.add(int(m.group(3)))
    return ki


def nev_hasznalhato(n):
    t = n.split()
    if not t:
        return False
    if len(t) == 1:
        return len(n) >= 8 and n not in ALTALANOS_NEV
    return not all(x in ALTALANOS_NEV for x in t)


def utca_szuro(utca):
    """(mag, szuffix) a normalizált utcanévből: 'Arany János utca' -> ('arany janos', 'utca')."""
    t = norm(utca).split()
    if len(t) >= 2 and t[-1] in SZUFFIX:
        return " ".join(t[:-1]), SZUFFIX[t[-1]]
    return " ".join(t), ""


# ---------- 3. a párosítás ----------
def paros(fajlok, ep):
    utcak = {}      # (mag, szuffix) -> {házszám -> [kulcs]}
    for kulcs, e in ep.items():
        for utca, hsz in e["cimek"]:
            mag, szuf = utca_szuro(utca)
            if not mag:
                continue
            for n in hsz:
                utcak.setdefault((mag, szuf), {}).setdefault(n, []).append(kulcs)
    mag_db = defaultdict(int)
    for (mag, szuf) in utcak:
        mag_db[mag] += 1
    regexek = {}
    for (mag, szuf) in utcak:
        regexek[(mag, szuf)] = re.compile(
            r"\b" + re.escape(mag) + r"(?: (utca|u|ut|ter|korut|krt|rakpart|rkp|koz|setany|fasor|sor|park|lepcso))?"
            r" (\d{1,3})(?: ([a-z])\b)?(?: (\d{1,3})\b)?")
    nev_index = defaultdict(list)
    for kulcs, e in ep.items():
        for n in e["nevek"]:
            nev_index[n].append(kulcs)

    jeloltek = defaultdict(list)    # csoportkulcs -> [(pontszám, mód, fájl)]
    for f in fajlok:
        cim = f["title"].split(":", 1)[-1]
        cim = re.sub(r"\.[A-Za-z0-9]{3,4}$", "", cim)
        t = norm(cim)
        if any(norm(x) in t for x in TILTOTT):
            continue
        # a részletfotó (emléktábla, belső tér...) is jobb a semminél: csak hátrébb kerül a homlokzati fotónál
        bonusz = (-40 if RESZLET.search(t) else 0) + (10 if "homlokzat" in t or "facade" in t else 0) - (15 if "fortepan" in t else 0)
        talalat = {}                # kulcs -> (pont, mód)
        for (mag, szuf), re_ in regexek.items():
            if mag not in t:
                continue
            for m in re_.finditer(t):
                kapott = SZUFFIX.get(m.group(1) or "", "")
                if kapott and szuf and kapott != szuf:
                    continue
                if not kapott and szuf and mag_db[mag] > 1:
                    continue
                n1 = int(m.group(2))
                n2 = int(m.group(4)) if m.group(4) else None
                szamok_ = {n1} if n2 is None or not (0 < n2 - n1 <= 30) else set(range(n1, n2 + 1))
                for n in szamok_:
                    for kulcs in utcak[(mag, szuf)].get(n, []):
                        d = tavolsag(f["lat"], f["lon"], ep[kulcs]["lat"], ep[kulcs]["lon"])
                        if d <= CIM_TAV:
                            pont = 100 + (CIM_TAV - d) / 18 + bonusz
                            if kulcs not in talalat or talalat[kulcs][0] < pont:
                                talalat[kulcs] = (pont, "cim")
        if not talalat:
            for n, kulcsok in nev_index.items():
                if re.search(r"\b" + re.escape(n) + r"\b", t):
                    for kulcs in kulcsok:
                        d = tavolsag(f["lat"], f["lon"], ep[kulcs]["lat"], ep[kulcs]["lon"])
                        if d <= NEV_TAV:
                            talalat[kulcs] = (60 + (NEV_TAV - d) / 12 + bonusz, "nev")
        # ha a fájl több épületet is megnevez, a legközelebbi kapja
        if talalat:
            kulcs, (pont, mod) = max(talalat.items(), key=lambda kv: kv[1][0])
            jeloltek[ep[kulcs]["kulcs"]].append((pont, mod, f["title"], kulcs))
    legjobb = {}
    for csoport, lista in jeloltek.items():
        lista.sort(key=lambda x: -x[0])
        legjobb[csoport] = lista[:3]          # tartalék is: ha az elsőnek nincs szabad licence vagy kicsi
    return legjobb


# ---------- 4. szerző, licenc, méret ----------
def szoveg(h):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", str(h or "")))).strip()


INFO_CACHE = ADAT / "cache" / "commons_info.json"


def imageinfo(cimek):
    """Képadatok (méret, szerző, licenc); a már lekérteket a gyorsítótárból veszi."""
    eredmeny = json.loads(INFO_CACHE.read_text(encoding="utf-8")) if INFO_CACHE.exists() else {}
    cimek = sorted(c for c in set(cimek) if c not in eredmeny)
    if not cimek:
        return eredmeny
    for i in range(0, len(cimek), 40):
        reszlet = cimek[i:i + 40]
        j = get({"action": "query", "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
                 "titles": "|".join(reszlet)})
        for lap in ((j.get("query") or {}).get("pages") or {}).values():
            ii = (lap.get("imageinfo") or [None])[0]
            if ii:
                eredmeny[lap["title"]] = ii
        # a Commons a címeket normalizálhatja (pl. aláhúzás -> szóköz): ugyanígy kulcsoljuk vissza
        for atirt in ((j.get("query") or {}).get("normalized") or []):
            if atirt["to"] in eredmeny:
                eredmeny[atirt["from"]] = eredmeny[atirt["to"]]
        INFO_CACHE.write_text(json.dumps(eredmeny, ensure_ascii=False), encoding="utf-8")
        time.sleep(SZUNET)
        print(f"  képadatok: {min(i + 40, len(cimek))}/{len(cimek)}")
    return eredmeny


def main():
    ep = epuletek_beolvasasa()
    print(f"Épületek: {len(ep)}")
    fajlok = fajlok_lekerese()
    print(f"Commons-fájlok a területen: {len(fajlok)}")
    legjobb = paros(fajlok, ep)
    print(f"Névvel vagy címmel párosított épületek: {len(legjobb)}")
    ii = imageinfo([t for lista in legjobb.values() for (_, _, t, _) in lista])
    kimenet = {}
    mod_db = defaultdict(int)
    for csoport, lista in legjobb.items():
        for pont, mod, cim, kulcs in lista:
            info = ii.get(cim) or ii.get(cim.replace("_", " "))
            if not info:
                continue
            if not str(info.get("mime", "")).startswith("image/") or info.get("mime") in ("image/svg+xml", "image/gif"):
                continue
            if info.get("width", 0) < MIN_SZELES:
                continue
            em = info.get("extmetadata") or {}
            licenc = szoveg((em.get("LicenseShortName") or {}).get("value"))
            if not licenc or "non-free" in licenc.lower() or licenc.lower().startswith("fair use"):
                continue
            kimenet[csoport] = {
                "f": cim.split(":", 1)[-1].replace(" ", "_"),
                "a": szoveg((em.get("Artist") or {}).get("value"))[:90],
                "l": licenc,
                "u": szoveg((em.get("LicenseUrl") or {}).get("value")),
                "m": mod,
                "r": 1 if RESZLET.search(norm(re.sub(r"\.[A-Za-z0-9]{3,4}$", "", cim.split(":", 1)[-1]))) else 0,
            }
            mod_db[mod] += 1
            break
    (ADAT / "commons_kepek.json").write_text(json.dumps(kimenet, ensure_ascii=False, indent=0), encoding="utf-8")
    sorok = ["# Commons-fotók az épületekhez", "",
             f"- Commons-fájl a területen: {len(fajlok)}",
             f"- épület fotóval: {len(kimenet)} (cím alapján: {mod_db['cim']}, név alapján: {mod_db['nev']})", "",
             "## Példák az ellenőrzéshez (mód; épület; fájl)", ""]
    nevek = {e["kulcs"]: (e["nev"] or "") for e in ep.values()}
    for csoport, k in list(kimenet.items())[:60]:
        sorok.append(f"- {k['m']}; {nevek.get(csoport) or csoport}; https://commons.wikimedia.org/wiki/File:{k['f']}")
    (ADAT / "commons_kepek_jelentes.md").write_text("\n".join(sorok) + "\n", encoding="utf-8")
    print(f"Kész: {len(kimenet)} épületnek van fotója (cím: {mod_db['cim']}, név: {mod_db['nev']}).")
    print("Mentve: data/commons_kepek.json, data/commons_kepek_jelentes.md  (most futtasd: py csempek_keszites.py)")


if __name__ == "__main__":
    main()
