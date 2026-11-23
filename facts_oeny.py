"""E-Örökség (oeny.hu) PDFs saved from the advanced search -> data/tenyek/oeny.csv

Usage:
  1. In oeny.hu's advanced search filter for a district (e.g. Budapest V.), and save the result
     pages (48 per page) one by one as PDF (Print -> Save as PDF).
  2. Put the PDFs in the data/oeny_pdf/ folder (the data/ folder is not in git).
  3. py -m pip install pdfplumber      (needed once)
  4. py facts_oeny.py            (the inner city)
     py facts_oeny.py varos      (the whole city: addresses are searched within the district, by 'BUDAPEST 10';
                                   first: py city_assembly.py)

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

from common import write_facts

PDF_FOLDER = Path("data/oeny_pdf")
JSON_OUTPUT = Path("data/oeny_epuletek.json")
CITY = "varos" in sys.argv[1:]          # py facts_oeny.py varos  (the whole city, paired per district)
ADDRESSES = "data/varos/osm_cimek.csv" if CITY else "data/osm_cimek.csv"
BUILDINGS = "data/varos/epuletek.geojson"
RENAMING = "forras/utcanev_atnevezesek.csv"
REGISTER = "data/muemlek_jegyzek.json"
OUTPUT = "data/tenyek/oeny.csv"
NOT_PAIRED = "data/oeny_nem_parositott.csv"

NAME = r"[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+(?:-[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+)*"
PERSON = rf"{NAME} {NAME}"                                  # 'Hild József'
PEOPLE = rf"{PERSON}(?:(?:,| és) {PERSON})*"                # 'Quittner Zsigmond és Vágó József'
GROUP = rf"{NAME}(?:-{NAME})+"                           # 'Feszl-Gerster-Kauser'
YEAR = r"(1[5-9]\d\d)(?:\s*-\s*(1[5-9]\d\d))?"
MONTHS = "januar|februar|marcius|aprilis|majus|junius|julius|augusztus|szeptember|oktober|november|december"


# ---------------------------------------------------------------- PDF -> cards
def pdf_cards(path_):
    import pdfplumber
    cards, current = [], None

    def close():
        nonlocal current
        if current:
            cards.append(current)
        current = None

    with pdfplumber.open(path_) as pdf:
        for page in pdf.pages:
            words = page.extract_words(extra_attrs=["fontname", "size"])
            # next to every record of the result list there is the data sheet's link: /monument/<monument id>
            links = []
            for h in page.hyperlinks:
                mm = re.search(r"/public/monument/(\d+)\s*$", h.get("uri") or "")
                if mm:
                    links.append((h["top"], int(mm.group(1))))
            end_ = min([w["top"] for w in words if w["text"] == "db/oldal"] or [10 ** 6])
            words = [w for w in words if w["top"] < end_ - 1 and w["top"] > 24 and w["x0"] > 245 and w["x1"] < 440]
            words.sort(key=lambda w: (round(w["top"]), w["x0"]))
            for w in words:
                t, m, f = w["text"], w["size"], w["fontname"]
                if "Bold" in f and 3.4 < m < 4.4 and re.fullmatch(r"\d{3,6}", t):
                    close()
                    current = {"torzsszam": int(t), "nev": [], "cim": [], "cim_szoveg": "", "leiras": []}
                    near = [(abs(top - w["top"]), az) for top, az in links if abs(top - w["top"]) <= 12]
                    if near:
                        current["azonosito"] = min(near)[1]
                elif current is None:
                    continue
                elif 8 < m < 9.2:
                    current["nev"].append(t)
                elif 4.6 < m < 5.6:
                    current["cim"].append(t)
                elif 6.2 < m < 7.4:
                    current["leiras"].append(t)
    close()
    for k in cards:
        k["nev"] = " ".join(k["nev"])
        k["cim_szoveg"] = " ".join(k.pop("cim"))
        k["leiras"] = " ".join(k["leiras"])
    return cards


# ---------------------------------------------------------------- description -> facts
def description_facts(d):
    """(designer, year) from the description, if unambiguous. Otherwise Nones."""
    d = " ".join(d.split())
    d = re.sub(r"(?<=\w)- (?=\w)", "-", d)             # hyphen split at a line break: 'Borsody- ház'
    truncated = d.endswith("…")
    designer = year = None
    # 'Quittner Zsigmond és Vágó József, 1907.'  /  'Weber Antal 1872.'  /  'Feszl-Gerster-Kauser, 1853-1854.'
    # with several building phases we take the first (the original construction): 'Brein Ignác, 1820., ifj. Zitterbarth Mátyás, 1861.'
    m = re.search(rf"(?<![\wÁÉÍÓÖŐÚÜŰáéíóöőúüű-])({PEOPLE}|{GROUP}),? {YEAR}(?!\d|-b)", d)
    if m:
        designer = m.group(1)
        year = int(m.group(2))
    else:
        m = re.search(rf"[Tt]ervezte:? ({PEOPLE}|{GROUP})|[Tt]ervezője:? ({PEOPLE}|{GROUP})|({PEOPLE}|{GROUP}) (?:tervei|terve) szerint", d)
        if m:
            designer = next(g for g in m.groups() if g)
        # standalone year of construction: 'épült 1910-ben' (built in 1910) / 'Banképület, épült 1910-ben.' / ', 1813.'
        e = re.search(rf"[ée]pült:? {YEAR}", d)
        if e:
            year = int(e.group(1))
        elif not truncated:
            e = re.search(rf"(?:,|\.) {YEAR}\.(?: |$)", d)
            if e:
                year = int(e.group(1))
    return designer, year


# ---------------------------------------------------------------- address -> (street, house numbers)
def strip(s):
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", "", s)


def numbers_(text_):
    out = set()
    for a, b in re.findall(r"(\d+)\s*(?:[-–]\s*(\d+))?", text_ or ""):
        out.add(int(a))
        if b:
            out.add(int(b))
    return out


def clean_street(s):
    return re.sub(r"[^a-z0-9]", "", strip(s))


def split_addresses(address_text, street_names, renaming):
    """'BUDAPEST 5, ZO LTÁ N UT C A 1 8 ., DEÁK...' -> [(street_name_stripped, {house numbers}), ...]"""
    t = address_text
    t = re.sub(r"^\s*BUDAPEST\s*\d+\s*,", "", t)
    t = strip(t)
    t = re.sub(r"(?<=[a-z])u\.(?=\d)", "utca", t)            # 'BÁSTYA U. 33.' -> 'bastyautca33.'
    t = re.sub(rf"({MONTHS})(\d+)\.", r"\1\2", t)
    t = re.sub(r"(?<=[a-z])-(?=[a-z])", "", t)          # 'bajcsy-zsilinszky' -> 'bajcsyzsilinszky'
    long = sorted(street_names, key=len, reverse=True)
    out, i = [], 0
    while i < len(t):
        for u in long:
            if t.startswith(u, i):
                j = i + len(u)
                m = re.match(r"(\d+)(?:\.?-(\d+))?\.?", t[j:])
                if m:
                    out.append((renaming.get(u, u), numbers_(m.group(0))))
                    i = j + m.end()
                else:
                    i = j
                break
        else:
            i += 1
    return out


# ---------------------------------------------------------------- main program
def pdf_read():
    everything = []
    if PDF_FOLDER.exists():
        pdfk = sorted(PDF_FOLDER.glob("*.pdf"))
        if pdfk:
            try:
                import pdfplumber  # noqa: F401
            except ImportError:
                sys.exit("Hiányzik a pdfplumber. Telepítés:  py -m pip install pdfplumber")
            for p in pdfk:
                k = pdf_cards(p)
                print(f"  {p.name}: {len(k)} bejegyzés")
                everything += k
    if everything:
        unique = {}
        for k in everything:
            previous = unique.get((k["torzsszam"], k["cim_szoveg"]))
            az = list(previous.get("azonositok", [])) if previous else []
            if k.get("azonosito") and k["azonosito"] not in az:
                az.append(k["azonosito"])
            k["azonositok"] = az                        # several monument ids (data sheets) can belong to one register number
            k.pop("azonosito", None)
            unique[(k["torzsszam"], k["cim_szoveg"])] = k
        everything = list(unique.values())
        JSON_OUTPUT.parent.mkdir(exist_ok=True)
        JSON_OUTPUT.write_text(json.dumps(everything, ensure_ascii=False, indent=1), encoding="utf-8")
    elif JSON_OUTPUT.exists():
        everything = json.loads(JSON_OUTPUT.read_text(encoding="utf-8"))
        print(f"  (nincs PDF a {PDF_FOLDER} mappában, a korábbi {JSON_OUTPUT} adatait használom)")
    else:
        sys.exit(f"Tedd a PDF-eket a {PDF_FOLDER} mappába.")
    return everything


def main():
    cards = pdf_read()
    print(f"Bejegyzések összesen: {len(cards)}")
    # register number -> data-sheet ids; assemble.py uses it for the monument zones drawn in the zone editor
    az_map = {}
    for k in cards:
        for a in k.get("azonositok", []):
            if a not in az_map.setdefault(str(k["torzsszam"]), []):
                az_map[str(k["torzsszam"])].append(a)
    Path("data/oeny_azonositok.json").write_text(json.dumps(az_map, ensure_ascii=False), encoding="utf-8")

    atn = {}                       # old street name (stripped) -> current name (stripped); left out if there are several possibilities
    try:
        with open(RENAMING, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                if r.get("regi") and r.get("uj") and "|" not in r["uj"]:
                    atn[clean_street(r["regi"])] = clean_street(r["uj"])
    except FileNotFoundError:
        pass

    district = {}                  # (type, id) -> district number (only in city mode)
    if CITY:
        with open(BUILDINGS, encoding="utf-8") as f:
            for ft in json.load(f)["features"]:
                pr = ft["properties"]
                if pr.get("kerulet"):
                    district[(pr["osm_tipus"], int(pr["id"]))] = pr["kerulet"]
        if not district:
            sys.exit("Az épületeknél nincs kerület. Futtasd: py budapest_pbf.py, majd py city_assembly.py")
    streets = defaultdict(lambda: defaultdict(list))     # (district, stripped street name) -> house number -> [(type, id)]
    street_names = set()
    with open(ADDRESSES, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if CITY and (r["osm_tipus"], int(r["id"])) not in district:
                continue
            kn = district.get((r["osm_tipus"], int(r["id"])), 0)
            u0 = clean_street(r["utca"])
            street_names.add(u0)
            for sz in numbers_(r["hazszam"]):
                streets[(kn, u0)][sz].append((r["osm_tipus"], int(r["id"])))
    street_names |= set(atn)

    book = {}
    try:
        for b in json.loads(Path(REGISTER).read_text(encoding="utf-8"))["bejegyzesek"]:
            book[int(b["torzsszam"])] = b
    except (FileNotFoundError, ValueError, KeyError):
        pass

    done = set()
    candidates = defaultdict(list)   # (type, id) -> [(score, card, designer, year, remark)]
    left_out = []                  # the unpaired entries for manual completion
    stat = Counter()
    none_street = Counter()
    for k in cards:
        designer, year = description_facts(k["leiras"])
        stat["tervező kiolvasva"] += bool(designer)
        stat["év kiolvasva"] += bool(year)
        stat["törzsszám a műemlékjegyzék-könyvben is"] += k["torzsszam"] in book
        addresses = split_addresses(k["cim_szoveg"], street_names, atn)
        mk = re.match(r"\s*BUDAPEST\s*(\d+)", k["cim_szoveg"])
        kn = int(mk.group(1)) if (CITY and mk) else 0
        # Only the entry's first (main) address is used. The other addresses are typically the corner house's
        # entrance on the other street, which is often a neighbouring building's address and would bring wrong data to it.
        hit = set()
        points = Counter()         # building -> how many of its address rows match the house numbers of the entry's main address
        if addresses:
            u, sz = addresses[0]
            for n in sz:
                for b in streets.get((kn, u), {}).get(n, []):
                    points[b] += 1
                    hit.add(b)
        if not hit:
            stat["nem párosítható épülethez"] += 1
            if not addresses:
                ok = "nincs házszám, vagy az utcanév alakja nem ismerhető fel (az OSM-ben más néven szerepelhet)"
            elif addresses[0][0] in {u for u in street_names}:
                ok = "a fő cím házszáma nincs az OSM-épületek címei között"
            else:
                ok = "a fő cím utcája nincs az OSM-címek között"
            # buildings possible by the other addresses (only a hint, not certain!)
            other = []
            for u, sz in addresses[1:]:
                for n in sorted(sz):
                    for kind, id_ in streets.get((kn, u), {}).get(n, []):
                        other.append(f"{kind} {id_} ({u} {n})")
            left_out.append([k["torzsszam"], k.get("nev", ""), re.sub(r"^\s*BUDAPEST\s*\d+\s*,\s*", "", k["cim_szoveg"]),
                             ok, designer or "", year or "", "; ".join(other)])
            if not addresses:
                none_street[k["cim_szoveg"][:60]] += 1
            continue
        stat["párosítva"] += 1
        remark = f"E-Örökség, törzsszám {k['torzsszam']}" + (f", {len(hit)} OSM-épület" if len(hit) > 1 else "")
        for b in hit:
            candidates[b].append((points[b], k, designer, year, remark))
    # Several entries can match one large OSM building (a block) because its addresses include the addresses of several monuments.
    # In that case only the entry(ies) matching the most address rows are kept (all on a tie); the others would bring wrong data (year, designer) to it.
    for (t, i), list_ in candidates.items():
        best = max(p for p, *_ in list_)
        stat["több bejegyzésből csak a legjobb marad (épület)"] += len(list_) > 1
        for p, k, designer, year, remark in list_:
            if p < best:
                continue
            rows = [("muemlek_torzsszam", k["torzsszam"])]
            if k["torzsszam"] not in book:
                rows.append(("vedettseg", "M"))         # a register number not in the book: it is on the list's 'Műemlékek' (monuments) tab
            for az in k.get("azonositok", [])[:3]:
                rows.append(("oeny_azonosito", az))          # the data sheet: https://www.oeny.hu/oeny/eorok/public/monument/<id>
            if designer:
                rows.append(("tervezo", designer))
            if year:
                rows.append(("ev", year))
            for field, value in rows:
                done.add((t, i, field, value, "oeny", remark + (" (leírásból kiolvasva)" if field in ("tervezo", "ev") else "")))
    left_out.sort(key=lambda s: s[2])
    with open(NOT_PAIRED, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["torzsszam", "megnevezes", "cim", "miert_nem_parosult", "kiolvasott_tervezo",
                    "kiolvasott_ev", "lehetseges_epuletek_a_tobbi_cim_alapjan"])
        w.writerows(left_out)
    print(f"Nem párosított bejegyzések listája: {NOT_PAIRED} ({len(left_out)} sor)")
    write_facts(OUTPUT, sorted(done, key=lambda s: (s[0], s[1], s[2])))
    for building_key, v in stat.items():
        print(f"  {building_key}: {v}")
    if none_street:
        print("\nNem értelmezhető címek (példák):")
        for c, n in list(none_street.items())[:15]:
            print(f"  {c}")
    print(f"Mentve: {OUTPUT}")


if __name__ == "__main__":
    main()
