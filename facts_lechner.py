"""Points of the Lechner Knowledge Centre -> fact table (data/tenyek/lechner.csv).
We take over only facts (name, construction time, designer); deliberately not the descriptions and photos."""
import csv
import html
import json
import re
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

from common import building_key, write_facts
from area_common import BuildingIndex

KML = "data/lechner.kml"
CITY = len(sys.argv) > 1 and sys.argv[1] == "varos"      # py facts_lechner.py varos  -> the whole city
OSM = "data/varos/epuletek.geojson" if CITY else "data/belvaros_epuletek.geojson"
OUTPUT = "data/tenyek/lechner.csv"
POINTS = "data/lechner_pontok.json"
MANUAL = "forras/lechner_kezi_parositas.csv"   # manual checking of the near and the unmatched points: you fill in the 'osm_azonosito' column
NEARBY_METER = 15  # if a point does not fall into a building, we accept a building within this many metres
ns = {"k": "http://www.opengis.net/kml/2.2"}
CUT = r"újjáépít|átépít|átalakít|felújít|rekonstrukció|restaurál|bővít|majd|bizonytalan"


def period(text_):
    """The start and end year of the construction period, and whether it is unambiguous.
    '1875–1884' -> (1875, 1884, True); '1817, majd 1909–1913' ('1817, then 1909–1913') -> (1817, 1817, False)."""
    if not text_:
        return None, None, False
    certain = not re.search(r"majd|bizonytalan|körül|as évek|\?|század", text_)
    first_part = re.split(CUT, text_, maxsplit=1)[0]
    m = re.search(r"(?<!\d)(1[0-9]{3}|20[0-2][0-9])\s*[–-]\s*(\d{2,4})(?!\d)", first_part)
    if m:
        start_ = int(m.group(1))
        end_text = m.group(2)
        end_ = int(end_text) if len(end_text) == 4 else int(m.group(1)[:2] + end_text)
        if end_ < start_:
            end_ = start_
        return start_, end_, certain
    years = [int(x) for x in re.findall(r"(?<!\d)(1[0-9]{3}|20[0-2][0-9])(?!\d)", first_part)]
    if not years:
        return None, None, False
    if len(years) > 1:
        certain = False
    return min(years), max(years), certain


def kml_read(path_):
    root = ET.parse(path_).getroot()
    points = []
    for p in root.findall(".//k:Placemark", ns):
        name_ = " ".join((p.findtext("k:name", namespaces=ns) or "").split())
        coord = p.findtext("k:Point/k:coordinates", namespaces=ns)
        if not coord:
            continue
        lon, lat = (float(x) for x in coord.strip().split(",")[:2])
        description = html.unescape(p.findtext("k:description", namespaces=ns) or "")
        description = re.sub(r"<br\s*/?>", "\n", description)
        description = re.sub(r"<[^>]+>", "", description)
        m = re.search(r"Épült:\s*([^\n]*)", description)
        built = m.group(1).split("Tervező:")[0].strip() if m else None
        m = re.search(r"Tervező:\s*([^\n]*)", description)
        designer = m.group(1).strip() if m else None
        if designer in ("–", "-", "—"):          # in the Lechner description this is the sign of "no designer"
            designer = None
        start_, end_, certain = period(built)
        points.append({"nev": name_, "lat": lat, "lon": lon, "epult": built,
                       "ev_kezdet": start_, "ev_veg": end_, "ev_egyertelmu": certain,
                       "tervezo": designer})
    return points


