"""Építészfórum map: links of the articles belonging to the points -> data/epforum/cikkek.csv

On clicking a map point, the epiteszforum.hu/terkep page requests the list of the point's articles from the /terkep/mapresult endpoint
(the browser loads the same). We also request this once per point (with a pause of about 0.7 s, robots.txt allows it) and store it.
Points already requested are not requested again on the next run, so the run is fast; for new points it resumes automatically.

Input:    data/epforum/budapesti_kortars_epuletek_lista.csv   (ID column)
Output:   data/epforum/cikkek.csv   (id;url;cim) - one point in several rows, in Építészfórum's order; a row with the title 'nincs' = no article
Run:      py facts_epforum_articles.py   (afterwards: py facts_epforum.py)  - you can also give an ID: py facts_epforum_articles.py 898 899"""
import csv
import re
import sys
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

LISTA = "data/epforum/budapesti_kortars_epuletek_lista.csv"
KIMENET = Path("data/epforum/cikkek.csv")
ALAP = "https://epiteszforum.hu"
SZUNET = 0.7


class Cikkek(HTMLParser):
    """The result list: in the .oneItem blocks, the link of the div with class .title."""
    def __init__(self):
        super().__init__()
        self.cikkek, self._title, self._a = [], False, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "div" and "title" in (a.get("class") or "").split():
            self._title = True
        if tag == "a" and self._title and a.get("href"):
            self._a = [a["href"], ""]

    def handle_data(self, data):
        if self._a is not None:
            self._a[1] += data

    def handle_endtag(self, tag):
        if tag == "a" and self._a is not None:
            h = self._a[0]
            if h.startswith("/") and not any(h == c[0] for c in self.cikkek):
                self.cikkek.append((h, re.sub(r"\s+", " ", self._a[1]).strip()))
            self._a = None
        if tag == "div":
            self._title = False


def lekerdez(azon):
    adat = urllib.parse.urlencode({"map_elements_id": azon}).encode()
    keres = urllib.request.Request(ALAP + "/terkep/mapresult", data=adat, headers={
        "Content-Type": "application/x-www-form-urlencoded", "X-Requested-With": "XMLHttpRequest",
        "User-Agent": "budapest-by-building (personal, non-commercial map project)"})
    with urllib.request.urlopen(keres, timeout=30) as v:
        p = Cikkek()
        p.feed(v.read().decode("utf-8", "replace"))
        return p.cikkek


def main():
    ids = sys.argv[1:] or [r["ID"].strip() for r in csv.DictReader(open(LISTA, encoding="utf-8-sig"), delimiter=";") if r.get("ID", "").strip()]
    sorok, kesz = [], set()
    if KIMENET.exists():
        for r in csv.DictReader(open(KIMENET, encoding="utf-8-sig"), delimiter=";"):
            sorok.append([r["id"], r["url"], r["cim"]])
            kesz.add(r["id"])
    ujak = [i for i in ids if i not in kesz]
    print(f"{len(ids)} pont, ebből {len(ujak)} még nincs lekérve")
    for n, azon in enumerate(ujak, 1):
        try:
            cikkek = lekerdez(azon)
        except Exception as e:
            print(f"  {azon}: hiba ({e}); a következő futásnál újra próbálja")
            continue
        sorok += [[azon, ALAP + h, c] for h, c in cikkek] or [[azon, "", "nincs"]]
        if n % 25 == 0:
            print(f"  {n}/{len(ujak)}")
        time.sleep(SZUNET)
    KIMENET.parent.mkdir(parents=True, exist_ok=True)
    with open(KIMENET, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["id", "url", "cim"])
        w.writerows(sorok)
    print(f"Kész: {len(sorok)} sor -> {KIMENET}")


main()
