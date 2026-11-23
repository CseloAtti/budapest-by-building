"""Downloading the street-by-street building lists of the Hungarian Wikipedia (A budapesti ... épületeinek listája = The list of buildings of Budapest's ...).

Output:   data/wikipedia_lista/sorok.csv     (lap;utca;kerulet;szakasz;sor;szam;nev;ev;tervezo;stilus;megjegyzes)
          data/wikipedia_lista/cache/*.json  (the downloaded pages; if they are there, it does not download again - delete to download again)

Run:       py facts_wikipedia_list_download.py
Afterwards: py facts_wikipedia_list.py varos     (matching with the OSM addresses, facts, checking table)

The text of Wikipedia is under the CC BY-SA licence; the remark of the facts always names the page and the row.
The 'sor' is the row number in the page's tables (from 1, without the header, from the top of the page downwards).
"""
import csv
import html
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

FOLDER = Path("data/wikipedia_lista")
CACHE = FOLDER / "cache"
OUTPUT = FOLDER / "sorok.csv"
API = "https://hu.wikipedia.org/w/api.php?action=parse&format=json&formatversion=2&redirects=1&prop=text&page="
UA = "budapest-by-building/1.0 (hobby map project; contact: cselovszki.attila@gmail.com)"
DELAY = 0.7

PAGES = [
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
HEADER = ["lap", "utca", "kerulet", "szakasz", "sor", "szam", "nev", "ev", "tervezo", "stilus", "megjegyzes"]
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12,
         "XIII": 13, "XIV": 14, "XV": 15, "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20, "XXI": 21, "XXII": 22, "XXIII": 23}


def street_a_from_address(address):
    s = re.sub(r"^(A budapesti |A Budapest [IVX]+\. kerületi |A )", "", address)
    return re.sub(r" épületeinek listája$", "", s)


def district_a_from_address(address):
    m = re.search(r"Budapest ([IVX]+)\. kerületi", address)
    return ROMAN.get(m.group(1), "") if m else ""


def download(address):
    CACHE.mkdir(parents=True, exist_ok=True)
    path_ = CACHE / (re.sub(r"[^\w]+", "_", address) + ".json")
    if path_.exists():
        return json.loads(path_.read_text(encoding="utf-8"))["parse"]["text"]
    request_ = urllib.request.Request(API + urllib.parse.quote(address), headers={"User-Agent": UA})
    with urllib.request.urlopen(request_, timeout=60) as v:
        data_ = v.read().decode("utf-8")
    path_.write_text(data_, encoding="utf-8")
    time.sleep(DELAY)
    return json.loads(data_)["parse"]["text"]


def text_(h):
    h = re.sub(r"<sup[^>]*class=\"[^\"]*reference[^\"]*\".*?</sup>", "", h, flags=re.S)
    h = re.sub(r"<(style|script)[^>]*>.*?</\1>", "", h, flags=re.S)
    h = re.sub(r"<br\s*/?>|</p>|</li>", " ", h)
    h = re.sub(r"<[^>]+>", "", h)
    h = html.unescape(h).replace("\xa0", " ")
    return re.sub(r"\s+", " ", h).strip()


def tables(h):
    """[(section, [rows])] - the rows' cell lists; rowspan/colspan spread out, the header row marked with 'th'."""
    events = []
    for m in re.finditer(r"<h[2-4][^>]*>(.*?)</h[2-4]>", h, flags=re.S):
        events.append((m.start(), "h", text_(m.group(1)).replace("[szerkesztés]", "").strip()))
    for m in re.finditer(r"<table[^>]*class=\"[^\"]*wikitable[^\"]*\"[^>]*>(.*?)</table>", h, flags=re.S):
        events.append((m.start(), "t", m.group(1)))
    events.sort(key=lambda e: e[0])
    section, out = "", []
    for _, kind, content in events:
        if kind == "h":
            section = content
            continue
        grid, rows = {}, []
        for sn, row in enumerate(re.findall(r"<tr[^>]*>(.*?)</tr>", content, flags=re.S)):
            cells = re.findall(r"<(t[dh])([^>]*)>(.*?)</t[dh]>", row, flags=re.S)
            output, column = [], 0
            header = bool(cells) and all(c[0] == "th" for c in cells)

            def next_free(o):
                while (sn, o) in grid:
                    o += 1
                return o
            for type_, attr, inner in cells:
                column = next_free(column)
                rs = int(re.search(r"rowspan=\"?(\d+)", attr).group(1)) if re.search(r"rowspan=\"?(\d+)", attr) else 1
                cs = int(re.search(r"colspan=\"?(\d+)", attr).group(1)) if re.search(r"colspan=\"?(\d+)", attr) else 1
                value = text_(inner)
                for dr in range(rs):
                    for dc in range(cs):
                        if dr == 0:
                            output.append((column + dc, value))
                        else:
                            grid[(sn + dr, column + dc)] = value
                column += cs
            for (r, o), value in list(grid.items()):
                if r == sn and not any(o == k for k, _ in output):
                    output.append((o, value))
            output.sort()
            rows.append((header, [e for _, e in output]))
        out.append((section, rows))
    return out


def columns(header):
    t = {}
    for i, c in enumerate(header):
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
    if "szam" not in t and header and header[0] == "":
        t["szam"] = 0              # on some pages the house-number column has no label
    return t


def main():
    FOLDER.mkdir(parents=True, exist_ok=True)
    total = 0
    with open(OUTPUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(HEADER)
        for address in PAGES:
            try:
                h = download(address)
            except Exception as e:
                print(f"HIBA: {address}: {e}")
                continue
            street, district, serial, count_ = street_a_from_address(address), district_a_from_address(address), 0, 0
            for section, rows in tables(h):
                t = {}
                for header, cells in rows:
                    if header:
                        t = columns(cells)
                        continue
                    if not t or "szam" not in t:
                        continue
                    serial += 1
                    g = lambda k: cells[t[k]] if k in t and t[k] < len(cells) else ""
                    if not g("szam") and not g("nev"):
                        continue
                    w.writerow([address, street, district, section, serial, g("szam"), g("nev"), g("ev"), g("tervezo"), g("stilus"), g("megjegyzes")])
                    count_ += 1
            total += count_
            print(f"{address}: {count_} sor")
    print(f"Összesen {total} sor -> {OUTPUT}")


if __name__ == "__main__":
    main()
