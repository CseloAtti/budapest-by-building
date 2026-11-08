"""Az összes forrás tényeiből előállítja a térkép végleges adatfájlját.

Bemenet:  data/belvaros_epuletek.geojson     (OSM-épületek, geojson_keszites.py)
          data/tenyek/*.csv                  (tenyek_*.py szkriptek)
          forras/kezi_javitasok.csv          (a te kézi javításaid, mindig ezek győznek)
          forras/prioritas.json              (melyik forrás győz melyik mezőnél)
Kimenet:  data/belvaros_epuletek_vegleges.geojson
          data/utkozesek.csv                 (ahol a források eltérnek, átnézésre)
"""
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from kozos import belso_pont, kulcs, pont_gyuruben, pont_poligonban, tenyek_olvasasa, teruletu_kozeppont

OSM = "data/belvaros_epuletek.geojson"
TENYEK_MAPPA = Path("data/tenyek")
KEZI = "forras/kezi_javitasok.csv"
PRIORITAS = "forras/prioritas.json"
RESZEK = "data/belvaros_reszek.geojson"           # building:part elemek (geojson_keszites.py)
KIMENET = "data/belvaros_epuletek_vegleges.geojson"
UTKOZESEK = "data/utkozesek.csv"
CIMEK = "data/osm_cimek.csv"                      # cimek_letoltes.py kimenete (OSM-címpontok)
BECSLES = "data/ev_becsles.csv"                   # ev_becsles.py kimenete (csak becslés, nem adat)
BECSLES_KORSZAKOK = ["1848 előtt", "1848–1918", "1919–1944", "1945–1956", "1957–1989", "1990–2010", "2011-től"]

DONTO_MEZOK = ["ev", "szintek", "tervezo", "magassag"]
SZAMOS = {"ev", "szintek", "magassag", "lechner_ev_kezdet", "lechner_ev_veg", "szintek_kep",
          "eubucco_magassag_min", "eubucco_magassag_max", "eubucco_szintek"}


def szam(x):
    try:
        v = float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return int(v) if v == int(v) else v


def tervezo_nevek(x):
    """'Feszl Frigyes (1821–1884)' és 'Feszl Frigyes' ugyanaz; több név: ',' ';' ' és ' elválasztja."""
    x = re.sub(r"\u00ad\s*|\u200b", "", re.sub(r"\([^)]*\)", "", str(x)))
    reszek = re.split(r",|;|\bés\b", x)
    ki = set()
    for r in reszek:
        r = " ".join(r.split()).lower().replace("ifj. ", "").replace("id. ", "")
        if r:
            ki.add(r)
    return ki


def tervezo_egyezik(a, b):
    na, nb = tervezo_nevek(a), tervezo_nevek(b)
    return bool(na and nb and (na <= nb or nb <= na))


# A részek ezeket a tulajdonságokat az épülettől örökölhetik, ha magukhoz nincs saját adatuk
NEM_OROKOLT = {"id", "osm_tipus", "resz", "szulo_id", "szulo_tipus"}
EV_CSOPORT = ("ev", "ev_forras")
SZINT_CSOPORT = ("szintek", "szintek_forras", "szintek_osm", "szint_eltero")
MAGASSAG_CSOPORT = ("magassag", "magassag_forras", "magassag_szintbol")
TOVABB_FEDETT = 0.5          # ennél kisebb arányban lefedett épületnél a részeket figyelmen kívül hagyjuk


def gyuru_terulet(gyuruk):
    """Terület m²-ben: a külső gyűrű mínusz a lyukak (udvarok)."""
    return max(teruletu_kozeppont(gyuruk[0])[0] - sum(teruletu_kozeppont(h)[0] for h in gyuruk[1:]), 1e-9)


