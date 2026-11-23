"""Checking the data sheets of the defining buildings and the data of the architectural styles.
Run: py tests/test_datasheets.py
It catches the errors so far: a missing 'forrasok'/'kepek' array (the popup did not appear because of it), broken keys, a missing image file."""
import json
import re
from test_common import GYOKER, ellenoriz, figyelmeztet, hiba, vege

ADATLAP = GYOKER / "terkep3d" / "adatlapok.json"
EPITESZ = GYOKER / "terkep3d" / "epitesz.json"
KEPEK = GYOKER / "terkep3d" / "kepek"
KULCS = re.compile(r"^(way|relation|node)/\d+$")


def main():
    print("[adatlapok] adatlapok.json, epitesz.json")
    d = json.loads(ADATLAP.read_text(encoding="utf-8"))
    ellenoriz({"adatlapok", "stilusok"} <= set(d), "az adatlapok.json-ból hiányzik az 'adatlapok' vagy a 'stilusok' kulcs")
    a = d.get("adatlapok", {})
    for k, v in a.items():
        ellenoriz(KULCS.match(k), f"hibás adatlap-kulcs: {k}")
        ellenoriz(isinstance(v.get("szoveg"), str), f"{k}: a 'szoveg' nem szöveg")
        ellenoriz(isinstance(v.get("forrasok"), list), f"{k}: hiányzik a 'forrasok' tömb (a kártya hibára futna)")
        ellenoriz(isinstance(v.get("kepek"), list), f"{k}: hiányzik a 'kepek' tömb")
        for f in v.get("forrasok") or []:
            ellenoriz(isinstance(f, dict) and str(f.get("url", "")).startswith(("http://", "https://")), f"{k}: hibás forráslink: {f}")
        for kep in v.get("kepek") or []:
            fajl = kep.get("f") if isinstance(kep, dict) else None
            if fajl and not (GYOKER / "terkep3d" / fajl).exists():
                hiba(f"{k}: hiányzó képfájl: {fajl}")
            for mezo in ("szerzo", "licenc"):
                if isinstance(kep, dict) and not kep.get(mezo):
                    figyelmeztet(f"{k}: a képnek nincs {mezo} megadva ({fajl})")
        if len(v.get("szoveg", "")) < 80:
            figyelmeztet(f"{k}: nagyon rövid leírás ({len(v.get('szoveg', ''))} karakter)")

    # the building lists of the styles
    for stilus, hazak in d.get("stilusok", {}).items():
        for h in hazak:
            if h.get("azon") not in a:
                hiba(f"stílus '{stilus}': a(z) '{h.get('nev')}' ({h.get('azon')}) házhoz nincs adatlap")
            ellenoriz(KULCS.match(str(h.get("azon", ""))), f"stílus '{stilus}': hibás azonosító: {h.get('azon')}")

    # architectural styles
    e = json.loads(EPITESZ.read_text(encoding="utf-8"))
    nevek = set()
    for s in e:
        nev = s.get("nev_hu") or s.get("hu")
        ellenoriz(nev, "névtelen stílus az epitesz.json-ban")
        ellenoriz(nev not in nevek, f"kétszer szereplő stílus: {nev}")
        nevek.add(nev)
        for mezo in ("korszak", "szin", "d", "ossz"):
            ellenoriz(s.get(mezo) not in (None, ""), f"{nev}: hiányzik a(z) '{mezo}' mező")
        ellenoriz(re.match(r"^#[0-9a-fA-F]{6}$", str(s.get("szin", ""))), f"{nev}: hibás szín: {s.get('szin')}")
        ep_nevek = [x.get("nev") for x in s.get("epitesz", [])]
        ellenoriz(len(ep_nevek) == len(set(ep_nevek)), f"{nev}: ismétlődő építész a listában")
        for x in s.get("epitesz", []):
            ellenoriz(x.get("nev"), f"{nev}: névtelen építész-bejegyzés")
    return vege("adatlapok")


if __name__ == "__main__":
    raise SystemExit(main())
