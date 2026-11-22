"""Budapest Legenda (budapestlegenda.hu) kortárs épületei -> data/tenyek/budapestlegenda.csv

Bemenet:  forras/legenda_kezi_parositas.csv   (a Legenda-lista és az OSM-párosítás; az 'osm_azonosito' oszlopot te töltöd ki)
Opcionális oszlop: 'kep_url' (a Legenda-oldal képének közvetlen címe; a kártya ezt használja, ha nincs más kép).
Kimenet:  data/tenyek/budapestlegenda.csv     - 'legenda_url', 'legenda_kep', 'ev' és 'tervezo' tények az osszeepit.py-hoz (forrás: 'budapestlegenda')

Futtatás:  py tenyek_legenda.py

Fontos: a Legenda "építés éve" mezője sok helyen a tervezés (vagy a díj) éve, nem az átadásé: az Építészfórum-lista
elkészülési éveinél jellemzően 1-4 évvel korábbi, a metróállomásoknál 10 évvel. Ezért a forrás az 'ev' prioritásban az
Építészfórum mögött áll, és csak az 'uj_epulet = igen' sorokat vesszük át (felújítás/rekonstrukció/köztér nem építési év).
Csak akkor készül tény, ha az 'osm_azonosito' ki van töltve. Elfogadott alakok: "way 123456", "123456" (way), "relation 123",
az OSM-oldal linkje; több épület '|' jellel.
"""
import csv
import re
from pathlib import Path

from kozos import tenyek_irasa

TABLA = "forras/legenda_kezi_parositas.csv"
KEPEK = "forras/legenda_kepek.csv"   # url;epites_eve;tervezo;kep_url - a Legenda-oldalakról kigyűjtve (az építés éve itt az "Elkészült" év)
KIMENET = "data/tenyek/budapestlegenda.csv"


def tisztit_tervezo(sz):
    """A kigyűjtött szövegből ("Név Építész iroda X Kft Tervezés éve ... Cím ...") csak a tervező neve."""
    return re.split(r"\s+(?:Építész iroda|Tervezés éve|Elkészült|Cím)\b", (sz or "").strip())[0].strip()


def main():
    kesz = set()
    kepek = {}
    if Path(KEPEK).exists():
        for k in csv.DictReader(open(KEPEK, encoding="utf-8-sig"), delimiter=";"):
            kepek[(k.get("url") or "").strip()] = k
    sorok = list(csv.DictReader(open(TABLA, encoding="utf-8-sig"), delimiter=";"))
    kitoltott = hianyzo = kihagyott = 0
    for r in sorok:
        azok = []
        for resz in re.split(r"[|;,\n]+", r.get("osm_azonosito") or ""):
            m = re.search(r"(?:(way|relation|node)[/ :]*)?(\d{3,})", resz.strip(), flags=re.I)
            if m:
                azok.append(((m.group(1) or "way").lower(), int(m.group(2))))
        if not azok:
            if (r.get("uj_epulet") or "").strip().lower() == "igen" and not (r.get("epforum_egyezes") or "").strip():
                hianyzo += 1
            continue
        # a link (és a megadott kép) minden párosított sorhoz kell, az év/tervező csak új épületnél
        lnk = (r.get("legenda_link") or "").strip()
        uj = kepek.get(lnk, {})
        kep = (r.get("kep_url") or uj.get("kep_url") or "").strip()
        if not (r.get("ev") or "").strip().isdigit() or uj.get("epites_eve", "").strip().isdigit():
            if (uj.get("epites_eve") or "").strip().isdigit():
                r["ev"] = uj["epites_eve"].strip()   # a friss, "Elkészült" év felülírja a régi (tervezési) évet
        if not (r.get("tervezo") or "").strip() and tisztit_tervezo(uj.get("tervezo")):
            r["tervezo"] = tisztit_tervezo(uj.get("tervezo"))
        for t, i in azok:
            if re.match(r"https://budapestlegenda\.hu/", lnk):
                kesz.add((t, i, "legenda_url", lnk, "budapestlegenda", "Budapest Legenda: " + r["nev"]))
                if re.match(r"https://[a-z0-9.-]*budapestlegenda\.hu/", kep):
                    kesz.add((t, i, "legenda_kep", kep, "budapestlegenda", "Budapest Legenda: " + r["nev"]))
        if (r.get("uj_epulet") or "").strip().lower() != "igen":
            kihagyott += 1
            continue
        kitoltott += 1
        megj = f"Budapest Legenda: {r['nev']} {r['legenda_link']} (a Legenda-oldal szerinti elkészülés éve)"
        for t, i in azok:
            if (r.get("ev") or "").strip().isdigit():
                kesz.add((t, i, "ev", int(r["ev"]), "budapestlegenda", megj))
            if (r.get("tervezo") or "").strip():
                kesz.add((t, i, "tervezo", r["tervezo"].strip(), "budapestlegenda", megj))
    tenyek_irasa(KIMENET, sorted(kesz, key=lambda s: (s[0], s[1], s[2])))
    print(f"Legenda-sorok: {len(sorok)}; OSM-hez kötve: {kitoltott}; még kitöltendő új épület: {hianyzo}; "
          f"felújítás miatt kihagyva: {kihagyott}")
    print(f"Tények: {len(kesz)} sor -> {KIMENET}")


if __name__ == "__main__":
    main()
