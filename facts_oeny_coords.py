"""Matching the E-Örökség (OENY) data sheets to OSM buildings based on OENY's own coordinates.

Input:    forras/oeny_vegleges_adatok.csv   (the final table: adatlap_azonosito, torzsszam, cim_a_pdf_szerint, wgs84 ...)
          data/varos/epuletek.geojson, data/varos/osm_cimek.csv   (the OSM buildings and their addresses)
          data/tenyek/oeny.csv, data/tenyek/oeny_kezi.csv          (the earlier matching based on serial number/address; this does not modify it)
          data/muemlek_jegyzek.json                                (year of construction, designer, style, number of storeys from the register)
          forras/oeny_koord_kezi.csv                               (YOU fill in THIS for the rows to be checked, see below)
Output:   data/tenyek/oeny_koord.csv        - the facts of the data sheets matched with certainty by coordinate, for assemble.py
          forras/oeny_koord_ellenorzes.csv  - what was not unambiguous (rewritten on every run, do NOT edit this)

Run:       py facts_oeny_coords.py varos      (afterwards: zones_refresh.bat)

How it matches: the data sheet's point (the "wgs84" column; OENY swaps the N and E labels, the number is degrees + decimal minutes) falls into the
OSM building within whose outline it lies (taking the courtyard holes into account). If the point falls outside, the nearest building
within 20 metres can come into question. If several buildings come into question, the one whose OSM address matches the data sheet's address wins, then the nearer one.
The finished matches are accepted automatically according to the following rules:
  K  the point is within the outline of exactly one building: the coordinate decides, the OSM address does not matter (this also overrides the old matching)
  A  already matched correctly now (unchanged)
  B  partly right: the data sheet is already on the building, but also appears elsewhere (the superfluous, wrong reference is removed)
  C  new: the building has no OENY data yet, the point is inside, and the address does not contradict (matches or there is no address in OSM)
  E  relocation: the data sheet used to be on another building, but the address confirms the new building
What is more uncertain than this (D new-to-be-checked, F relocation-to-be-checked, G another serial number is on the building, R no coordinate
or no building nearby) goes into forras/oeny_koord_ellenorzes.csv, and does NOT change anything.

Manual decision: forras/oeny_koord_kezi.csv  (adatlap;osm_azonosito;megjegyzes). The 'osm_azonosito' can be:
  "jo"                       - accept the suggested matching
  "nem"                      - do not match it (the earlier matching stays)
  "way 123|relation 456"     - tie the data sheet to these buildings (several buildings with the '|' sign)
If you write "töröld" (delete it) in the 'megjegyzes' column, the script ignores the data sheet completely: it does not match it, and also removes its reference
from the buildings in the earlier (serial number/address based) matching (the serial number and the protection stay).
The script only creates the file (with a header), it does not touch its rows.
"""
import collections
import csv
import json
import math
import re
import sys
from pathlib import Path

from common import write_facts

TABLE = "forras/oeny_vegleges_adatok.csv"
BUILDINGS = "data/varos/epuletek.geojson"
ADDRESSES = "data/varos/osm_cimek.csv"
EARLIER = ["data/tenyek/oeny.csv", "data/tenyek/oeny_kezi.csv"]
REGISTER = "data/muemlek_jegyzek.json"
MANUAL = "forras/oeny_koord_kezi.csv"
OUTPUT = "data/tenyek/oeny_koord.csv"
CHECK = "forras/oeny_koord_ellenorzes.csv"
RADIUS = 20          # m: a building within this distance comes into question if the point falls into none of them
KX = 111000 * math.cos(math.radians(47.5))


