"""A magyar Wikipedia utcánkénti épületlistáinak letöltése (A budapesti ... épületeinek listája).

Kimenet:  data/wikipedia_lista/sorok.csv     (lap;utca;kerulet;szakasz;sor;szam;nev;ev;tervezo;stilus;megjegyzes)
          data/wikipedia_lista/cache/*.json  (a letöltött oldalak; ha ott vannak, nem tölti le újra - törölve újratölt)

Futtatás:  py tenyek_wikipedia_lista_letolt.py
Utána:     py tenyek_wikipedia_lista.py varos     (párosítás az OSM-címekkel, tények, ellenőrző tábla)

A Wikipedia szövege CC BY-SA licenc alatt van; a tények megjegyzése mindig megnevezi a lapot és a sort.
A 'sor' az oldal táblázatainak sorszáma (1-től, a fejléc nélkül, az oldalon felülről lefelé).
"""
import csv
import html
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

MAPPA = Path("data/wikipedia_lista")
CACHE = MAPPA / "cache"
KIMENET = MAPPA / "sorok.csv"
API = "https://hu.wikipedia.org/w/api.php?action=parse&format=json&formatversion=2&redirects=1&prop=text&page="
UA = "budapest-by-building/1.0 (hobby map project; contact: cselovszki.attila@gmail.com)"
KESLELTETES = 0.7

LAPOK = [
    "A budapesti Ajtósi Dürer sor épületeinek listája", "A budapesti Andrássy út épületeinek listája",
    "A Budapest VIII. kerületi Baross utca épületeinek listája", "A budapesti Baross tér épületeinek listája",
    "A budapesti Dózsa György út épületeinek listája", "A budapesti Erzsébet körút épületeinek listája",
    "A budapesti Ferenc körút épületeinek listája", "A budapesti Fiumei út épületeinek listája",
    "A budapesti Gubacsi út épületeinek listája", "A budapesti Hermina út épületeinek listája",
    "A budapesti Hungária körút épületeinek listája", "A budapesti József körút épületeinek listája",
    "A budapesti Károly körút épületeinek listája", "A budapesti Kerepesi út épületeinek listája",
    "A budapesti Kossuth Lajos utca épületeinek listája", "A budapesti Könyves Kálmán körút épületeinek listája",
    "A budapesti Lehel utca épületeinek listája", "A budapesti Mester utca épületeinek listája",
    "A budapesti Múzeum körút épületeinek listája", "A budapesti Podmaniczky utca épületeinek listája",
    "A budapesti Rákóczi út épületeinek listája", "A budapesti Róbert Károly körút épületeinek listája",
    "A budapesti Soroksári út épületeinek listája", "A budapesti Stefánia út épületeinek listája",
    "A budapesti Szabolcs utca épületeinek listája", "A budapesti Szent István körút épületeinek listája",
    "A budapesti Teréz körút épületeinek listája", "A budapesti Thököly út épületeinek listája",
    "A budapesti Üllői út épületeinek listája", "A budapesti Váci út épületeinek listája",
    "A budapesti Városligeti fasor épületeinek listája", "A budapesti Verseny utca épületeinek listája",
]
FEJLEC = ["lap", "utca", "kerulet", "szakasz", "sor", "szam", "nev", "ev", "tervezo", "stilus", "megjegyzes"]
ROMAI = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12,
         "XIII": 13, "XIV": 14, "XV": 15, "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20, "XXI": 21, "XXII": 22, "XXIII": 23}


def utca_a_cimbol(cim):
    s = re.sub(r"^(A budapesti |A Budapest [IVX]+\. kerületi |A )", "", cim)
    return re.sub(r" épületeinek listája$", "", s)


def kerulet_a_cimbol(cim):
    m = re.search(r"Budapest ([IVX]+)\. kerületi", cim)
    return ROMAI.get(m.group(1), "") if m else ""


def letolt(cim):
    CACHE.mkdir(parents=True, exist_ok=True)
    ut = CACHE / (re.sub(r"[^\w]+", "_", cim) + ".json")
    if ut.exists():
        return json.loads(ut.read_text(encoding="utf-8"))["parse"]["text"]
    kerelem = urllib.request.Request(API + urllib.parse.quote(cim), headers={"User-Agent": UA})
    with urllib.request.urlopen(kerelem, timeout=60) as v:
        adat = v.read().decode("utf-8")
    ut.write_text(adat, encoding="utf-8")
    time.sleep(KESLELTETES)
    return json.loads(adat)["parse"]["text"]


