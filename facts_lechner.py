"""Points of the Lechner Knowledge Centre -> fact table (data/tenyek/lechner.csv).
We take over only facts (name, construction time, designer); deliberately not the descriptions and photos."""
import csv
import html
import json
import re
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

from common import kulcs, tenyek_irasa
from area_common import EpuletIndex

KML = "data/lechner.kml"
VAROS = len(sys.argv) > 1 and sys.argv[1] == "varos"      # py facts_lechner.py varos  -> the whole city
OSM = "data/varos/epuletek.geojson" if VAROS else "data/belvaros_epuletek.geojson"
KIMENET = "data/tenyek/lechner.csv"
PONTOK = "data/lechner_pontok.json"
KEZI = "forras/lechner_kezi_parositas.csv"   # manual checking of the near and the unmatched points: you fill in the 'osm_azonosito' column
KOZELI_METER = 15  # if a point does not fall into a building, we accept a building within this many metres
ns = {"k": "http://www.opengis.net/kml/2.2"}
VAGAS = r"újjáépít|átépít|átalakít|felújít|rekonstrukció|restaurál|bővít|majd|bizonytalan"


def idoszak(szoveg):
    """The start and end year of the construction period, and whether it is unambiguous.
    '1875–1884' -> (1875, 1884, True); '1817, majd 1909–1913' ('1817, then 1909–1913') -> (1817, 1817, False)."""
    if not szoveg:
        return None, None, False
    bizonyos = not re.search(r"majd|bizonytalan|körül|as évek|\?|század", szoveg)
    elso_resz = re.split(VAGAS, szoveg, maxsplit=1)[0]
    m = re.search(r"(?<!\d)(1[0-9]{3}|20[0-2][0-9])\s*[–-]\s*(\d{2,4})(?!\d)", elso_resz)
    if m:
        kezdet = int(m.group(1))
        veg_szoveg = m.group(2)
        veg = int(veg_szoveg) if len(veg_szoveg) == 4 else int(m.group(1)[:2] + veg_szoveg)
        if veg < kezdet:
            veg = kezdet
        return kezdet, veg, bizonyos
    evek = [int(x) for x in re.findall(r"(?<!\d)(1[0-9]{3}|20[0-2][0-9])(?!\d)", elso_resz)]
    if not evek:
        return None, None, False
    if len(evek) > 1:
        bizonyos = False
    return min(evek), max(evek), bizonyos


def kml_beolvas(ut):
    gyoker = ET.parse(ut).getroot()
    pontok = []
    for p in gyoker.findall(".//k:Placemark", ns):
        nev = " ".join((p.findtext("k:name", namespaces=ns) or "").split())
        koord = p.findtext("k:Point/k:coordinates", namespaces=ns)
        if not koord:
            continue
        lon, lat = (float(x) for x in koord.strip().split(",")[:2])
        leiras = html.unescape(p.findtext("k:description", namespaces=ns) or "")
        leiras = re.sub(r"<br\s*/?>", "\n", leiras)
        leiras = re.sub(r"<[^>]+>", "", leiras)
        m = re.search(r"Épült:\s*([^\n]*)", leiras)
        epult = m.group(1).split("Tervező:")[0].strip() if m else None
        m = re.search(r"Tervező:\s*([^\n]*)", leiras)
        tervezo = m.group(1).strip() if m else None
        if tervezo in ("–", "-", "—"):          # in the Lechner description this is the sign of "no designer"
            tervezo = None
        kezdet, veg, bizonyos = idoszak(epult)
        pontok.append({"nev": nev, "lat": lat, "lon": lon, "epult": epult,
                       "ev_kezdet": kezdet, "ev_veg": veg, "ev_egyertelmu": bizonyos,
                       "tervezo": tervezo})
    return pontok


