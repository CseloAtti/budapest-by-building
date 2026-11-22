"""A rajzolt zónák (forras/zonak_poligon.geojson) típusa, kerülete és évei -> terkep3d/zonak.json
A 3D nézet Lakótelepek fülének listája ezt használja: az ipar_kereskedelem típusú zónák nem lakótelepek,
ezért nem szerepelnek a listában és a kiemelésben. Futtatás: py zonak_json_keszites.py (az "Újraépítés" gomb is lefuttatja)."""
import json
from pathlib import Path

BE = Path("forras/zonak_poligon.geojson")
KI = Path("terkep3d/zonak.json")


def main():
    zonak = {}
    for f in json.loads(BE.read_text(encoding="utf-8")).get("features", []):
        p = f.get("properties", {})
        nev = (p.get("nev") or "").strip()
        if not nev or nev in zonak:
            continue
        zonak[nev] = {"t": p.get("tipus") or "", "k": p.get("kerulet") or "", "a": p.get("ev_tol") or None, "b": p.get("ev_ig") or None}
    KI.write_text(json.dumps(zonak, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  zonak.json: {len(zonak)} zóna")


if __name__ == "__main__":
    main()
