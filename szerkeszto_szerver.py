"""Helyi szerver a térképhez, szerkesztési móddal.

Elindítás (a projekt mappájában):   py szerkeszto_szerver.py
Megnyitás a böngészőben:            http://localhost:8000

Ugyanazt tudja, mint a `py -m http.server 8000`, de a térképen az épületek adatait
a popupban a "Szerkesztés" gombbal javítani lehet. A javítások a forras/kezi_javitasok.csv
fájlba kerülnek (ezek mindig győznek). A "Térkép újraépítése" gomb lefuttatja az osszeepit.py-t.

Biztonság: a szerver csak a saját gépedről érhető el (127.0.0.1), csak ezt az egy fájlt írja,
és minden beírt értéket ellenőriz.
"""
import csv
import json
import math
import re
import unicodedata
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8000
KEZI = Path("forras/kezi_javitasok.csv")
FEJLEC = ["osm_tipus", "id", "mezo", "ertek", "forras", "megjegyzes", "lat", "lon"]
SZAMOS = {"ev": (1000, 2100), "szintek": (1, 80), "magassag": (1, 500)}
SZOVEGES = {"tervezo", "stilus"}
EGYSOROS = {"nev": 120}                      # az épület neve
HOSSZU_SZOVEG = {"about": 1500}              # szabad szöveges leírás (több bekezdés is lehet)
VEDETTSEG_KODOK = {"M", "MJ", "VK", "MK", "MJT"}   # műemlék, műemlék jellegű, városképi, műemléki környezet, műemléki jelentőségű terület
ENGEDELYEZETT_ORIGIN = {f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}"}

# --- zónák (poligonok) a zonak.html szerkesztőből ---
ZONAK = Path("forras/zonak_poligon.geojson")
ZONA_TIPUSOK = {"lakotelep", "telep", "kertvaros", "negyed", "lakopark", "ipar_kereskedelem", "egyeb", "muemlek"}
ZONA_ALLAPOTOK = {"helyismeret", "forrasolt", "ellenorizendo"}
ZONA_EREDET = {"kezi", "osm", "nominatim", "epuletbol", "lista"}
MAX_ZONA_KERES = 3_000_000
ELVETETT = Path("forras/zona_elvetett.json")   # a szerkesztőben véglegesen törölt zónalista-tételek / jelöltek azonosítói


def elvetett_mentese(adat):
    """{"ids": [...]} -> forras/zona_elvetett.json (a régi állapot .bak.json-ban marad). Visszaad: (db, hiba)."""
    ids = adat.get("ids") if isinstance(adat, dict) else None
    if not isinstance(ids, list) or len(ids) > 5000:
        return None, "Hibás kérés."
    tiszta = []
    for x in ids:
        if not isinstance(x, str) or not x or len(x) > 120 or re.search(r"[\x00-\x1f<>]", x):
            return None, "Hibás azonosító."
        if x not in tiszta:
            tiszta.append(x)
    ELVETETT.parent.mkdir(exist_ok=True)
    if ELVETETT.exists():
        try:
            ELVETETT.replace(ELVETETT.with_suffix(".bak.json"))
        except OSError:
            pass
    ido = ELVETETT.with_suffix(".tmp")
    ido.write_text(json.dumps({"ids": sorted(tiszta)}, ensure_ascii=False, indent=1), encoding="utf-8")
    ido.replace(ELVETETT)
    return len(tiszta), None



def tiszta_szoveg(x, max_hossz):
    x = " ".join(str(x).split())          # sortörések, tabok, dupla szóközök ki
    if not x or len(x) > max_hossz or re.search(r"[\x00-\x1f;]", str(x)):
        return None
    return x


def szabad_szoveg(x, max_hossz, tobb_sor):
    """Szabad szöveg: a vezérlőkarakterek (a sortörés kivételével) tiltottak; ';' megengedett (a CSV idézi)."""
    x = str(x).replace("\r\n", "\n").replace("\r", "\n")
    if tobb_sor:
        sorok = [" ".join(s.split()) for s in x.split("\n")]
        x = "\n".join(sorok).strip()
        while "\n\n\n" in x:
            x = x.replace("\n\n\n", "\n\n")
    else:
        x = " ".join(x.split())
    if not x or len(x) > max_hossz or re.search(r"[\x00-\x09\x0b-\x1f\x7f<>]", x):
        return None
    return x


def wikipedia_cim(x):
    """Elfogad: 'https://hu.wikipedia.org/wiki/Cím' (a mobil 'hu.m.' és a séma nélküli alak is), 'hu:Cím', 'en:Cím',
    vagy egy sima cím ('Vécsey utcai lakótelep' -> hu:Vécsey utcai lakótelep). Kimenet: 'hu:Cím' (csak hu/en)."""
    x = str(x).strip().strip("\"'“”„").strip()
    m = re.match(r"^(?:https?://)?(hu|en)(?:\.m)?\.wikipedia\.org/wiki/([^?#\s]+)(?:[#?].*)?$", x)
    if m:
        nyelv, cim = m.group(1), urllib.parse.unquote(m.group(2)).replace("_", " ")
    elif re.match(r"^(?:https?://)?(hu|en)(?:\.m)?\.wikipedia\.org/w/index\.php\?", x):
        # szerkesztési/permalink alak: /w/index.php?title=Cím&oldid=123 -> a title paraméter
        m = re.match(r"^(?:https?://)?(hu|en)(?:\.m)?\.wikipedia\.org/w/index\.php\?(.*)$", x)
        t = urllib.parse.parse_qs(m.group(2).split("#")[0]).get("title")
        if not t:
            return None
        nyelv, cim = m.group(1), t[0].replace("_", " ")
    else:
        m = re.match(r"^(hu|en):(.+)$", x)
        if m:
            nyelv, cim = m.group(1), m.group(2).strip()
        elif re.match(r"^(?:https?://|www\.)", x, re.I) or re.search(r"\.(org|com|hu|net)\b", x, re.I):
            return None                      # más oldal linkje: nem Wikipedia-cikk
        else:
            nyelv, cim = "hu", x             # sima cím: magyar cikknek vesszük
    cim = " ".join(cim.split()).rstrip("/")
    if not cim or len(cim) > 150 or re.search(r"[\x00-\x1f;|<>\[\]{}]", cim):
        return None
    return f"{nyelv}:{cim}"


def wikipedia_cikkek(x):
    """Több cikk '|' jellel elválasztva (legfeljebb 3); '-' = a mező eltávolítása."""
    x = str(x).strip()
    if x == "-":
        return "-"
    reszek = [wikipedia_cim(r) for r in x.split("|") if r.strip()]
    if not reszek or len(reszek) > 3 or any(r is None for r in reszek):
        return None
    return "|".join(dict.fromkeys(reszek))


def url_tiszta(x, csak_https=False):
    """Webcím ellenőrzése (a CSV-be és a kártyára kerül): nincs szóköz, idézőjel, < > ; | és vezérlőkarakter."""
    x = str(x).strip()
    if not 8 <= len(x) <= 400 or re.search(r"[\s<>\"'`;|\\\x00-\x1f\x7f]", x):
        return None
    if not re.match(r"^https://[^/]+\.[^/]+" if csak_https else r"^https?://[^/]+\.[^/]+", x, re.I):
        return None
    return x


ALKOTAS_ALAP_ID = 3_000_000_000          # a kézzel felvett alkotások azonosítói (az OSM-azonosítók ennél jóval kisebbek)
KEZI_EPULETEK = Path("forras/kezi_epuletek.geojson")
KERULETEK = Path("data/kerulethatarok.json")


