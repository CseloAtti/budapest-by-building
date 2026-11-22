"""Kerületi értékkatasztereken alapuló tények -> data/tenyek/ertekleltar.csv

Bemenet:  data/ertekleltar_kartyak.json  (a II., III., IV., X., XIV., XV., XXI., XXIII. kerületi értékkatasztereknek és kézikönyveknek az épületlapokból kiolvasott adatai:
          cím, hrsz, építés éve, tervező, stílus, védelem; csak tények, a leírások szövegét nem tároljuk)
          data/varos/epuletek.geojson, data/varos/osm_cimek.csv   (py varos_osszeallitas.py)
Kimenet:  data/tenyek/ertekleltar.csv            - tények az osszeepit.py-hoz (forrás: 'ertekleltar')
          data/ertekleltar_nem_parositott.csv    - amit nem sikerült épülethez kötni (kézi javításhoz)
          data/varos/ertekleltar_kozelito.csv    - 'az 1930-as évek', '1910 körül' jellegű korszakadatok (CSAK a becslőnek, nem 'ev')

Futtatás:  py tenyek_ertekleltar.py
Az épületet kerület + utca + házszám alapján keresi. A betűs házszámot (27/C) pontosan kell találnia; ha az OSM-ben
nincs betű, de a számon legfeljebb 2 épület van, azt fogadja el.
"""
import csv
import json
import re
from collections import Counter, defaultdict

from tenyek_oeny import tisztit_utca, szamok
from kozos import tenyek_irasa
from szazad import szoveg_evtartomany

KARTYAK = "data/ertekleltar_kartyak.json"
EPULETEK = "data/varos/epuletek.geojson"
CIMEK = "data/varos/osm_cimek.csv"
ATNEVEZES = "forras/utcanev_atnevezesek.csv"
KIMENET = "data/tenyek/ertekleltar.csv"
NEM_PAROSITOTT = "data/ertekleltar_nem_parositott.csv"
KOZELITO = "data/varos/ertekleltar_kozelito.csv"


def hazszam_kulcs(s):
    return re.sub(r"[\s.]", "", (s or "").lower()).replace("–", "-")


def cim_felbontas(cim):
    """'KORPONAI UTCA 4. - Endre utca 1/A.' -> (utca_lecsupaszítva, [házszám-szövegek]) az első címből."""
    c = re.split(r"\s+[-–=]\s+|;|\s*\bés\b\s", cim.strip(), maxsplit=1)[0]
    c = re.sub(r"\b(u)\.(?=\s|$)", "utca", c, flags=re.I)
    c = re.sub(r"\.(?=/)", "", c).strip(" -")
    m = re.match(r"^(.*?[^\d\s])\s*(\d+(?:\s*[/-]\s*[0-9A-Za-z]+)*[A-Za-z]?)\.?\s*(?:,.*)?$", c)
    if not m:
        return None, []
    utca, hsz = m.group(1), m.group(2)
    kulcsok = []
    r = re.fullmatch(r"(\d+)\s*-\s*(\d+)", hsz)
    if r and int(r.group(2)) > int(r.group(1)) and int(r.group(2)) - int(r.group(1)) <= 20:
        a, b = int(r.group(1)), int(r.group(2))
        kulcsok = [str(n) for n in range(a, b + 1, 2)] if b - a > 1 else [str(a), str(b)]
    else:
        kulcsok = [hazszam_kulcs(hsz)]
    return tisztit_utca(utca), kulcsok


