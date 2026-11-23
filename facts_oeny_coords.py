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

from common import tenyek_irasa

TABLA = "forras/oeny_vegleges_adatok.csv"
EPULETEK = "data/varos/epuletek.geojson"
CIMEK = "data/varos/osm_cimek.csv"
KORABBI = ["data/tenyek/oeny.csv", "data/tenyek/oeny_kezi.csv"]
JEGYZEK = "data/muemlek_jegyzek.json"
KEZI = "forras/oeny_koord_kezi.csv"
KIMENET = "data/tenyek/oeny_koord.csv"
ELLENORZES = "forras/oeny_koord_ellenorzes.csv"
SUGAR = 20          # m: a building within this distance comes into question if the point falls into none of them
KX = 111000 * math.cos(math.radians(47.5))


def olvas(ut):
    with open(ut, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def pontok(w):
    """From the 'wgs84' field (lat, lon) pairs instead of (lon, lat). Two formats: 'N 19° 2.031'; E 47° 30.039'' (with swapped labels) and 'lat, lon'."""
    ki = []
    for resz in (w or "").split("|"):
        m = re.findall(r"([NE])\s*(\d+)°\s*([\d.,]+)'", resz)
        if len(m) == 2:
            v = {c: int(d) + float(mm.replace(",", ".")) / 60 for c, d, mm in m}
            ki.append((v["E"], v["N"]))          # the 'E' label is the latitude, the 'N' is the longitude
            continue
        m = re.match(r"\s*([\d.]+)\s*,\s*([\d.]+)\s*$", resz)
        if m:
            ki.append((float(m.group(1)), float(m.group(2))))
    return ki


def gyuruben(x, y, r):
    bent, j = False, len(r) - 1
    for i in range(len(r)):
        xi, yi = r[i]
        xj, yj = r[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            bent = not bent
        j = i
    return bent


def tavolsag(x, y, r):
    best, px, py = 1e9, x * KX, y * 111000
    for i in range(len(r) - 1):
        ax, ay, bx, by = r[i][0] * KX, r[i][1] * 111000, r[i + 1][0] * KX, r[i + 1][1] * 111000
        dx, dy = bx - ax, by - ay
        L = dx * dx + dy * dy
        t = 0 if L == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L))
        best = min(best, math.hypot(px - ax - t * dx, py - ay - t * dy))
    return best


class Epuletek:
    def __init__(self):
        self.polik, self.racs = [], collections.defaultdict(list)
        for f in json.load(open(EPULETEK, encoding="utf-8"))["features"]:
            p = f["properties"]
            if p.get("tipus") == "roof":
                continue
            g = f["geometry"]["coordinates"]
            xs, ys = [a for a, _ in g[0]], [b for _, b in g[0]]
            i = len(self.polik)
            self.polik.append((p["osm_tipus"], int(p["id"]), g, p.get("tipus")))
            for gx in range(int(min(xs) * 400), int(max(xs) * 400) + 1):
                for gy in range(int(min(ys) * 400), int(max(ys) * 400) + 1):
                    self.racs[(gx, gy)].append(i)

    def keres(self, lat, lon):
        """[(distance m, (osm_tipus, id), building type)], by proximity; the distance of buildings containing the point is 0."""
        lattam, ki = set(), {}
        gx0, gy0 = int(lon * 400), int(lat * 400)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for i in self.racs.get((gx0 + dx, gy0 + dy), []):
                    if i in lattam:
                        continue
                    lattam.add(i)
                    t, id_, g, tip = self.polik[i]
                    bent = gyuruben(lon, lat, g[0]) and not any(gyuruben(lon, lat, h) for h in g[1:])
                    d = 0 if bent else tavolsag(lon, lat, g[0])
                    if d <= SUGAR and ((t, id_) not in ki or d < ki[(t, id_)][0]):
                        ki[(t, id_)] = (round(d, 1), tip)
        return sorted((d, k, tip) for k, (d, tip) in ki.items())


def utcakulcs(s):
    s = s.lower().replace(".", "").strip()
    s = re.sub(r"\b(utca|u)\b$", "u", s)
    s = re.sub(r"\b(körút|krt)\b$", "krt", s)
    s = re.sub(r"\b(út)\b$", "ut", s)
    return re.sub(r"\s+", " ", s)


