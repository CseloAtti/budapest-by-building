"""Matching the street-by-street building lists of the Hungarian Wikipedia with the OSM buildings (by address), and writing out the facts.

Input:    data/wikipedia_lista/sorok.csv      (made by tenyek_wikipedia_lista_letolt.py: street lists)
          data/wikipedia_lista/sorok_tema.csv (made by tenyek_wikipedia_temalista_letolt.py: schools, hospitals ... - optional)
          data/varos/epuletek.geojson, data/varos/osm_cimek.csv
          forras/wikipedia_lista_kezi.csv     (YOU fill in THIS for the rows of the checking table, see below)
Output:   data/tenyek/wikipedia_lista.csv     - the facts of the rows matched with certainty (osszeepit.py reads it; source: wikipedia_lista)
          forras/wikipedia_lista_ellenorzes.csv - what was not unambiguous (rewritten on every run, do NOT edit this)

Run:       py tenyek_wikipedia_lista.py varos      (afterwards: zona_frissit.bat)

Rules:
  - By the row's street and house number, an OSM building is matched if the street matches and the house number is among the building's OSM addresses
    (it also understands forms like '12-14', '2/a'). If the street runs through several districts, the page's section title (e.g. 'XIII. kerület') helps.
  - It is unambiguous if a single building (of at least 40 m²) comes into question. Several candidates, or several rows pointing to the same building with different
    data: it writes nothing, it goes into the checking table. It skips the rows of demolished/destroyed buildings.
  - Name: only if the building has no name yet (in OSM or from another source). Style: only if there is none yet. Year of construction and designer: the source
    is at the end in prioritas.json, so it never overwrites another source's data (osszeepit.py writes the discrepancies into data/varos/utkozesek.csv).
  - The remark always names the source: page and row.

Manual decision: forras/wikipedia_lista_kezi.csv  (utca;sor;osm_azonosito;megjegyzes). The 'osm_azonosito' can be:
  "nem"                     - skip this row
  "way 123|relation 456"    - tie the row to these buildings (several buildings with the '|' sign)
The script only creates the file (with a header), it does not touch its rows. 'utca' and 'sor' can be copied from the checking table.
"""
import collections
import csv
import json
import math
import re
from pathlib import Path

from kozos import tenyek_irasa

SOROK = "data/wikipedia_lista/sorok.csv"
SOROK_TEMA = "data/wikipedia_lista/sorok_tema.csv"     # the topic lists (schools, hospitals ...), if downloaded
EPULETEK = "data/varos/epuletek.geojson"
CIMEK = "data/varos/osm_cimek.csv"
TENYEK = "data/tenyek"
KEZI = "forras/wikipedia_lista_kezi.csv"
KIMENET = "data/tenyek/wikipedia_lista.csv"
ELLENORZES = "forras/wikipedia_lista_ellenorzes.csv"
ARANY = 3                   # the largest candidate is this many times larger than the second: that is the main building
MIN_TERULET = 40            # m²: a smaller building (pantry, garage) is not regarded as a candidate
KX = 111000 * math.cos(math.radians(47.5))
ALTALANOS = re.compile(r"^(bérház|lakóház|ház|irodaház|lakó- és irodaház|üzletház|családi ház|villa|társasház|lakóépület|bérpalota)$", re.I)
ELBONTVA = re.compile(r"elbont|lebont|elpusztult|megsemmis|már nem áll|nem áll fenn|nem létezik", re.I)
ROMAI = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12, "XIII": 13, "XIV": 14,
         "XV": 15, "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20, "XXI": 21, "XXII": 22, "XXIII": 23}


def olvas(ut):
    with open(ut, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def utcakulcs(s):
    s = s.lower().replace(".", "").strip()
    s = re.sub(r"\b(utca|u)\b$", "u", s)
    s = re.sub(r"\b(körút|krt)\b$", "krt", s)
    s = re.sub(r"\b(út)\b$", "ut", s)
    return re.sub(r"\s+", " ", s)


def szamok(h):
    ki = set()
    for a, b in re.findall(r"(\d+)\s*[a-zA-Z]?(?:\s*[-–]\s*(\d+))?", h or ""):
        a = int(a)
        ki.add(a)
        if b and a < int(b) < a + 60:
            ki.update(range(a, int(b) + 1, 2) if (int(b) - a) % 2 == 0 else range(a, int(b) + 1))
    return ki


def tokenek(h):
    """[(number, suffix)]: '89/c' -> (89, 'c'); '1-5' -> (1,''), (3,''), (5,''); the elements of the range have no suffix."""
    ki = []
    for a, sa, b in re.findall(r"(\d+)\s*(?:/?\s*([a-zA-Z])\b)?(?:\s*[-–]\s*(\d+))?", h or ""):
        a = int(a)
        if b and a < int(b) < a + 60:
            ki += [(n, "") for n in (range(a, int(b) + 1, 2) if (int(b) - a) % 2 == 0 else range(a, int(b) + 1))]
        else:
            ki.append((a, sa.lower()))
            if b:
                ki.append((int(b), ""))
    return list(dict.fromkeys(ki))


def terulet(g):
    r = g[0]
    return abs(sum(r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1] for i in range(len(r) - 1))) / 2 * KX * 111000


