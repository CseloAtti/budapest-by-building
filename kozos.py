"""Közös segédfüggvények a tény-tábla rendszerhez (ezt a fájlt nem kell futtatni)."""
import csv
import json
import math
import time
import urllib.error
import urllib.request
from pathlib import Path

FEJLEC = ["osm_tipus", "id", "mezo", "ertek", "forras", "megjegyzes", "lat", "lon"]


def kulcs(pr):
    """Az épület azonosítója: (osm_tipus, id). A régi fájlokban nincs osm_tipus: akkor way."""
    return (pr.get("osm_tipus") or "way", int(pr["id"]))


def tenyek_irasa(ut, sorok):
    """sorok: (osm_tipus, id, mezo, ertek, forras, megjegyzes) listája. Excelben is megnyitható."""
    Path(ut).parent.mkdir(parents=True, exist_ok=True)
    with open(ut, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(FEJLEC)
        for s in sorok:
            w.writerow(list(s) + [""] * (len(FEJLEC) - len(s)))


def tenyek_olvasasa(ut, alap_forras=None):
    """Visszaadja a sorokat szótárként. Hiányzó 'forras' mezőt az alap_forras tölti ki."""
    sorok = []
    with open(ut, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if not (r.get("mezo") or "").strip():
                continue
            if not (r.get("forras") or "").strip():
                r["forras"] = alap_forras or Path(ut).stem
            sorok.append(r)
    return sorok


# ---- geometria ----
def poligonok(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return geom["coordinates"]
    return []


def pont_gyuruben(x, y, gyuru):
    bent = False
    for (x1, y1), (x2, y2) in zip(gyuru, gyuru[1:]):
        if (y1 > y) != (y2 > y):
            if x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                bent = not bent
    return bent


def pont_poligonban(x, y, gyuruk):
    """gyuruk[0] a külső körvonal, a többi udvar (lyuk)."""
    if not pont_gyuruben(x, y, gyuruk[0]):
        return False
    return not any(pont_gyuruben(x, y, lyuk) for lyuk in gyuruk[1:])


def pont_barmelyikben(x, y, polik):
    return any(pont_poligonban(x, y, p) for p in polik)


def teruletu_kozeppont(gyuru):
    """(terület m², x, y) a külső körvonalból."""
    kx = 111320 * math.cos(math.radians(gyuru[0][1]))
    ky = 110540
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(gyuru, gyuru[1:]):
        c = x1 * y2 - x2 * y1
        a += c
        cx += (x1 + x2) * c
        cy += (y1 + y2) * c
    if abs(a) < 1e-18:
        xs = [p[0] for p in gyuru]
        ys = [p[1] for p in gyuru]
        return 0.0, sum(xs) / len(xs), sum(ys) / len(ys)
    return abs(a) / 2 * kx * ky, cx / (3 * a), cy / (3 * a)


def belso_pont(polik):
    """Egy pont, ami biztosan az épületen belül van."""
    gyuru = polik[0][0]
    _, cx, cy = teruletu_kozeppont(gyuru)
    jeloltek = [(cx, cy)]
    for px, py in gyuru[:-1]:
        jeloltek.append(((px + cx) / 2, (py + cy) / 2))
        jeloltek.append((px * 0.8 + cx * 0.2, py * 0.8 + cy * 0.2))
    for x, y in jeloltek:
        if pont_barmelyikben(x, y, polik):
            return x, y
    return cx, cy


def legkozelebbi_csucs_m(x, y, gyuru):
    kx = 111320 * math.cos(math.radians(y))
    ky = 110540
    return min(math.hypot((px - x) * kx, (py - y) * ky) for px, py in gyuru)


def kliens_nev():
    """A kéréseknél megadott kliensnév. Ha van data/kapcsolat.txt (csak a te gépeden, a git nem
    viszi fel), annak tartalmát hozzáfűzi: a Wikimedia így nem kezeli névtelen robotként."""
    nev = "budapest-by-building/1.0 (tanulasi projekt)"
    ut = Path("data/kapcsolat.txt")
    if ut.exists():
        extra = ut.read_text(encoding="utf-8").strip()
        if extra:
            nev += " " + extra
    return nev


def http_json(url, fejlec=None, probak=6, alap_varakozas=60, timeout=120):
    """JSON lekérése; 429/5xx hibánál vár (a szerver kérése szerint), majd újra próbálkozik."""
    fejlec = dict(fejlec or {})
    fejlec.setdefault("User-Agent", kliens_nev())
    for p in range(1, probak + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=fejlec), timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as hiba:
            if hiba.code not in (429, 500, 502, 503, 504) or p == probak:
                raise
            v = alap_varakozas
            try:
                v = max(v, int(hiba.headers.get("Retry-After", 0)) + 5)
            except (TypeError, ValueError, AttributeError):
                pass
            print(f"  A szerver most lassít ({hiba.code}), {p}/{probak}. próba. Várok {v} másodpercet...")
            time.sleep(v)
        except urllib.error.URLError as hiba:
            if p == probak:
                raise
            print(f"  Hálózati hiba ({hiba.reason}), {p}/{probak}. próba. Várok 30 másodpercet...")
            time.sleep(30)