def main():
    kartyak = json.load(open(KARTYAK, encoding="utf-8"))
    atn = {}
    try:
        with open(ATNEVEZES, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                if r.get("regi") and r.get("uj") and "|" not in r["uj"]:
                    atn[tisztit_utca(r["regi"])] = tisztit_utca(r["uj"])
    except FileNotFoundError:
        pass
    kerulete = {}
    with open(EPULETEK, encoding="utf-8") as f:
        for ft in json.load(f)["features"]:
            pr = ft["properties"]
            if pr.get("kerulet"):
                kerulete[(pr["osm_tipus"], int(pr["id"]))] = pr["kerulet"]
    if not kerulete:
        raise SystemExit("Az épületeknél nincs kerület. Futtasd: py budapest_pbf.py, majd py varos_osszeallitas.py")
    pontos = defaultdict(set)        # (kerület, utca, házszám-kulcs) -> épületek
    szam = defaultdict(set)          # (kerület, utca, szám) -> épületek (betű nélkül)
    with open(CIMEK, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            e = (r["osm_tipus"], int(r["id"]))
            kn = kerulete.get(e)
            if not kn:
                continue
            u = tisztit_utca(r["utca"])
            for resz in re.split(r"[;,]", r["hazszam"] or ""):
                k = hazszam_kulcs(resz)
                if not k:
                    continue
                pontos[(kn, u, k)].add(e)
                m = re.match(r"(\d+)", k)
                if m:
                    szam[(kn, u, m.group(1))].add(e)

    kesz, kimaradt, kozelito = set(), [], []
    stat = Counter()
    for k in kartyak:
        kn = k["kerulet"]
        u, hszok = cim_felbontas(k["cim"])
        u = atn.get(u, u)
        talalat = set()
        if u:
            for h in hszok:
                t = pontos.get((kn, u, h))
                if not t and re.fullmatch(r"\d+", h):
                    t = pontos.get((kn, u, h)) or (szam.get((kn, u, h)) if len(szam.get((kn, u, h), ())) <= 2 else None)
                elif not t and re.match(r"\d+[a-z]", h):
                    t = None                      # betűs házszám, az OSM-ben nincs meg: nem találgatunk
                talalat |= set(t or ())
        masodlagos = False
        if not talalat and u:
            # Saroktelek: 'GÁBOR ÁRON UTCA 11. - PASARÉTI ÚT 56.' Ha az első cím nincs az OSM-ben, a többi címet is megnézzük,
            # de óvatosan: csak pontos házszám-egyezés, és címenként legfeljebb 2 épület (nem szám-alapú találgatás).
            for resz in re.split(r"\s+[-–=]\s+|;", k["cim"].strip())[1:]:
                u2, h2 = cim_felbontas(resz)
                if not u2:
                    continue
                u2 = atn.get(u2, u2)
                t2 = set()
                for h in h2:
                    t2 |= set(pontos.get((kn, u2, h), ()))
                if t2 and len(t2) <= 2:
                    talalat, masodlagos = t2, True
                    break
        if not talalat:
            stat["nem párosítható"] += 1
            kimaradt.append([kn, k["cim"], k["hrsz"], k["ev_szoveg"], k["tervezo"], k["vedelem"], k["forras"]])
            continue
        stat["párosítva"] += 1
        stat["ebből másodlagos (sarok) címmel"] += masodlagos
        megj = f"{k['forras']}" + (" (a kártya másik címe alapján párosítva)" if masodlagos else "") + (f", hrsz {k['hrsz']}" if k["hrsz"] else "") + (f", {k['oldal']}. oldal" if k.get("oldal") else "")
        for t, i in sorted(talalat):
            if k["ev"]:
                kesz.add((t, i, "ev", k["ev"], "ertekleltar", megj))
            elif k.get("korszak"):
                kozelito.append([t, i, k["korszak"][0], k["korszak"][1], k["ev_szoveg"], k["forras"]])
            else:
                tart = szoveg_evtartomany(k.get("ev_szoveg"))      # 'XIX. sz. vége', '1930-as évek második fele'
                if tart:
                    kozelito.append([t, i, tart[0], tart[1], k["ev_szoveg"], k["forras"]])
                    stat["századszöveg"] += 1
            if k["tervezo"]:
                kesz.add((t, i, "tervezo", k["tervezo"], "ertekleltar", megj))
            if k["stilus"]:
                kesz.add((t, i, "stilus", k["stilus"], "ertekleltar", megj))
            ved = k["vedelem"]
            if ved and ved not in ("E", "Mk", "Mk / E", "-") and "javasolt" not in ved:
                kesz.add((t, i, "vedettseg_helyi", ved if "védelem" in ved.lower() else ved, "ertekleltar", megj))
    tenyek_irasa(KIMENET, sorted(kesz, key=lambda s: (s[0], s[1], s[2])))
    with open(NEM_PAROSITOTT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["kerulet", "cim", "hrsz", "epites_ideje", "tervezo", "vedelem", "forras"])
        w.writerows(kimaradt)
    with open(KOZELITO, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["osm_tipus", "id", "ev_tol", "ev_ig", "szoveg", "forras"])
        w.writerows(kozelito)
    print(f"Kártyák: {len(kartyak)}  párosítva: {stat['párosítva']}  nem párosítható: {stat['nem párosítható']}")
    print(f"Tények: {len(kesz)} sor -> {KIMENET}; közelítő korszakadat: {len(kozelito)} -> {KOZELITO}")
    print(f"Nem párosított: {NEM_PAROSITOTT}")
    print(f"Ebből a kártya másik (sarok-) címével párosítva: {stat['ebből másodlagos (sarok) címmel']}")
    print(f"Ebből szövegből (század/évtized) feldolgozott közelítő adat: {stat['századszöveg']} épület")


if __name__ == "__main__":
    main()