def _gyuruben(x, y, gyuru):
    bent = False
    for (x1, y1), (x2, y2) in zip(gyuru, gyuru[1:]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            bent = not bent
    return bent


def alkotas_felvetel(adat):
    """Köztéri alkotás (nem épület) felvétele egy pontból: egy kicsi, 3x3 m-es kézi 'épület' a forras/kezi_epuletek.geojson-ban
    (az osszeepit.py ezt a többi épülettel együtt építi be), a név/év/tervező/leírás/fotó/link pedig kézi tényként
    a forras/kezi_javitasok.csv-be kerül - így az építész-kiemelés, a kártya és a keresés ugyanúgy működik, mint az épületeknél."""
    nev = szabad_szoveg(adat.get("nev", ""), 120, False)
    if not nev:
        return None, "Add meg az alkotás nevét (legfeljebb 120 karakter)."
    tervezo = tiszta_szoveg(adat.get("tervezo", ""), 100)
    if not tervezo:
        return None, "Add meg az alkotó nevét (pl. Szabó Levente; több alkotó: vesszővel)."
    try:
        ev = int(str(adat.get("ev", "")).strip())
        lat, lon = float(adat.get("lat")), float(adat.get("lon"))
    except (TypeError, ValueError):
        return None, "Az év vagy a helyszín hibás."
    if not 1000 <= ev <= 2100:
        return None, "Az év 1000 és 2100 között lehet."
    if not (18.7 <= lon <= 19.5 and 47.2 <= lat <= 47.8):
        return None, "A pont Budapesten kívül van."
    about = str(adat.get("about", "")).strip()
    if about:
        about = szabad_szoveg(about, 1500, True)
        if about is None:
            return None, "A leírás legfeljebb 1500 karakter lehet, és nem tartalmazhat < > jelet."
    kep = str(adat.get("kep_url", "")).strip()
    if kep and not url_tiszta(kep, True):
        return None, "A fotó címe egy https:// kezdetű, közvetlen képlink legyen."
    link = str(adat.get("link_url", "")).strip()
    if link and not url_tiszta(link):
        return None, "A link http:// vagy https:// kezdetű webcím legyen."
    gj = json.loads(KEZI_EPULETEK.read_text(encoding="utf-8")) if KEZI_EPULETEK.exists() else {"type": "FeatureCollection", "features": []}
    azon = max([f["properties"]["id"] for f in gj["features"] if f["properties"].get("id", 0) >= ALKOTAS_ALAP_ID], default=ALKOTAS_ALAP_ID) + 1
    kerulet = None
    try:
        for kn, gyuruk in json.loads(KERULETEK.read_text(encoding="utf-8")).items():
            if any(_gyuruben(lon, lat, g) for g in gyuruk):
                kerulet = int(kn)
                break
    except (OSError, ValueError):
        pass
    dx, dy = 1.5 / (111320 * math.cos(math.radians(47.5))), 1.5 / 110574
    gyuru = [[round(lon - dx, 7), round(lat - dy, 7)], [round(lon + dx, 7), round(lat - dy, 7)], [round(lon + dx, 7), round(lat + dy, 7)],
             [round(lon - dx, 7), round(lat + dy, 7)], [round(lon - dx, 7), round(lat - dy, 7)]]
    gj["features"].append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [gyuru]}, "properties": {
        "id": azon, "osm_tipus": "way", "nev": nev, "tipus": "yes", "resz": False, "szintek": None, "magassag": 3.0, "magassag_forras": "kezi",
        "ev": None, "ev_forras": None, "wikidata": None, "commons": None, "kerulet": kerulet, "pont_alapu": True, "alkotas": True}})
    tmp = KEZI_EPULETEK.with_suffix(".tmp")
    tmp.write_text(json.dumps(gj, ensure_ascii=False), encoding="utf-8")
    tmp.replace(KEZI_EPULETEK)
    megj = f"Köztéri alkotás (kézzel felvett pont): {nev}"[:200]
    for mezo, ertek in (("ev", ev), ("tervezo", tervezo), ("magassag", 3), ("about", about), ("kep_url", kep), ("link_url", link)):
        if ertek not in ("", None):
            sor_hozzaadasa(["way", azon, mezo, ertek, "kezi", megj, "", ""])
    return {"id": azon, "kulcs": f"w{azon}", "kerulet": kerulet}, None


def ellenoriz(adat):
    """Visszaadja a CSV-sort vagy hibaüzenetet."""
    tipus = adat.get("osm_tipus")
    if tipus not in ("way", "relation"):
        return None, "Ismeretlen épülettípus."
    try:
        azon = int(adat.get("id"))
    except (TypeError, ValueError):
        return None, "Hibás azonosító."
    mezo = adat.get("mezo")
    if mezo in SZAMOS:
        try:
            v = float(str(adat.get("ertek")).replace(",", "."))
        except ValueError:
            return None, f"A(z) {mezo} értéke nem szám."
        lo, hi = SZAMOS[mezo]
        if not lo <= v <= hi:
            return None, f"A(z) {mezo} értéke {lo} és {hi} között lehet."
        ertek = int(v) if v == int(v) else round(v, 1)
    elif mezo in EGYSOROS or mezo in HOSSZU_SZOVEG:
        if str(adat.get("ertek", "")).strip() == "-":
            ertek = "-"
        else:
            hatar = EGYSOROS.get(mezo) or HOSSZU_SZOVEG[mezo]
            ertek = szabad_szoveg(adat.get("ertek", ""), hatar, mezo in HOSSZU_SZOVEG)
            if ertek is None:
                return None, f"A(z) {mezo} értéke üres, legfeljebb {hatar} karakter lehet, és nem tartalmazhat < > jelet."
    elif mezo == "vedettseg":
        ertek = str(adat.get("ertek", "")).strip()
        if ertek != "-" and ertek not in VEDETTSEG_KODOK:
            return None, "A védettség csak M, MJ, VK, MK vagy MJT lehet (vagy '-' az eltávolításhoz)."
    elif mezo == "muemlek_torzsszam":
        ertek = str(adat.get("ertek", "")).strip()
        if ertek != "-":
            if not re.fullmatch(r"\d{1,6}", ertek):
                return None, "A műemléki törzsszám 1–6 jegyű szám (vagy '-' az eltávolításhoz)."
            ertek = int(ertek)
    elif mezo == "linkek":
        ertek = str(adat.get("ertek", "")).replace("\r\n", "\n").replace("\r", "\n").strip()
        if ertek != "-":
            sorok = [x.strip() for x in ertek.split("\n") if x.strip()]
            kesz = []
            for sor in sorok:
                felirat, _, url = sor.rpartition("|")
                felirat, url = felirat.strip(), url.strip()
                url = url_tiszta(url)
                if url is None or len(felirat) > 60 or re.search(r"[<>\"\x00-\x1f]", felirat):
                    return None, "Linkek: soronként egy webcím (http:// vagy https://, szóköz nélkül), elé tetszés szerint „Felirat | ” (legfeljebb 60 karakter); '-' vagy üres = eltávolítás."
                kesz.append((felirat + " | " if felirat else "") + url)
            if not kesz or len(kesz) > 8:
                return None, "Linkek: legalább 1, legfeljebb 8 sor."
            ertek = "\n".join(kesz)
    elif mezo == "kepek_linkek":
        ertek = str(adat.get("ertek", "")).replace("\r\n", "\n").replace("\r", "\n").strip()
        if ertek != "-":
            kesz = []
            for sor in [x.strip() for x in ertek.split("\n") if x.strip()]:
                felirat, _, url = sor.rpartition("|")
                felirat, url = felirat.strip(), url.strip()
                url = url_tiszta(url, True)
                if url is None or len(felirat) > 80 or re.search(r"[<>\"\x00-\x1f]", felirat):
                    return None, "Kép linkek: soronként egy közvetlen képlink (https:// kezdetű, szóköz nélkül), elé tetszés szerint „Forrás / szerző | ” (legfeljebb 80 karakter); '-' vagy üres = eltávolítás."
                kesz.append((felirat + " | " if felirat else "") + url)
            if not kesz or len(kesz) > 12:
                return None, "Kép linkek: legalább 1, legfeljebb 12 sor."
            ertek = "\n".join(kesz)
    elif mezo == "budapest100_url":
        ertek = str(adat.get("ertek", "")).strip()
        if ertek != "-":
            m_ = re.match(r"(?i)^(?:https?://)?(?:www\.)?(budapest100\.hu/[A-Za-z0-9._~%/\-]*)$", ertek)
            if not m_:
                return None, "A Budapest100-oldal a budapest100.hu teljes címe legyen (pl. https://budapest100.hu/house/…); '-' vagy üres = eltávolítás."
            ertek = "https://" + m_.group(1)
    elif mezo == "commons_kep":
        ertek = str(adat.get("ertek", "")).strip()
        if ertek.lower() in ("nincs", "nincs kép", "nincs kep"):
            ertek = "nincs"          # a kártyán egyáltalán nincs fotó (az automatikus párosítást is letiltja)
        elif ertek != "-":
            m_ = re.match(r"(?i)^(?:https?://)?(?:[a-z]+\.)?(?:commons\.)?wikimedia\.org/wiki/(?:File|F%C3%A1jl|Fájl):([^?#\s]+)$", ertek)
            nev = urllib.parse.unquote(m_.group(1)) if m_ else re.sub(r"(?i)^(?:File|Fájl):", "", ertek)
            nev = nev.replace(" ", "_")
            if not re.fullmatch(r"[^/\\<>;|\x00-\x1f]{3,200}\.(?:jpe?g|png|gif|tiff?|webp|svg)", nev, flags=re.I):
                return None, "A Commons-fotó a Commons fájl-oldalának teljes linkje legyen (https://commons.wikimedia.org/wiki/File:…), vagy a fájl neve; '-' vagy üres = a kézi választás eltávolítása."
            ertek = "https://commons.wikimedia.org/wiki/File:" + urllib.parse.quote(nev, safe="_-.~()',!")
    elif mezo in ("kep_url", "link_url"):
        ertek = str(adat.get("ertek", "")).strip()
        if ertek != "-":
            ertek = url_tiszta(ertek, mezo == "kep_url")
            if ertek is None:
                return None, ("A fotó címe egy https:// kezdetű, közvetlen képlink legyen (legfeljebb 400 karakter)." if mezo == "kep_url"
                              else "A link http:// vagy https:// kezdetű webcím legyen (legfeljebb 400 karakter); '-' vagy üres = eltávolítás.")
    elif mezo == "wikipedia":
        if re.match(r"(?i)^\s*(https?://)?(www\.)?budapest100\.hu/", str(adat.get("ertek", ""))):
            return None, "Ez egy Budapest100-link: írd a „Budapest100-oldal” mezőbe, ne a Wikipédia-mezőbe."
        ertek = wikipedia_cikkek(adat.get("ertek", ""))
        if ertek is None:
            return None, "A Wikipedia-oldal legyen hu.wikipedia.org vagy en.wikipedia.org cikk (link, vagy pl. 'hu:Vigadó'); több cikket | jellel válassz el."
    elif mezo in SZOVEGES:
        ertek = "-" if str(adat.get("ertek", "")).strip() == "-" else tiszta_szoveg(adat.get("ertek", ""), 150 if mezo == "stilus" else 100)    # '-' = a mező eltávolítása
        if ertek is None:
            return None, f"A(z) {mezo} értéke üres, túl hosszú, vagy tiltott karaktert tartalmaz."
    else:
        return None, "Ez a mező nem szerkeszthető."
    megj = tiszta_szoveg(adat.get("megjegyzes", ""), 200)
    if megj is None:
        return None, "Add meg a forrást (rövid szöveg, pl. 'Időgép, 1944-es lakásív')."
    return [tipus, azon, mezo, ertek, "kezi", megj, "", ""], None


