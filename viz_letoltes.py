"""
viz_letoltes.py - a Duna, a tavak és a parkok sokszögei az OpenStreetMapból (a 3D nézet talajához).

Futtatás (a projekt mappájában):   py viz_letoltes.py
Kimenet:  data/viz_zold.json   (utána futtasd: py csempek_keszites.py)

Csak a Python alap könyvtárát használja. Az Overpass-szervereket sorban próbálja.
A sokszögeket a megjelenített területre vágja, így a Duna sem lesz túl nagy.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

OVERPASS_URLS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

# a megjelenített terület: a vizsgált épületterületnél kicsit nagyobb (dél, nyugat, észak, kelet)
DEL, NYUGAT, ESZAK, KELET = 47.480, 19.025, 47.523, 19.075
BBOX = f"{DEL},{NYUGAT},{ESZAK},{KELET}"

QUERY = f"""
[out:json][timeout:180];
(
  way["natural"="water"]({BBOX});
  relation["natural"="water"]({BBOX});
  way["waterway"="riverbank"]({BBOX});
  relation["waterway"="riverbank"]({BBOX});
);
out geom;
(
  way["leisure"~"^(park|garden)$"]({BBOX});
  relation["leisure"~"^(park|garden)$"]({BBOX});
  way["landuse"~"^(grass|recreation_ground)$"]({BBOX});
  relation["landuse"~"^(grass|recreation_ground)$"]({BBOX});
);
out geom;
"""


def letolt():
    adat = urllib.parse.urlencode({"data": QUERY}).encode("utf-8")
    for kor in range(3):
        for url in OVERPASS_URLS:
            print(f"Próbálkozás: {url}")
            keres = urllib.request.Request(url, data=adat, headers={"User-Agent": "budapest-by-building-tanulas/0.1"})
            try:
                with urllib.request.urlopen(keres, timeout=200) as valasz:
                    eredmeny = json.load(valasz)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as hiba:
                print(f"  Nem sikerült: {hiba}")
                continue
            if eredmeny.get("remark"):
                print("  A szerver figyelmeztet:", eredmeny["remark"])
                continue
            print("  Letöltött elemek:", dict(Counter(e["type"] for e in eredmeny["elements"])))
            return eredmeny["elements"]
        print("Minden szerver hibázott, 20 másodperc várakozás...")
        time.sleep(20)
    raise SystemExit("Nem sikerült letölteni. Próbáld meg később.")


def gyurukke_fuz(szakaszok):
    """Szétdarabolt körvonal-szakaszokat fűz össze zárt gyűrűkké (mint a geojson_keszites.py)."""
    szakaszok = [list(s) for s in szakaszok if len(s) >= 2]
    gyuruk = []
    while szakaszok:
        gyuru = szakaszok.pop(0)
        while gyuru[0] != gyuru[-1]:
            for i, s in enumerate(szakaszok):
                if s[0] == gyuru[-1]:
                    gyuru.extend(s[1:])
                elif s[-1] == gyuru[-1]:
                    gyuru.extend(reversed(s[:-1]))
                elif s[-1] == gyuru[0]:
                    gyuru = s[:-1] + gyuru
                elif s[0] == gyuru[0]:
                    gyuru = list(reversed(s[1:])) + gyuru
                else:
                    continue
                szakaszok.pop(i)
                break
            else:
                break
        if gyuru[0] == gyuru[-1] and len(gyuru) >= 4:
            gyuruk.append(gyuru)
    return gyuruk


def vag(gyuru):
    """Sutherland–Hodgman: a sokszöget a megjelenített téglalapra vágja. gyuru: [(lon, lat), ...] zárt."""
    pontok = gyuru[:-1] if gyuru[0] == gyuru[-1] else list(gyuru)
    # (belül-e, metszéspont) a négy éllel
    hatarok = [
        (lambda p: p[0] >= NYUGAT, lambda a, b: (NYUGAT, a[1] + (b[1] - a[1]) * (NYUGAT - a[0]) / (b[0] - a[0]))),
        (lambda p: p[0] <= KELET, lambda a, b: (KELET, a[1] + (b[1] - a[1]) * (KELET - a[0]) / (b[0] - a[0]))),
        (lambda p: p[1] >= DEL, lambda a, b: (a[0] + (b[0] - a[0]) * (DEL - a[1]) / (b[1] - a[1]), DEL)),
        (lambda p: p[1] <= ESZAK, lambda a, b: (a[0] + (b[0] - a[0]) * (ESZAK - a[1]) / (b[1] - a[1]), ESZAK)),
    ]
    for bent, metszes in hatarok:
        if not pontok:
            return []
        ki = []
        elozo = pontok[-1]
        for p in pontok:
            if bent(p):
                if not bent(elozo):
                    ki.append(metszes(elozo, p))
                ki.append(p)
            elif bent(elozo):
                ki.append(metszes(elozo, p))
            elozo = p
        pontok = ki
    return pontok if len(pontok) >= 3 else []


def pont_gyuruben(pont, gyuru):
    x, y = pont
    bent = False
    for (x1, y1), (x2, y2) in zip(gyuru, gyuru[1:] + gyuru[:1]):
        if (y1 > y) != (y2 > y):
            if x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                bent = not bent
    return bent


def fajta(tags):
    if tags.get("natural") == "water" or tags.get("waterway") == "riverbank":
        return "viz"
    return "park"


def main():
    elemek = letolt()
    kesz = []
    ki = Counter()
    for e in elemek:
        tags = e.get("tags", {})
        if not tags:
            continue
        f = fajta(tags)
        if e["type"] == "way":
            gy = [(p["lon"], p["lat"]) for p in e.get("geometry", [])]
            kulsok = [gy] if len(gy) >= 4 and gy[0] == gy[-1] else []
            belsok = []
        else:
            kulso_sz, belso_sz = [], []
            for m in e.get("members", []):
                if m["type"] != "way" or not m.get("geometry"):
                    continue
                sz = [(p["lon"], p["lat"]) for p in m["geometry"]]
                (belso_sz if m.get("role") == "inner" else kulso_sz).append(sz)
            kulsok, belsok = gyurukke_fuz(kulso_sz), gyurukke_fuz(belso_sz)
        if not kulsok:
            ki[f"{f}: nem zárható gyűrű"] += 1
            continue
        for k in kulsok:
            vagott = vag(k)
            if not vagott:
                ki[f"{f}: a területen kívül"] += 1
                continue
            gyuruk = [vagott + [vagott[0]]]
            for b in belsok:
                if pont_gyuruben(b[0], k):
                    bv = vag(b)
                    if bv:
                        gyuruk.append(bv + [bv[0]])
            kesz.append({"fajta": f, "gyuruk": [[list(p) for p in g] for g in gyuruk]})
            ki[f"{f}: kész"] += 1
    Path("data").mkdir(exist_ok=True)
    Path("data/viz_zold.json").write_text(json.dumps(kesz), encoding="utf-8")
    for k, v in sorted(ki.items()):
        print(f"  {k}: {v}")
    print("Mentve: data/viz_zold.json  (most futtasd: py csempek_keszites.py)")


if __name__ == "__main__":
    main()
