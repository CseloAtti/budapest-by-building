"""Budapest100: filling in the addresses not matched by facts_bp100.py (missing house number -> interpolation / OSM address point / corner-house rule).

Input:    data/bp100_nem_parositott.csv, data/bp100/budapest100_teljes.csv, data/bp100/kepek.json,
          data/varos/epuletek.geojson, data/varos/osm_cimek.csv, data/ertekleltar_cimpontok*.csv, forras/utcanev_atnevezesek.csv
Output:   data/tenyek/budapest100_sarok.csv   - the facts of the unambiguous (~95%) matches (ev, budapest100_url, kep)
          data/bp100_sarok_javaslat.csv       - every unmatched item: status + candidates (for manual checking)
Method: the same as in the inventory-based facts_corner.py (the same Terkep class and automatic rule).
Run:      py facts_bp100.py   then   py facts_bp100_corner.py
"""
import csv
import json
import re
import collections
from pathlib import Path

import facts_corner as S
from facts_inventory import address_split
from facts_oeny import clean_street
from facts_bp100 import GOOD_SOURCE, district_from_postcode
from common import write_facts

INPUT = Path("data/bp100/budapest100_teljes.csv")
IMAGES = Path("data/bp100/kepek.json")
NOT = Path("data/bp100_nem_parositott.csv")
OUTPUT = "data/tenyek/budapest100_sarok.csv"
SUGGESTION = "data/bp100_sarok_javaslat.csv"
ADDRESS_POINT_FILES = ["data/ertekleltar_cimpontok.csv", "data/ertekleltar_cimpontok_wiki.csv", "data/bp100_cimpontok.csv"]


def candidate(T, kn, u, house_no):
    """-> (auto, valoszinu, mod, [(tav, e, sarok, ter)]) or (None, None, status, [])"""
    n = int(re.match(r"\d+", house_no).group(0))
    cp = T.address_point(kn, u, house_no)
    if cp:
        return len(cp) == 1, False, "OSM címpont alapján", cp
    u2, remark = T.street_resolve(u, kn)
    if not u2:
        return None, None, "ismeretlen utca az OSM-címek között", []
    p, mode, c = T.candidates(kn, u2, n)
    if not c:
        return None, None, f"nincs jelölt ({mode})", []
    first = c[0]
    res = 99 if len(c) == 1 else c[1][0] - first[0]
    auto = mode == "interpolált" and ((first[0] < 5 and res >= 15) or (first[0] < 1 and res >= 8))
    probable = False
    if not auto and mode == "interpolált":
        corners = [y for y in c if y[2]]
        if corners and corners[0][0] < 5:
            rest = [y for y in c if y is not corners[0]]
            r2 = 99 if not rest else rest[0][0] - corners[0][0]
            if r2 >= 8:
                c, auto = [corners[0]] + rest, True
            elif corners[0][0] < 4 and r2 >= 4:
                c, probable = [corners[0]] + rest, True
        elif first[0] < 4 and res >= 4:
            probable = True
    return auto, probable, mode + (", " + remark if remark else ""), c