def zona_szoveg(x, max_hossz):
    x = " ".join(str(x or "").split())
    if len(x) > max_hossz or re.search(r"[\x00-\x1f<>]", x):
        return None
    return x


def zonak_ellenoriz(adat):
    """A teljes zóna-FeatureCollection ellenőrzése. Visszaad: (tiszta adat, hiba)."""
    if not isinstance(adat, dict) or adat.get("type") != "FeatureCollection" or not isinstance(adat.get("features"), list):
        return None, "Hibás zóna-fájl."
    if len(adat["features"]) > 600:
        return None, "Legfeljebb 600 zóna menthető."
    ki, azonok = [], set()
    for f in adat["features"]:
        try:
            g, p = f["geometry"], f["properties"]
            if g["type"] != "Polygon" or len(g["coordinates"]) != 1:
                return None, "Csak egy külső gyűrűs sokszög (Polygon) menthető."
            gyuru = g["coordinates"][0]
            if not 4 <= len(gyuru) <= 3000 or gyuru[0] != gyuru[-1]:
                return None, "A sokszög gyűrűje hibás (3–3000 csúcs, zárt)."
            tiszta_gyuru = []
            for lon, lat in gyuru:
                lon, lat = float(lon), float(lat)
                if not (18.7 <= lon <= 19.5 and 47.2 <= lat <= 47.8):
                    return None, "A sokszög kilóg Budapestről."
                tiszta_gyuru.append([round(lon, 6), round(lat, 6)])
            azon = zona_szoveg(p.get("id"), 80)
            if not azon or azon in azonok:
                return None, "Hiányzó vagy ismétlődő zónaazonosító."
            azonok.add(azon)
            tol, ig = int(p.get("ev_tol")), int(p.get("ev_ig"))
            if not (1 <= tol <= ig <= 2100):
                return None, f"A(z) {azon} évei hibásak (ev_tol <= ev_ig, 1–2100)."
            tipus = p.get("tipus") or "egyeb"
            allapot = p.get("allapot") or "helyismeret"
            eredet = p.get("eredet") or "kezi"
            if tipus not in ZONA_TIPUSOK or allapot not in ZONA_ALLAPOTOK or eredet not in ZONA_EREDET:
                return None, f"A(z) {azon} típusa, állapota vagy eredete hibás."
            tiszta = {"id": azon, "tipus": tipus, "allapot": allapot, "eredet": eredet, "ev_tol": tol, "ev_ig": ig,
                      "mero": bool(p.get("mero")), "ig_hatar": bool(p.get("ig_hatar"))}
            if "zona_nev_hozzaad" in p:     # háromállapotú: hiányzik = a zónatípus dönt (lakótelep: igen)
                tiszta["zona_nev_hozzaad"] = bool(p["zona_nev_hozzaad"])
            for mezo, hossz in (("nev", 120), ("kerulet", 40), ("forras", 300), ("megjegyzes", 400), ("lista_id", 80), ("tervezo", 200)):
                v = zona_szoveg(p.get(mezo), hossz)
                if v is None:
                    return None, f"A(z) {azon} {mezo} mezője túl hosszú vagy tiltott karaktert tartalmaz."
                tiszta[mezo] = v
            bp = str(p.get("budapest100") or "").strip()
            wiki = str(p.get("wikipedia") or "").strip()
            if re.match(r"(?i)^(https?://)?(www\.)?budapest100\.hu/", wiki):      # tévedésből a Wikipédia-mezőbe írt Budapest100-link átkerül a sajátjába
                bp, wiki = bp or wiki, ""
            if bp:
                bp = bp.strip().strip("\"'")
                m = re.match(r"(?i)^(?:https?://)?(?:www\.)?(budapest100\.hu/[A-Za-z0-9._~%/\-]*)$", bp)
                if not m:
                    return None, (f"A(z) {azon} ({tiszta.get('nev') or 'névtelen'}) Budapest100-linkje hibás: „{bp[:80]}”. "
                                  "Írd be a budapest100.hu oldal teljes címét (https://budapest100.hu/...).")
                bp = "https://" + m.group(1)
            tiszta["budapest100"] = bp
            if wiki and wiki != "-":
                wiki = wikipedia_cikkek(wiki)
                if wiki is None:
                    return None, (f"A(z) {azon} ({tiszta.get('nev') or 'névtelen'}) Wikipedia-cikke hibás: „{str(p.get('wikipedia'))[:80]}”. "
                                  "Írj hu.wikipedia.org / en.wikipedia.org linket, vagy 'hu:Cím'-et (vagy csak a címet); legfeljebb 3 cikk, | jellel elválasztva.")
            else:
                wiki = ""
            tiszta["wikipedia"] = wiki
            ki.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [tiszta_gyuru]}, "properties": tiszta})
        except (KeyError, TypeError, ValueError):
            return None, "Hibás zóna-bejegyzés."
    return {"type": "FeatureCollection", "features": ki}, None


def zonak_mentese(adat):
    ZONAK.parent.mkdir(exist_ok=True)
    if ZONAK.exists():
        try:
            ZONAK.replace(ZONAK.with_suffix(".bak.geojson"))
        except OSError:
            pass
    ido = ZONAK.with_suffix(".tmp")
    ido.write_text(json.dumps(adat, ensure_ascii=False), encoding="utf-8")
    ido.replace(ZONAK)


def sor_hozzaadasa(sor):
    KEZI.parent.mkdir(exist_ok=True)
    uj = not KEZI.exists() or KEZI.stat().st_size == 0
    if not uj:
        with open(KEZI, "rb") as f:
            f.seek(-1, 2)
            vege_ujsor = f.read(1) in (b"\n", b"\r")
    else:
        vege_ujsor = True
    with open(KEZI, "a", encoding="utf-8-sig" if uj else "utf-8", newline="") as f:
        if not vege_ujsor:
            f.write("\r\n")
        w = csv.writer(f, delimiter=";")
        if uj:
            w.writerow(FEJLEC)
        w.writerow(sor)