def osm_azon(s):
    ki = []
    for resz in re.split(r"[|;,\n]+", s or ""):
        m = re.search(r"(?:(way|relation|node)[/ :]*)?(\d{3,})", resz.strip(), flags=re.I)
        if m:
            ki.append(((m.group(1) or "way").lower(), int(m.group(2))))
    return ki


def ev_ertek(s):
    if re.search(r"évek|század|\bvagy\b", s or ""):          # '1880-as évek' (the 1880s), '19. század' (19th century): not an exact year
        return None
    m = re.search(r"\b(1[0-9]{3}|20[0-2][0-9])\b", s or "")
    return int(m.group(1)) if m else None


def main():
    for ut in (SOROK, EPULETEK, CIMEK):
        if not Path(ut).exists():
            raise SystemExit(f"Hiányzik: {ut}" + (" - előbb futtasd: py tenyek_wikipedia_lista_letolt.py" if ut == SOROK else ""))
    sorok = olvas(SOROK) + (olvas(SOROK_TEMA) if Path(SOROK_TEMA).exists() else [])
    # buildings: area, district, OSM name; addresses
    ep = {}
    for f in json.load(open(EPULETEK, encoding="utf-8"))["features"]:
        p = f["properties"]
        if p.get("tipus") == "roof":
            continue
        k = (p["osm_tipus"], int(p["id"]))
        ter = terulet(f["geometry"]["coordinates"])
        if k not in ep or ter > ep[k]["ter"]:
            ep[k] = {"ter": ter, "ker": p.get("kerulet"), "nev": p.get("nev")}
    cim = collections.defaultdict(list)
    for r in olvas(CIMEK):
        cim[(r["osm_tipus"], int(r["id"]))].append((utcakulcs(r["utca"]), szamok(r["hazszam"])))
    utca_szam = collections.defaultdict(dict)          # (street key, number) -> {building key: {suffixes}}
    osm_cimek_szoveg = collections.defaultdict(set)
    for r_ in olvas(CIMEK):
        k = (r_["osm_tipus"], int(r_["id"]))
        if k not in ep:
            continue
        u = utcakulcs(r_["utca"])
        osm_cimek_szoveg[k].add((u, r_["hazszam"].strip().lower()))
        for n, suf in tokenek(r_["hazszam"]):
            utca_szam[(u, n)].setdefault(k, set()).add(suf)
    # name / style already present from another source
    van_nev, van_stilus = set(), set()
    for ut in sorted(Path(TENYEK).glob("*.csv")):
        if ut.name == Path(KIMENET).name:
            continue
        for r in olvas(ut):
            k = (r.get("osm_tipus") or "way", int(r["id"])) if (r.get("id") or "").isdigit() else None
            if k and (r.get("ertek") or "").strip():
                if r["mezo"] == "nev":
                    van_nev.add(k)
                elif r["mezo"] == "stilus":
                    van_stilus.add(k)
    # manual decisions
    kezi = {}
    if Path(KEZI).exists():
        for r in olvas(KEZI):
            if (r.get("utca") or "").strip() and (r.get("sor") or "").strip():
                kezi[(r["utca"].strip(), r["sor"].strip())] = (r.get("osm_azonosito") or "").strip()
    else:
        Path(KEZI).parent.mkdir(parents=True, exist_ok=True)
        with open(KEZI, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f, delimiter=";").writerow(["utca", "sor", "osm_azonosito", "megjegyzes"])

    def jeloltek(uk, n, suf):
        """Buildings bearing the (street, house number[, suffix]) address and of at least MIN_TERULET m²; the suffix (89/c) makes it more precise."""
        mind = [k for k in utca_szam.get((uk, n), {}) if ep[k]["ter"] >= MIN_TERULET]
        if suf:
            pontos = [k for k in mind if suf in utca_szam[(uk, n)][k]]
        else:
            pontos = [k for k in mind if "" in utca_szam[(uk, n)][k]]
        return pontos or mind

    def kulcsszavak(sz):
        return {w for w in re.findall(r"[a-záéíóöőúüű]{5,}", sz.lower()) if w not in ("bérház", "bérpalota", "lakóház", "épület", "lakóépület", "irodaház")}

    # pass 1: in which districts the street runs (based on the unambiguous hits)
    kerek = collections.defaultdict(collections.Counter)
    for r in sorok:
        for n, suf in tokenek(r["szam"]):
            j = jeloltek(utcakulcs(r["utca"]), n, suf)
            if len(j) == 1:
                kerek[r["utca"]][ep[j[0]]["ker"]] += 1
    fo_ker = {u: {k for k, v in c.items() if v >= max(3, 0.1 * sum(c.values()))} for u, c in kerek.items()}

    paros = []                     # (row, [building keys])
    ellenorzes, stat = [], collections.Counter()
    for r in sorok:
        sz = r["szam"]
        alap = {"lap": r["lap"], "utca": r["utca"], "sor": r["sor"], "szam": sz, "nev": r["nev"], "ev": r["ev"], "tervezo": r["tervezo"],
                "szakasz": r["szakasz"], "megjegyzes_wikipedia": r["megjegyzes"]}
        if ELBONTVA.search(" ".join((r["nev"], r["megjegyzes"], r["ev"]))):
            stat["elbontott: kihagyva"] += 1
            continue
        dont = kezi.get((r["utca"], r["sor"]), "")
        if dont.lower() == "nem":
            stat["kézi: nem"] += 1
            continue
        if dont and osm_azon(dont):
            paros.append((r, osm_azon(dont)))
            stat["kézi: megadott épület"] += 1
            continue
        toks = tokenek(sz)
        if not toks:
            stat["nincs használható házszám"] += 1
            continue
        uk = utcakulcs(r["utca"])
        ker = int(r["kerulet"]) if (r["kerulet"] or "").isdigit() else None
        m = re.search(r"\b([IVX]+)\.\s*kerület", r["szakasz"] or "")
        ker = ker or (ROMAI.get(m.group(1)) if m else None)
        talalt, hianyzik, tobb = [], [], []
        kw = kulcsszavak(r["nev"])
        for n, suf in toks:
            jel = jeloltek(uk, n, suf)
            if ker:
                jel = [k for k in jel if ep[k]["ker"] == ker] or jel
            fk = fo_ker.get(r["utca"])
            if fk and len(jel) > 1:
                jel = [k for k in jel if ep[k]["ker"] in fk] or jel
            if len(jel) > 1:                                  # match by name: the OSM name or type has a word in common
                nevesek = [k for k in jel if kw and kulcsszavak(ep[k]["nev"] or "") & kw]
                if len(nevesek) == 1:
                    jel = nevesek
            if len(jel) > 1:
                jel.sort(key=lambda k: -ep[k]["ter"])
                cimek_ = [frozenset(osm_cimek_szoveg[k]) for k in jel]
                if ep[jel[0]]["ter"] >= ARANY * ep[jel[1]]["ter"]:          # the largest is the main building, the rest are outbuildings
                    jel = jel[:1]
                elif len(set(cimek_)) == 1 and ep[jel[0]]["ter"] <= ARANY * ep[jel[-1]]["ter"] and len({ep[k]["ker"] for k in jel}) == 1:
                    pass                                          # sibling buildings with the same title and similar size: all of them get it
                else:
                    tobb.append((n, jel))
                    continue
            if len(jel) >= 1:
                talalt += jel
            else:
                hianyzik.append(n)
        talalt = list(dict.fromkeys(talalt))
        if talalt and not tobb:
            paros.append((r, talalt))
            stat["párosítva" if not hianyzik else "párosítva (néhány házszám hiányzik az OSM-ben)"] += 1
        else:
            if tobb:
                kat = "több jelölt (több épület viseli ezt a címet)"
                javaslat = " | ".join(f"{t} {i}" for _, jel in tobb[:2] for t, i in jel[:3])
            else:
                kat = "nincs OSM-épület ezzel a címmel"
                javaslat = ""
            stat[kat[:20]] += 1
            ellenorzes.append({**alap, "kategoria": kat, "javasolt_osm": javaslat, "hianyzo_hazszam": " ".join(map(str, hianyzik))})

    # rows pointing to the same building: if they carry different data, we write nothing
    epulet_sorok = collections.defaultdict(list)
    for r, ks in paros:
        for k in ks:
            epulet_sorok[k].append(r)
    kesz, ellenorzott_sorok = set(), set()
    for k, lista in epulet_sorok.items():
        evek = {ev_ertek(x["ev"]) for x in lista if ev_ertek(x["ev"])}
        nevek = {x["nev"] for x in lista if x["nev"]}
        if len(lista) > 1 and evek and max(evek) - min(evek) > 2:      # a difference in names is no obstacle (a corner house in the lists of two streets): there we write no name
            for x in lista:
                if (x["utca"], x["sor"]) not in ellenorzott_sorok:
                    ellenorzott_sorok.add((x["utca"], x["sor"]))
                    ellenorzes.append({"lap": x["lap"], "utca": x["utca"], "sor": x["sor"], "szam": x["szam"], "nev": x["nev"], "ev": x["ev"],
                                       "tervezo": x["tervezo"], "szakasz": x["szakasz"], "megjegyzes_wikipedia": x["megjegyzes"],
                                       "kategoria": "több sor mutat ugyanarra az épületre, eltérő adattal",
                                       "javasolt_osm": f"{k[0]} {k[1]}", "hianyzo_hazszam": ""})
            stat["több sor, eltérő adat"] += 1
    def egyezo(k, mezo_fn):
        vals = {mezo_fn(x) for x in epulet_sorok[k]}
        vals.discard(None)
        vals.discard("")
        return vals

    for r, ks in paros:
        if (r["utca"], r["sor"]) in ellenorzott_sorok:
            continue
        megj = f"hu.wikipedia.org {r['lap']}, {r['sor']}. sor ({r['utca']} {r['szam']})"
        ev = ev_ertek(r["ev"])
        tervezo = re.sub(r"\s+", " ", r["tervezo"]).strip()
        if tervezo.lower() in ("", "?", "ismeretlen", "-", "–", "nem ismert", "n. a.", "n.a.") or "?" in tervezo or re.search(r"\bvagy\b", tervezo):
            tervezo = ""
        for k in ks:
            if len(epulet_sorok[k]) > 1:      # several lists mention it: only the consistent data goes out
                if ev and len(egyezo(k, lambda x: ev_ertek(x["ev"]))) > 1:
                    ev = None
                if tervezo and len(egyezo(k, lambda x: re.sub(r"\s+", " ", x["tervezo"]).strip())) > 1:
                    tervezo = ""
                nev_ok = len(egyezo(k, lambda x: x["nev"].strip())) <= 1
            else:
                nev_ok = True
            if ev:
                kesz.add((k[0], k[1], "ev", ev, "wikipedia_lista", megj))
            if tervezo:
                kesz.add((k[0], k[1], "tervezo", tervezo, "wikipedia_lista", megj))
            if nev_ok and r["nev"] and not ALTALANOS.match(r["nev"].strip()) and r["nev"].strip()[0].isupper() and k not in van_nev and not ep[k]["nev"]:
                kesz.add((k[0], k[1], "nev", r["nev"].strip(), "wikipedia_lista", megj))
            if r["stilus"] and k not in van_stilus:
                kesz.add((k[0], k[1], "stilus", r["stilus"].strip(), "wikipedia_lista", megj))
    tenyek_irasa(KIMENET, sorted(kesz, key=lambda s: (s[0], s[1], s[2], str(s[3]))))

    mezok = ["kategoria", "lap", "utca", "sor", "szam", "nev", "ev", "tervezo", "szakasz", "megjegyzes_wikipedia", "javasolt_osm", "hianyzo_hazszam"]
    ellenorzes.sort(key=lambda x: (x["kategoria"], x["utca"], int(x["sor"]) if str(x["sor"]).isdigit() else 0))
    with open(ELLENORZES, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=mezok, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows(ellenorzes)
    print(f"Wikipedia-sorok: {len(sorok)}")
    for k, v in sorted(stat.items()):
        print(f"  {k}: {v}")
    print(f"Tények: {len(kesz)} sor -> {KIMENET} ({len(epulet_sorok)} épület)")
    print(f"Ellenőrizendő: {len(ellenorzes)} sor -> {ELLENORZES}")


if __name__ == "__main__":
    main()