def szamok(h):
    ki = set()
    for a, b in re.findall(r"(\d+)\s*[a-zA-Z]?(?:\s*[-–]\s*(\d+))?", h):
        a = int(a)
        ki.add(a)
        if b and a < int(b) < a + 60:
            ki.update(range(a, int(b) + 1, 2) if (int(b) - a) % 2 == 0 else range(a, int(b) + 1))
    return ki


def pdf_cimek(c):
    ki = []
    for seg in re.split(r"\.\s*,|,\s*(?=[A-ZÁÉÍÓÖŐÚÜŰ])", c or ""):
        seg = seg.strip().rstrip(".").strip()
        m = re.match(r"(.*?)\s+(\d[\d\-–/a-zA-Z, ]*)$", seg)
        if m:
            ki.append((utcakulcs(m.group(1)), szamok(m.group(2))))
        elif seg:
            ki.append((utcakulcs(seg), set()))
    return ki


def osm_azon(s):
    ki = []
    for resz in re.split(r"[|;,\n]+", s or ""):
        m = re.search(r"(?:(way|relation|node)[/ :]*)?(\d{3,})", resz.strip(), flags=re.I)
        if m:
            ki.append(((m.group(1) or "way").lower(), int(m.group(2))))
    return ki


def main():
    for ut in (TABLA, EPULETEK, CIMEK):
        if not Path(ut).exists():
            raise SystemExit(f"Hiányzik: {ut}")
    sorok = olvas(TABLA)
    ep = Epuletek()
    cim = collections.defaultdict(list)
    for r in olvas(CIMEK):
        cim[(r["osm_tipus"], int(r["id"]))].append((utcakulcs(r["utca"]), szamok(r["hazszam"])))

    def cimegyezes(pdf, k):
        oc = cim.get(k)
        if not oc:
            return "nincs OSM-cím"
        for su, sn in pdf_cimek(pdf):
            for ou, on in oc:
                if su == ou and (not sn or not on or sn & on):
                    return "egyezik"
        return "eltér"

    # the state of the earlier (serial number/address based) matching
    cur = collections.defaultdict(lambda: {"t": set(), "a": []})
    for ut in KORABBI:
        if Path(ut).exists():
            for r in olvas(ut):
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
    kezi, torolt = {}, set()
    if Path(KEZI).exists():
        for r in olvas(KEZI):
            if (r.get("adatlap") or "").strip():
                az = re.sub(r"\.0$", "", r["adatlap"].strip())
                kezi[az] = (r.get("osm_azonosito") or "").strip()
                if "töröld" in (r.get("megjegyzes") or "").lower():
                    torolt.add(az)          # completely ignored, and also removed from the old matching
    else:
        Path(KEZI).parent.mkdir(parents=True, exist_ok=True)
        with open(KEZI, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f, delimiter=";").writerow(["adatlap", "osm_azonosito", "megjegyzes"])

    elfogadott = {}      # data sheet -> [building keys]
    ellenorzes, stat = [], collections.Counter()
    for r in sorok:
        en, ts = r["adatlap_azonosito"].strip(), r["torzsszam"].strip()
        P = pontok(r["wgs84"])
        alap = {"torzsszam": ts, "adatlap": en, "megnevezes": r["megnevezes"], "cim_a_pdf_szerint": r["cim_a_pdf_szerint"],
                "oeny_oldal": r.get("oeny_oldal", ""), "lat": "", "lon": "", "javasolt_osm": "", "tavolsag_m": "",
                "javasolt_cim_egyezes": "", "jelenlegi_osm": " | ".join(f"{t} {i}" for t, i in sorted(ad2b.get(en, [])))}
        dont = kezi.get(en, "").lower()
        if en in torolt:
            stat["kézi: töröld (figyelmen kívül hagyva)"] += 1
            continue
        if dont == "nem":
            stat["kézi: nem"] += 1
            continue
        kezi_id = osm_azon(kezi.get(en, "")) if dont not in ("jo", "jó", "") else []
        if kezi_id:
            elfogadott[en] = kezi_id
            stat["kézi: megadott épület"] += 1
            continue
        if not P:
            stat["nincs koordináta (terület/együttes: figyelmen kívül hagyva)"] += 1   # the individual buildings of the ensembles have their own data sheets
            continue
        jel = [ep.keres(lat, lon) for lat, lon in P]
        if not any(jel):
            ellenorzes.append({**alap, "lat": P[0][0], "lon": P[0][1], "kategoria": f"R nincs épület {SUGAR} m-en belül"})
            stat["R nincs épület a közelben"] += 1
            continue
        ch = []
        for j in jel:
            if not j:
                continue
            bent = [c for c in j if c[0] == 0] or j[:1]
            ch.append(sorted(bent, key=lambda c: (cimegyezes(r["cim_a_pdf_szerint"], c[1]) != "egyezik", c[0]))[0])
        tobb = any(sum(1 for c in j if c[0] == 0) > 1 for j in jel if j)
        ks = list(dict.fromkeys(c[1] for c in ch))
        ce = [cimegyezes(r["cim_a_pdf_szerint"], k) for k in ks]
        belul = all(c[0] == 0 for c in ch)
        egyertelmu = not (tobb and "egyezik" not in ce)
        regi = ad2b.get(en, set())
        van_mar = any(en in cur[k]["a"] for k in ks)
        mas_torzs = any(cur[k]["t"] and ts not in cur[k]["t"] for k in ks)
        regi_mas = [k for k in regi if k not in ks]
        egy_belul = belul and all(sum(1 for c in j if c[0] == 0) == 1 for j in jel if j)
        if dont in ("jo", "jó"):
            kat = "kézi: jó"
        elif van_mar and not regi_mas:
            kat = "A"
        elif van_mar:
            kat = "B"
        elif egy_belul:
            kat = "K"            # the point is within the outline of exactly one building: the coordinate decides, the address does not matter
        elif mas_torzs:
            kat = "G ütközés: más törzsszám van az épületen"
        elif regi:
            okold = [cimegyezes(r["cim_a_pdf_szerint"], k) for k in regi_mas]
            if ("egyezik" in ce and "egyezik" not in okold) or \
               (belul and "eltér" not in ce and egyertelmu and okold and all(x == "eltér" for x in okold)):
                kat = "E"
            else:
                kat = "F áthelyezés (a régi épületen más cím igazolja): ellenőrizendő"
        else:
            kat = "C" if ((belul or (min(c[0] for c in ch) <= 5 and "egyezik" in ce)) and "eltér" not in ce and egyertelmu) \
                else "D új: ellenőrizendő"
        stat[kat[:1] if len(kat) > 1 and kat[1] == " " else kat] += 1
        if kat in ("A", "B", "K", "C", "E", "kézi: jó"):
            elfogadott[en] = ks
        else:
            ellenorzes.append({**alap, "lat": P[0][0], "lon": P[0][1], "kategoria": kat,
                               "javasolt_osm": " | ".join(f"{t} {i}" for t, i in ks), "tavolsag_m": " | ".join(str(c[0]) for c in ch),
                               "javasolt_cim_egyezes": " | ".join(ce)})

    # ---- facts ----
    konyv = {}
    try:
        for b in json.loads(Path(JEGYZEK).read_text(encoding="utf-8"))["bejegyzesek"]:
            konyv[str(b["torzsszam"])] = b
    except (FileNotFoundError, ValueError, KeyError):
        pass
    sor_adat = {r["adatlap_azonosito"].strip(): r for r in sorok}
    epulet_adatlap = collections.defaultdict(list)
    for en, ks in elfogadott.items():
        for k in ks:
            if en not in epulet_adatlap[k]:
                epulet_adatlap[k].append(en)
    kesz = set()
    valtozott = lehuzott = maradt = 0
    for k, lista in epulet_adatlap.items():
        lista = lista[:3]
        tsz_lista = [sor_adat[a]["torzsszam"].strip() for a in lista if a in sor_adat]
        tsz = next((t for t in tsz_lista if t in cur[k]["t"]), tsz_lista[0] if tsz_lista else "")
        if set(lista) == set(cur[k]["a"]) and tsz in cur[k]["t"]:
            continue
        valtozott += 1
        megj = f"E-Örökség, törzsszám {tsz}, adatlap {'/'.join(lista)}, párosítás az OENY koordinátái alapján"
        kesz.add((k[0], k[1], "oeny_azonosito", "|".join(lista), "oeny_koord", megj))
        if tsz:
            kesz.add((k[0], k[1], "muemlek_torzsszam", tsz, "oeny_koord", megj))
        if tsz and tsz not in cur[k]["t"]:
            b = konyv.get(tsz)
            if b:
                kesz.update({(k[0], k[1], "vedettseg", b["vedettseg"], "muemlek", megj), (k[0], k[1], "muemlek_hrsz", b["hrsz"], "muemlek", megj),
                             (k[0], k[1], "stilus", b["stilus"], "muemlek", megj)})
                if b["evek"]:
                    kesz.add((k[0], k[1], "ev", b["evek"][0][1], "muemlek", megj))
                if b["tervezo"]:
                    kesz.add((k[0], k[1], "tervezo", b["tervezo"], "muemlek", megj))
                if b["emelet"] is not None:
                    kesz.add((k[0], k[1], "szintek", b["emelet"] + 1, "muemlek", megj))
            else:
                kesz.add((k[0], k[1], "vedettseg", "MJT" if "területe" in sor_adat[lista[0]]["megnevezes"].lower() else "M", "oeny", megj))
            for a in lista:
                rr = sor_adat.get(a, {})
                m = re.match(r"\s*(\d{4})(?:\.0)?\s*$", rr.get("kiolvasott_ev") or "")
                if m:
                    kesz.add((k[0], k[1], "ev", int(m.group(1)), "oeny", megj))
                if (rr.get("kiolvasott_tervezo") or "").strip():
                    kesz.add((k[0], k[1], "tervezo", rr["kiolvasott_tervezo"].strip(), "oeny", megj))
    # removing the earlier, wrong references: a data sheet that is elsewhere according to the coordinate must not stay on the old building
    hova = {a: set(ks) for a, ks in elfogadott.items()}
    for k, v in cur.items():
        if k in epulet_adatlap:
            continue
        if any(a in torolt for a in v["a"]):      # the reference of a data sheet with the 'töröld' (delete) remark is removed from everywhere
            marad = [a for a in v["a"] if a not in torolt and not (a in hova and k not in hova[a])]
            lehuzott += 1
            kesz.add((k[0], k[1], "oeny_azonosito", "|".join(marad[:3]) or "-", "oeny_koord",
                      "E-Örökség: a 'töröld' megjegyzésű adatlap hivatkozását levette a koordinátás párosítás"))
            continue
        marad = [a for a in v["a"] if not (a in hova and k not in hova[a])]
        if not marad and v["a"]:
            # we do not lose data: if this is the building's only data sheet reference, it stays, but goes into the checking table
            maradt += 1
            continue
        if len(marad) != len(v["a"]):
            lehuzott += 1
            kesz.add((k[0], k[1], "oeny_azonosito", "|".join(marad[:3]) or "-", "oeny_koord",
                      "E-Örökség: az adatlap az OENY koordinátái szerint másik épületen van (ezt a hivatkozást levette a koordinátás párosítás)"))
    tenyek_irasa(KIMENET, sorted(kesz, key=lambda s: (s[0], s[1], s[2], str(s[3]))))

    mezok = ["kategoria", "torzsszam", "adatlap", "megnevezes", "cim_a_pdf_szerint", "lat", "lon", "javasolt_osm", "tavolsag_m",
             "javasolt_cim_egyezes", "jelenlegi_osm", "oeny_oldal"]
    ellenorzes.sort(key=lambda x: (x["kategoria"], int(x["torzsszam"]) if x["torzsszam"].isdigit() else 0))
    with open(ELLENORZES, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=mezok, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows(ellenorzes)
    print(f"Adatlapok: {len(sorok)}")
    for k, v in sorted(stat.items()):
        print(f"  {k}: {v}")
    print(f"Elfogadott párosítás: {len(elfogadott)} adatlap, {len(epulet_adatlap)} épület; ebből változik: {valtozott}; téves hivatkozás levéve: {lehuzott} épületről")
    print(f"Régi hivatkozás megmaradt (nincs helyette másik, ezért nem nyúlunk hozzá): {maradt} épület")
    print(f"Tények: {len(kesz)} sor -> {KIMENET}")
    print(f"Ellenőrizendő: {len(ellenorzes)} sor -> {ELLENORZES}")


if __name__ == "__main__":
    main()