def main():
    atn = {}
    try:
        with open(S.RENAMING, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                if r.get("regi") and r.get("uj") and "|" not in r["uj"]:
                    atn[clean_street(r["regi"])] = clean_street(r["uj"])
    except FileNotFoundError:
        pass
    T = S.Map(S.geometry(), S.ADDRESSES, atn)
    # we merge the address-point files (Terkep loads only one at a time)
    merged = Path("data/_bp100_cimpontok_egyesitett.csv")
    rows_p = []
    for path_ in ADDRESS_POINT_FILES:
        if Path(path_).exists():
            with open(path_, encoding="utf-8-sig", newline="") as f:
                rows_p += list(csv.DictReader(f, delimiter=";"))
    with open(merged, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["osm_tipus", "osm_id", "lat", "lon", "utca", "hazszam"], delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows_p)
    T.load_points(str(merged))
    merged.unlink()

    source = collections.defaultdict(list)
    for r in csv.DictReader(open(INPUT, encoding="utf-8-sig", newline="")):
        source[r["clean_address"].strip()].append(r)
    images = json.load(open(IMAGES, encoding="utf-8")) if IMAGES.exists() else {}
    not_ = list(csv.DictReader(open(NOT, encoding="utf-8-sig", newline=""), delimiter=";"))
    street_round = collections.defaultdict(set)
    for u, l in T.street.items():
        for k, _, _ in l:
            street_round[u].add(k)

    done, suggestion, stat = set(), [], collections.Counter()
    # a building that facts_bp100.py has already given Budapest100 data (typically the other address of a corner house) is not overwritten / not made to collide
    has = set()
    path_ = Path("data/tenyek/budapest100.csv")
    if path_.exists():
        with open(path_, encoding="utf-8-sig", newline="") as f:
            has = {(r["osm_tipus"], int(r["id"])) for r in csv.DictReader(f, delimiter=";")}
    for n in not_:
        address = n["cim"].strip()
        if n["miert"] == "nincs házszám":
            stat["nincs házszám (kihagyva)"] += 1
            continue
        r = (source.get(address) or [{}])[0]
        year = None
        try:
            if r.get("built_year") and r.get("year_source") in GOOD_SOURCE and 1000 <= int(float(r["built_year"])) <= 2030:
                year = int(float(r["built_year"]))
        except ValueError:
            pass
        url = (r.get("url") or "").strip()
        if not re.fullmatch(r"https://budapest100\.hu/house/[A-Za-z0-9_%\-]+/?", url):
            url = ""
        kn0 = district_from_postcode(r.get("zip_code"))
        u, house_nos = address_split(address)
        state, result = "nincs házszám / utca", None
        if u and house_nos:
            u = atn.get(u, u)
            for house_no in house_nos:
                if not re.fullmatch(r"\d+[a-z]?(?:/[a-z0-9]+)?", house_no):
                    continue
                round_ = [kn0] if kn0 else sorted(street_round.get(u, set()) or {k for k in street_round.get(T.street_resolve(u, None)[0] or "", set())}, key=str)
                hits = []
                for kn in round_:
                    a, v, mode, c = candidate(T, kn, u, house_no)
                    if a is None:
                        state = mode
                        continue
                    hits.append((kn, a, v, mode, c))
                if not hits:
                    continue
                if not kn0 and len([t for t in hits if t[1] or t[2]]) > 1:
                    state = "több kerületben is lehetséges"
                    continue
                kn, a, v, mode, c = sorted(hits, key=lambda t: (not t[1], not t[2]))[0]
                result = (kn, a, v, mode, c, house_no)
                break
        if not result:
            stat[state] += 1
            suggestion.append([address, year or "", url, state, "", "", ""])
            continue
        kn, a, v, mode, c, house_no = result
        sign = " | ".join(f"{e[0]} {e[1]} ({d:.0f} m{', saroképület' if sa else ''})" for d, e, sa, _ in c[:4])
        if a and c[0][1] in has:
            stat["már van Budapest100-adata (sarokház?), kézi döntés"] += 1
            suggestion.append([address, year or "", url, "már van Budapest100-adata (sarokház?), kézi döntés", f"{c[0][1][0]} {c[0][1][1]}", mode, sign])
        elif a:
            stat["automatikusan párosítva"] += 1
            e = c[0][1]
            remark = f"Budapest100: {address} (hiányzó cím: {mode} párosítva) {url}".strip()
            if year:
                done.add((e[0], e[1], "ev", year, "budapest100", remark))
            if url:
                done.add((e[0], e[1], "budapest100_url", url, "budapest100", remark))
                image = images.get(url) or images.get(url.rstrip("/") + "/") or images.get(url.rstrip("/")) or {}
                if isinstance(image, str):
                    image = {"kep": image, "foto": ""}
                if image.get("kep"):
                    done.add((e[0], e[1], "budapest100_kep", image["kep"], "budapest100", remark))
                    if image.get("foto"):
                        done.add((e[0], e[1], "budapest100_foto", image["foto"], "budapest100", remark))
            suggestion.append([address, year or "", url, "automatikusan párosítva", f"{e[0]} {e[1]}", mode, sign])
        else:
            st = "valószínű (kézi megerősítés kell)" if v else "bizonytalan, jelöltekkel"
            stat[st] += 1
            suggestion.append([address, year or "", url, st, "", mode, sign])
    # manual decisions (3D editor, forras/bp100_kezi_parositas.csv): a filled-in osm_azonosito overrides the suggestion
    manual_path = Path("forras/bp100_kezi_parositas.csv")
    if manual_path.exists():
        with open(manual_path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                m = re.fullmatch(r"(way|relation)\s+(\d+)", (r.get("osm_azonosito") or "").strip())
                if not m:
                    continue
                e = (m.group(1), int(m.group(2)))
                address, url = r["cim"].strip(), (r.get("url") or "").strip()
                remark = f"Budapest100: {address} (kézi párosítás) {url}".strip()
                try:
                    year = int(float(r["ev"])) if r.get("ev") else None
                except ValueError:
                    year = None
                if year:
                    done.add((e[0], e[1], "ev", year, "budapest100", remark))
                if url:
                    done.add((e[0], e[1], "budapest100_url", url, "budapest100", remark))
                    image = images.get(url) or images.get(url.rstrip("/") + "/") or images.get(url.rstrip("/")) or {}
                    if isinstance(image, str):
                        image = {"kep": image, "foto": ""}
                    if image.get("kep"):
                        done.add((e[0], e[1], "budapest100_kep", image["kep"], "budapest100", remark))
                        if image.get("foto"):
                            done.add((e[0], e[1], "budapest100_foto", image["foto"], "budapest100", remark))
                stat["kézi párosítás beépítve"] += 1
    write_facts(OUTPUT, sorted(done, key=lambda s: (s[0], s[1], s[2])))
    with open(SUGGESTION, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["cim", "ev", "url", "allapot", "javasolt_osm", "mod", "jeloltek"])
        w.writerows(suggestion)
    for k, v in stat.most_common():
        print(f"  {k}: {v}")
    print(f"Tények: {len(done)} sor -> {OUTPUT}; javaslat: {SUGGESTION}")


if __name__ == "__main__":
    main()
