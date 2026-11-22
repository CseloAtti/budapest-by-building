"""Az épületadatok (terkep3d/data_varos/epuletek.json) épségének ellenőrzése. Futtatás: py tesztek/teszt_adatok.py
Az újraépítés után érdemes lefuttatni: kiszűri a hiányzó/értelmetlen mezőket, és figyelmeztet, ha az arányok hirtelen változnak."""
import json
import sys
from collections import Counter
from kozos_teszt import GYOKER, ellenoriz, figyelmeztet, hiba, vege

FAJL = GYOKER / "terkep3d" / "data_varos" / "epuletek.json"
# a Budapestet körülvevő téglalap (bő)
LAT = (47.30, 47.70)
LON = (18.90, 19.40)
DARAB = (240_000, 300_000)           # az épületek elvárt száma (ha ezen kívül esik, gyanús)
ISMERT_ARANY = (0.02, 0.06)          # az ismert évű épületek aránya (jelenleg ~3,3%)


def main(fajl=FAJL):
    print(f"[adatok] {fajl}")
    adat = json.loads(fajl.read_text(encoding="utf-8"))
    n = len(adat)
    ellenoriz(DARAB[0] <= n <= DARAB[1], f"az épületek száma gyanús: {n} (elvárt: {DARAB[0]}–{DARAB[1]})")
    kulcsok = Counter()
    ismert = 0
    forras = Counter()
    for p in adat:
        az = (p.get("osm_tipus"), p.get("id"))
        kulcsok[az] += 1
        la, lo = p.get("lat"), p.get("lon")
        if not (isinstance(la, (int, float)) and isinstance(lo, (int, float)) and LAT[0] <= la <= LAT[1] and LON[0] <= lo <= LON[1]):
            hiba(f"{az}: a koordináta hibás vagy Budapesten kívüli: {la}, {lo}")
        m = p.get("magassag")
        if m is not None and not (isinstance(m, (int, float)) and 0 < m <= 400):
            hiba(f"{az}: a magasság értelmetlen: {m}")
        ev = p.get("ev")
        if ev:
            ismert += 1
            forras[p.get("ev_forras")] += 1
            if not (isinstance(ev, int) and 1000 <= ev <= 2026):
                hiba(f"{az}: az év értelmetlen: {ev}")
            if not p.get("ev_forras"):
                figyelmeztet(f"{az}: ismert év, de nincs forrása")
        k = p.get("kor")
        if k is not None and not (isinstance(k, int) and 0 <= k <= 6):
            hiba(f"{az}: a korszak-index értelmetlen: {k}")
        v = p.get("ev_becsles_valoszinuseg")
        if v is not None and not (0 <= v <= 1):
            hiba(f"{az}: a becslés valószínűsége értelmetlen: {v}")
        if len(__import__("kozos_teszt").HIBAK) > 50:
            print("  (túl sok hiba, a vizsgálat megszakad)")
            break
    # a több külön poligonból álló relation (multipolygon) többször szerepelhet; egy way azonban nem
    ismetlodo_way = [a for a, c in kulcsok.items() if c > 1 and a[0] == "way"]
    ellenoriz(not ismetlodo_way, f"{len(ismetlodo_way)} way-azonosító többször szerepel (pl. {ismetlodo_way[:3]})")
    ismetlodo_rel = [a for a, c in kulcsok.items() if c > 1 and a[0] != "way"]
    if ismetlodo_rel:
        figyelmeztet(f"{len(ismetlodo_rel)} relation több poligonrészként szerepel (ez rendben van, ha az épületkártya kezeli)")
    # kitalált évszám nem lehet adat (a tenyek_veletlen_ev.py korábban ilyet írt: 202 ház, a kártyán valódi évként)
    kitalalt = sum(1 for p in adat if p.get("ev") and p.get("ev_forras") == "veletlen")
    ellenoriz(not kitalalt, f"{kitalalt} épület éve kitalált ('veletlen' forrás): ez nem lehet pontos év (futtasd: py tenyek_veletlen_ev.py varos)")
    # a Névjegy száma a budapest.json-ból jön, nem kézzel beírt szám
    cfg = fajl.parent / "budapest.json"
    if cfg.exists():
        st = json.loads(cfg.read_text(encoding="utf-8")).get("stats", {})
        ellenoriz(st.get("ismert_ev_epulet"), "a budapest.json stats részéből hiányzik az 'ismert_ev_epulet' (a Névjegy száma): futtasd a csempek_keszites.py-t")
        if st.get("ismert_ev_epulet"):
            print(f"  a Névjegyben: {st['ismert_ev_epulet']} ismert évű épület a {st.get('epulet_egyedi')} közül")
    app = (GYOKER / "terkep3d" / "app.js").read_text(encoding="utf-8")
    ellenoriz("{ISMERT_HU}" in app and "8470" not in app, "a Névjegy ismert-évű száma kézzel van beírva az app.js-be (a budapest.json-ból kell jönnie)")
    # a kézi javítás (forras/kezi_javitasok.csv) mindig győz: az utolsó kézi évszám-sor legyen a térképen ('-' = nincs pontos év)
    kezi_ut = GYOKER / "forras" / "kezi_javitasok.csv"
    if kezi_ut.exists():
        import csv
        utolso = {}
        for r in csv.DictReader(open(kezi_ut, encoding="utf-8-sig", newline=""), delimiter=";"):
            if r.get("mezo") == "ev" and (r.get("id") or "").strip().isdigit():
                utolso[((r.get("osm_tipus") or "way").strip(), int(r["id"]))] = (r.get("ertek") or "").strip()
        terkep = {}
        for p in adat:
            if not p.get("resz"):
                terkep.setdefault((p.get("osm_tipus") or "way", p.get("id")), p.get("ev"))
        # '-' után nem lehet pontos év; szám után kell, hogy legyen (az értéke egy épületcsoportban a csoporté lehet)
        rossz = [(k, v, terkep[k]) for k, v in utolso.items() if k in terkep and
                 ((v == "-" and terkep[k]) or (v.isdigit() and terkep[k] is None))]
        ellenoriz(not rossz, f"{len(rossz)} épületnél nem a kézi évszám-javítás látszik (pl. {rossz[:3]}): futtasd újra a zona_frissit.bat-ot")
    arany = ismert / n if n else 0
    ellenoriz(ISMERT_ARANY[0] <= arany <= ISMERT_ARANY[1], f"az ismert évű épületek aránya gyanús: {arany:.1%} (elvárt: {ISMERT_ARANY[0]:.0%}–{ISMERT_ARANY[1]:.0%})")
    print(f"  épületek: {n}, ismert évű: {ismert} ({arany:.1%})")
    print("  a legnagyobb évforrások:", ", ".join(f"{k}: {v}" for k, v in forras.most_common(6)))
    return vege("adatok")


if __name__ == "__main__":
    raise SystemExit(main())
