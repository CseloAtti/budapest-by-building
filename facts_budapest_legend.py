"""Contemporary buildings of Budapest Legenda (budapestlegenda.hu) -> data/tenyek/budapestlegenda.csv

Input:    forras/legenda_kezi_parositas.csv   (the Legenda list and the OSM matching; you fill in the 'osm_azonosito' column)
Optional column: 'kep_url' (the direct address of the Legenda page's image; the card uses it if there is no other image).
Output:   data/tenyek/budapestlegenda.csv     - 'legenda_url', 'legenda_kep', 'ev' and 'tervezo' facts for assemble.py (source: 'budapestlegenda')

Run:       py facts_budapest_legend.py

Important: the Legenda "year of construction" field is in many places the year of design (or of the award), not of handover: compared with the completion years of the
Építészfórum list it is typically 1-4 years earlier, for the metro stations 10 years. So in the 'ev' priority the source ranks
behind Építészfórum, and we take over only the rows with 'uj_epulet = igen' (renovation/reconstruction/public space is not a construction year).
A fact is made only if 'osm_azonosito' is filled in. Accepted forms: "way 123456", "123456" (way), "relation 123",
the link of the OSM page; several buildings with the '|' sign.
"""
import csv
import re
from pathlib import Path

from common import write_facts

TABLE = "forras/legenda_kezi_parositas.csv"
IMAGES = "forras/legenda_kepek.csv"   # url;epites_eve;tervezo;kep_url - collected from the Legenda pages (the year of construction here is the "Elkészült" (completed) year)
OUTPUT = "data/tenyek/budapestlegenda.csv"


def clean_designer(sz):
    """From the collected text ("Name Architect office X Ltd Year of design ... Address ...") only the designer's name."""
    return re.split(r"\s+(?:Építész iroda|Tervezés éve|Elkészült|Cím)\b", (sz or "").strip())[0].strip()


def main():
    done = set()
    images = {}
    if Path(IMAGES).exists():
        for k in csv.DictReader(open(IMAGES, encoding="utf-8-sig"), delimiter=";"):
            images[(k.get("url") or "").strip()] = k
    rows = list(csv.DictReader(open(TABLE, encoding="utf-8-sig"), delimiter=";"))
    filled = missing = skipped = 0
    for r in rows:
        those = []
        for part in re.split(r"[|;,\n]+", r.get("osm_azonosito") or ""):
            m = re.search(r"(?:(way|relation|node)[/ :]*)?(\d{3,})", part.strip(), flags=re.I)
            if m:
                those.append(((m.group(1) or "way").lower(), int(m.group(2))))
        if not those:
            if (r.get("uj_epulet") or "").strip().lower() == "igen" and not (r.get("epforum_egyezes") or "").strip():
                missing += 1
            continue
        # the link (and the given image) is needed for every matched row, the year/designer only for a new building
        lnk = (r.get("legenda_link") or "").strip()
        new = images.get(lnk, {})
        image = (r.get("kep_url") or new.get("kep_url") or "").strip()
        if not (r.get("ev") or "").strip().isdigit() or new.get("epites_eve", "").strip().isdigit():
            if (new.get("epites_eve") or "").strip().isdigit():
                r["ev"] = new["epites_eve"].strip()   # the fresh "Elkészült" (completed) year overrides the old (design) year
        if not (r.get("tervezo") or "").strip() and clean_designer(new.get("tervezo")):
            r["tervezo"] = clean_designer(new.get("tervezo"))
        for t, i in those:
            if re.match(r"https://budapestlegenda\.hu/", lnk):
                done.add((t, i, "legenda_url", lnk, "budapestlegenda", "Budapest Legenda: " + r["nev"]))
                if re.match(r"https://[a-z0-9.-]*budapestlegenda\.hu/", image):
                    done.add((t, i, "legenda_kep", image, "budapestlegenda", "Budapest Legenda: " + r["nev"]))
        if (r.get("uj_epulet") or "").strip().lower() != "igen":
            skipped += 1
            continue
        filled += 1
        remark = f"Budapest Legenda: {r['nev']} {r['legenda_link']} (a Legenda-oldal szerinti elkészülés éve)"
        for t, i in those:
            if (r.get("ev") or "").strip().isdigit():
                done.add((t, i, "ev", int(r["ev"]), "budapestlegenda", remark))
            if (r.get("tervezo") or "").strip():
                done.add((t, i, "tervezo", r["tervezo"].strip(), "budapestlegenda", remark))
    write_facts(OUTPUT, sorted(done, key=lambda s: (s[0], s[1], s[2])))
    print(f"Legenda-sorok: {len(rows)}; OSM-hez kötve: {filled}; még kitöltendő új épület: {missing}; "
          f"felújítás miatt kihagyva: {skipped}")
    print(f"Tények: {len(done)} sor -> {OUTPUT}")


if __name__ == "__main__":
    main()
