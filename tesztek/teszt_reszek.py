"""Checking the uniform era of the building parts (building:part). Run: py tesztek/teszt_reszek.py
The error it catches: if a building is drawn from its parts and has no year, the parts used to each get the era of the nearest
building one by one, so one house showed in several colours (46 buildings). Now all the year-less parts of a building get the same
era. It reads the parts' parent from data/varos/epuletek_vegleges.geojson (a large file, ~10-20 s)."""
import json
from collections import defaultdict
from kozos_teszt import GYOKER, ellenoriz, figyelmeztet, vege

VEGLEGES = GYOKER / "data" / "varos" / "epuletek_vegleges.geojson"
KARTYA = GYOKER / "terkep3d" / "data_varos" / "epuletek.json"


def main():
    print("[reszek] egy épület részei egy korszakban")
    if not VEGLEGES.exists() or not KARTYA.exists():
        figyelmeztet("nincs meg az epuletek_vegleges.geojson vagy az epuletek.json: a teszt kimaradt")
        return vege("reszek")
    szulo = {}
    for f in json.loads(VEGLEGES.read_text(encoding="utf-8"))["features"]:
        p = f["properties"]
        if p.get("resz") and p.get("szulo_id"):
            szulo[(p.get("osm_tipus") or "way", int(p["id"]))] = (p.get("szulo_tipus"), p["szulo_id"])
    kor = defaultdict(set)
    for p in json.loads(KARTYA.read_text(encoding="utf-8")):
        if p.get("resz") and not p.get("ev"):
            s = szulo.get((p.get("osm_tipus") or "way", p["id"]))
            if s:
                kor[s].add(p.get("kor"))
    # a year-less part drawn together with its parent (standing outside it, but connected to it) gets the parent's era
    kartya = {}
    for p in json.loads(KARTYA.read_text(encoding="utf-8")):
        kartya[(p.get("osm_tipus") or "way", p["id"])] = p
    elter = []
    for k, s in szulo.items():
        r, sp = kartya.get(k), kartya.get((s[0] or "way", int(s[1])))
        if r and sp and not r.get("ev") and not sp.get("ev") and r.get("kor") != sp.get("kor"):
            elter.append(k)
    ellenoriz(not elter, f"{len(elter)} épületrész más korszakot kapott, mint a szülő épülete (pl. {elter[:3]})")
    tobbszinu = [k for k, v in kor.items() if len(v) > 1]
    ellenoriz(not tobbszinu, f"{len(tobbszinu)} épület részei különböző korszakot kaptak (pl. {tobbszinu[:3]})")
    print(f"  részekből álló, év nélküli épület: {len(kor)}, ebből több színű: {len(tobbszinu)}")
    return vege("reszek")


if __name__ == "__main__":
    raise SystemExit(main())
