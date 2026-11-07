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
from collections import Counter, defaultdict
from pathlib import Path

from kozos import kulcs, pont_poligonban, tenyek_olvasasa

OSM = "data/belvaros_epuletek.geojson"
TENYEK_MAPPA = Path("data/tenyek")
KEZI = "forras/kezi_javitasok.csv"
PRIORITAS = "forras/prioritas.json"
KIMENET = "data/belvaros_epuletek_vegleges.geojson"
UTKOZESEK = "data/utkozesek.csv"

DONTO_MEZOK = ["ev", "szintek", "tervezo", "magassag"]
SZAMOS = {"ev", "szintek", "magassag", "lechner_ev_kezdet", "lechner_ev_veg", "szintek_kep",
          "eubucco_magassag_min", "eubucco_magassag_max", "eubucco_szintek"}


def szam(x):
    try:
        v = float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return int(v) if v == int(v) else v


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
                            m != "ev" or abs(v - valasztott[1]) > tol):
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

    with open(KIMENET, "w", encoding="utf-8") as f:
        json.dump(gj, f, ensure_ascii=False)
    Path(UTKOZESEK).parent.mkdir(exist_ok=True)
    with open(UTKOZESEK, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["osm_tipus", "id", "nev", "mezo", "gyoztes", "eltero_forras"])
        w.writerows(utkozesek)

    print(f"\nÉpületek: {len(feats)}")
    for m in DONTO_MEZOK:
        print(f"  {m}: {dict(stat[m])}")
    ossz = Counter(u[3] for u in utkozesek)
    print(f"Ütközések (források eltérnek): {dict(ossz)}  -> {UTKOZESEK}")
    print(f"Mentve: {KIMENET}")


main()
