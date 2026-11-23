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

from facts_oeny import clean_street, numbers_
from common import write_facts
from century import text_year_range

CARDS = "data/ertekleltar_kartyak.json"
BUILDINGS = "data/varos/epuletek.geojson"
ADDRESSES = "data/varos/osm_cimek.csv"
RENAMING = "forras/utcanev_atnevezesek.csv"
OUTPUT = "data/tenyek/ertekleltar.csv"
NOT_PAIRED = "data/ertekleltar_nem_parositott.csv"
APPROXIMATE = "data/varos/ertekleltar_kozelito.csv"


def house_number_key(s):
    return re.sub(r"[\s.]", "", (s or "").lower()).replace("–", "-")


def address_split(address):
    """'KORPONAI UTCA 4. - Endre utca 1/A.' -> (stripped_street, [house-number texts]) from the first address."""
    c = re.split(r"\s+[-–=]\s+|;|\s*\bés\b\s", address.strip(), maxsplit=1)[0]
    c = re.sub(r"\b(u)\.(?=\s|$)", "utca", c, flags=re.I)
    c = re.sub(r"\.(?=/)", "", c).strip(" -")
    m = re.match(r"^(.*?[^\d\s])\s*(\d+(?:\s*[/-]\s*[0-9A-Za-z]+)*[A-Za-z]?)\.?\s*(?:,.*)?$", c)
    if not m:
        return None, []
    street, house_no = m.group(1), m.group(2)
    keys = []
    r = re.fullmatch(r"(\d+)\s*-\s*(\d+)", house_no)
    if r and int(r.group(2)) > int(r.group(1)) and int(r.group(2)) - int(r.group(1)) <= 20:
        a, b = int(r.group(1)), int(r.group(2))
        keys = [str(n) for n in range(a, b + 1, 2)] if b - a > 1 else [str(a), str(b)]
    else:
        keys = [house_number_key(house_no)]
    return clean_street(street), keys


def main():
    cards = json.load(open(CARDS, encoding="utf-8"))
    atn = {}
    try:
        with open(RENAMING, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                if r.get("regi") and r.get("uj") and "|" not in r["uj"]:
                    atn[clean_street(r["regi"])] = clean_street(r["uj"])
    except FileNotFoundError:
        pass
    district = {}
    with open(BUILDINGS, encoding="utf-8") as f:
        for ft in json.load(f)["features"]:
            pr = ft["properties"]
            if pr.get("kerulet"):
                district[(pr["osm_tipus"], int(pr["id"]))] = pr["kerulet"]
    if not district:
        raise SystemExit("Az épületeknél nincs kerület. Futtasd: py budapest_pbf.py, majd py city_assembly.py")
    exact = defaultdict(set)        # (district, street, house-number key) -> buildings
    number = defaultdict(set)          # (district, street, number) -> buildings (without the letter)
    with open(ADDRESSES, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            e = (r["osm_tipus"], int(r["id"]))
            kn = district.get(e)
            if not kn:
                continue
            u = clean_street(r["utca"])
            for part in re.split(r"[;,]", r["hazszam"] or ""):
                k = house_number_key(part)
                if not k:
                    continue
                exact[(kn, u, k)].add(e)
                m = re.match(r"(\d+)", k)
                if m:
                    number[(kn, u, m.group(1))].add(e)

    done, left_out, approximate = set(), [], []
    stat = Counter()
    for k in cards:
        kn = k["kerulet"]
        u, house_nos = address_split(k["cim"])
        u = atn.get(u, u)
        hit = set()
        if u:
            for h in house_nos:
                t = exact.get((kn, u, h))
                if not t and re.fullmatch(r"\d+", h):
                    t = exact.get((kn, u, h)) or (number.get((kn, u, h)) if len(number.get((kn, u, h), ())) <= 2 else None)
                elif not t and re.match(r"\d+[a-z]", h):
                    t = None                      # lettered house number, not present in OSM: we do not guess
                hit |= set(t or ())
        secondary = False
        if not hit and u:
            # Corner plot: 'GÁBOR ÁRON UTCA 11. - PASARÉTI ÚT 56.' If the first address is not in OSM, we also check the other addresses,
            # but carefully: only an exact house-number match, and at most 2 buildings per address (not number-based guessing).
            for part in re.split(r"\s+[-–=]\s+|;", k["cim"].strip())[1:]:
                u2, h2 = address_split(part)
                if not u2:
                    continue
                u2 = atn.get(u2, u2)
                t2 = set()
                for h in h2:
                    t2 |= set(exact.get((kn, u2, h), ()))
                if t2 and len(t2) <= 2:
                    hit, secondary = t2, True
                    break
        if not hit:
            stat["nem párosítható"] += 1
            left_out.append([kn, k["cim"], k["hrsz"], k["ev_szoveg"], k["tervezo"], k["vedelem"], k["forras"]])
            continue
        stat["párosítva"] += 1
        stat["ebből másodlagos (sarok) címmel"] += secondary
        remark = f"{k['forras']}" + (" (a kártya másik címe alapján párosítva)" if secondary else "") + (f", hrsz {k['hrsz']}" if k["hrsz"] else "") + (f", {k['oldal']}. oldal" if k.get("oldal") else "")
        for t, i in sorted(hit):
            if k["ev"]:
                done.add((t, i, "ev", k["ev"], "ertekleltar", remark))
            elif k.get("korszak"):
                approximate.append([t, i, k["korszak"][0], k["korszak"][1], k["ev_szoveg"], k["forras"]])
            else:
                hold = text_year_range(k.get("ev_szoveg"))      # 'XIX. sz. vége' (end of the 19th century), '1930-as évek második fele' (second half of the 1930s)
                if hold:
                    approximate.append([t, i, hold[0], hold[1], k["ev_szoveg"], k["forras"]])
                    stat["századszöveg"] += 1
            if k["tervezo"]:
                done.add((t, i, "tervezo", k["tervezo"], "ertekleltar", remark))
            if k["stilus"]:
                done.add((t, i, "stilus", k["stilus"], "ertekleltar", remark))
            protect = k["vedelem"]
            if protect and protect not in ("E", "Mk", "Mk / E", "-") and "javasolt" not in protect:
                done.add((t, i, "vedettseg_helyi", protect if "védelem" in protect.lower() else protect, "ertekleltar", remark))
    write_facts(OUTPUT, sorted(done, key=lambda s: (s[0], s[1], s[2])))
    with open(NOT_PAIRED, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["kerulet", "cim", "hrsz", "epites_ideje", "tervezo", "vedelem", "forras"])
        w.writerows(left_out)
    with open(APPROXIMATE, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["osm_tipus", "id", "ev_tol", "ev_ig", "szoveg", "forras"])
        w.writerows(approximate)
    print(f"Kártyák: {len(cards)}  párosítva: {stat['párosítva']}  nem párosítható: {stat['nem párosítható']}")
    print(f"Tények: {len(done)} sor -> {OUTPUT}; közelítő korszakadat: {len(approximate)} -> {APPROXIMATE}")
    print(f"Nem párosított: {NOT_PAIRED}")
    print(f"Ebből a kártya másik (sarok-) címével párosítva: {stat['ebből másodlagos (sarok) címmel']}")
    print(f"Ebből szövegből (század/évtized) feldolgozott közelítő adat: {stat['századszöveg']} épület")


if __name__ == "__main__":
    main()
