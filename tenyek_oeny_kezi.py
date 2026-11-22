"""Kézi párosítás az E-Örökség (OENY) műemlékeihez, amelyeket a tenyek_oeny.py nem tudott OSM-épülethez kötni.

Bemenet:  data/oeny_nem_parositott.csv         (a tenyek_oeny.py készíti: ami nem párosult)
          forras/oeny_kezi_parositas.csv       (EZT töltöd ki: az 'osm_azonosito' oszlopba írd az OSM-épület azonosítóját)
          data/oeny_epuletek.json, data/muemlek_jegyzek.json   (az OENY-kártyák és a műemlékjegyzék)
Kimenet:  data/tenyek/oeny_kezi.csv            - a kézzel párosított műemlékek tényei az osszeepit.py-hoz

Futtatás:  py tenyek_oeny_kezi.py       (utána a szokásos: py osszeepit.py varos ... vagy zona_frissit.bat)

A táblázat első futáskor jön létre. Később a script csak a még nem szereplő (új) nem párosított bejegyzéseket fűzi hozzá a végére;
ha nincs új sor, a fájlhoz nem ér hozzá. A formázás (feltételes formázás, rejtett oszlopok) CSV-ben amúgy sem tárolódik, ahhoz az Excel-fájlt (.xlsx) mentsd külön. A 'terbeli_biztonsag' és 'terbeli_javaslat' oszlopot a koordináták (ArcGIS) alapján töltöttük ki: ahol a biztonság 'magas', az
osm_azonosito már ki van töltve (ellenőrizd), a többinél a javaslatok közül másold be a megfelelőt.
Az 'osm_azonosito' elfogadott alakjai: "way 123456", "123456" (way), "relation 123",
az OSM-oldal linkje; több épület '|' jellel elválasztva (pl. egy műemlék több épületből áll).
Ha az épületet nem lehet vagy nem kell párosítani, írd a 'megjegyzes' oszlopba (pl. "nincs már meg"), az osm_azonosito maradjon üres.
Átvett tények: műemléki törzsszám, védettség (a jegyzék szerint; ha nincs benne: M, a "területe" nevűeknél MJT),
az OENY-adatlap azonosítója, a jegyzékből az építés éve, tervezője, stílusa, szintszáma, valamint az OENY-leírásból kiolvasott év/tervező.
"""
import collections
import csv
import json
import re
import urllib.parse
from pathlib import Path

from kozos import tenyek_irasa

NEM_PAROSITOTT = "data/oeny_nem_parositott.csv"
TABLA = "forras/oeny_kezi_parositas.csv"
KARTYAK = "data/oeny_epuletek.json"
JEGYZEK = "data/muemlek_jegyzek.json"
KIMENET = "data/tenyek/oeny_kezi.csv"
OSZLOPOK = ["torzsszam", "megnevezes", "cim", "miert_nem_parosult", "kiolvasott_tervezo", "kiolvasott_ev",
            "lehetseges_epuletek_a_tobbi_cim_alapjan", "oeny_oldal", "osm_kereses", "arcgis_lat", "arcgis_lon",
            "terbeli_biztonsag", "terbeli_javaslat", "osm_azonosito", "megjegyzes"]


