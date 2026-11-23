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

LIST = "data/epforum/budapesti_kortars_epuletek_lista.csv"
OUTPUT = Path("data/epforum/cikkek.csv")
BASE = "https://epiteszforum.hu"
PAUSE = 0.7


class Articles(HTMLParser):
    """The result list: in the .oneItem blocks, the link of the div with class .title."""
    def __init__(self):
        super().__init__()
        self.articles, self._title, self._a = [], False, None

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
            if h.startswith("/") and not any(h == c[0] for c in self.articles):
                self.articles.append((h, re.sub(r"\s+", " ", self._a[1]).strip()))
            self._a = None
        if tag == "div":
            self._title = False


def query(id_):
    data_ = urllib.parse.urlencode({"map_elements_id": id_}).encode()
    search_ = urllib.request.Request(BASE + "/terkep/mapresult", data=data_, headers={
        "Content-Type": "application/x-www-form-urlencoded", "X-Requested-With": "XMLHttpRequest",
        "User-Agent": "budapest-by-building (personal, non-commercial map project)"})
    with urllib.request.urlopen(search_, timeout=30) as v:
        p = Articles()
        p.feed(v.read().decode("utf-8", "replace"))
        return p.articles


def main():
    ids = sys.argv[1:] or [r["ID"].strip() for r in csv.DictReader(open(LIST, encoding="utf-8-sig"), delimiter=";") if r.get("ID", "").strip()]
    rows, done = [], set()
    if OUTPUT.exists():
        for r in csv.DictReader(open(OUTPUT, encoding="utf-8-sig"), delimiter=";"):
            rows.append([r["id"], r["url"], r["cim"]])
            done.add(r["id"])
    new = [i for i in ids if i not in done]
    print(f"{len(ids)} pont, ebből {len(new)} még nincs lekérve")
    for n, id_ in enumerate(new, 1):
        try:
            articles = query(id_)
        except Exception as e:
            print(f"  {id_}: hiba ({e}); a következő futásnál újra próbálja")
            continue
        rows += [[id_, BASE + h, c] for h, c in articles] or [[id_, "", "nincs"]]
        if n % 25 == 0:
            print(f"  {n}/{len(new)}")
        time.sleep(PAUSE)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["id", "url", "cim"])
        w.writerows(rows)
    print(f"Kész: {len(rows)} sor -> {OUTPUT}")


main()
