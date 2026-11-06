import html
import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

KML = "data/lechner.kml"
BEMENET = "data/belvaros_epuletek.geojson"
KIMENET = "data/belvaros_epuletek_lechner.geojson"
PONTOK = "data/lechner_pontok.json"
KOZELI_METER = 15  # ha egy pont nem esik épületbe, ennyi méteren belüli épületet fogadunk el

ns = {"k": "http://www.opengis.net/kml/2.2"}


VAGAS = r"újjáépít|átépít|átalakít|felújít|rekonstrukció|restaurál|bővít|majd|bizonytalan"


def idoszak(szoveg):
    """Az építési időszak kezdő és záró éve, és hogy egyértelmű-e.
    '1875–1884' -> (1875, 1884, True); '1845–46' -> (1845, 1846, True);
    '1817, majd 1909–1913' -> (1817, 1817, False): a későbbi átépítést nem vesszük figyelembe."""
    if not szoveg:
        return None, None, False
    # a későbbi felújítás/átépítés említése nem teszi bizonytalanná az eredeti építést
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
    """Csak tényeket veszünk át: név, hely, építési idő, tervező.
    A leírásokat és a fotókat szándékosan NEM (szerzői jog)."""
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


def pont_gyuruben(x, y, gyuru):
    bent = False
    for (x1, y1), (x2, y2) in zip(gyuru, gyuru[1:]):
        if (y1 > y) != (y2 > y):
            if x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                bent = not bent
    return bent


def pont_poligonban(x, y, gyuruk):
    """gyuruk[0] a külső körvonal, a többi udvar (lyuk)."""
    if not pont_gyuruben(x, y, gyuruk[0]):
        return False
    return not any(pont_gyuruben(x, y, lyuk) for lyuk in gyuruk[1:])


def legkozelebbi_csucs_m(x, y, gyuru):
    """Legközelebbi csúcs távolsága méterben (közelítés Budapest szélességén)."""
    kx = 111320 * math.cos(math.radians(y))
    ky = 110540
    return min(math.hypot((px - x) * kx, (py - y) * ky) for px, py in gyuru)


def main():
    pontok = kml_beolvas(KML)
    print(f"Pontok a KML-ben: {len(pontok)}")

    with open(BEMENET, encoding="utf-8") as f:
        gj = json.load(f)
    feats = gj["features"]
    for ft in feats:
        k = ft["geometry"]["coordinates"][0]
        ft["_bb"] = (min(p[0] for p in k), min(p[1] for p in k),
                     max(p[0] for p in k), max(p[1] for p in k))
    lon_min = min(ft["_bb"][0] for ft in feats)
    lat_min = min(ft["_bb"][1] for ft in feats)
    lon_max = max(ft["_bb"][2] for ft in feats)
    lat_max = max(ft["_bb"][3] for ft in feats)

    terulet = [p for p in pontok
               if lon_min <= p["lon"] <= lon_max and lat_min <= p["lat"] <= lat_max]
    print(f"Ebből a letöltött területen belül: {len(terulet)}")

    belul = kozeli = nincs = uj_ev = egyezik = elter = bizonytalan = 0
    for p in terulet:
        x, y = p["lon"], p["lat"]
        talalat, mod = None, None
        for ft in feats:
            b = ft["_bb"]
            if b[0] <= x <= b[2] and b[1] <= y <= b[3]:
                if pont_poligonban(x, y, ft["geometry"]["coordinates"]):
                    talalat, mod = ft, "belul"
                    break
        if talalat is None:
            legjobb, tav = None, KOZELI_METER
            for ft in feats:
                d = legkozelebbi_csucs_m(x, y, ft["geometry"]["coordinates"][0])
                if d < tav:
                    legjobb, tav = ft, d
            if legjobb:
                talalat, mod = legjobb, "kozeli"
        if talalat is None:
            nincs += 1
            p["illesztes"] = None
            continue
        if mod == "belul":
            belul += 1
        else:
            kozeli += 1
        pr = talalat["properties"]
        pr["lechner_nev"] = p["nev"]
        pr["lechner_epult"] = p["epult"]
        pr["lechner_ev_kezdet"] = p["ev_kezdet"]
        pr["lechner_ev_veg"] = p["ev_veg"]
        pr["lechner_tervezo"] = p["tervezo"]
        pr["lechner_illesztes"] = mod
        p["illesztes"] = {"osm_tipus": pr.get("osm_tipus", "way"), "id": pr["id"], "mod": mod}
        if not p["ev_veg"]:
            continue
        # Az OSM start_date jellemzően a befejezés éve, ezért a záró évet használjuk
        if not p["ev_egyertelmu"]:
            bizonytalan += 1
        elif not pr.get("ev"):
            pr["ev"] = p["ev_veg"]
            pr["ev_forras"] = "lechner" if mod == "belul" else "lechner_kozeli"
            uj_ev += 1
        elif p["ev_kezdet"] - 2 <= pr["ev"] <= p["ev_veg"] + 2:
            egyezik += 1
        else:
            elter += 1
            tartomany = f"{p['ev_kezdet']}–{p['ev_veg']}" if p["ev_kezdet"] != p["ev_veg"] else str(p["ev_kezdet"])
            print(f"  Eltérés: {p['nev'][:45]} | OSM: {pr['ev']} | Lechner: {tartomany} | {mod}")

    for ft in feats:
        ft.pop("_bb", None)

    Path("data").mkdir(exist_ok=True)
    with open(KIMENET, "w", encoding="utf-8") as f:
        json.dump(gj, f, ensure_ascii=False)
    with open(PONTOK, "w", encoding="utf-8") as f:
        json.dump(pontok, f, ensure_ascii=False, indent=1)

    print(f"\nÉpületbe esik: {belul}, közeli (≤{KOZELI_METER} m): {kozeli}, nem párosítható: {nincs}")
    print(f"Új építési év az épületeken: {uj_ev}")
    print(f"Az OSM-évvel összefér (±2 év a Lechner-időszakkal): {egyezik}, tényleg eltér: {elter}")
    print(f"Bizonytalan Lechner-adat (átépítés, 'körül', évszázad...), nem írtuk be: {bizonytalan}")
    print(f"Mentve: {KIMENET} és {PONTOK}")


main()