def manual_read():
    """name -> [(osm_tipus, id), ...]  (empty list: 'nincs' = there is no OSM building for this point). Empty cell: the automatic one stays."""
    out = {}
    if not Path(MANUAL).exists():
        return out
    with open(MANUAL, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            value = (r.get("osm_azonosito") or "").strip()
            if not value:
                continue
            if re.fullmatch(r"nincs|-|–|nem", value, flags=re.I):
                out[r["lechner_nev"].strip()] = []
                continue
            those = []
            for part in re.split(r"[|;,\n]+", value):
                m = re.search(r"(?:(way|relation|node)[/ :]*)?(\d{3,})", part.strip(), flags=re.I)
                if m:
                    those.append(((m.group(1) or "way").lower(), int(m.group(2))))
            if those:
                out[r["lechner_nev"].strip()] = those
    return out


def main():
    manual = manual_read()
    points = kml_read(KML)
    with open(OSM, encoding="utf-8") as f:
        feats = [x for x in json.load(f)["features"] if x["properties"].get("tipus") != "roof"]
    index = BuildingIndex(feats)
    del feats
    xs = [p[0] for ft, pl in index.elements for poly in pl for p in poly[0]]
    ys = [p[1] for ft, pl in index.elements for poly in pl for p in poly[0]]
    lon_min, lon_max, lat_min, lat_max = min(xs), max(xs), min(ys), max(ys)
    area = [p for p in points if lon_min <= p["lon"] <= lon_max and lat_min <= p["lat"] <= lat_max]
    print(f"Pontok a KML-ben: {len(points)}, ebből a területen: {len(area)}")

    rows = []
    inside_ = nearby = none = manual_count = 0
    for p in area:
        x, y = p["lon"], p["lat"]
        if p["nev"].strip() in manual:                      # manually checked point: the building(s) you gave, with the source "lechner"
            those = manual[p["nev"].strip()]
            if not those:
                none += 1
                p["illesztes"] = None
                continue
            manual_count += 1
            p["illesztes"] = {"osm_tipus": those[0][0], "id": those[0][1], "mod": "kezi"}
            for t, i in those:
                L = "lechner"
                rows += [(t, i, "lechner_nev", p["nev"], L, ""), (t, i, "lechner_epult", p["epult"] or "", L, ""),
                          (t, i, "lechner_ev_kezdet", p["ev_kezdet"] or "", L, ""), (t, i, "lechner_ev_veg", p["ev_veg"] or "", L, ""),
                          (t, i, "lechner_tervezo", p["tervezo"] or "", L, ""), (t, i, "lechner_illesztes", "kezi", L, "")]
                if p["tervezo"]:
                    rows.append((t, i, "tervezo", p["tervezo"], L, p["nev"]))
                if p["ev_veg"] and p["ev_egyertelmu"]:
                    rows.append((t, i, "ev", p["ev_veg"], L, p["epult"] or ""))
            continue
        hit, mode = index.in_(x, y), "belul"
        if hit is None:
            hit = index.nearby(x, y, NEARBY_METER)
            mode = "kozeli" if hit else None
        if hit is None:
            none += 1
            p["illesztes"] = None
            continue
        inside_ += mode == "belul"
        nearby += mode == "kozeli"
        t, i = building_key(hit["properties"])
        p["illesztes"] = {"osm_tipus": t, "id": i, "mod": mode}
        L = "lechner"
        rows += [(t, i, "lechner_nev", p["nev"], L, ""),
                  (t, i, "lechner_epult", p["epult"] or "", L, ""),
                  (t, i, "lechner_ev_kezdet", p["ev_kezdet"] or "", L, ""),
                  (t, i, "lechner_ev_veg", p["ev_veg"] or "", L, ""),
                  (t, i, "lechner_tervezo", p["tervezo"] or "", L, ""),
                  (t, i, "lechner_illesztes", mode, L, "")]
        if p["tervezo"]:
            rows.append((t, i, "tervezo", p["tervezo"], L if mode == "belul" else "lechner_kozeli", p["nev"]))
        # The OSM start_date is typically the year of completion, so we use the end year
        if p["ev_veg"] and p["ev_egyertelmu"]:
            rows.append((t, i, "ev", p["ev_veg"], L if mode == "belul" else "lechner_kozeli", p["epult"] or ""))
    write_facts(OUTPUT, [s for s in rows if s[3] != ""])
    with open(POINTS, "w", encoding="utf-8") as f:
        json.dump(points, f, ensure_ascii=False, indent=1)
    print(f"Épületbe esik: {inside_}, közeli (≤{NEARBY_METER} m): {nearby}, kézzel párosított: {manual_count}, nem párosítható: {none}")
    print(f"Mentve: {OUTPUT}")


main()