def kezi_beolvas():
    """name -> [(osm_tipus, id), ...]  (empty list: 'nincs' = there is no OSM building for this point). Empty cell: the automatic one stays."""
    ki = {}
    if not Path(KEZI).exists():
        return ki
    with open(KEZI, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            ertek = (r.get("osm_azonosito") or "").strip()
            if not ertek:
                continue
            if re.fullmatch(r"nincs|-|–|nem", ertek, flags=re.I):
                ki[r["lechner_nev"].strip()] = []
                continue
            azok = []
            for resz in re.split(r"[|;,\n]+", ertek):
                m = re.search(r"(?:(way|relation|node)[/ :]*)?(\d{3,})", resz.strip(), flags=re.I)
                if m:
                    azok.append(((m.group(1) or "way").lower(), int(m.group(2))))
            if azok:
                ki[r["lechner_nev"].strip()] = azok
    return ki


def main():
    kezi = kezi_beolvas()
    pontok = kml_beolvas(KML)
    with open(OSM, encoding="utf-8") as f:
        feats = [x for x in json.load(f)["features"] if x["properties"].get("tipus") != "roof"]
    index = EpuletIndex(feats)
    del feats
    xs = [p[0] for ft, pl in index.elemek for poli in pl for p in poli[0]]
    ys = [p[1] for ft, pl in index.elemek for poli in pl for p in poli[0]]
    lon_min, lon_max, lat_min, lat_max = min(xs), max(xs), min(ys), max(ys)
    terulet = [p for p in pontok if lon_min <= p["lon"] <= lon_max and lat_min <= p["lat"] <= lat_max]
    print(f"Pontok a KML-ben: {len(pontok)}, ebből a területen: {len(terulet)}")

    sorok = []
    belul = kozeli = nincs = kezi_db = 0
    for p in terulet:
        x, y = p["lon"], p["lat"]
        if p["nev"].strip() in kezi:                      # manually checked point: the building(s) you gave, with the source "lechner"
            azok = kezi[p["nev"].strip()]
            if not azok:
                nincs += 1
                p["illesztes"] = None
                continue
            kezi_db += 1
            p["illesztes"] = {"osm_tipus": azok[0][0], "id": azok[0][1], "mod": "kezi"}
            for t, i in azok:
                L = "lechner"
                sorok += [(t, i, "lechner_nev", p["nev"], L, ""), (t, i, "lechner_epult", p["epult"] or "", L, ""),
                          (t, i, "lechner_ev_kezdet", p["ev_kezdet"] or "", L, ""), (t, i, "lechner_ev_veg", p["ev_veg"] or "", L, ""),
                          (t, i, "lechner_tervezo", p["tervezo"] or "", L, ""), (t, i, "lechner_illesztes", "kezi", L, "")]
                if p["tervezo"]:
                    sorok.append((t, i, "tervezo", p["tervezo"], L, p["nev"]))
                if p["ev_veg"] and p["ev_egyertelmu"]:
                    sorok.append((t, i, "ev", p["ev_veg"], L, p["epult"] or ""))
            continue
        talalat, mod = index.benne(x, y), "belul"
        if talalat is None:
            talalat = index.kozeli(x, y, KOZELI_METER)
            mod = "kozeli" if talalat else None
        if talalat is None:
            nincs += 1
            p["illesztes"] = None
            continue
        belul += mod == "belul"
        kozeli += mod == "kozeli"
        t, i = kulcs(talalat["properties"])
        p["illesztes"] = {"osm_tipus": t, "id": i, "mod": mod}
        L = "lechner"
        sorok += [(t, i, "lechner_nev", p["nev"], L, ""),
                  (t, i, "lechner_epult", p["epult"] or "", L, ""),
                  (t, i, "lechner_ev_kezdet", p["ev_kezdet"] or "", L, ""),
                  (t, i, "lechner_ev_veg", p["ev_veg"] or "", L, ""),
                  (t, i, "lechner_tervezo", p["tervezo"] or "", L, ""),
                  (t, i, "lechner_illesztes", mod, L, "")]
        if p["tervezo"]:
            sorok.append((t, i, "tervezo", p["tervezo"], L if mod == "belul" else "lechner_kozeli", p["nev"]))
        # The OSM start_date is typically the year of completion, so we use the end year
        if p["ev_veg"] and p["ev_egyertelmu"]:
            sorok.append((t, i, "ev", p["ev_veg"], L if mod == "belul" else "lechner_kozeli", p["epult"] or ""))
    tenyek_irasa(KIMENET, [s for s in sorok if s[3] != ""])
    with open(PONTOK, "w", encoding="utf-8") as f:
        json.dump(pontok, f, ensure_ascii=False, indent=1)
    print(f"Épületbe esik: {belul}, közeli (≤{KOZELI_METER} m): {kozeli}, kézzel párosított: {kezi_db}, nem párosítható: {nincs}")
    print(f"Mentve: {KIMENET}")


main()