def olvas(ut):
    with open(ut, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def oeny_azonositok():
    try:
        return {int(k["torzsszam"]): k.get("azonositok", []) for k in json.loads(Path(KARTYAK).read_text(encoding="utf-8"))}
    except (FileNotFoundError, ValueError, KeyError):
        return {}


def tabla_szinkron():
    """Létrehozza vagy bővíti a kézi táblázatot a nem párosított bejegyzésekkel (a kitöltött sorokat nem bántja)."""
    if not Path(NEM_PAROSITOTT).exists():
        raise SystemExit(f"Hiányzik: {NEM_PAROSITOTT}. Előbb futtasd: py tenyek_oeny.py varos")
    # Egy törzsszámhoz több sor is tartozhat. Új sort csak akkor fűzünk hozzá, ha a táblázatban kevesebb sor van az adott
    # törzsszámhoz, mint a nem párosított listában (a címet te javíthatod a táblázatban, ez nem számít újnak).
    sorok = olvas(TABLA) if Path(TABLA).exists() else []
    van = collections.Counter(r["torzsszam"].strip() for r in sorok)
    azon = oeny_azonositok()
    uj = 0
    for r in olvas(NEM_PAROSITOTT):
        tsz = r["torzsszam"].strip()
        if van[tsz] > 0:
            van[tsz] -= 1
            continue
        a = azon.get(int(tsz), []) if tsz.isdigit() else []
        cim = r["cim"].split(",")[0].strip()
        sorok.append({
            **{k: r.get(k, "") for k in OSZLOPOK[:7]}, "arcgis_lat": "", "arcgis_lon": "", "terbeli_biztonsag": "", "terbeli_javaslat": "",
            "oeny_oldal": f"https://www.oeny.hu/oeny/eorok/public/monument/{a[0]}" if a else "",
            "osm_kereses": "https://www.openstreetmap.org/search?query=" + urllib.parse.quote(f"{cim}, Budapest"),
            "osm_azonosito": "", "megjegyzes": "",
        })
        uj += 1
    if not uj:
        return sorok, 0            # nincs új sor: a táblázat fájlját NEM írjuk át (megmarad minden, amit Excelben beállítottál)
    if Path(TABLA).exists():
        # csak a végére fűzzük az új sorokat, a meglévő sorokhoz, sorrendhez és oszlopokhoz nem nyúlunk
        with open(TABLA, "rb") as f:
            adat = f.read()
        with open(TABLA, encoding="utf-8-sig", newline="") as f:
            fej = next(csv.reader(f, delimiter=";"))
        sorvege = "\r\n" if b"\r\n" in adat else "\n"
        with open(TABLA, "a", encoding="utf-8", newline="") as f:
            if not adat.endswith((b"\n", b"\r")):
                f.write(sorvege)
            w = csv.DictWriter(f, fieldnames=fej, delimiter=";", extrasaction="ignore", lineterminator=sorvege)
            w.writerows(sorok[-uj:])
    else:
        Path(TABLA).parent.mkdir(parents=True, exist_ok=True)
        with open(TABLA, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=OSZLOPOK, delimiter=";", extrasaction="ignore")
            w.writeheader()
            w.writerows(sorok)
    return sorok, uj


def main():
    sorok, uj = tabla_szinkron()
    konyv = {}
    try:
        for b in json.loads(Path(JEGYZEK).read_text(encoding="utf-8"))["bejegyzesek"]:
            konyv[int(b["torzsszam"])] = b
    except (FileNotFoundError, ValueError, KeyError):
        pass
    azon = oeny_azonositok()
    kesz = set()
    kitoltott = hianyzo = 0
    for r in sorok:
        osm = []
        for resz in re.split(r"[|;,\n]+", r.get("osm_azonosito") or ""):
            m = re.search(r"(?:(way|relation|node)[/ :]*)?(\d{3,})", resz.strip(), flags=re.I)
            if m:
                osm.append(((m.group(1) or "way").lower(), int(m.group(2))))
        if not osm:
            hianyzo += 1
            continue
        kitoltott += 1
        tsz = int(r["torzsszam"])
        b = konyv.get(tsz)
        megj = f"E-Örökség, törzsszám {tsz}, kézi párosítás"
        sorok_ki = [("muemlek_torzsszam", tsz, "oeny")]
        for az in azon.get(tsz, [])[:3]:
            sorok_ki.append(("oeny_azonosito", az, "oeny"))
        if b:
            sorok_ki += [("vedettseg", b["vedettseg"], "muemlek"), ("muemlek_hrsz", b["hrsz"], "muemlek"), ("stilus", b["stilus"], "muemlek")]
            if b["evek"]:
                sorok_ki.append(("ev", b["evek"][0][1], "muemlek"))
            if b["tervezo"]:
                sorok_ki.append(("tervezo", b["tervezo"], "muemlek"))
            if b["emelet"] is not None:
                sorok_ki.append(("szintek", b["emelet"] + 1, "muemlek"))
        else:
            sorok_ki.append(("vedettseg", "MJT" if "területe" in r["megnevezes"].lower() else "M", "oeny"))
        mev = re.match(r"\s*(\d{4})(?:\.0)?\s*$", r.get("kiolvasott_ev") or "")   # az Excel "1934.0"-ra alakíthatja
        if mev:
            sorok_ki.append(("ev", int(mev.group(1)), "oeny"))
        if (r.get("kiolvasott_tervezo") or "").strip():
            sorok_ki.append(("tervezo", r["kiolvasott_tervezo"].strip(), "oeny"))
        for t, i in osm:
            for mezo, ertek, forras in sorok_ki:
                if ertek not in (None, ""):
                    kesz.add((t, i, mezo, ertek, forras, megj))
    tenyek_irasa(KIMENET, sorted(kesz, key=lambda s: (s[0], s[1], s[2], str(s[3]))))
    print(f"Táblázat: {TABLA} ({len(sorok)} sor, ebből új: {uj})")
    print(f"OSM-hez kötve: {kitoltott}; még kitöltendő: {hianyzo}")
    print(f"Tények: {len(kesz)} sor -> {KIMENET}")


if __name__ == "__main__":
    main()
