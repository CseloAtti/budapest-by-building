"""Type, district and years of the drawn zones (forras/zonak_poligon.geojson) -> terkep3d/zonak.json
The 3D view's Housing estates tab list uses this: zones of the ipar_kereskedelem (industry/commerce) type are not housing estates,
so they do not appear in the list or in the highlighting. Run: py build_zones_json.py (the "Rebuild" button also runs it)."""
import json
from pathlib import Path

BE = Path("forras/zonak_poligon.geojson")
OUT = Path("terkep3d/zonak.json")


def main():
    zones = {}
    for f in json.loads(BE.read_text(encoding="utf-8")).get("features", []):
        p = f.get("properties", {})
        name_ = (p.get("nev") or "").strip()
        if not name_ or name_ in zones:
            continue
        zones[name_] = {"t": p.get("tipus") or "", "k": p.get("kerulet") or "", "a": p.get("ev_tol") or None, "b": p.get("ev_ig") or None}
    OUT.write_text(json.dumps(zones, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  zonak.json: {len(zones)} zóna")


if __name__ == "__main__":
    main()