OENY_KIZART = Path("forras/oeny_kizart.csv")


ERT_TABLA = Path("forras/ertekleltar_kezi_parositas.csv")
ERT_OSZLOPOK = ["kerulet", "cim", "hrsz", "epites_ideje", "tervezo", "allapot", "javasolt_osm", "jeloltek", "osm_azonosito", "megjegyzes"]


def ert_olvas():
    if not ERT_TABLA.exists():
        return []
    with open(ERT_TABLA, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def ert_dontes(adat):
    """Az értékleltár kézi párosító tábla egy sorának döntése: osm_azonosito (way/relation azonosító) vagy 'nem párosítható' megjegyzés.
    A sort a sorszám + (kerület, cím, hrsz) kulcs azonosítja; a fájlt egészében, atomikusan írjuk újra (BOM, CRLF)."""
    sorok = ert_olvas()
    kulcs = (str(adat.get("kerulet", "")), str(adat.get("cim", "")).strip(), str(adat.get("hrsz", "")).strip())
    try:
        i = int(adat.get("index"))
    except (TypeError, ValueError):
        i = -1
    egyezik = lambda r: (r.get("kerulet", ""), r.get("cim", "").strip(), r.get("hrsz", "").strip()) == kulcs
    if not (0 <= i < len(sorok) and egyezik(sorok[i])):
        talalt = [j for j, r in enumerate(sorok) if egyezik(r)]
        if len(talalt) != 1:
            return None, "A sor nem található (a tábla közben megváltozott?). Töltsd újra a listát."
        i = talalt[0]
    osm = re.sub(r"\s+", " ", str(adat.get("osm_azonosito") or "")).strip()
    if osm and not re.fullmatch(r"(way|relation) \d{3,}", osm):
        return None, "Hibás OSM-azonosító (way 123456 vagy relation 123 alakban)."
    megj = re.sub(r"\s+", " ", str(adat.get("megjegyzes") or "")).strip()[:200]
    sorok[i]["osm_azonosito"] = osm
    sorok[i]["megjegyzes"] = megj
    try:
        tmp = ERT_TABLA.with_suffix(".csv.tmp")
        with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=ERT_OSZLOPOK, delimiter=";", extrasaction="ignore", lineterminator="\r\n")
            w.writeheader()
            w.writerows(sorok)
        try:
            tmp.replace(ERT_TABLA)
        except OSError:                   # Windowson a csere elbukhat (a célfájlt valami nyitva tartja): közvetlen írás
            with open(ERT_TABLA, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=ERT_OSZLOPOK, delimiter=";", extrasaction="ignore", lineterminator="\r\n")
                w.writeheader()
                w.writerows(sorok)
            try:
                tmp.unlink()
            except OSError:
                pass
    except OSError as hiba:
        return None, f"A forras/ertekleltar_kezi_parositas.csv nem írható ({hiba.__class__.__name__}): valószínűleg meg van nyitva Excelben vagy más programban. Zárd be, és próbáld újra."
    return i, None


# ---- kézi döntési táblák (Budapest100 sarokházak, Wikipédia-konfliktusok) és az elvetett építész-tételek ----
TABLAK = {
    "bp100": {"ut": Path("forras/bp100_kezi_parositas.csv"),
              "oszlopok": ["cim", "ev", "url", "allapot", "javasolt_osm", "mod", "jeloltek", "osm_azonosito", "megjegyzes"],
              "kulcs": ("cim",)},
    "telek2": {"ut": Path("forras/ertekleltar_telek2_parositas.csv"),
               "oszlopok": ["lista", "kerulet", "cim", "hrsz", "n", "mai_cim", "adat", "allapot", "javasolt_osm", "jeloltek", "osm_azonosito", "megjegyzes"],
               "kulcs": ("lista", "kerulet", "cim", "hrsz", "n")},
    "konfliktus": {"ut": Path("forras/wikipedia_konfliktus_dontes.csv"),
                   "oszlopok": ["id", "epitesz", "tetel", "mod", "osm", "db_nev", "db_tervezo", "db_ev", "wiki_ev", "ok", "dontes", "megjegyzes"],
                   "kulcs": ("id",)},
}
EPITESZ_PAROSITOTT = Path("forras/epitesz_parositott.csv")    # epitesz;tetel;osm - a párosító listában már elvégzett párosítások (minden böngészőben eltűnnek a listából)
EPITESZ_ELVETETT = Path("forras/epitesz_elvetett.csv")      # epitesz;tetel - a párosító listából kivett (lebontott, csak terv) tételek
OSM_AZON = re.compile(r"(?:way|relation) \d{3,}(?: \| (?:way|relation) \d{3,})*")