def orokol(rp, sp):
    """A rész (rp) megkapja az épület (sp) tulajdonságait, ha a sajátjából hiányoznak."""
    rp["szulo_id"] = sp["id"]
    rp["szulo_tipus"] = sp["osm_tipus"]
    if rp.get("tipus") in (None, "yes"):
        rp["tipus"] = sp.get("tipus")
    sajat_ev = rp.get("ev") and sp.get("ev_forras") != "kezi"
    sajat_szint = rp.get("szintek") and sp.get("szintek_forras") != "kezi"
    sajat_mag = rp.get("magassag_forras") in ("height", "szintszam", "szintterkep", "kezi") \
        and sp.get("magassag_forras") != "kezi"
    for k, v in sp.items():
        if k in NEM_OROKOLT or k == "tipus":
            continue
        if k in EV_CSOPORT and sajat_ev:
            continue
        if k in SZINT_CSOPORT and sajat_szint:
            continue
        if k in MAGASSAG_CSOPORT and sajat_mag:
            continue
        if k in EV_CSOPORT + SZINT_CSOPORT + MAGASSAG_CSOPORT or rp.get(k) in (None, ""):
            rp[k] = v


def kozos_csucsok(gy_a, gy_b):
    return len({tuple(p) for p in gy_a} & {tuple(p) for p in gy_b})


def reszek_kezelese(feats):
    """Az épületrészeket (building:part) hozzárendeli az őket tartalmazó épülethez.

    1. Ha egy rész belső pontja az épület külső körvonalán belül van (az udvarok is
       az épülethez tartoznak), a rész az épületé.
    2. Ha a részek legalább felét lefedik az épület kontúrjának, a kontúr helyett a részeket
       rajzoljuk ki; ha kevésbé, a részeket hagyjuk el, és a kontúr marad.
    3. Az épületen kívül álló, de hozzá kapcsolódó részek (közös csúcsok, vagy a rész egyik
       csúcsa az épületen belül van) is öröklik az épület adatait, de önállóan jelennek meg.
    A név, a védettség stb. örökölt; a saját (OSM-ben megadott vagy kézzel javított) év,
    szintszám és magasság a résznél marad."""
    reszek = [ft for ft in feats if ft["properties"].get("resz")]
    szulok = [ft for ft in feats if not ft["properties"].get("resz")]
    stat = Counter()
    if not reszek:
        return feats, stat
    adatok = []
    for s in szulok:
        gy = s["geometry"]["coordinates"]
        xs = [p[0] for p in gy[0]]
        ys = [p[1] for p in gy[0]]
        adatok.append((min(xs), max(xs), min(ys), max(ys), gyuru_terulet(gy), s))
    csoportok = defaultdict(list)                 # id(szülő) -> [rész]
    kapcsolodo = []                               # (rész, szülő-feature)
    for r in reszek:
        gy = r["geometry"]["coordinates"]
        x, y = belso_pont([gy])
        jeloltek = [a for a in adatok if a[0] <= x <= a[1] and a[2] <= y <= a[3]
                    and pont_gyuruben(x, y, a[5]["geometry"]["coordinates"][0])]
        if jeloltek:
            szulo = min(jeloltek, key=lambda a: a[4])
            csoportok[id(szulo[5])].append((r, szulo))
            continue
        # nincs benne egyik kontúrban sem: kapcsolódik-e valamelyikhez?
        rx = [p[0] for p in gy[0]]
        ry = [p[1] for p in gy[0]]
        legjobb, pont = None, 0
        for a in adatok:
            if a[1] < min(rx) or a[0] > max(rx) or a[3] < min(ry) or a[2] > max(ry):
                continue
            kulso = a[5]["geometry"]["coordinates"][0]
            kozos = kozos_csucsok(gy[0], kulso)
            bent = sum(1 for px, py in gy[0][:-1] if pont_gyuruben(px, py, kulso))
            if kozos >= 2 or bent >= 1:
                p_ = kozos * 2 + bent
                if p_ > pont:
                    legjobb, pont = a, p_
        if legjobb:
            kapcsolodo.append((r, legjobb[5]))
        else:
            stat["önálló rész (nincs épületkontúr)"] += 1
    kihagy = set()
    for lista in csoportok.values():
        szulo = lista[0][1][5]
        szulo_ter = lista[0][1][4]
        fedett = sum(gyuru_terulet(r["geometry"]["coordinates"]) for r, _ in lista) / szulo_ter
        if fedett < TOVABB_FEDETT:
            for r, _ in lista:
                kihagy.add(id(r))
            stat["rész kihagyva (kevéssé fedi le az épületet)"] += len(lista)
            continue
        kihagy.add(id(szulo))
        stat["épület helyett részei"] += 1
        stat["rész az épületen belül"] += len(lista)
        for r, _ in lista:
            orokol(r["properties"], szulo["properties"])
    for r, szulo in kapcsolodo:
        orokol(r["properties"], szulo["properties"])
        stat["épületen kívüli, de hozzá kapcsolódó rész (örökli az adatait)"] += 1
    return [ft for ft in feats if id(ft) not in kihagy], stat


