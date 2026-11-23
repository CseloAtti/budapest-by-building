"""Contemporary buildings of Budapest Legenda (budapestlegenda.hu) -> data/tenyek/budapestlegenda.csv

Input:    forras/legenda_kezi_parositas.csv   (the Legenda list and the OSM matching; you fill in the 'osm_azonosito' column)
Optional column: 'kep_url' (the direct address of the Legenda page's image; the card uses it if there is no other image).
Output:   data/tenyek/budapestlegenda.csv     - 'legenda_url', 'legenda_kep', 'ev' and 'tervezo' facts for osszeepit.py (source: 'budapestlegenda')

Run:       py tenyek_legenda.py

Important: the Legenda "year of construction" field is in many places the year of design (or of the award), not of handover: compared with the completion years of the
Építészfórum list it is typically 1-4 years earlier, for the metro stations 10 years. So in the 'ev' priority the source ranks
behind Építészfórum, and we take over only the rows with 'uj_epulet = igen' (renovation/reconstruction/public space is not a construction year).
A fact is made only if 'osm_azonosito' is filled in. Accepted forms: "way 123456", "123456" (way), "relation 123",
the link of the OSM page; several buildings with the '|' sign.
"""
import csv
import re
from pathlib import Path

from kozos import tenyek_irasa

TABLA = "forras/legenda_kezi_parositas.csv"
KEPEK = "forras/legenda_kepek.csv"   # url;epites_eve;tervezo;kep_url - collected from the Legenda pages (the year of construction here is the "Elkészült" (completed) year)
KIMENET = "data/tenyek/budapestlegenda.csv"


def tisztit_tervezo(sz):
    """From the collected text ("Name Architect office X Ltd Year of design ... Address ...") only the designer's name."""
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
        # the link (and the given image) is needed for every matched row, the year/designer only for a new building
        lnk = (r.get("legenda_link") or "").strip()
        uj = kepek.get(lnk, {})
        kep = (r.get("kep_url") or uj.get("kep_url") or "").strip()
        if not (r.get("ev") or "").strip().isdigit() or uj.get("epites_eve", "").strip().isdigit():
            if (uj.get("epites_eve") or "").strip().isdigit():
                r["ev"] = uj["epites_eve"].strip()   # the fresh "Elkészült" (completed) year overrides the old (design) year
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
