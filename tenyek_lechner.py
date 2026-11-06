"""Lechner Tudásközpont pontjai -> tény-tábla (data/tenyek/lechner.csv).
Csak tényeket veszünk át (név, építési idő, tervező); a leírásokat és a fotókat szándékosan nem."""
import html
import json
import re
import xml.etree.ElementTree as ET

from kozos import kulcs, legkozelebbi_csucs_m, pont_poligonban, tenyek_irasa

KML = "data/lechner.kml"
OSM = "data/belvaros_epuletek.geojson"
KIMENET = "data/tenyek/lechner.csv"
PONTOK = "data/lechner_pontok.json"
KOZELI_METER = 15  # ha egy pont nem esik épületbe, ennyi méteren belüli épületet fogadunk el
ns = {"k": "http://www.opengis.net/kml/2.2"}
VAGAS = r"újjáépít|átépít|átalakít|felújít|rekonstrukció|restaurál|bővít|majd|bizonytalan"


def idoszak(szoveg):
    """Az építési időszak kezdő és záró éve, és hogy egyértelmű-e.
    '1875–1884' -> (1875, 1884, True); '1817, majd 1909–1913' -> (1817, 1817, False)."""
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
        kezdet, veg, bizonyos = idoszak(epult)
        pontok.append({"nev": nev, "lat": lat, "lon": lon, "epult": epult,
                       "ev_kezdet": kezdet, "ev_veg": veg, "ev_egyertelmu": bizonyos,
                       "tervezo": tervezo})
    return pontok


def main():
    pontok = kml_beolvas(KML)
    with open(OSM, encoding="utf-8") as f:
        feats = [x for x in json.load(f)["features"] if x["properties"].get("tipus") != "roof"]
    for ft in feats:
        k = ft["geometry"]["coordinates"][0]
        ft["_bb"] = (min(p[0] for p in k), min(p[1] for p in k), max(p[0] for p in k), max(p[1] for p in k))
    lon_min = min(f["_bb"][0] for f in feats); lat_min = min(f["_bb"][1] for f in feats)
    lon_max = max(f["_bb"][2] for f in feats); lat_max = max(f["_bb"][3] for f in feats)
    terulet = [p for p in pontok if lon_min <= p["lon"] <= lon_max and lat_min <= p["lat"] <= lat_max]
    print(f"Pontok a KML-ben: {len(pontok)}, ebből a területen: {len(terulet)}")

    sorok = []
    belul = kozeli = nincs = 0
    for p in terulet:
        x, y = p["lon"], p["lat"]
        talalat, mod = None, None
        for ft in feats:
            b = ft["_bb"]
            if b[0] <= x <= b[2] and b[1] <= y <= b[3] and pont_poligonban(x, y, ft["geometry"]["coordinates"]):
                talalat, mod = ft, "belul"
                break
        if talalat is None:
            tav = KOZELI_METER
            for ft in feats:
                d = legkozelebbi_csucs_m(x, y, ft["geometry"]["coordinates"][0])
                if d < tav:
                    talalat, tav = ft, d
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
        # Az OSM start_date jellemzően a befejezés éve, ezért a záró évet használjuk
        if p["ev_veg"] and p["ev_egyertelmu"]:
            sorok.append((t, i, "ev", p["ev_veg"], L if mod == "belul" else "lechner_kozeli", p["epult"] or ""))
    tenyek_irasa(KIMENET, [s for s in sorok if s[3] != ""])
    with open(PONTOK, "w", encoding="utf-8") as f:
        json.dump(pontok, f, ensure_ascii=False, indent=1)
    print(f"Épületbe esik: {belul}, közeli (≤{KOZELI_METER} m): {kozeli}, nem párosítható: {nincs}")
    print(f"Mentve: {KIMENET}")


main()
