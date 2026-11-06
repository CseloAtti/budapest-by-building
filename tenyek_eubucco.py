"""EUBUCCO (data/eubucco.geojson) -> data/tenyek/eubucco.csv
A magasság nagyrészt gépi tanulással becsült (kb. ±4 m sáv), ezért a forrás neve
"eubucco_becsles"; ahol a forrásadatból származik: "eubucco_forras"."""
import json
from collections import Counter, defaultdict

from kozos import (belso_pont, kulcs, pont_barmelyikben, poligonok,
                   teruletu_kozeppont, tenyek_irasa)

OSM = "data/belvaros_epuletek.geojson"
EUBUCCO = "data/eubucco.geojson"
KIMENET = "data/tenyek/eubucco.csv"
CELLA = 0.002  # fok, a gyors kereséshez használt rács mérete


def cella(x, y):
    return int(x / CELLA), int(y / CELLA)


def main():
    with open(EUBUCCO, encoding="utf-8") as f:
        eub = json.load(f)["features"]
    with open(OSM, encoding="utf-8") as f:
        feats = [x for x in json.load(f)["features"] if x["properties"].get("tipus") != "roof"]
    print(f"EUBUCCO épületek: {len(eub)}, saját épületek: {len(feats)}")

    darabok, racs = [], defaultdict(list)
    for ft in eub:
        polik = poligonok(ft["geometry"])
        if not polik:
            continue
        ter, cx, cy = teruletu_kozeppont(polik[0][0])
        if not pont_barmelyikben(cx, cy, polik):
            cx, cy = belso_pont(polik)
        d = {"p": ft["properties"], "polik": polik, "ter": ter, "x": cx, "y": cy}
        darabok.append(d)
        racs[cella(cx, cy)].append(d)

    sorok, mod = [], Counter()
    for ft in feats:
        polik = poligonok(ft["geometry"])
        if not polik:
            continue
        xs = [p[0] for p in polik[0][0]]
        ys = [p[1] for p in polik[0][0]]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        talalat = []
        for i in range(int(x0 / CELLA) - 1, int(x1 / CELLA) + 2):
            for j in range(int(y0 / CELLA) - 1, int(y1 / CELLA) + 2):
                for d in racs.get((i, j), []):
                    if x0 <= d["x"] <= x1 and y0 <= d["y"] <= y1 and pont_barmelyikben(d["x"], d["y"], polik):
                        talalat.append(d)
        how = "darabok_bennunk"
        if not talalat:
            bx, by = belso_pont(polik)
            ci, cj = cella(bx, by)
            for i in range(ci - 2, ci + 3):
                for j in range(cj - 2, cj + 3):
                    for d in racs.get((i, j), []):
                        if pont_barmelyikben(bx, by, d["polik"]):
                            talalat.append(d)
            how = "mi_benne_vagyunk"
        if not talalat:
            mod["nincs_par"] += 1
            continue
        mod[how] += 1
        e = max(talalat, key=lambda z: z["ter"])["p"]
        t, i = kulcs(ft["properties"])
        becsult = e.get("height_source") == 2
        F = "eubucco_becsles" if becsult else "eubucco_forras"
        sorok += [(t, i, "eubucco_id", e.get("id"), F, f"{len(talalat)} darab"),
                  (t, i, "eubucco_magassag_min", e.get("height_confidence_lower"), F, ""),
                  (t, i, "eubucco_magassag_max", e.get("height_confidence_upper"), F, ""),
                  (t, i, "eubucco_szintek", e.get("floors"), F, "becsult" if e.get("floors_source") == 2 else "forrasbol")]
        if e.get("height") is not None:
            sorok.append((t, i, "magassag", round(float(e["height"]), 1), F, ""))
        if e.get("construction_year"):
            sorok.append((t, i, "ev", int(e["construction_year"]), "eubucco", ""))
    tenyek_irasa(KIMENET, [s for s in sorok if s[3] not in (None, "")])
    for k, v in sorted(mod.items()):
        print(f"  {k}: {v}")
    print(f"Mentve: {KIMENET}")


main()
