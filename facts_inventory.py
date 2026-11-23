"""Facts based on the district value registers -> data/tenyek/ertekleltar.csv

Input:    data/ertekleltar_kartyak.json  (data read from the building sheets of the value registers and handbooks of the II., III., IV., X., XIV., XV., XXI., XXIII. districts:
          address, lot number, year of construction, designer, style, protection; only facts, the text of the descriptions is not stored)
          data/varos/epuletek.geojson, data/varos/osm_cimek.csv   (py city_assembly.py)
Output:   data/tenyek/ertekleltar.csv            - facts for assemble.py (source: 'ertekleltar')
          data/ertekleltar_nem_parositott.csv    - what could not be tied to a building (for manual correction)
          data/varos/ertekleltar_kozelito.csv    - era data of the 'the 1930s', 'around 1910' kind (ONLY for the estimator, not 'ev')

Run:       py facts_inventory.py
It looks for the building by district + street + house number. A lettered house number (27/C) must be found exactly; if OSM has
no letter, but there are at most 2 buildings on the number, it accepts that.
"""
import csv
import json
import re
from collections import Counter, defaultdict

from facts_oeny import tisztit_utca, szamok
from common import tenyek_irasa
from century import szoveg_evtartomany

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
    """'KORPONAI UTCA 4. - Endre utca 1/A.' -> (stripped_street, [house-number texts]) from the first address."""
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
        raise SystemExit("Az épületeknél nincs kerület. Futtasd: py budapest_pbf.py, majd py city_assembly.py")
    pontos = defaultdict(set)        # (district, street, house-number key) -> buildings
    szam = defaultdict(set)          # (district, street, number) -> buildings (without the letter)
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
                    t = None                      # lettered house number, not present in OSM: we do not guess
                talalat |= set(t or ())
        masodlagos = False
        if not talalat and u:
            # Corner plot: 'GÁBOR ÁRON UTCA 11. - PASARÉTI ÚT 56.' If the first address is not in OSM, we also check the other addresses,
            # but carefully: only an exact house-number match, and at most 2 buildings per address (not number-based guessing).
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
                tart = szoveg_evtartomany(k.get("ev_szoveg"))      # 'XIX. sz. vége' (end of the 19th century), '1930-as évek második fele' (second half of the 1930s)
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