def read_(path_):
    with open(path_, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def points(w):
    """From the 'wgs84' field (lat, lon) pairs instead of (lon, lat). Two formats: 'N 19° 2.031'; E 47° 30.039'' (with swapped labels) and 'lat, lon'."""
    out = []
    for part in (w or "").split("|"):
        m = re.findall(r"([NE])\s*(\d+)°\s*([\d.,]+)'", part)
        if len(m) == 2:
            v = {c: int(d) + float(mm.replace(",", ".")) / 60 for c, d, mm in m}
            out.append((v["E"], v["N"]))          # the 'E' label is the latitude, the 'N' is the longitude
            continue
        m = re.match(r"\s*([\d.]+)\s*,\s*([\d.]+)\s*$", part)
        if m:
            out.append((float(m.group(1)), float(m.group(2))))
    return out


def in_ring(x, y, r):
    inside, j = False, len(r) - 1
    for i in range(len(r)):
        xi, yi = r[i]
        xj, yj = r[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def distance(x, y, r):
    best, px, py = 1e9, x * KX, y * 111000
    for i in range(len(r) - 1):
        ax, ay, bx, by = r[i][0] * KX, r[i][1] * 111000, r[i + 1][0] * KX, r[i + 1][1] * 111000
        dx, dy = bx - ax, by - ay
        L = dx * dx + dy * dy
        t = 0 if L == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L))
        best = min(best, math.hypot(px - ax - t * dx, py - ay - t * dy))
    return best


class Buildings:
    def __init__(self):
        self.polys, self.grid = [], collections.defaultdict(list)
        for f in json.load(open(BUILDINGS, encoding="utf-8"))["features"]:
            p = f["properties"]
            if p.get("tipus") == "roof":
                continue
            g = f["geometry"]["coordinates"]
            xs, ys = [a for a, _ in g[0]], [b for _, b in g[0]]
            i = len(self.polys)
            self.polys.append((p["osm_tipus"], int(p["id"]), g, p.get("tipus")))
            for gx in range(int(min(xs) * 400), int(max(xs) * 400) + 1):
                for gy in range(int(min(ys) * 400), int(max(ys) * 400) + 1):
                    self.grid[(gx, gy)].append(i)

    def search_(self, lat, lon):
        """[(distance m, (osm_tipus, id), building type)], by proximity; the distance of buildings containing the point is 0."""
        seen, out = set(), {}
        gx0, gy0 = int(lon * 400), int(lat * 400)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for i in self.grid.get((gx0 + dx, gy0 + dy), []):
                    if i in seen:
                        continue
                    seen.add(i)
                    t, id_, g, kind = self.polys[i]
                    inside = in_ring(lon, lat, g[0]) and not any(in_ring(lon, lat, h) for h in g[1:])
                    d = 0 if inside else distance(lon, lat, g[0])
                    if d <= RADIUS and ((t, id_) not in out or d < out[(t, id_)][0]):
                        out[(t, id_)] = (round(d, 1), kind)
        return sorted((d, k, kind) for k, (d, kind) in out.items())


def street_key(s):
    s = s.lower().replace(".", "").strip()
    s = re.sub(r"\b(utca|u)\b$", "u", s)
    s = re.sub(r"\b(körút|krt)\b$", "krt", s)
    s = re.sub(r"\b(út)\b$", "ut", s)
    return re.sub(r"\s+", " ", s)


def numbers_(h):
    out = set()
    for a, b in re.findall(r"(\d+)\s*[a-zA-Z]?(?:\s*[-–]\s*(\d+))?", h):
        a = int(a)
        out.add(a)
        if b and a < int(b) < a + 60:
            out.update(range(a, int(b) + 1, 2) if (int(b) - a) % 2 == 0 else range(a, int(b) + 1))
    return out


def pdf_addresses(c):
    out = []
    for helper in re.split(r"\.\s*,|,\s*(?=[A-ZÁÉÍÓÖŐÚÜŰ])", c or ""):
        helper = helper.strip().rstrip(".").strip()
        m = re.match(r"(.*?)\s+(\d[\d\-–/a-zA-Z, ]*)$", helper)
        if m:
            out.append((street_key(m.group(1)), numbers_(m.group(2))))
        elif helper:
            out.append((street_key(helper), set()))
    return out


