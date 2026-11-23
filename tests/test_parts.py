"""Checking the uniform era of the building parts (building:part). Run: py tests/test_parts.py
The error it catches: if a building is drawn from its parts and has no year, the parts used to each get the era of the nearest
building one by one, so one house showed in several colours (46 buildings). Now all the year-less parts of a building get the same
era. It reads the parts' parent from data/varos/epuletek_vegleges.geojson (a large file, ~10-20 s)."""
import json
from collections import defaultdict
from test_common import ROOT, check, warn, end_

FINAL = ROOT / "data" / "varos" / "epuletek_vegleges.geojson"
CARD = ROOT / "terkep3d" / "data_varos" / "epuletek.json"


def main():
    print("[reszek] egy épület részei egy korszakban")
    if not FINAL.exists() or not CARD.exists():
        warn("nincs meg az epuletek_vegleges.geojson vagy az epuletek.json: a teszt kimaradt")
        return end_("reszek")
    parent_ = {}
    for f in json.loads(FINAL.read_text(encoding="utf-8"))["features"]:
        p = f["properties"]
        if p.get("resz") and p.get("szulo_id"):
            parent_[(p.get("osm_tipus") or "way", int(p["id"]))] = (p.get("szulo_tipus"), p["szulo_id"])
    era = defaultdict(set)
    for p in json.loads(CARD.read_text(encoding="utf-8")):
        if p.get("resz") and not p.get("ev"):
            s = parent_.get((p.get("osm_tipus") or "way", p["id"]))
            if s:
                era[s].add(p.get("kor"))
    # a year-less part drawn together with its parent (standing outside it, but connected to it) gets the parent's era
    card = {}
    for p in json.loads(CARD.read_text(encoding="utf-8")):
        card[(p.get("osm_tipus") or "way", p["id"])] = p
    differs = []
    for k, s in parent_.items():
        r, sp = card.get(k), card.get((s[0] or "way", int(s[1])))
        if r and sp and not r.get("ev") and not sp.get("ev") and r.get("kor") != sp.get("kor"):
            differs.append(k)
    check(not differs, f"{len(differs)} épületrész más korszakot kapott, mint a szülő épülete (pl. {differs[:3]})")
    multicolor = [k for k, v in era.items() if len(v) > 1]
    check(not multicolor, f"{len(multicolor)} épület részei különböző korszakot kaptak (pl. {multicolor[:3]})")
    print(f"  részekből álló, év nélküli épület: {len(era)}, ebből több színű: {len(multicolor)}")
    return end_("reszek")


if __name__ == "__main__":
    raise SystemExit(main())