def szoveg(h):
    h = re.sub(r"<sup[^>]*class=\"[^\"]*reference[^\"]*\".*?</sup>", "", h, flags=re.S)
    h = re.sub(r"<(style|script)[^>]*>.*?</\1>", "", h, flags=re.S)
    h = re.sub(r"<br\s*/?>|</p>|</li>", " ", h)
    h = re.sub(r"<[^>]+>", "", h)
    h = html.unescape(h).replace("\xa0", " ")
    return re.sub(r"\s+", " ", h).strip()


def tablak(h):
    """[(szakasz, [sorok])] - a sorok cellalistái; a rowspan/colspan szétterítve, a fejlécsor 'th'-val jelölve."""
    esemenyek = []
    for m in re.finditer(r"<h[2-4][^>]*>(.*?)</h[2-4]>", h, flags=re.S):
        esemenyek.append((m.start(), "h", szoveg(m.group(1)).replace("[szerkesztés]", "").strip()))
    for m in re.finditer(r"<table[^>]*class=\"[^\"]*wikitable[^\"]*\"[^>]*>(.*?)</table>", h, flags=re.S):
        esemenyek.append((m.start(), "t", m.group(1)))
    esemenyek.sort(key=lambda e: e[0])
    szakasz, ki = "", []
    for _, tip, tartalom in esemenyek:
        if tip == "h":
            szakasz = tartalom
            continue
        racs, sorok = {}, []
        for sn, sor in enumerate(re.findall(r"<tr[^>]*>(.*?)</tr>", tartalom, flags=re.S)):
            cellak = re.findall(r"<(t[dh])([^>]*)>(.*?)</t[dh]>", sor, flags=re.S)
            kimenet, oszlop = [], 0
            fejlec = bool(cellak) and all(c[0] == "th" for c in cellak)

            def kovetkezo_szabad(o):
                while (sn, o) in racs:
                    o += 1
                return o
            for tip_, attr, belso in cellak:
                oszlop = kovetkezo_szabad(oszlop)
                rs = int(re.search(r"rowspan=\"?(\d+)", attr).group(1)) if re.search(r"rowspan=\"?(\d+)", attr) else 1
                cs = int(re.search(r"colspan=\"?(\d+)", attr).group(1)) if re.search(r"colspan=\"?(\d+)", attr) else 1
                ertek = szoveg(belso)
                for dr in range(rs):
                    for dc in range(cs):
                        if dr == 0:
                            kimenet.append((oszlop + dc, ertek))
                        else:
                            racs[(sn + dr, oszlop + dc)] = ertek
                oszlop += cs
            for (r, o), ertek in list(racs.items()):
                if r == sn and not any(o == k for k, _ in kimenet):
                    kimenet.append((o, ertek))
            kimenet.sort()
            sorok.append((fejlec, [e for _, e in kimenet]))
        ki.append((szakasz, sorok))
    return ki


def oszlopok(fejlec):
    t = {}
    for i, c in enumerate(fejlec):
        k = c.lower()
        if k.startswith(("házszám", "szám")) and "szam" not in t:
            t["szam"] = i
        elif k.startswith(("név", "épület", "megnevezés")) and "nev" not in t:
            t["nev"] = i
        elif k.startswith("építés") and "ev" not in t:
            t["ev"] = i
        elif k.startswith(("tervező", "építész")) and "tervezo" not in t:
            t["tervezo"] = i
        elif k.startswith("stílus") and "stilus" not in t:
            t["stilus"] = i
        elif k.startswith("megjegyzés") and "megjegyzes" not in t:
            t["megjegyzes"] = i
    if "szam" not in t and fejlec and fejlec[0] == "":
        t["szam"] = 0              # néhány lapon a házszám oszlopának nincs felirata
    return t


def main():
    MAPPA.mkdir(parents=True, exist_ok=True)
    ossz = 0
    with open(KIMENET, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(FEJLEC)
        for cim in LAPOK:
            try:
                h = letolt(cim)
            except Exception as e:
                print(f"HIBA: {cim}: {e}")
                continue
            utca, ker, sorszam, db = utca_a_cimbol(cim), kerulet_a_cimbol(cim), 0, 0
            for szakasz, sorok in tablak(h):
                t = {}
                for fejlec, cellak in sorok:
                    if fejlec:
                        t = oszlopok(cellak)
                        continue
                    if not t or "szam" not in t:
                        continue
                    sorszam += 1
                    g = lambda k: cellak[t[k]] if k in t and t[k] < len(cellak) else ""
                    if not g("szam") and not g("nev"):
                        continue
                    w.writerow([cim, utca, ker, szakasz, sorszam, g("szam"), g("nev"), g("ev"), g("tervezo"), g("stilus"), g("megjegyzes")])
                    db += 1
            ossz += db
            print(f"{cim}: {db} sor")
    print(f"Összesen {ossz} sor -> {KIMENET}")


if __name__ == "__main__":
    main()
