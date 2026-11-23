"""Checking the data sheets of the defining buildings and the data of the architectural styles.
Run: py tests/test_datasheets.py
It catches the errors so far: a missing 'forrasok'/'kepek' array (the popup did not appear because of it), broken keys, a missing image file."""
import json
import re
from test_common import ROOT, check, warn, error_, end_

DATASHEET = ROOT / "terkep3d" / "adatlapok.json"
ARCHITECT = ROOT / "terkep3d" / "epitesz.json"
IMAGES = ROOT / "terkep3d" / "kepek"
KEY = re.compile(r"^(way|relation|node)/\d+$")


def main():
    print("[adatlapok] adatlapok.json, epitesz.json")
    d = json.loads(DATASHEET.read_text(encoding="utf-8"))
    check({"adatlapok", "stilusok"} <= set(d), "az adatlapok.json-ból hiányzik az 'adatlapok' vagy a 'stilusok' kulcs")
    a = d.get("adatlapok", {})
    for k, v in a.items():
        check(KEY.match(k), f"hibás adatlap-kulcs: {k}")
        check(isinstance(v.get("szoveg"), str), f"{k}: a 'szoveg' nem szöveg")
        check(isinstance(v.get("forrasok"), list), f"{k}: hiányzik a 'forrasok' tömb (a kártya hibára futna)")
        check(isinstance(v.get("kepek"), list), f"{k}: hiányzik a 'kepek' tömb")
        for f in v.get("forrasok") or []:
            check(isinstance(f, dict) and str(f.get("url", "")).startswith(("http://", "https://")), f"{k}: hibás forráslink: {f}")
        for image in v.get("kepek") or []:
            file = image.get("f") if isinstance(image, dict) else None
            if file and not (ROOT / "terkep3d" / file).exists():
                error_(f"{k}: hiányzó képfájl: {file}")
            for field in ("szerzo", "licenc"):
                if isinstance(image, dict) and not image.get(field):
                    warn(f"{k}: a képnek nincs {field} megadva ({file})")
        if len(v.get("szoveg", "")) < 80:
            warn(f"{k}: nagyon rövid leírás ({len(v.get('szoveg', ''))} karakter)")

    # the building lists of the styles
    for style, houses in d.get("stilusok", {}).items():
        for h in houses:
            if h.get("azon") not in a:
                error_(f"stílus '{style}': a(z) '{h.get('nev')}' ({h.get('azon')}) házhoz nincs adatlap")
            check(KEY.match(str(h.get("azon", ""))), f"stílus '{style}': hibás azonosító: {h.get('azon')}")

    # architectural styles
    e = json.loads(ARCHITECT.read_text(encoding="utf-8"))
    names = set()
    for s in e:
        name_ = s.get("nev_hu") or s.get("hu")
        check(name_, "névtelen stílus az epitesz.json-ban")
        check(name_ not in names, f"kétszer szereplő stílus: {name_}")
        names.add(name_)
        for field in ("korszak", "szin", "d", "ossz"):
            check(s.get(field) not in (None, ""), f"{name_}: hiányzik a(z) '{field}' mező")
        check(re.match(r"^#[0-9a-fA-F]{6}$", str(s.get("szin", ""))), f"{name_}: hibás szín: {s.get('szin')}")
        ep_names = [x.get("nev") for x in s.get("epitesz", [])]
        check(len(ep_names) == len(set(ep_names)), f"{name_}: ismétlődő építész a listában")
        for x in s.get("epitesz", []):
            check(x.get("nev"), f"{name_}: névtelen építész-bejegyzés")
    return end_("adatlapok")


if __name__ == "__main__":
    raise SystemExit(main())
