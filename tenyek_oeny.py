"""E-Örökség (oeny.hu) PDFs saved from the advanced search -> data/tenyek/oeny.csv

Usage:
  1. In oeny.hu's advanced search filter for a district (e.g. Budapest V.), and save the result
     pages (48 per page) one by one as PDF (Print -> Save as PDF).
  2. Put the PDFs in the data/oeny_pdf/ folder (the data/ folder is not in git).
  3. py -m pip install pdfplumber      (needed once)
  4. py tenyek_oeny.py            (the inner city)
     py tenyek_oeny.py varos      (the whole city: addresses are searched within the district, by 'BUDAPEST 10';
                                   first: py varos_osszeallitas.py)

What it extracts: the monument register number, address(es), and from the short description the designer and the year of
construction, if clearly readable ("..., Hild József, 1837."). It takes over only facts and does not store the text of
the description. The page cuts the description to 2-3 lines ("..."), so the designer/year cannot
be read out everywhere. The source of the extracted data is "oeny" (in prioritas.json it comes after the monument
register).
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

PDF_MAPPA = Path("data/oeny_pdf")
JSON_KIMENET = Path("data/oeny_epuletek.json")
VAROS = "varos" in sys.argv[1:]          # py tenyek_oeny.py varos  (the whole city, paired per district)
CIMEK = "data/varos/osm_cimek.csv" if VAROS else "data/osm_cimek.csv"
EPULETEK = "data/varos/epuletek.geojson"
ATNEVEZES = "forras/utcanev_atnevezesek.csv"
JEGYZEK = "data/muemlek_jegyzek.json"
KIMENET = "data/tenyek/oeny.csv"
NEM_PAROSITOTT = "data/oeny_nem_parositott.csv"

NEV = r"[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+(?:-[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+)*"
EMBER = rf"{NEV} {NEV}"                                  # 'Hild József'
EMBEREK = rf"{EMBER}(?:(?:,| és) {EMBER})*"                # 'Quittner Zsigmond és Vágó József'
CSOPORT = rf"{NEV}(?:-{NEV})+"                           # 'Feszl-Gerster-Kauser'
EV = r"(1[5-9]\d\d)(?:\s*-\s*(1[5-9]\d\d))?"
HONAPOK = "januar|februar|marcius|aprilis|majus|junius|julius|augusztus|szeptember|oktober|november|december"


# ---------------------------------------------------------------- PDF -> cards
def pdf_kartyak(ut):
    import pdfplumber
    kartyak, akt = [], None

    def lezar():
        nonlocal akt
        if akt:
            kartyak.append(akt)
        akt = None

    with pdfplumber.open(ut) as pdf:
        for oldal in pdf.pages:
            szavak = oldal.extract_words(extra_attrs=["fontname", "size"])
            # next to every record of the result list there is the data sheet's link: /monument/<monument id>
            linkek = []
            for h in oldal.hyperlinks:
                mm = re.search(r"/public/monument/(\d+)\s*$", h.get("uri") or "")
                if mm:
                    linkek.append((h["top"], int(mm.group(1))))
            vege = min([w["top"] for w in szavak if w["text"] == "db/oldal"] or [10 ** 6])
            szavak = [w for w in szavak if w["top"] < vege - 1 and w["top"] > 24 and w["x0"] > 245 and w["x1"] < 440]
            szavak.sort(key=lambda w: (round(w["top"]), w["x0"]))
            for w in szavak:
                t, m, f = w["text"], w["size"], w["fontname"]
                if "Bold" in f and 3.4 < m < 4.4 and re.fullmatch(r"\d{3,6}", t):
                    lezar()
                    akt = {"torzsszam": int(t), "nev": [], "cim": [], "cim_szoveg": "", "leiras": []}
                    kozel = [(abs(top - w["top"]), az) for top, az in linkek if abs(top - w["top"]) <= 12]
                    if kozel:
                        akt["azonosito"] = min(kozel)[1]
                elif akt is None:
                    continue
                elif 8 < m < 9.2:
                    akt["nev"].append(t)
                elif 4.6 < m < 5.6:
                    akt["cim"].append(t)
                elif 6.2 < m < 7.4:
                    akt["leiras"].append(t)
    lezar()
    for k in kartyak:
        k["nev"] = " ".join(k["nev"])
        k["cim_szoveg"] = " ".join(k.pop("cim"))
        k["leiras"] = " ".join(k["leiras"])
    return kartyak


# ---------------------------------------------------------------- description -> facts
def leiras_tenyek(d):
    """(designer, year) from the description, if unambiguous. Otherwise Nones."""
    d = " ".join(d.split())
    d = re.sub(r"(?<=\w)- (?=\w)", "-", d)             # hyphen split at a line break: 'Borsody- ház'
    csonka = d.endswith("…")
    tervezo = ev = None
    # 'Quittner Zsigmond és Vágó József, 1907.'  /  'Weber Antal 1872.'  /  'Feszl-Gerster-Kauser, 1853-1854.'
    # with several building phases we take the first (the original construction): 'Brein Ignác, 1820., ifj. Zitterbarth Mátyás, 1861.'
    m = re.search(rf"(?<![\wÁÉÍÓÖŐÚÜŰáéíóöőúüű-])({EMBEREK}|{CSOPORT}),? {EV}(?!\d|-b)", d)
    if m:
        tervezo = m.group(1)
        ev = int(m.group(2))
    else:
        m = re.search(rf"[Tt]ervezte:? ({EMBEREK}|{CSOPORT})|[Tt]ervezője:? ({EMBEREK}|{CSOPORT})|({EMBEREK}|{CSOPORT}) (?:tervei|terve) szerint", d)
        if m:
            tervezo = next(g for g in m.groups() if g)
        # standalone year of construction: 'épült 1910-ben' (built in 1910) / 'Banképület, épült 1910-ben.' / ', 1813.'
        e = re.search(rf"[ée]pült:? {EV}", d)
        if e:
            ev = int(e.group(1))
        elif not csonka:
            e = re.search(rf"(?:,|\.) {EV}\.(?: |$)", d)
            if e:
                ev = int(e.group(1))
    return tervezo, ev


# ---------------------------------------------------------------- address -> (street, house numbers)
def lecsupaszit(s):
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", "", s)


def szamok(szoveg):
    ki = set()
    for a, b in re.findall(r"(\d+)\s*(?:[-–]\s*(\d+))?", szoveg or ""):
        ki.add(int(a))
        if b:
            ki.add(int(b))
    return ki


def tisztit_utca(s):
    return re.sub(r"[^a-z0-9]", "", lecsupaszit(s))


def cimek_felbontasa(cim_szoveg, utcanevek, atnevezes):
    """'BUDAPEST 5, ZO LTÁ N UT C A 1 8 ., DEÁK...' -> [(street_name_stripped, {house numbers}), ...]"""
    t = cim_szoveg
    t = re.sub(r"^\s*BUDAPEST\s*\d+\s*,", "", t)
    t = lecsupaszit(t)
    t = re.sub(r"(?<=[a-z])u\.(?=\d)", "utca", t)            # 'BÁSTYA U. 33.' -> 'bastyautca33.'
    t = re.sub(rf"({HONAPOK})(\d+)\.", r"\1\2", t)
    t = re.sub(r"(?<=[a-z])-(?=[a-z])", "", t)          # 'bajcsy-zsilinszky' -> 'bajcsyzsilinszky'
    hosszu = sorted(utcanevek, key=len, reverse=True)
    ki, i = [], 0
    while i < len(t):
        for u in hosszu:
            if t.startswith(u, i):
                j = i + len(u)
                m = re.match(r"(\d+)(?:\.?-(\d+))?\.?", t[j:])
                if m:
                    ki.append((atnevezes.get(u, u), szamok(m.group(0))))
                    i = j + m.end()
                else:
                    i = j
                break
        else:
            i += 1
    return ki


# ---------------------------------------------------------------- main program
def pdf_beolvasas():
    mind = []
    if PDF_MAPPA.exists():
        pdfk = sorted(PDF_MAPPA.glob("*.pdf"))
        if pdfk:
            try:
                import pdfplumber  # noqa: F401
            except ImportError:
                sys.exit("Hiányzik a pdfplumber. Telepítés:  py -m pip install pdfplumber")
            for p in pdfk:
                k = pdf_kartyak(p)
                print(f"  {p.name}: {len(k)} bejegyzés")
                mind += k
    if mind:
        egyedi = {}
        for k in mind:
            elozo = egyedi.get((k["torzsszam"], k["cim_szoveg"]))
            az = list(elozo.get("azonositok", [])) if elozo else []
            if k.get("azonosito") and k["azonosito"] not in az:
                az.append(k["azonosito"])
            k["azonositok"] = az                        # several monument ids (data sheets) can belong to one register number
            k.pop("azonosito", None)
            egyedi[(k["torzsszam"], k["cim_szoveg"])] = k
        mind = list(egyedi.values())
        JSON_KIMENET.parent.mkdir(exist_ok=True)
        JSON_KIMENET.write_text(json.dumps(mind, ensure_ascii=False, indent=1), encoding="utf-8")
    elif JSON_KIMENET.exists():
        mind = json.loads(JSON_KIMENET.read_text(encoding="utf-8"))
        print(f"  (nincs PDF a {PDF_MAPPA} mappában, a korábbi {JSON_KIMENET} adatait használom)")
    else:
        sys.exit(f"Tedd a PDF-eket a {PDF_MAPPA} mappába.")
    return mind


def main():
    kartyak = pdf_beolvasas()
    print(f"Bejegyzések összesen: {len(kartyak)}")
    # register number -> data-sheet ids; osszeepit.py uses it for the monument zones drawn in the zone editor
    az_map = {}
    for k in kartyak:
        for a in k.get("azonositok", []):
            if a not in az_map.setdefault(str(k["torzsszam"]), []):
                az_map[str(k["torzsszam"])].append(a)
    Path("data/oeny_azonositok.json").write_text(json.dumps(az_map, ensure_ascii=False), encoding="utf-8")

    atn = {}                       # old street name (stripped) -> current name (stripped); left out if there are several possibilities
    try:
        with open(ATNEVEZES, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                if r.get("regi") and r.get("uj") and "|" not in r["uj"]:
                    atn[tisztit_utca(r["regi"])] = tisztit_utca(r["uj"])
    except FileNotFoundError:
        pass

    kerulete = {}                  # (type, id) -> district number (only in city mode)
    if VAROS:
        with open(EPULETEK, encoding="utf-8") as f:
            for ft in json.load(f)["features"]:
                pr = ft["properties"]
                if pr.get("kerulet"):
                    kerulete[(pr["osm_tipus"], int(pr["id"]))] = pr["kerulet"]
        if not kerulete:
            sys.exit("Az épületeknél nincs kerület. Futtasd: py budapest_pbf.py, majd py varos_osszeallitas.py")
    utcak = defaultdict(lambda: defaultdict(list))     # (district, stripped street name) -> house number -> [(type, id)]
    utcanevek = set()
    with open(CIMEK, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if VAROS and (r["osm_tipus"], int(r["id"])) not in kerulete:
                continue
            kn = kerulete.get((r["osm_tipus"], int(r["id"])), 0)
            u0 = tisztit_utca(r["utca"])
            utcanevek.add(u0)
            for sz in szamok(r["hazszam"]):
                utcak[(kn, u0)][sz].append((r["osm_tipus"], int(r["id"])))
    utcanevek |= set(atn)

    konyv = {}
    try:
        for b in json.loads(Path(JEGYZEK).read_text(encoding="utf-8"))["bejegyzesek"]:
            konyv[int(b["torzsszam"])] = b
    except (FileNotFoundError, ValueError, KeyError):
        pass

    kesz = set()
    jeloltek = defaultdict(list)   # (type, id) -> [(score, card, designer, year, remark)]
    kimaradt = []                  # the unpaired entries for manual completion
    stat = Counter()
    nincs_utca = Counter()
    for k in kartyak:
        tervezo, ev = leiras_tenyek(k["leiras"])
        stat["tervező kiolvasva"] += bool(tervezo)
        stat["év kiolvasva"] += bool(ev)
        stat["törzsszám a műemlékjegyzék-könyvben is"] += k["torzsszam"] in konyv
        cimek = cimek_felbontasa(k["cim_szoveg"], utcanevek, atn)
        mk = re.match(r"\s*BUDAPEST\s*(\d+)", k["cim_szoveg"])
        kn = int(mk.group(1)) if (VAROS and mk) else 0
        # Only the entry's first (main) address is used. The other addresses are typically the corner house's
        # entrance on the other street, which is often a neighbouring building's address and would bring wrong data to it.
        talalat = set()
        pontok = Counter()         # building -> how many of its address rows match the house numbers of the entry's main address
        if cimek:
            u, sz = cimek[0]
            for n in sz:
                for b in utcak.get((kn, u), {}).get(n, []):
                    pontok[b] += 1
                    talalat.add(b)
        if not talalat:
            stat["nem párosítható épülethez"] += 1
            if not cimek:
                ok = "nincs házszám, vagy az utcanév alakja nem ismerhető fel (az OSM-ben más néven szerepelhet)"
            elif cimek[0][0] in {u for u in utcanevek}:
                ok = "a fő cím házszáma nincs az OSM-épületek címei között"
            else:
                ok = "a fő cím utcája nincs az OSM-címek között"
            # buildings possible by the other addresses (only a hint, not certain!)
            mas = []
            for u, sz in cimek[1:]:
                for n in sorted(sz):
                    for tip, azon in utcak.get((kn, u), {}).get(n, []):
                        mas.append(f"{tip} {azon} ({u} {n})")
            kimaradt.append([k["torzsszam"], k.get("nev", ""), re.sub(r"^\s*BUDAPEST\s*\d+\s*,\s*", "", k["cim_szoveg"]),
                             ok, tervezo or "", ev or "", "; ".join(mas)])
            if not cimek:
                nincs_utca[k["cim_szoveg"][:60]] += 1
            continue
        stat["párosítva"] += 1
        megj = f"E-Örökség, törzsszám {k['torzsszam']}" + (f", {len(talalat)} OSM-épület" if len(talalat) > 1 else "")
        for b in talalat:
            jeloltek[b].append((pontok[b], k, tervezo, ev, megj))
    # Several entries can match one large OSM building (a block) because its addresses include the addresses of several monuments.
    # In that case only the entry(ies) matching the most address rows are kept (all on a tie); the others would bring wrong data (year, designer) to it.
    for (t, i), lista in jeloltek.items():
        legjobb = max(p for p, *_ in lista)
        stat["több bejegyzésből csak a legjobb marad (épület)"] += len(lista) > 1
        for p, k, tervezo, ev, megj in lista:
            if p < legjobb:
                continue
            sorok = [("muemlek_torzsszam", k["torzsszam"])]
            if k["torzsszam"] not in konyv:
                sorok.append(("vedettseg", "M"))         # a register number not in the book: it is on the list's 'Műemlékek' (monuments) tab
            for az in k.get("azonositok", [])[:3]:
                sorok.append(("oeny_azonosito", az))          # the data sheet: https://www.oeny.hu/oeny/eorok/public/monument/<id>
            if tervezo:
                sorok.append(("tervezo", tervezo))
            if ev:
                sorok.append(("ev", ev))
            for mezo, ertek in sorok:
                kesz.add((t, i, mezo, ertek, "oeny", megj + (" (leírásból kiolvasva)" if mezo in ("tervezo", "ev") else "")))
    kimaradt.sort(key=lambda s: s[2])
    with open(NEM_PAROSITOTT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["torzsszam", "megnevezes", "cim", "miert_nem_parosult", "kiolvasott_tervezo",
                    "kiolvasott_ev", "lehetseges_epuletek_a_tobbi_cim_alapjan"])
        w.writerows(kimaradt)
    print(f"Nem párosított bejegyzések listája: {NEM_PAROSITOTT} ({len(kimaradt)} sor)")
    tenyek_irasa(KIMENET, sorted(kesz, key=lambda s: (s[0], s[1], s[2])))
    for kulcs, v in stat.items():
        print(f"  {kulcs}: {v}")
    if nincs_utca:
        print("\nNem értelmezhető címek (példák):")
        for c, n in list(nincs_utca.items())[:15]:
            print(f"  {c}")
    print(f"Mentve: {KIMENET}")


if __name__ == "__main__":
    main()