def osm_id(s):
    out = []
    for part in re.split(r"[|;,\n]+", s or ""):
        m = re.search(r"(?:(way|relation|node)[/ :]*)?(\d{3,})", part.strip(), flags=re.I)
        if m:
            out.append(((m.group(1) or "way").lower(), int(m.group(2))))
    return out


def main():
    for path_ in (TABLE, BUILDINGS, ADDRESSES):
        if not Path(path_).exists():
            raise SystemExit(f"Hiányzik: {path_}")
    rows = read_(TABLE)
    ep = Buildings()
    address = collections.defaultdict(list)
    for r in read_(ADDRESSES):
        address[(r["osm_tipus"], int(r["id"]))].append((street_key(r["utca"]), numbers_(r["hazszam"])))

    def address_match(pdf, k):
        oc = address.get(k)
        if not oc:
            return "nincs OSM-cím"
        for su, sn in pdf_addresses(pdf):
            for ou, on in oc:
                if su == ou and (not sn or not on or sn & on):
                    return "egyezik"
        return "eltér"

    # the state of the earlier (serial number/address based) matching
    cur = collections.defaultdict(lambda: {"t": set(), "a": []})
    for path_ in EARLIER:
        if Path(path_).exists():
            for r in read_(path_):
                k = (r["osm_tipus"], int(r["id"]))
                if r["mezo"] == "muemlek_torzsszam":
                    cur[k]["t"].add(str(r["ertek"]))
                elif r["mezo"] == "oeny_azonosito" and str(r["ertek"]) not in cur[k]["a"]:
                    cur[k]["a"].append(str(r["ertek"]))
    ad2b = collections.defaultdict(set)
    for k, v in cur.items():
        for a in v["a"]:
            ad2b[a].add(k)

    # manual decisions
    manual, deleted = {}, set()
    if Path(MANUAL).exists():
        for r in read_(MANUAL):
            if (r.get("adatlap") or "").strip():
                az = re.sub(r"\.0$", "", r["adatlap"].strip())
                manual[az] = (r.get("osm_azonosito") or "").strip()
                if "töröld" in (r.get("megjegyzes") or "").lower():
                    deleted.add(az)          # completely ignored, and also removed from the old matching
    else:
        Path(MANUAL).parent.mkdir(parents=True, exist_ok=True)
        with open(MANUAL, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f, delimiter=";").writerow(["adatlap", "osm_azonosito", "megjegyzes"])

    accepted = {}      # data sheet -> [building keys]
    check, stat = [], collections.Counter()
    for r in rows:
        en, ts = r["adatlap_azonosito"].strip(), r["torzsszam"].strip()
        P = points(r["wgs84"])
        base = {"torzsszam": ts, "adatlap": en, "megnevezes": r["megnevezes"], "cim_a_pdf_szerint": r["cim_a_pdf_szerint"],
                "oeny_oldal": r.get("oeny_oldal", ""), "lat": "", "lon": "", "javasolt_osm": "", "tavolsag_m": "",
                "javasolt_cim_egyezes": "", "jelenlegi_osm": " | ".join(f"{t} {i}" for t, i in sorted(ad2b.get(en, [])))}
        decide = manual.get(en, "").lower()
        if en in deleted:
            stat["kézi: töröld (figyelmen kívül hagyva)"] += 1
            continue
        if decide == "nem":
            stat["kézi: nem"] += 1
            continue
        manual_id = osm_id(manual.get(en, "")) if decide not in ("jo", "jó", "") else []
        if manual_id:
            accepted[en] = manual_id
            stat["kézi: megadott épület"] += 1
            continue
        if not P:
            stat["nincs koordináta (terület/együttes: figyelmen kívül hagyva)"] += 1   # the individual buildings of the ensembles have their own data sheets
            continue
        sign = [ep.search_(lat, lon) for lat, lon in P]
        if not any(sign):
            check.append({**base, "lat": P[0][0], "lon": P[0][1], "kategoria": f"R nincs épület {RADIUS} m-en belül"})
            stat["R nincs épület a közelben"] += 1
            continue
        ch = []
        for j in sign:
            if not j:
                continue
            inside = [c for c in j if c[0] == 0] or j[:1]
            ch.append(sorted(inside, key=lambda c: (address_match(r["cim_a_pdf_szerint"], c[1]) != "egyezik", c[0]))[0])
        several = any(sum(1 for c in j if c[0] == 0) > 1 for j in sign if j)
        ks = list(dict.fromkeys(c[1] for c in ch))
        ce = [address_match(r["cim_a_pdf_szerint"], k) for k in ks]
        inside_ = all(c[0] == 0 for c in ch)
        unambiguous = not (several and "egyezik" not in ce)
        old = ad2b.get(en, set())
        has_already = any(en in cur[k]["a"] for k in ks)
        other_serial = any(cur[k]["t"] and ts not in cur[k]["t"] for k in ks)
        old_other = [k for k in old if k not in ks]
        one_inside = inside_ and all(sum(1 for c in j if c[0] == 0) == 1 for j in sign if j)
        if decide in ("jo", "jó"):
            category = "kézi: jó"
        elif has_already and not old_other:
            category = "A"
        elif has_already:
            category = "B"
        elif one_inside:
            category = "K"            # the point is within the outline of exactly one building: the coordinate decides, the address does not matter
        elif other_serial:
            category = "G ütközés: más törzsszám van az épületen"
        elif old:
            reason = [address_match(r["cim_a_pdf_szerint"], k) for k in old_other]
            if ("egyezik" in ce and "egyezik" not in reason) or \
               (inside_ and "eltér" not in ce and unambiguous and reason and all(x == "eltér" for x in reason)):
                category = "E"
            else:
                category = "F áthelyezés (a régi épületen más cím igazolja): ellenőrizendő"
        else:
            category = "C" if ((inside_ or (min(c[0] for c in ch) <= 5 and "egyezik" in ce)) and "eltér" not in ce and unambiguous) \
                else "D új: ellenőrizendő"
        stat[category[:1] if len(category) > 1 and category[1] == " " else category] += 1
        if category in ("A", "B", "K", "C", "E", "kézi: jó"):
            accepted[en] = ks
        else:
            check.append({**base, "lat": P[0][0], "lon": P[0][1], "kategoria": category,
                               "javasolt_osm": " | ".join(f"{t} {i}" for t, i in ks), "tavolsag_m": " | ".join(str(c[0]) for c in ch),
                               "javasolt_cim_egyezes": " | ".join(ce)})

    # ---- facts ----
    book = {}
    try:
        for b in json.loads(Path(REGISTER).read_text(encoding="utf-8"))["bejegyzesek"]:
            book[str(b["torzsszam"])] = b
    except (FileNotFoundError, ValueError, KeyError):
        pass
    row_data = {r["adatlap_azonosito"].strip(): r for r in rows}
    building_datasheet = collections.defaultdict(list)
    for en, ks in accepted.items():
        for k in ks:
            if en not in building_datasheet[k]:
                building_datasheet[k].append(en)
    done = set()
    changed = pulled = left = 0
    for k, list_ in building_datasheet.items():
        list_ = list_[:3]
        serial_no_list = [row_data[a]["torzsszam"].strip() for a in list_ if a in row_data]
        serial_no = next((t for t in serial_no_list if t in cur[k]["t"]), serial_no_list[0] if serial_no_list else "")
        if set(list_) == set(cur[k]["a"]) and serial_no in cur[k]["t"]:
            continue
        changed += 1
        remark = f"E-Örökség, törzsszám {serial_no}, adatlap {'/'.join(list_)}, párosítás az OENY koordinátái alapján"
        done.add((k[0], k[1], "oeny_azonosito", "|".join(list_), "oeny_koord", remark))
        if serial_no:
            done.add((k[0], k[1], "muemlek_torzsszam", serial_no, "oeny_koord", remark))
        if serial_no and serial_no not in cur[k]["t"]:
            b = book.get(serial_no)
            if b:
                done.update({(k[0], k[1], "vedettseg", b["vedettseg"], "muemlek", remark), (k[0], k[1], "muemlek_hrsz", b["hrsz"], "muemlek", remark),
                             (k[0], k[1], "stilus", b["stilus"], "muemlek", remark)})
                if b["evek"]:
                    done.add((k[0], k[1], "ev", b["evek"][0][1], "muemlek", remark))
                if b["tervezo"]:
                    done.add((k[0], k[1], "tervezo", b["tervezo"], "muemlek", remark))
                if b["emelet"] is not None:
                    done.add((k[0], k[1], "szintek", b["emelet"] + 1, "muemlek", remark))
            else:
                done.add((k[0], k[1], "vedettseg", "MJT" if "területe" in row_data[list_[0]]["megnevezes"].lower() else "M", "oeny", remark))
            for a in list_:
                rr = row_data.get(a, {})
                m = re.match(r"\s*(\d{4})(?:\.0)?\s*$", rr.get("kiolvasott_ev") or "")
                if m:
                    done.add((k[0], k[1], "ev", int(m.group(1)), "oeny", remark))
                if (rr.get("kiolvasott_tervezo") or "").strip():
                    done.add((k[0], k[1], "tervezo", rr["kiolvasott_tervezo"].strip(), "oeny", remark))
    # removing the earlier, wrong references: a data sheet that is elsewhere according to the coordinate must not stay on the old building
    to = {a: set(ks) for a, ks in accepted.items()}
    for k, v in cur.items():
        if k in building_datasheet:
            continue
        if any(a in deleted for a in v["a"]):      # the reference of a data sheet with the 'töröld' (delete) remark is removed from everywhere
            remains = [a for a in v["a"] if a not in deleted and not (a in to and k not in to[a])]
            pulled += 1
            done.add((k[0], k[1], "oeny_azonosito", "|".join(remains[:3]) or "-", "oeny_koord",
                      "E-Örökség: a 'töröld' megjegyzésű adatlap hivatkozását levette a koordinátás párosítás"))
            continue
        remains = [a for a in v["a"] if not (a in to and k not in to[a])]
        if not remains and v["a"]:
            # we do not lose data: if this is the building's only data sheet reference, it stays, but goes into the checking table
            left += 1
            continue
        if len(remains) != len(v["a"]):
            pulled += 1
            done.add((k[0], k[1], "oeny_azonosito", "|".join(remains[:3]) or "-", "oeny_koord",
                      "E-Örökség: az adatlap az OENY koordinátái szerint másik épületen van (ezt a hivatkozást levette a koordinátás párosítás)"))
    write_facts(OUTPUT, sorted(done, key=lambda s: (s[0], s[1], s[2], str(s[3]))))

    fields = ["kategoria", "torzsszam", "adatlap", "megnevezes", "cim_a_pdf_szerint", "lat", "lon", "javasolt_osm", "tavolsag_m",
             "javasolt_cim_egyezes", "jelenlegi_osm", "oeny_oldal"]
    check.sort(key=lambda x: (x["kategoria"], int(x["torzsszam"]) if x["torzsszam"].isdigit() else 0))
    with open(CHECK, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows(check)
    print(f"Adatlapok: {len(rows)}")
    for k, v in sorted(stat.items()):
        print(f"  {k}: {v}")
    print(f"Elfogadott párosítás: {len(accepted)} adatlap, {len(building_datasheet)} épület; ebből változik: {changed}; téves hivatkozás levéve: {pulled} épületről")
    print(f"Régi hivatkozás megmaradt (nincs helyette másik, ezért nem nyúlunk hozzá): {left} épület")
    print(f"Tények: {len(done)} sor -> {OUTPUT}")
    print(f"Ellenőrizendő: {len(check)} sor -> {CHECK}")


if __name__ == "__main__":
    main()
