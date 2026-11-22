"""A magyar Wikipedia témalistáinak (iskolák, kórházak, katonai épületek, vásárcsarnokok, egyetemek, vasúti épületek ...) letöltése.

Kimenet:  data/wikipedia_lista/sorok_tema.csv   (ugyanaz a felépítés, mint az utcalistáké: lap;utca;kerulet;szakasz;sor;szam;nev;ev;tervezo;stilus;megjegyzes)
A cím oszlopot utcára és házszámra bontja; ami nem budapesti vagy nincs házszáma, az kimarad. Ha egy sorban több cím van, annyi sor lesz.
Futtatás:  py tenyek_wikipedia_temalista_letolt.py    (a tenyek_wikipedia_lista_letolt.py-val azonos mappában; a letöltések a cache-ben maradnak)
Utána:     py tenyek_wikipedia_lista.py varos        (az utcalistákat és a témalistákat együtt párosítja)
"""
import csv
import re
from pathlib import Path

import tenyek_wikipedia_lista_letolt as L

KIMENET = L.MAPPA / "sorok_tema.csv"
LAPOK = [
    "Budapest 1945 előtti áruházépületeinek listája", "Budapesti általános iskolák listája", "Budapesti középiskolák listája",
    "Budapesti kórházak listája", "Budapesti katonai épületek listája", "Nevezetes budapesti postaépületek listája",
    "Magyarországi vásárcsarnokok listája", "A Budapesti Műszaki és Gazdaságtudományi Egyetem épületeinek listája",
    "Az Eötvös Loránd Tudományegyetem épületeinek listája", "Budapesti felsőoktatási intézmények listája",
    "„Udvar” elnevezésű budapesti épületek listája", "Budapesti villamoskocsiszínek listája",
    "Eredeti funkciójukban nem működő budapesti iskolaépületek listája", "Bárczy István kislakás- és iskolaépítési programja",
    "Liber Endre kislakásépítési programja", "Budapesti vasúti épületek és épületegyüttesek listája",
    "Budapesti tömegközlekedési épületek és épületegyüttesek listája",
]
# a lapok nagy része csak budapesti épületeket tartalmaz; a vásárcsarnokok listája országos, ott a 'Budapest' szót keressük a címben
CSAK_BUDAPEST = {"Magyarországi vásárcsarnokok listája"}


def oszlopok(fejlec):
    t = {}
    for i, c in enumerate(fejlec):
        k = c.lower().strip()
        if k.startswith(("cím", "elhelyezkedés", "mai cím")) and "cim" not in t:
            t["cim"] = i
        elif k.startswith("kerület") and "ker" not in t:
            t["ker"] = i
        elif k.startswith(("épületnév", "név")) and "nev" not in t:
            t["nev"] = i
        elif k.startswith("állomás") and "allomas" not in t:
            t["allomas"] = i
        elif k.startswith(("építés", "építési", "létesítés éve", "alapítási")) and "ev" not in t:
            t["ev"] = i
        elif k.startswith(("tervező", "építész")) and "tervezo" not in t:
            t["tervezo"] = i
            t["tervezo_ev"] = "építési" in k           # 'Tervező, építési idő' összevont oszlop (kórházak)
        elif k.startswith("stílus") and "stilus" not in t:
            t["stilus"] = i
        elif k.startswith("megjegyzés") and "megj" not in t:
            t["megj"] = i
    return t


def cimek(cella):
    """[(kerület|'', utca, házszám)] a szabad szövegű címből."""
    ki = []
    for resz in re.split(r";|\sés\s|\n", cella or ""):
        resz = re.sub(r"\(.*?\)", "", resz).strip(" ,.")
        ker = ""
        m = re.search(r"\b([IVX]+)\.\s*ker(?:ület)?\.?,?", resz)
        if m:
            ker = str(L.ROMAI.get(m.group(1), ""))
            resz = (resz[:m.start()] + resz[m.end():]).strip(" ,")
        resz = re.sub(r"^\d{4}\s+", "", resz)
        resz = re.sub(r"^Budapest\s*,?\s*", "", resz).strip(" ,")
        resz = re.sub(r",?\s*\d{4}$", "", resz).strip(" ,")
        m = re.match(r"^(.*?[^\d\s,/])\s+(\d.*)$", resz)
        if m:
            ki.append((ker, m.group(1).strip(" ,"), m.group(2).strip()))
    return ki


def main():
    L.MAPPA.mkdir(parents=True, exist_ok=True)
    ossz = 0
    with open(KIMENET, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(L.FEJLEC)
        for cim in LAPOK:
            try:
                h = L.letolt(cim)
            except Exception as e:
                print(f"HIBA: {cim}: {e}")
                continue
            sorszam, db = 0, 0
            for szakasz, sorok in L.tablak(h):
                t = {}
                for fejlec, cellak in sorok:
                    if fejlec:
                        t = oszlopok(cellak)
                        continue
                    if "cim" not in t:
                        continue
                    sorszam += 1
                    g = lambda k: cellak[t[k]] if k in t and t[k] < len(cellak) else ""
                    nev = g("nev") or g("allomas")
                    ev, tervezo = g("ev"), g("tervezo")
                    if t.get("tervezo_ev"):                      # 'Kiss István, 1903'
                        m = re.match(r"^(.*?)[,;]?\s*((?:1[0-9]|20)\d\d(?:\s*[-–−]\s*\d{4})?)\s*$", tervezo)
                        if m:
                            tervezo, ev = m.group(1).strip(" ,;"), m.group(2)
                    if cim in CSAK_BUDAPEST and "Budapest" not in g("cim"):
                        continue
                    for ker, utca, szam in cimek(g("cim")):
                        ker = ker or (str(L.ROMAI.get(g("ker").strip(" ."), "")) if g("ker") else "")
                        w.writerow([cim, utca, ker, szakasz, sorszam, szam, nev, ev, tervezo, g("stilus"), g("megj")])
                        db += 1
            ossz += db
            print(f"{cim}: {db} sor")
    print(f"Összesen {ossz} sor -> {KIMENET}")


if __name__ == "__main__":
    main()
