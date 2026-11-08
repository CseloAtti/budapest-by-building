"""E-Örökség (oeny.hu) összetett keresőből mentett PDF-ek -> data/tenyek/oeny.csv

Használat:
  1. Az oeny.hu összetett keresőjében szűrj kerületre (pl. Budapest V.), és a találati
     oldalakat (48 db/oldal) egyenként mentsd PDF-be (Nyomtatás -> Mentés PDF-ként).
  2. A PDF-eket tedd a data/oeny_pdf/ mappába (a data/ mappa nincs a gitben).
  3. py -m pip install pdfplumber      (egyszer kell)
  4. py tenyek_oeny.py

Amit kinyer: műemléki törzsszám, cím(ek), és a rövid leírásból a tervező és az építés éve,
ha egyértelműen kiolvasható ("..., Hild József, 1837."). Csak tényeket vesz át, a leírás
szövegét nem tárolja. A leírást az oldal 2-3 sorra vágja ("…"), ezért a tervező/év nem
mindenhol olvasható ki. A kinyert adatok forrása "oeny" (a prioritás.json-ban a műemlékjegyzék
után következik).
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
CIMEK = "data/osm_cimek.csv"
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


# ---------------------------------------------------------------- PDF -> kártyák
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
            vege = min([w["top"] for w in szavak if w["text"] == "db/oldal"] or [10 ** 6])
            szavak = [w for w in szavak if w["top"] < vege - 1 and w["top"] > 24 and w["x0"] > 245 and w["x1"] < 440]
            szavak.sort(key=lambda w: (round(w["top"]), w["x0"]))
            for w in szavak:
                t, m, f = w["text"], w["size"], w["fontname"]
                if "Bold" in f and 3.4 < m < 4.4 and re.fullmatch(r"\d{3,6}", t):
                    lezar()
                    akt = {"torzsszam": int(t), "nev": [], "cim": [], "cim_szoveg": "", "leiras": []}
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


# ---------------------------------------------------------------- leírás -> tények
def leiras_tenyek(d):
    """(tervező, év) a leírásból, ha egyértelmű. Egyébként None-ok."""
    d = " ".join(d.split())
    d = re.sub(r"(?<=\w)- (?=\w)", "-", d)             # sortöréskor elválasztott kötőjel: 'Borsody- ház'
    csonka = d.endswith("…")
    tervezo = ev = None
    # 'Quittner Zsigmond és Vágó József, 1907.'  /  'Weber Antal 1872.'  /  'Feszl-Gerster-Kauser, 1853-1854.'
    # több építési szakasznál az elsőt vesszük (az eredeti építést): 'Brein Ignác, 1820., ifj. Zitterbarth Mátyás, 1861.'
    m = re.search(rf"(?<![\wÁÉÍÓÖŐÚÜŰáéíóöőúüű-])({EMBEREK}|{CSOPORT}),? {EV}(?!\d|-b)", d)
    if m:
        tervezo = m.group(1)
        ev = int(m.group(2))
    else:
        m = re.search(rf"[Tt]ervezte:? ({EMBEREK}|{CSOPORT})|[Tt]ervezője:? ({EMBEREK}|{CSOPORT})|({EMBEREK}|{CSOPORT}) (?:tervei|terve) szerint", d)
        if m:
            tervezo = next(g for g in m.groups() if g)
        # önálló építési év: 'épült 1910-ben' / 'Banképület, épült 1910-ben.' / ', 1813.'
        e = re.search(rf"[ée]pült:? {EV}", d)
        if e:
            ev = int(e.group(1))
        elif not csonka:
            e = re.search(rf"(?:,|\.) {EV}\.(?: |$)", d)
            if e:
                ev = int(e.group(1))
    return tervezo, ev


# ---------------------------------------------------------------- cím -> (utca, házszámok)
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
    """'BUDAPEST 5, ZO LTÁ N UT C A 1 8 ., DEÁK...' -> [(utcanév_lecsupaszítva, {házszámok}), ...]"""
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


# ---------------------------------------------------------------- fő program
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

    atn = {}                       # régi utcanév (lecsupaszítva) -> mai név (lecsupaszítva); több lehetőségnél kimarad
    try:
        with open(ATNEVEZES, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                if r.get("regi") and r.get("uj") and "|" not in r["uj"]:
                    atn[tisztit_utca(r["regi"])] = tisztit_utca(r["uj"])
    except FileNotFoundError:
        pass

    utcak = defaultdict(lambda: defaultdict(list))     # lecsupaszított utcanév -> házszám -> [(tip, id)]
    with open(CIMEK, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            for sz in szamok(r["hazszam"]):
                utcak[tisztit_utca(r["utca"])][sz].append((r["osm_tipus"], int(r["id"])))
    utcanevek = set(utcak) | set(atn)

    konyv = {}
    try:
        for b in json.loads(Path(JEGYZEK).read_text(encoding="utf-8"))["bejegyzesek"]:
            konyv[int(b["torzsszam"])] = b
    except (FileNotFoundError, ValueError, KeyError):
        pass

    kesz = set()
    kimaradt = []                  # a nem párosított bejegyzések kézi pótláshoz
    stat = Counter()
    nincs_utca = Counter()
    for k in kartyak:
        tervezo, ev = leiras_tenyek(k["leiras"])
        stat["tervező kiolvasva"] += bool(tervezo)
        stat["év kiolvasva"] += bool(ev)
        stat["törzsszám a műemlékjegyzék-könyvben is"] += k["torzsszam"] in konyv
        cimek = cimek_felbontasa(k["cim_szoveg"], utcanevek, atn)
        # Csak a bejegyzés első (fő) címét használjuk. A többi cím jellemzően a sarokház
        # másik utcai bejárata, ami gyakran egy szomszéd épület címe, és téves adatot vinne rá.
        talalat = set()
        if cimek:
            u, sz = cimek[0]
            for n in sz:
                talalat.update(utcak[u].get(n, []))
        if not talalat:
            stat["nem párosítható épülethez"] += 1
            if not cimek:
                ok = "nincs házszám, vagy az utcanév alakja nem ismerhető fel (az OSM-ben más néven szerepelhet)"
            elif cimek[0][0] in {u for u in utcanevek}:
                ok = "a fő cím házszáma nincs az OSM-épületek címei között"
            else:
                ok = "a fő cím utcája nincs az OSM-címek között"
            # a többi cím alapján lehetséges épületek (csak segítség, nem biztos!)
            mas = []
            for u, sz in cimek[1:]:
                for n in sorted(sz):
                    for tip, azon in utcak.get(u, {}).get(n, []):
                        mas.append(f"{tip} {azon} ({u} {n})")
            kimaradt.append([k["torzsszam"], k.get("nev", ""), re.sub(r"^\s*BUDAPEST\s*\d+\s*,\s*", "", k["cim_szoveg"]),
                             ok, tervezo or "", ev or "", "; ".join(mas)])
            if not cimek:
                nincs_utca[k["cim_szoveg"][:60]] += 1
            continue
        stat["párosítva"] += 1
        megj = f"E-Örökség, törzsszám {k['torzsszam']}" + (f", {len(talalat)} OSM-épület" if len(talalat) > 1 else "")
        for t, i in talalat:
            sorok = [("muemlek_torzsszam", k["torzsszam"])]
            if k["torzsszam"] not in konyv:
                sorok.append(("vedettseg", "M"))         # a könyvben nem szereplő törzsszám: a lista 'Műemlékek' fülén van
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
