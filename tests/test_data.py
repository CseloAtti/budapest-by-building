"""Checking the integrity of the building data (terkep3d/data_varos/epuletek.json). Run: py tests/test_data.py
It is worth running after a rebuild: it filters out missing/meaningless fields, and warns if the proportions change suddenly."""
import json
import sys
from collections import Counter
from test_common import ROOT, check, warn, error_, end_

FILE = ROOT / "terkep3d" / "data_varos" / "epuletek.json"
# the rectangle around Budapest (generous)
LAT = (47.30, 47.70)
LON = (18.90, 19.40)
COUNT = (240_000, 300_000)           # the expected number of buildings (outside this it is suspicious)
KNOWN_RATIO = (0.02, 0.06)          # the proportion of buildings with a known year (currently ~3.3%)


def main(file=FILE):
    print(f"[adatok] {file}")
    data_ = json.loads(file.read_text(encoding="utf-8"))
    n = len(data_)
    check(COUNT[0] <= n <= COUNT[1], f"az épületek száma gyanús: {n} (elvárt: {COUNT[0]}–{COUNT[1]})")
    keys = Counter()
    known = 0
    source = Counter()
    for p in data_:
        az = (p.get("osm_tipus"), p.get("id"))
        keys[az] += 1
        la, lo = p.get("lat"), p.get("lon")
        if not (isinstance(la, (int, float)) and isinstance(lo, (int, float)) and LAT[0] <= la <= LAT[1] and LON[0] <= lo <= LON[1]):
            error_(f"{az}: a koordináta hibás vagy Budapesten kívüli: {la}, {lo}")
        m = p.get("magassag")
        if m is not None and not (isinstance(m, (int, float)) and 0 < m <= 400):
            error_(f"{az}: a magasság értelmetlen: {m}")
        year = p.get("ev")
        if year:
            known += 1
            source[p.get("ev_forras")] += 1
            if not (isinstance(year, int) and 1000 <= year <= 2026):
                error_(f"{az}: az év értelmetlen: {year}")
            if not p.get("ev_forras"):
                warn(f"{az}: ismert év, de nincs forrása")
        k = p.get("kor")
        if k is not None and not (isinstance(k, int) and 0 <= k <= 6):
            error_(f"{az}: a korszak-index értelmetlen: {k}")
        v = p.get("ev_becsles_valoszinuseg")
        if v is not None and not (0 <= v <= 1):
            error_(f"{az}: a becslés valószínűsége értelmetlen: {v}")
        if len(__import__("test_common").ERRORS) > 50:
            print("  (túl sok hiba, a vizsgálat megszakad)")
            break
    # a relation (multipolygon) made of several separate polygons may appear several times; a way, however, may not
    duplicate_way = [a for a, c in keys.items() if c > 1 and a[0] == "way"]
    check(not duplicate_way, f"{len(duplicate_way)} way-azonosító többször szerepel (pl. {duplicate_way[:3]})")
    duplicate_rel = [a for a, c in keys.items() if c > 1 and a[0] != "way"]
    if duplicate_rel:
        warn(f"{len(duplicate_rel)} relation több poligonrészként szerepel (ez rendben van, ha az épületkártya kezeli)")
    # an invented year must not be data (facts_assumed_year.py used to write such: 202 houses, on the card as a real year)
    invented = sum(1 for p in data_ if p.get("ev") and p.get("ev_forras") == "veletlen")
    check(not invented, f"{invented} épület éve kitalált ('veletlen' forrás): ez nem lehet pontos év (futtasd: py facts_assumed_year.py varos)")
    # the About count comes from budapest.json, it is not a hand-typed number
    cfg = file.parent / "budapest.json"
    if cfg.exists():
        st = json.loads(cfg.read_text(encoding="utf-8")).get("stats", {})
        check(st.get("ismert_ev_epulet"), "a budapest.json stats részéből hiányzik az 'ismert_ev_epulet' (a Névjegy száma): futtasd a build_tiles.py-t")
        if st.get("ismert_ev_epulet"):
            print(f"  a Névjegyben: {st['ismert_ev_epulet']} ismert évű épület a {st.get('epulet_egyedi')} közül")
    app = (ROOT / "terkep3d" / "app.js").read_text(encoding="utf-8")
    check("{ISMERT_HU}" in app and "8470" not in app, "a Névjegy ismert-évű száma kézzel van beírva az app.js-be (a budapest.json-ból kell jönnie)")
    # the manual correction (forras/kezi_javitasok.csv) always wins: the last manual year row should be on the map ('-' = no exact year)
    manual_path = ROOT / "forras" / "kezi_javitasok.csv"
    if manual_path.exists():
        import csv
        last = {}
        for r in csv.DictReader(open(manual_path, encoding="utf-8-sig", newline=""), delimiter=";"):
            if r.get("mezo") == "ev" and (r.get("id") or "").strip().isdigit():
                last[((r.get("osm_tipus") or "way").strip(), int(r["id"]))] = (r.get("ertek") or "").strip()
        map_ = {}
        for p in data_:
            if not p.get("resz"):
                map_.setdefault((p.get("osm_tipus") or "way", p.get("id")), p.get("ev"))
        # there cannot be an exact year after '-'; there must be one after a number (its value in a building group may be the group's)
        bad = [(k, v, map_[k]) for k, v in last.items() if k in map_ and
                 ((v == "-" and map_[k]) or (v.isdigit() and map_[k] is None))]
        check(not bad, f"{len(bad)} épületnél nem a kézi évszám-javítás látszik (pl. {bad[:3]}): futtasd újra a zones_refresh.bat-ot")
    ratio = known / n if n else 0
    check(KNOWN_RATIO[0] <= ratio <= KNOWN_RATIO[1], f"az ismert évű épületek aránya gyanús: {ratio:.1%} (elvárt: {KNOWN_RATIO[0]:.0%}–{KNOWN_RATIO[1]:.0%})")
    print(f"  épületek: {n}, ismert évű: {known} ({ratio:.1%})")
    print("  a legnagyobb évforrások:", ", ".join(f"{k}: {v}" for k, v in source.most_common(6)))
    return end_("adatok")


if __name__ == "__main__":
    raise SystemExit(main())