def tabla_olvas(nev):
    t = TABLAK.get(nev)
    if not t or not t["ut"].exists():
        return []
    with open(t["ut"], encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def csv_atomikus_iras(ut, oszlopok, sorok):
    """BOM + CRLF, ideiglenes fájlon át; Windowson a csere elbukhat: ilyenkor közvetlen írás. OSError-t dob, ha a fájl nem írható."""
    def ir(cel):
        with open(cel, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=oszlopok, delimiter=";", extrasaction="ignore", lineterminator="\r\n")
            w.writeheader()
            w.writerows(sorok)
    tmp = ut.with_suffix(ut.suffix + ".tmp")
    ir(tmp)
    try:
        tmp.replace(ut)
    except OSError:
        ir(ut)
        try:
            tmp.unlink()
        except OSError:
            pass


def tobb_tervezo(regi, uj):
    """A meglévő tervező(k) + az új: 'A; B'; az évszámos zárójeleket (Hild József (1789–1867)) levesszük, a duplikátumot nem írjuk be."""
    def fold(x):
        return re.sub(r"[^a-z]", "", unicodedata.normalize("NFD", str(x).lower()).encode("ascii", "ignore").decode())
    nevek = [re.sub(r"\s*\(\d{4}[^)]*\)", "", r).strip() for r in re.split(r"[;,]", regi or "") if r.strip()]
    if fold(uj) not in [fold(n) for n in nevek]:
        nevek.append(uj.strip())
    return "; ".join(nevek)


def tabla_dontes(adat):
    """Egy sor döntése: bp100: osm_azonosito / megjegyzes; konfliktus: dontes (hozzaad / felulir / elvet) + megjegyzes.
    A konfliktus 'hozzaad' és 'felulir' döntése a forras/kezi_javitasok.csv-be is beír egy tervezo sort a tétel minden épületére."""
    nev = adat.get("tabla")
    t = TABLAK.get(nev)
    if not t:
        return None, "Ismeretlen tábla."
    sorok = tabla_olvas(nev)
    kulcs = {k: str(adat.get(k, "")).strip() for k in t["kulcs"]}
    egyezik = lambda r: all(str(r.get(k, "")).strip() == v for k, v in kulcs.items())
    try:
        i = int(adat.get("index"))
    except (TypeError, ValueError):
        i = -1
    if not (0 <= i < len(sorok) and egyezik(sorok[i])):
        talalt = [j for j, r in enumerate(sorok) if egyezik(r)]
        if len(talalt) != 1:
            return None, "A sor nem található (a tábla közben megváltozott?). Töltsd újra a listát."
        i = talalt[0]
    sor = sorok[i]
    megj = re.sub(r"\s+", " ", str(adat.get("megjegyzes") or "")).strip()[:200]
    if nev in ("bp100", "telek2"):
        osm = re.sub(r"\s*[|;,]\s*", " | ", re.sub(r"\s+", " ", str(adat.get("osm_azonosito") or "")).strip())
        if osm and not OSM_AZON.fullmatch(osm):
            return None, "Hibás OSM-azonosító (way 123456 vagy relation 123 alakban, több esetén | jellel)."
        sor["osm_azonosito"], sor["megjegyzes"] = osm, megj
    else:
        dontes = str(adat.get("dontes") or "").strip()
        if dontes not in ("hozzaad", "felulir", "elvet", ""):
            return None, "Ismeretlen döntés."
        if dontes in ("hozzaad", "felulir"):
            epitesz = re.sub(r"\s+", " ", sor.get("epitesz", "")).strip()
            ertek = epitesz if dontes == "felulir" else tobb_tervezo(sor.get("db_tervezo", ""), epitesz)
            if not epitesz or len(ertek) > 200 or ";" in ertek.replace("; ", ""):
                return None, "Hibás tervező-érték."
            azonok = [x.split() for x in str(sor.get("osm", "")).split("|") if x.strip()][:8]
            if not azonok or any(len(x) != 2 or x[0] not in ("way", "relation") or not x[1].isdigit() for x in azonok):
                return None, "A tételhez nincs érvényes OSM-azonosító."
            if sor.get("dontes") in ("hozzaad", "felulir"):
                return None, "Erre a tételre már született döntés (a forras/kezi_javitasok.csv-ben a sor megvan). Módosítsd ott."
            for tip, azon in azonok:
                sor_hozzaadasa([tip, int(azon), "tervezo", ertek, "kezi", "Wikipédia művek-lista (konfliktus-döntés): " + sor.get("tetel", "")[:100], "", ""])
        sor["dontes"], sor["megjegyzes"] = dontes, megj
    try:
        csv_atomikus_iras(t["ut"], t["oszlopok"], sorok)
    except OSError as hiba:
        return None, f"A {t['ut']} nem írható ({hiba.__class__.__name__}): valószínűleg meg van nyitva Excelben. Zárd be, és próbáld újra."
    return i, None


def elvetett_olvas():
    """Az elvetett ÉS a már párosított tételek (mindkettő eltűnik a párosító listából)."""
    ki = []
    for ut in (EPITESZ_ELVETETT, EPITESZ_PAROSITOTT):
        if ut.exists():
            with open(ut, encoding="utf-8-sig", newline="") as f:
                ki += [{"a": r["epitesz"], "t": r["tetel"]} for r in csv.DictReader(f, delimiter=";")]
    return ki


def epitesz_parositott_rogzit(epitesz, tetel, osm):
    a = re.sub(r"\s+", " ", str(epitesz or "")).strip()[:120]
    tt = re.sub(r"\s+", " ", str(tetel or "")).strip()[:400]
    if not a or not tt:
        return
    sorok = []
    if EPITESZ_PAROSITOTT.exists():
        with open(EPITESZ_PAROSITOTT, encoding="utf-8-sig", newline="") as f:
            sorok = [{"epitesz": r["epitesz"], "tetel": r["tetel"], "osm": r.get("osm", "")} for r in csv.DictReader(f, delimiter=";")]
    for x in sorok:
        if x["epitesz"] == a and x["tetel"] == tt:
            x["osm"] = osm
            break
    else:
        sorok.append({"epitesz": a, "tetel": tt, "osm": osm})
    try:
        csv_atomikus_iras(EPITESZ_PAROSITOTT, ["epitesz", "tetel", "osm"], sorok)
    except OSError:
        pass       # a párosítás maga (kezi_javitasok.csv) már megvan; a lista-rejtés csak kényelmi


def epitesz_elvetes(adat):
    a = re.sub(r"\s+", " ", str(adat.get("epitesz") or "")).strip()[:120]
    tt = re.sub(r"\s+", " ", str(adat.get("tetel") or "")).strip()[:400]
    if not a or not tt:
        return None, "Hiányzó építész vagy tétel."
    sorok = [{"epitesz": x["a"], "tetel": x["t"]} for x in elvetett_olvas()]
    if not any(x["epitesz"] == a and x["tetel"] == tt for x in sorok):
        sorok.append({"epitesz": a, "tetel": tt})
    try:
        csv_atomikus_iras(EPITESZ_ELVETETT, ["epitesz", "tetel"], sorok)
    except OSError as hiba:
        return None, f"A {EPITESZ_ELVETETT} nem írható ({hiba.__class__.__name__}): zárd be, ha meg van nyitva."
    return len(sorok), None


def oeny_levetel(adat):
    """Az E-Örökség (OENY) adatok levétele egy épületről: egy sor a forras/oeny_kizart.csv-be (az osszeepit.py eldobja az
    épület minden oeny/oeny_koord tényét). Visszaad: (állapot, hiba); az állapot "uj" vagy "mar_szerepelt"."""
    tipus = adat.get("osm_tipus")
    if tipus not in ("way", "relation"):
        return None, "Ismeretlen épülettípus."
    try:
        azon = int(adat.get("id"))
    except (TypeError, ValueError):
        return None, "Hibás azonosító."
    megj = "kézzel kivéve az E-Örökség (OENY) adatokból"
    torzs = str(adat.get("torzsszam") or "").strip()
    if re.fullmatch(r"\d{1,6}", torzs):
        megj += f" (törzsszám {torzs})"
    egy = bool(adat.get("egy"))          # csak ezt az egy adatlapot (törzsszámot) vegyük le, a többit hagyjuk
    if egy and not re.fullmatch(r"\d{1,6}", torzs):
        return None, "Az egyedi levételhez törzsszám kell."
    kulcs = f"{tipus};{azon};"
    uj = not OENY_KIZART.exists() or OENY_KIZART.stat().st_size == 0
    if not uj:
        szoveg = OENY_KIZART.read_text(encoding="utf-8-sig")
        sorok = szoveg.splitlines()
        # teljes kizárás (nincs törzsszám-oszlop) már van -> minden adatlap le van véve; egyedi sor ugyanarra a törzsszámra
        if any(sor.startswith(kulcs) and (sor.count(";") < 3 or not sor.split(";")[3].strip()) for sor in sorok if not sor.startswith("osm_tipus")):
            return "mar_szerepelt", None
        if egy and any(sor.startswith(kulcs) and sor.rstrip().endswith(";" + torzs) for sor in sorok):
            return "mar_szerepelt", None
        if not egy and any(sor.startswith(kulcs) for sor in sorok):
            return "mar_szerepelt", None
        vege_ujsor = szoveg.endswith(("\n", "\r"))
        # a fejléc kiegészítése a torzsszam oszloppal (a régi sorok 3 mezősek maradhatnak)
        if egy and "torzsszam" not in sorok[0]:
            szoveg = szoveg.replace(sorok[0], sorok[0].rstrip() + ";torzsszam", 1)
            OENY_KIZART.write_text(szoveg, encoding="utf-8-sig", newline="")
    else:
        vege_ujsor = True
    OENY_KIZART.parent.mkdir(exist_ok=True)
    with open(OENY_KIZART, "a", encoding="utf-8-sig" if uj else "utf-8", newline="") as f:
        if uj:
            f.write("osm_tipus;id;megjegyzes;torzsszam\r\n")
        elif not vege_ujsor:
            f.write("\r\n")
        f.write(f"{tipus};{azon};{megj}" + (f";{torzs}" if egy else "") + "\r\n")
    return "uj", None


OENY_KEZI = Path("forras/oeny_kezi_parositas.csv")
# A gyanús (az OSM-cím utcája nem egyezik az OENY-címmel) automatikus OENY-párosítások törzsszámai, és a címalapú javaslat
OENY_GYANUS = ["15003", "15114", "15115", "15116", "15118", "15134", "15229", "15643", "15809", "15984", "16061",
               "16068", "16137", "16164", "16165", "16182", "16189", "16250", "16283"]
OENY_JAVASLAT = {"15003": "way 323479222", "15114": "way 1308611895", "15115": "relation 3361170", "15116": "way 250065364",
                 "15643": "way 1086635486", "16068": "relation 19132", "16182": "way 249857122"}
OENY_KEZI_OSZLOP = ["torzsszam", "megnevezes", "cim", "miert_nem_parosult", "kiolvasott_tervezo", "kiolvasott_ev",
                    "lehetseges_epuletek_a_tobbi_cim_alapjan", "oeny_oldal", "osm_kereses", "arcgis_lat", "arcgis_lon",
                    "terbeli_biztonsag", "terbeli_javaslat", "osm_azonosito", "megjegyzes"]


def oeny_gyanus_lista():
    with open(OENY_KEZI, encoding="utf-8-sig", newline="") as f:
        sorok = list(csv.DictReader(f, delimiter=";"))
    ki = []
    for r in sorok:
        t = r.get("torzsszam", "")
        if t not in OENY_GYANUS or not (r.get("osm_azonosito") or "").strip():
            continue
        megj = r.get("megjegyzes", "")
        if not (megj.startswith("automatikus") or megj.startswith("kézzel")):
            continue
        allapot = "ok" if megj.startswith("kézzel ellenőrizve") else "atrakva" if megj.startswith("kézzel átrakva") else "levetel" if megj.startswith("kézzel levéve") else ""
        jav = OENY_JAVASLAT.get(t, "")
        ki.append({"t": t, "nev": r.get("megnevezes", ""), "cim": r.get("cim", ""), "oeny": r.get("oeny_oldal", ""),
                   "akt": [x.strip() for x in re.split(r"[|;,]+", r["osm_azonosito"]) if x.strip()],
                   "javaslat": jav if jav and jav != r["osm_azonosito"].strip() else "", "allapot": allapot})
    ki.sort(key=lambda x: (OENY_GYANUS.index(x["t"]), x["cim"]))
    return ki


def oeny_atrak(adat):
    """Egy gyanús OENY-párosítás döntése: 'ok' (marad), 'levetel' (jelölés; a levételt az /api/oeny_levetel végzi) vagy új OSM-azonosító."""
    t = str(adat.get("t") or "").strip()
    cim = str(adat.get("cim") or "")
    uj = str(adat.get("uj") or "").strip()
    if t not in OENY_GYANUS:
        return None, "Ismeretlen törzsszám."
    if uj not in ("ok", "levetel") and not re.fullmatch(r"(way|relation) \d{1,12}", uj):
        return None, "Hibás új azonosító."
    with open(OENY_KEZI, encoding="utf-8-sig", newline="") as f:
        sorok = list(csv.DictReader(f, delimiter=";"))
    talalt = False
    for r in sorok:
        if r.get("torzsszam") == t and r.get("cim") == cim and (r.get("osm_azonosito") or "").strip():
            if uj == "ok":
                r["megjegyzes"] = "kézzel ellenőrizve (marad)"
            elif uj == "levetel":
                r["megjegyzes"] = "kézzel levéve az OENY-adatokból"
            else:
                r["osm_azonosito"] = uj
                r["megjegyzes"] = "kézzel átrakva (gyanús párosítás ellenőrzése)"
            talalt = True
            break
    if not talalt:
        return None, "A sor nem található."
    try:
        csv_atomikus_iras(OENY_KEZI, OENY_KEZI_OSZLOP, sorok)
    except OSError as hiba:
        return None, f"A {OENY_KEZI} nem írható ({hiba.__class__.__name__}): zárd be, ha meg van nyitva."
    return True, None


LEGENDA_KEZI = Path("forras/legenda_kezi_parositas.csv")
LEGENDA_KEPEK = Path("forras/legenda_kepek.csv")


def legenda_lista():
    with open(LEGENDA_KEZI, encoding="utf-8-sig", newline="") as f:
        sorok = list(csv.DictReader(f, delimiter=";"))
    kepek = {}
    if LEGENDA_KEPEK.exists():
        with open(LEGENDA_KEPEK, encoding="utf-8-sig", newline="") as f:
            kepek = {(k.get("url") or "").strip(): (k.get("kep_url") or "").strip() for k in csv.DictReader(f, delimiter=";")}
    ki = []
    for r in sorok:
        lnk = (r.get("legenda_link") or "").strip()
        ki.append({"id": r.get("legenda_id", ""), "nev": r.get("nev", ""), "ev": r.get("ev", ""), "tervezo": r.get("tervezo", ""),
                   "link": lnk, "uj": r.get("uj_epulet", ""), "allapot": r.get("allapot", ""), "epforum": r.get("epforum_egyezes", ""),
                   "javaslat": r.get("osm_javaslat", ""), "keres": r.get("osm_kereses", ""), "megj": r.get("megjegyzes", ""),
                   "osm": [x.strip() for x in re.split(r"[|;,]+", r.get("osm_azonosito") or "") if x.strip()],
                   "kep": (r.get("kep_url") or kepek.get(lnk, "")).strip()})
    return ki


def legenda_dontes(adat):
    """Egy Legenda-sor párosítása: hozzaad (OSM-épület), torol (az összes párosítás), nincs (nem párosítható), nyitott (jelölés törlése)."""
    azon = str(adat.get("id") or "").strip()
    muvelet = adat.get("muvelet")
    if muvelet not in ("hozzaad", "torol", "nincs", "nyitott"):
        return None, "Ismeretlen művelet."
    with open(LEGENDA_KEZI, encoding="utf-8-sig", newline="") as f:
        olv = csv.DictReader(f, delimiter=";")
        oszlopok = list(olv.fieldnames or [])
        sorok = list(olv)
    cel = next((r for r in sorok if r.get("legenda_id") == azon), None)
    if cel is None:
        return None, "A sor nem található."
    jelenlegi = [x.strip() for x in re.split(r"[|;,]+", cel.get("osm_azonosito") or "") if x.strip()]
    if muvelet == "hozzaad":
        tipus = adat.get("osm_tipus")
        try:
            oid = int(adat.get("osm_id"))
        except (TypeError, ValueError):
            return None, "Hibás OSM-azonosító."
        if tipus not in ("way", "relation"):
            return None, "Ismeretlen épülettípus."
        uj = f"{tipus} {oid}"
        if uj not in jelenlegi:
            jelenlegi.append(uj)
        cel["osm_azonosito"] = " | ".join(jelenlegi)
        if (cel.get("megjegyzes") or "").startswith("kézzel: nem párosítható"):
            cel["megjegyzes"] = ""
    elif muvelet == "torol":
        cel["osm_azonosito"] = ""
    elif muvelet == "nincs":
        cel["osm_azonosito"] = ""
        cel["megjegyzes"] = "kézzel: nem párosítható"
    else:
        if (cel.get("megjegyzes") or "").startswith("kézzel: nem párosítható"):
            cel["megjegyzes"] = ""
    try:
        csv_atomikus_iras(LEGENDA_KEZI, oszlopok, sorok)
    except OSError as hiba:
        return None, f"A {LEGENDA_KEZI} nem írható ({hiba.__class__.__name__}): zárd be, ha meg van nyitva."
    return cel["osm_azonosito"], None


KEZI_KORSZAK = Path("forras/kezi_korszak.csv")


def korszak_mentes(adat):
    """Egy épület kézi korszak-megadása (0-6, a térkép korszakainak sorrendjében; üres = törlés): forras/kezi_korszak.csv,
    majd a data/varos/kezi_kozelito.csv újragenerálása (lásd tenyek_kezi_korszak.py)."""
    tipus = adat.get("osm_tipus")
    try:
        azon = int(adat.get("id"))
    except (TypeError, ValueError):
        return "Hibás épületazonosító."
    if tipus not in ("way", "relation"):
        return "Ismeretlen épülettípus."
    kor = str(adat.get("korszak", "")).strip()
    if kor != "" and not (kor.isdigit() and 0 <= int(kor) <= 6):
        return "Hibás korszak."
    megj = re.sub(r"\s+", " ", str(adat.get("megjegyzes") or "")).strip()[:200].replace(";", ",")
    if kor != "" and not megj:
        return "Add meg a forrást / indoklást."
    sorok = []
    if KEZI_KORSZAK.exists():
        with open(KEZI_KORSZAK, encoding="utf-8-sig", newline="") as f:
            sorok = list(csv.DictReader(f, delimiter=";"))
    sorok = [r for r in sorok if not (r.get("osm_tipus") == tipus and str(r.get("id")) == str(azon))]
    if kor != "":
        sorok.append({"osm_tipus": tipus, "id": str(azon), "korszak": kor, "megjegyzes": megj})
    try:
        csv_atomikus_iras(KEZI_KORSZAK, ["osm_tipus", "id", "korszak", "megjegyzes"], sorok)
        import tenyek_kezi_korszak
        tenyek_kezi_korszak.generalas()
    except OSError as hiba:
        return f"A {KEZI_KORSZAK} nem írható ({hiba.__class__.__name__}): zárd be, ha meg van nyitva."
    return None


EPITESZ_IRODAK = Path("forras/epitesz_irodak.csv")
EPITESZ_TIPUSOK = ("iroda", "intezmeny", "tobb_szemely", "nem_nev", "szemely")
EPITESZ_IRODAK_OSZLOP = ["kulcs", "nev", "tipus", "forras", "megjegyzes"]


def epitesz_tipusok_olvas():
    """A Tervező mezőben előforduló nevek besorolása (forras/epitesz_irodak.csv): iroda / intezmeny / tobb_szemely / nem_nev; 'szemely' = kézzel személynek jelölt."""
    if not EPITESZ_IRODAK.exists():
        return []
    with open(EPITESZ_IRODAK, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def epitesz_tipus_mentes(adat):
    """Egy név besorolásának kézi megadása; az automatikus sort felülírja (forras=kezi)."""
    kulcs = re.sub(r"\s+", " ", str(adat.get("kulcs") or "")).strip()
    nev = re.sub(r"\s+", " ", str(adat.get("nev") or "")).strip().replace(";", ",")
    tipus = str(adat.get("tipus") or "")
    if not kulcs or len(kulcs) > 150 or not nev or len(nev) > 150:
        return "Hibás név."
    if tipus not in EPITESZ_TIPUSOK:
        return "Ismeretlen típus."
    sorok = epitesz_tipusok_olvas()
    regi = next((r for r in sorok if r.get("kulcs") == kulcs), None)
    sorok = [r for r in sorok if r.get("kulcs") != kulcs]
    sorok.append({"kulcs": kulcs, "nev": nev, "tipus": tipus, "forras": "kezi", "megjegyzes": (regi or {}).get("megjegyzes", "")})
    sorok.sort(key=lambda r: (r.get("nev") or "").lower())
    try:
        csv_atomikus_iras(EPITESZ_IRODAK, EPITESZ_IRODAK_OSZLOP, sorok)
    except OSError as hiba:
        return f"A {EPITESZ_IRODAK} nem írható ({hiba.__class__.__name__}): zárd be, ha meg van nyitva."
    return None


def oeny_lista(tipus, azon):
    """Az épülethez kötött OENY-adatlapok (törzsszám szerint csoportosítva), hogy egyenként levehetők legyenek."""
    csop = {}
    for fn in ("oeny", "oeny_koord", "oeny_kezi"):
        ut = Path("data/tenyek") / f"{fn}.csv"
        if not ut.exists():
            continue
        with open(ut, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                if r.get("osm_tipus") != tipus or r.get("id") != str(azon):
                    continue
                m = re.search(r"törzsszám (\d+)", r.get("megjegyzes") or "")
                tsz = m.group(1) if m else (str(r.get("ertek")).strip() if r.get("mezo") == "muemlek_torzsszam" else "")
                if not tsz:
                    continue
                c = csop.setdefault(tsz, {"torzsszam": tsz, "adatlap": set(), "ev": set(), "tervezo": set()})
                if r["mezo"] == "oeny_azonosito":
                    c["adatlap"].add(str(r["ertek"]))
                elif r["mezo"] in ("ev", "tervezo"):
                    c[r["mezo"]].add(str(r["ertek"]))
    ki = []
    for c in sorted(csop.values(), key=lambda c: int(c["torzsszam"])):
        ki.append({k: (sorted(v) if isinstance(v, set) else v) for k, v in c.items()})
    return ki


def fortepan_adat(url):
    """Fortepan-képlinkből (…fortepan_<id>…) kiolvassa az évet, a szerzőt és az adományozót: a fortepan.hu saját keresőszolgáltatását kérdezi (ugyanazt, amit az oldal használ)."""
    m = re.search(r"fortepan_(\d+)", url or "")
    if not m or not re.match(r"^https://(?:[a-z0-9-]+\.)?fortepan\.(?:hu|download)/", url):
        return {"ok": False, "hiba": "Csak Fortepan képlinkből olvasható ki."}
    try:
        torzs = json.dumps({"query": {"term": {"mid": int(m.group(1))}}, "size": 1}).encode()
        kerel = urllib.request.Request("https://fortepan.hu/api/elastic/prod/media/_search", data=torzs,
                                       headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (budapest-by-building szerkeszto)"})
        with urllib.request.urlopen(kerel, timeout=12) as r:
            talalat = json.loads(r.read(2_000_000).decode("utf-8", "replace"))["hits"]["hits"]
    except Exception as kiv:
        return {"ok": False, "hiba": f"A fortepan.hu nem érhető el ({kiv.__class__.__name__}) – írd be kézzel."}
    if not talalat:
        return {"ok": False, "hiba": "Ezt a fotót nem találtam a Fortepanon."}
    f = talalat[0].get("_source", {})
    egy = lambda k: str((f.get(k) or [""])[0]).strip()
    ev, szerzo, adomanyozo = egy("year"), egy("szerzo_name"), egy("adomanyozo_name")
    if not (ev or szerzo or adomanyozo):
        return {"ok": False, "hiba": "A fotónál nincs kiolvasható adat – írd be kézzel."}
    return {"ok": True, "ev": ev, "szerzo": szerzo, "adomanyozo": adomanyozo, "leiras": egy("description")}


IRAS_ZAR = threading.Lock()    # egyszerre csak egy mentés: a fájlt beolvasó-módosító-visszaíró végpontok párhuzamos kérésnél elveszítették egymás változtatásait


class Kezelo(SimpleHTTPRequestHandler):
    timeout = 30                # ha a kliens kevesebb adatot küld, mint amennyit bejelentett, a szál ne várjon örökké
    def _json(self, kod, adat):
        torzs = json.dumps(adat, ensure_ascii=False).encode("utf-8")
        self.send_response(kod)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(torzs)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(torzs)

    def end_headers(self):
        if self.path.split("?")[0].endswith((".geojson", ".json", ".html", ".js", ".css", ".bin", ".png")):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _helyi_host(self):
        """Csak a saját gépre szóló kérést szolgálunk ki. A 'Host' fejléc ellenőrzése nélkül egy rosszindulatú weboldal
        (DNS rebinding: a saját domainje 127.0.0.1-re mutat) a böngésződön át kiolvashatná a projekt minden fájlját (.git, forras/, data/)."""
        port = self.server.server_address[1]
        return (self.headers.get("Host") or "").lower() in {f"localhost:{port}", f"127.0.0.1:{port}", "localhost", "127.0.0.1"}

    def do_HEAD(self):
        if not self._helyi_host():
            return self._json(403, {"ok": False, "hiba": "Csak helyi kérés engedélyezett."})
        return super().do_HEAD()

    def do_GET(self):
        if not self._helyi_host():
            return self._json(403, {"ok": False, "hiba": "Csak helyi kérés engedélyezett."})
        if self.path.startswith("/api/kep_adat?"):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            return self._json(200, fortepan_adat((q.get("url") or [""])[0]))
        if self.path == "/api/ping":
            return self._json(200, {"szerkeszto": True})
        if self.path.startswith("/api/oeny_lista"):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            try:
                return self._json(200, {"ok": True, "adatlapok": oeny_lista((q.get("tipus") or ["way"])[0], int((q.get("id") or ["0"])[0]))})
            except Exception as kiv:
                return self._json(500, {"ok": False, "hiba": f"{kiv.__class__.__name__}: {kiv}"})
        if self.path == "/api/oeny_gyanus":
            try:
                return self._json(200, {"ok": True, "tetelek": oeny_gyanus_lista()})
            except Exception as kiv:
                return self._json(500, {"ok": False, "hiba": f"{kiv.__class__.__name__}: {kiv}"})
        if self.path == "/api/epitesz_tipusok":
            try:
                return self._json(200, {"ok": True, "sorok": epitesz_tipusok_olvas()})
            except Exception as kiv:
                return self._json(500, {"ok": False, "hiba": f"{kiv.__class__.__name__}: {kiv}"})
        if self.path == "/api/legenda_lista":
            try:
                return self._json(200, {"ok": True, "sorok": legenda_lista()})
            except Exception as kiv:
                return self._json(500, {"ok": False, "hiba": f"{kiv.__class__.__name__}: {kiv}"})
        if self.path == "/api/ertekleltar_lista":
            try:
                return self._json(200, {"ok": True, "sorok": ert_olvas()})
            except Exception as kiv:
                return self._json(500, {"ok": False, "hiba": f"{kiv.__class__.__name__}: {kiv}"})
        if self.path.startswith("/api/tabla?"):
            nev = self.path.split("nev=", 1)[-1].split("&", 1)[0]
            try:
                return self._json(200, {"ok": True, "sorok": tabla_olvas(nev)})
            except Exception as kiv:
                return self._json(500, {"ok": False, "hiba": f"{kiv.__class__.__name__}: {kiv}"})
        if self.path == "/api/epitesz_elvetett":
            try:
                return self._json(200, {"ok": True, "tetelek": elvetett_olvas()})
            except Exception as kiv:
                return self._json(500, {"ok": False, "hiba": f"{kiv.__class__.__name__}: {kiv}"})
        return super().do_GET()

    def _engedelyezett(self):
        origin = self.headers.get("Origin")
        return self.headers.get("X-Szerkeszto") == "1" and (origin is None or origin in ENGEDELYEZETT_ORIGIN)

    def do_POST(self):
        if not self._helyi_host() or not self._engedelyezett():
            return self._json(403, {"ok": False, "hiba": "Nem engedélyezett kérés."})
        try:
            hossz = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            hossz = -1
        if hossz < 0:          # negatív hossznál a beolvasás a kapcsolat végéig várna (a szál beragadna)
            return self._json(400, {"ok": False, "hiba": "Hibás kérés."})
        if hossz > (MAX_ZONA_KERES if self.path == "/api/zonak" else 20_000):
            return self._json(413, {"ok": False, "hiba": "Túl nagy kérés."})
        try:
            adat = json.loads(self.rfile.read(hossz) or b"{}")
        except (ValueError, RecursionError):
            return self._json(400, {"ok": False, "hiba": "Hibás kérés."})
        if not isinstance(adat, dict):          # pl. '[]': korábban a szerver válasz nélkül bontotta a kapcsolatot
            return self._json(400, {"ok": False, "hiba": "Hibás kérés."})
        if self.path == "/api/ujraepit":         # hosszú futás: nem tartja fel a mentéseket
            return self._post(adat)
        with IRAS_ZAR:
            return self._post(adat)

    def _post(self, adat):
        if self.path == "/api/zonak":
            tiszta, hiba = zonak_ellenoriz(adat)
            if hiba:
                return self._json(400, {"ok": False, "hiba": hiba})
            zonak_mentese(tiszta)
            return self._json(200, {"ok": True, "db": len(tiszta["features"])})
        if self.path == "/api/zona_elvetett":
            db, hiba = elvetett_mentese(adat)
            if hiba:
                return self._json(400, {"ok": False, "hiba": hiba})
            return self._json(200, {"ok": True, "db": db})
        if self.path == "/api/uj_alkotas":
            try:
                v, hiba = alkotas_felvetel(adat if isinstance(adat, dict) else {})
            except Exception as kiv:
                return self._json(500, {"ok": False, "hiba": f"Szerverhiba: {kiv}"})
            if hiba:
                return self._json(400, {"ok": False, "hiba": hiba})
            return self._json(200, {"ok": True, **v})
        if self.path == "/api/korszak":
            hiba = korszak_mentes(adat if isinstance(adat, dict) else {})
            if hiba:
                return self._json(400, {"ok": False, "hiba": hiba})
            return self._json(200, {"ok": True})
        if self.path == "/api/javitas":
            sor, hiba = ellenoriz(adat)
            if hiba:
                return self._json(400, {"ok": False, "hiba": hiba})
            sor_hozzaadasa(sor)
            return self._json(200, {"ok": True})
        if self.path == "/api/ertekleltar_dontes":
            try:
                i, hiba = ert_dontes(adat if isinstance(adat, dict) else {})
            except Exception as kiv:          # ne szakadjon meg a kapcsolat: a hiba üzenetként jusson el a felületre
                i, hiba = None, f"Szerverhiba: {kiv.__class__.__name__}: {kiv}"
                print(hiba)
            if hiba:
                return self._json(400, {"ok": False, "hiba": hiba})
            return self._json(200, {"ok": True, "index": i})
        if self.path in ("/api/tabla_dontes", "/api/epitesz_elvetes"):
            try:
                if self.path == "/api/tabla_dontes":
                    i, hiba = tabla_dontes(adat if isinstance(adat, dict) else {})
                else:
                    i, hiba = epitesz_elvetes(adat if isinstance(adat, dict) else {})
            except Exception as kiv:
                i, hiba = None, f"Szerverhiba: {kiv.__class__.__name__}: {kiv}"
                print(hiba)
            if hiba:
                return self._json(400, {"ok": False, "hiba": hiba})
            return self._json(200, {"ok": True, "index": i})
        if self.path == "/api/epitesz_parositas":
            a = adat if isinstance(adat, dict) else {}
            tipus = a.get("osm_tipus")
            ertek = re.sub(r"\s+", " ", str(a.get("ertek") or "")).strip()
            tetel = re.sub(r"\s+", " ", str(a.get("tetel") or "")).strip()[:120]
            try:
                azon = int(a.get("id"))
            except (TypeError, ValueError):
                azon = None
            if tipus not in ("way", "relation") or azon is None or not ertek or len(ertek) > 200 or ";" in ertek.replace("; ", ""):
                return self._json(400, {"ok": False, "hiba": "Hibás párosítási adat."})
            sor_hozzaadasa([tipus, azon, "tervezo", ertek, "kezi", "Wikipédia művek-lista (kézi párosítás): " + tetel, "", ""])
            epitesz_parositott_rogzit(a.get("epitesz"), a.get("tetel_teljes"), f"{tipus} {azon}")
            return self._json(200, {"ok": True})
        if self.path == "/api/epitesz_tipus":
            hiba = epitesz_tipus_mentes(adat if isinstance(adat, dict) else {})
            if hiba:
                return self._json(400, {"ok": False, "hiba": hiba})
            return self._json(200, {"ok": True})
        if self.path == "/api/legenda_dontes":
            osm, hiba = legenda_dontes(adat if isinstance(adat, dict) else {})
            if hiba:
                return self._json(400, {"ok": False, "hiba": hiba})
            return self._json(200, {"ok": True, "osm": osm})
        if self.path == "/api/oeny_atrak":
            ok, hiba = oeny_atrak(adat if isinstance(adat, dict) else {})
            if hiba:
                return self._json(400, {"ok": False, "hiba": hiba})
            return self._json(200, {"ok": True})
        if self.path == "/api/oeny_levetel":
            allapot, hiba = oeny_levetel(adat if isinstance(adat, dict) else {})
            if hiba:
                return self._json(400, {"ok": False, "hiba": hiba})
            return self._json(200, {"ok": True, "allapot": allapot})
        if self.path == "/api/ujraepit":
            varos = ["varos"] if isinstance(adat, dict) and adat.get("varos") else []   # a 3D (egész város) nézetből
            try:
                eredmeny = subprocess.run([sys.executable, "osszeepit.py", *varos], capture_output=True,
                                          text=True, encoding="utf-8", errors="replace", timeout=1800)
            except subprocess.TimeoutExpired:
                return self._json(500, {"ok": False, "hiba": "Az újraépítés túl sokáig tartott."})
            if eredmeny.returncode != 0:
                return self._json(500, {"ok": False, "hiba": (eredmeny.stderr or "")[-400:]})
            # a 3D nézet adatai is újra elkészülnek (ha ez hibázik, a 2D térkép attól még frissül)
            harom_d = "ok"
            try:
                e3 = subprocess.run([sys.executable, "csempek_keszites.py", *varos], capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=1800)
                if e3.returncode != 0:
                    harom_d = "hiba: " + ((e3.stderr or e3.stdout or "")[-300:])
            except (subprocess.TimeoutExpired, OSError) as hiba:
                harom_d = f"hiba: {hiba}"
            print(f"  3D adatok: {harom_d}")
            try:      # a 3D Lakótelepek fül zónalistája (típus, kerület, évek)
                subprocess.run([sys.executable, "zonak_json_keszites.py"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
            except (subprocess.TimeoutExpired, OSError):
                pass
            return self._json(200, {"ok": True, "harom_d": harom_d})
        return self._json(404, {"ok": False, "hiba": "Ismeretlen kérés."})

    def log_message(self, fmt, *args):
        if "/api/" in str(args[0] if args else ""):     # str(): a hibaüzenetek (pl. 404) első argumentuma szám, ettől korábban a szerver válasz nélkül bontotta a kapcsolatot
            super().log_message(fmt, *args)


if __name__ == "__main__":
    print(f"A térkép: http://localhost:{PORT}   (leállítás: Ctrl+C)")
    print("Szerkesztési mód aktív: a javítások a forras/kezi_javitasok.csv fájlba kerülnek.")
    ThreadingHTTPServer(("127.0.0.1", PORT), Kezelo).serve_forever()