def becsles_hozzafuzese(feats):
    """Az ev_becsles.csv-ből külön 'ev_becsles_*' mezőket tesz a SZÜRKE (ev nélküli) épületekre.
    Az 'ev' mezőhöz nem nyúl: a becslés sosem számít adatnak."""
    if not Path(BECSLES).exists():
        print(f"Becslés: nincs {BECSLES} (futtasd: py ev_becsles.py)")
        return 0
    becsles = {}
    with open(BECSLES, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            becsles[(r["osm_tipus"], int(r["id"]))] = r
    db = 0
    for x in feats:
        pr = x["properties"]
        if pr.get("ev") or pr.get("resz"):
            continue
        r = becsles.get(kulcs(pr))
        if not r or r["becsult_korszak"] not in BECSLES_KORSZAKOK:
            continue
        pr["ev_becsles_korszak"] = BECSLES_KORSZAKOK.index(r["becsult_korszak"])
        pr["ev_becsles_valoszinuseg"] = float(r["valoszinuseg"])
        pr["ev_becsles_bizonyossag"] = r["bizonyossag"]
        pr["ev_becsles_indoklas"] = r["indoklas"]
        db += 1
    return db


def cimek_hozzafuzese(feats):
    """A 'cim' (első cím, pl. 'Alkotmány utca 2') és 'cim_tobb' (hány további cím) mezők a kártyához."""
    if not Path(CIMEK).exists():
        return 0
    cimek = defaultdict(list)
    with open(CIMEK, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r["utca"] and r["hazszam"]:
                cimek[(r["osm_tipus"], int(r["id"]))].append(f'{r["utca"]} {r["hazszam"]}')
    db = 0
    for x in feats:
        pr = x["properties"]
        lista = cimek.get(kulcs(pr))
        if not lista and pr.get("szulo_id") and pr.get("szulo_tipus"):
            lista = cimek.get((pr["szulo_tipus"], int(pr["szulo_id"])))   # épületrész: a szülő címe
        if lista:
            lista = list(dict.fromkeys(lista))
            pr["cim"] = lista[0]
            if len(lista) > 1:
                pr["cim_tobb"] = len(lista) - 1
            db += 1
    return db


def ertek(mezo, x):
    return szam(x) if mezo in SZAMOS else x


def main():
    with open(PRIORITAS, encoding="utf-8") as f:
        pri = json.load(f)
    tol = pri.get("ev_tolerancia", 2)

    with open(OSM, encoding="utf-8") as f:
        gj = json.load(f)
    elozo = len(gj["features"])
    gj["features"] = [x for x in gj["features"] if x["properties"].get("tipus") != "roof"]
    if len(gj["features"]) != elozo:
        print(f"Tető-elemek kihagyva: {elozo - len(gj['features'])}")
    feats = gj["features"]
    if Path(RESZEK).exists():
        with open(RESZEK, encoding="utf-8") as f:
            reszek = json.load(f)["features"]
        van = {kulcs(ft["properties"]) for ft in feats}
        reszek = [r for r in reszek if kulcs(r["properties"]) not in van]
        for r in reszek:
            r["properties"]["resz"] = True
        feats.extend(reszek)
        print(f"  épületrészek (building:part): {len(reszek)}")
    index = defaultdict(list)
    for ft in feats:
        index[kulcs(ft["properties"])].append(ft)

    # ---- tények összegyűjtése ----
    tenyek = []
    for ut in sorted(TENYEK_MAPPA.glob("*.csv")):
        sorok = tenyek_olvasasa(ut)
        tenyek += sorok
        print(f"  {ut.name}: {len(sorok)} sor")
    kezi_sorok = tenyek_olvasasa(KEZI, "kezi") if Path(KEZI).exists() else []
    for r in kezi_sorok:
        r["forras"] = "kezi"
    print(f"  kézi javítások: {len(kezi_sorok)} sor")

    # kézi sor azonosító nélkül: koordináta alapján keressük meg az épületet
    nem_talalt = 0
    for r in kezi_sorok:
        if (r.get("id") or "").strip():
            continue
        try:
            x, y = float(r["lon"]), float(r["lat"])
        except (TypeError, ValueError):
            nem_talalt += 1
            r["id"] = ""
            continue
        for ft in feats:
            if pont_poligonban(x, y, ft["geometry"]["coordinates"]):
                r["osm_tipus"], r["id"] = kulcs(ft["properties"])
                break
        else:
            nem_talalt += 1
            r["id"] = ""
    tenyek += kezi_sorok

    szedett = defaultdict(lambda: defaultdict(list))   # kulcs -> mező -> [(forras, érték, megjegyzés)]
    ismeretlen = 0
    for r in tenyek:
        try:
            k = ((r.get("osm_tipus") or "way").strip(), int(r["id"]))
        except (TypeError, ValueError):
            ismeretlen += 1
            continue
        if k not in index:
            ismeretlen += 1
            continue
        v = ertek(r["mezo"], r["ertek"])
        if v in (None, ""):
            continue
        szedett[k][r["mezo"]].append((r["forras"], v, r.get("megjegyzes", "")))
    if ismeretlen or nem_talalt:
        print(f"Figyelem: {ismeretlen} tény-sor olyan épületre hivatkozik, ami nincs az OSM-fájlban; "
              f"{nem_talalt} kézi sor nem azonosítható.")

    utkozesek = []
    stat = {m: Counter() for m in DONTO_MEZOK}
    for k, lista in index.items():
        for ft in lista:
            pr = ft["properties"]
            tn = szedett.get(k, {})
            # az OSM saját adatai is forrásnak számítanak
            jel = {m: list(tn.get(m, [])) for m in DONTO_MEZOK}
            if pr.get("ev"):
                jel["ev"].append(("osm", pr["ev"], pr.get("ev_forras") or ""))
            if pr.get("szintek"):
                jel["szintek"].append(("osm", pr["szintek"], "building:levels"))
            if pr.get("magassag_forras") == "height":
                jel["magassag"].append(("osm_height", pr["magassag"], "height"))
            osm_ev_forras = pr.get("ev_forras")

            for m in ("ev", "tervezo", "szintek"):
                valasztott = None
                for forras in pri[m]:
                    # a kézi javításnál a legutoljára beírt érték győz
                    for f_, v, megj in (reversed(jel[m]) if forras == "kezi" else jel[m]):
                        if f_ == forras:
                            valasztott = (f_, v, megj)
                            break
                    if valasztott:
                        break
                for f_, v, megj in jel[m]:   # ütközések
                    if valasztott and f_ != valasztott[0] and v != valasztott[1] and (
                            m != "ev" or abs(v - valasztott[1]) > tol) and (
                            m != "tervezo" or not tervezo_egyezik(v, valasztott[1])):
                        utkozesek.append((k[0], k[1], pr.get("nev") or "", m,
                                          f"{valasztott[0]}={valasztott[1]}", f"{f_}={v}"))
                if valasztott:
                    f_, v, _ = valasztott
                    pr[m] = v
                    stat[m][f_] += 1
                    if m == "tervezo":
                        pr["tervezo_forras"] = f_
                    if m == "ev":
                        pr["ev_forras"] = osm_ev_forras if f_ == "osm" else f_
                    elif m == "szintek":
                        pr["szintek_forras"] = f_
                        osm_sz = pr.get("szintek") if f_ == "osm" else None
                    # szintek: az OSM-értéket külön is megőrizzük
                else:
                    pr.pop(m, None)
                    if m == "tervezo":
                        pr.pop("tervezo_forras", None)
                    if m == "ev":
                        pr["ev_forras"] = None
            osm_szint = next((v for f_, v, _ in jel["szintek"] if f_ == "osm"), None)
            if osm_szint is not None:
                pr["szintek_osm"] = osm_szint
            if pr.get("szintek") and osm_szint and pr["szintek"] != osm_szint:
                pr["szint_eltero"] = True
            else:
                pr.pop("szint_eltero", None)
            if pr.get("szintek") is None:
                pr.pop("szintek_forras", None)

            # magasság: a szintszámból számolt és az alapértelmezett is jelölt
            if pr.get("szintek"):
                jel["magassag"].append(("szintbol", pr["szintek"] * pri["meter_szintenkent"], ""))
                pr["magassag_szintbol"] = pr["szintek"] * pri["meter_szintenkent"]
            jel["magassag"].append(("alapertelmezett", pri["alapertelmezett_magassag"], ""))
            valasztott = None
            for forras in pri["magassag"]:
                for f_, v, megj in (reversed(jel["magassag"]) if forras == "kezi" else jel["magassag"]):
                    if f_ == forras:
                        valasztott = (f_, v)
                        break
                if valasztott:
                    break
            f_, v = valasztott
            pr["magassag"] = v
            stat["magassag"][f_] += 1
            if f_ == "osm_height":
                pr["magassag_forras"] = "height"
            elif f_ == "szintbol":
                pr["magassag_forras"] = "szintterkep" if pr.get("szintek_forras") == "szintterkep" else "szintszam"
            else:
                pr["magassag_forras"] = f_

            # minden egyéb tény egyszerű tulajdonságként (a lista utolsó eleme érvényes)
            for mezo, vals in tn.items():
                if mezo in DONTO_MEZOK:
                    continue
                kezi = [x for x in vals if x[0] == "kezi"]
                if kezi:                            # a kézi javítás az egyéb mezőknél is győz
                    pr[mezo] = kezi[-1][1]
                elif mezo == "wikipedia":           # több forrás cikkei egyesítve (legfeljebb 3)
                    egyedi = list(dict.fromkeys(str(x[1]) for x in vals))
                    pr[mezo] = "|".join(egyedi[:3])
                else:
                    pr[mezo] = vals[-1][1]
                if pr.get(mezo) in ("-", ""):       # '-' = a kézi javítás eltávolítja a mezőt
                    pr.pop(mezo, None)

    gj["features"], resz_stat = reszek_kezelese(feats)
    becsles_db = becsles_hozzafuzese(gj["features"])
    cim_db = cimek_hozzafuzese(gj["features"])
    with open(KIMENET, "w", encoding="utf-8") as f:
        json.dump(gj, f, ensure_ascii=False)
    Path(UTKOZESEK).parent.mkdir(exist_ok=True)
    with open(UTKOZESEK, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["osm_tipus", "id", "nev", "mezo", "gyoztes", "eltero_forras"])
        w.writerows(utkozesek)

    print(f"\nÉpületek: {len(feats)}")
    for kulcs_, db in resz_stat.items():
        print(f"  épületrészek – {kulcs_}: {db}")
    print(f"  kiírt elemek: {len(gj['features'])}")
    print(f"  becsült korszakkal ellátott szürke épület: {becsles_db}")
    print(f"  címmel ellátott elem: {cim_db}")
    for m in DONTO_MEZOK:
        print(f"  {m}: {dict(stat[m])}")
    ossz = Counter(u[3] for u in utkozesek)
    print(f"Ütközések (források eltérnek): {dict(ossz)}  -> {UTKOZESEK}")
    print(f"Mentve: {KIMENET}")


main()
