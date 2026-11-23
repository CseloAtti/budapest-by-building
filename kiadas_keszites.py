"""A nyilvános weboldal csomagja -> kiadas/ mappa (ezt kell feltölteni a Cloudflare Pagesre).
Futtatás (a projekt mappájában):   py kiadas_keszites.py

Mit csinál?
  1. Összeállítja a megjelenítőhöz SZÜKSÉGES fájlokat (szerkesztő, fejlesztői adatok és a nagy forrásfájlok nélkül).
  2. Az epuletek.json-t kisebb darabokra bontja (a Cloudflare Pages egy fájlra legfeljebb 25 MiB-ot enged), és elhagyja
     belőle az alapértelmezett "osm_tipus": "way" mezőt (a megjelenítő hiányzó mezőnél úgyis 'way'-t vesz).
     A .bin fájlokat (tiles.bin, terrain.bin) gzip-pel tömöríti: a Cloudflare ezeket magától nem tömöríti, a JSON-t igen.
     A megjelenítő (app.js, binarisBetolt) a tömörített fájlt felismeri és kibontja; a fájlnév nem változik.
  3. A KIADÁSI MÁSOLATBAN (az eredeti terkep3d/app.js érintetlen marad) átírja:
       - a betöltést, hogy a darabolt adatfájlokat olvassa,
       - a szerkesztő bekapcsolását (a nyilvános oldalon nincs szerkesztő).
  4. Ellenőrzi a méretkorlátokat, és kiírja a kiadás méretét.
Csak a Python alap könyvtárát használja. A kiadas/ mappa minden futtatáskor újra létrejön (a régi tartalma törlődik)."""
import gzip
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import felfedezo_keszites

GYOKER = Path(__file__).resolve().parent
FORRAS = GYOKER / "terkep3d"
KI = GYOKER / "kiadas"
MARKER = ".kiadas_mappa"                   # ezzel ismerjük fel, hogy a mappát mi hoztuk létre (csak ilyet törlünk)
LIMIT = 25 * 1024 * 1024                    # Cloudflare Pages: egy fájl legfeljebb 25 MiB
DARAB_CEL = 15 * 1024 * 1024                # egy adatdarab célmérete (bőven a korlát alatt)
FAJL_LIMIT = 20000

# a megjelenítőhöz szükséges fájlok és mappák (a terkep3d mappához képest)
FAJLOK = ["index.html", "app.js", "styles.css", "worker.js", "hidak.js", "adatlapok.json", "epitesz.json", "epitesz_dijak.json",
          "favicon.svg", "epitesz_elete.json", "epitesz_korok_kezi.json", "epitesz_kizart.json", "kerulethatarok.json", "zonak.json",
          "LICENSE-amsterdam.txt", "LICENSE-threejs.txt", "megosztas_hu.png", "megosztas_en.png"]
MAPPAK = ["vendor", "arculat"]
KEPEK_KIT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"}
ADAT = "data_varos"


EN_OG = {
    "title": "Age of Budapest's buildings - interactive 3D map",
    "desc": "About 260,000 Budapest buildings in 3D, coloured by construction year, architect and style - watch how the city grew.",
    "img": "megosztas_en.png",
    "url": "https://budapestbuildings.com/en/",
    "alt": "3D map of Budapest, building by building, coloured by construction year",
}


def en_oldal(html):
    """A magyar kezdőlapból angol belépő oldal (/en/): saját cím/leírás/megosztási kép, angol felület (html lang), <base href="/"> a relatív útvonalakhoz."""
    m = re.search(r"<!--OG-->.*?<!--/OG-->", html, flags=re.S)
    if not m:
        hiba("az index.html-ből hiányzik a <!--OG--> ... <!--/OG--> blokk.")
    b = m.group(0)
    b = re.sub(r"<title>.*?</title>", "<title>" + EN_OG["title"] + "</title>", b)
    b = re.sub(r'(name="description" content=")[^"]*', lambda x: x.group(1) + EN_OG["desc"], b)
    b = re.sub(r'(property="og:description" content=")[^"]*', lambda x: x.group(1) + EN_OG["desc"], b)
    b = re.sub(r'(name="twitter:description" content=")[^"]*', lambda x: x.group(1) + EN_OG["desc"], b)
    b = re.sub(r'((?:og|twitter):title" content=")[^"]*', lambda x: x.group(1) + EN_OG["title"], b)
    b = re.sub(r'(og:image:alt" content=")[^"]*', lambda x: x.group(1) + EN_OG["alt"], b)
    b = b.replace("Cselovszki Attila", "Attila Cselovszki")
    b = b.replace("megosztas_hu.png", EN_OG["img"]).replace("hu_HU", "en_US")
    b = re.sub(r'(rel="canonical" href=")[^"]*', lambda x: x.group(1) + EN_OG["url"], b)
    b = re.sub(r'(og:url" content=")[^"]*', lambda x: x.group(1) + EN_OG["url"], b)
    html = html.replace(m.group(0), b)
    html = html.replace('<html lang="hu">', '<html lang="en">', 1)
    return html.replace('<meta charset="utf-8">', '<meta charset="utf-8">\n  <base href="/">', 1)


def hiba(uzenet):
    sys.exit("HIBA: " + uzenet)


def csere(szoveg, regi, uj, nev):
    if szoveg.count(regi) != 1:
        hiba(f"nem találom az app.js-ben a(z) '{nev}' részt pontosan egyszer (az app.js közben megváltozott: a kiadas_keszites.py-t frissíteni kell).")
    return szoveg.replace(regi, uj, 1)


def karcsusit(ep):
    """Az alapértelmezett mezők elhagyása az épületlistából (a megjelenítő ugyanúgy olvassa): "osm_tipus": "way"."""
    return [{k: v for k, v in p.items() if not (k == "osm_tipus" and v == "way")} if isinstance(p, dict) else p for p in ep]


def gzip_iras(forras, cel):
    """Bináris fájl gzip-tömörítve, ugyanazzal a névvel (mtime=0: ugyanabból a bemenetből mindig ugyanaz a kimenet)."""
    adat = forras.read_bytes()
    cel.write_bytes(gzip.compress(adat, compresslevel=9, mtime=0))
    return len(adat), cel.stat().st_size


def main():
    if not FORRAS.exists():
        hiba(f"nincs meg a {FORRAS} mappa; a projekt mappájából futtasd.")
    if KI.exists():
        if not (KI / MARKER).exists():
            hiba(f"a {KI} mappa már létezik, és nem ez a szkript hozta létre; nevezd át vagy töröld, majd futtasd újra.")
        shutil.rmtree(KI)
    KI.mkdir()
    (KI / MARKER).write_text("A kiadas_keszites.py hozta létre; biztonságosan törölhető.\n", encoding="utf-8")

    # 1. egyszerű másolások
    for f in FAJLOK:
        if not (FORRAS / f).exists():
            print(f"  figyelem: hiányzik a {f}, kimarad")
            continue
        shutil.copy2(FORRAS / f, KI / f)
    for m in MAPPAK:
        if (FORRAS / m).exists():
            shutil.copytree(FORRAS / m, KI / m)
    # képek: csak a képfájlok (a kepek.csv-k a szerkesztéshez kellenek, nem a látogatónak)
    kepek = FORRAS / "kepek"
    if kepek.exists():
        db = 0
        for p in kepek.rglob("*"):
            if p.is_file() and p.suffix.lower() in KEPEK_KIT:
                cel = KI / "kepek" / p.relative_to(kepek)
                cel.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, cel)
                db += 1
        print(f"  adatlap-képek: {db} fájl")

    # 2. az adatmappa, az epuletek.json darabolva
    adat_be = FORRAS / ADAT
    adat_ki = KI / ADAT
    adat_ki.mkdir()
    for p in adat_be.iterdir():
        if not p.is_file() or p.name == "epuletek.json":
            continue
        if p.suffix == ".bin":
            elotte, utana = gzip_iras(p, adat_ki / p.name)
            print(f"  {p.name}: {elotte / 1e6:.1f} MB -> gzip {utana / 1e6:.1f} MB")
        else:
            shutil.copy2(p, adat_ki / p.name)
    ep_teljes = json.loads((adat_be / "epuletek.json").read_text(encoding="utf-8"))
    ep = karcsusit(ep_teljes)
    teljes = len(json.dumps(ep, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    n = max(1, math.ceil(teljes / DARAB_CEL))
    meret = math.ceil(len(ep) / n)
    for i in range(n):
        resz = ep[i * meret:(i + 1) * meret]
        (adat_ki / f"epuletek_{i}.json").write_text(json.dumps(resz, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  epuletek.json: {len(ep)} épület, {teljes / 1e6:.1f} MB -> {n} darab")

    # 3. a kiadási app.js
    js = (FORRAS / "app.js").read_text(encoding="utf-8")
    js = csere(js, "fetch(`${DATA}/epuletek.json`).then(r => r.json()),",
               f"Promise.all(Array.from({{ length: {n} }}, (_, i) => fetch(`${{DATA}}/epuletek_${{i}}.json`).then(r => r.json()))).then(a => a.flat()),",
               "épületek betöltése")
    js = csere(js, """fetch('/api/ping', { cache: 'no-store' }).then(r => r.json()).then(d => {
  szerkeszto = !!d.szerkeszto;
  if (szerkeszto) { szerkPanel(); window.__dbg = { nezet: nezetErtekek, uniforms, camera, controls, pick, rogzit, bezar, epuletek, config }; }
}).catch(() => {});""", "/* nyilvános kiadás: nincs szerkesztő (és nincs window.__dbg) */", "szerkesztő bekapcsolása")
    (KI / "app.js").write_text(js, encoding="utf-8")
    node = shutil.which("node")
    if node:
        r = subprocess.run([node, "--check", str(KI / "app.js")], capture_output=True, text=True)
        if r.returncode:
            hiba("a kiadási app.js szintaktikailag hibás: " + r.stderr[:300])

    # 3b. szöveges oldalak a keresőknek és a megosztáshoz (explore/, e/, sitemap.xml, robots.txt); a térképről az About szövege linkel rájuk
    config = json.loads((adat_be / "budapest.json").read_text(encoding="utf-8"))
    szoveg = felfedezo_keszites.keszit(KI, ep_teljes, config["periods"], js)
    print(f"  szöveges oldalak: {szoveg['epulet']} épület, {szoveg['korszak']} korszak, {szoveg['epitesz']} építész ({szoveg['oldal']} oldal)")

    # 3c. angol belépő oldal (/en/): a közösségi oldalak nem futtatnak JS-t, ezért az angol előnézethez külön HTML kell
    (KI / "en").mkdir()
    (KI / "en" / "index.html").write_text(en_oldal((KI / "index.html").read_text(encoding="utf-8")), encoding="utf-8")
    for kep in ("megosztas_hu.png", "megosztas_en.png"):
        if not (KI / kep).exists():
            print(f"  FIGYELEM: hiányzik a terkep3d/{kep} (1200x630 megosztási kép) - addig a megosztott linkeknek nem lesz képe")

    # 4. gyorsítótár-fejlécek (Cloudflare Pages)
    (KI / "_headers").write_text(
        "/data_varos/*\n  Cache-Control: public, max-age=86400\n"
        "/vendor/*\n  Cache-Control: public, max-age=604800\n"
        "/kepek/*\n  Cache-Control: public, max-age=604800\n"
        "/arculat/*\n  Cache-Control: public, max-age=604800\n"
        "/e/*\n  Cache-Control: public, max-age=3600\n"
        "/explore/*\n  Cache-Control: public, max-age=3600\n"
        "/*.js\n  Cache-Control: public, max-age=3600\n"
        "/*.json\n  Cache-Control: public, max-age=3600\n"
        "/*.css\n  Cache-Control: public, max-age=3600\n", encoding="utf-8")

    # 5. ellenőrzés
    fajlok = [p for p in KI.rglob("*") if p.is_file()]
    nagyok = [p for p in fajlok if p.stat().st_size > LIMIT]
    if nagyok:
        hiba("25 MiB-nál nagyobb fájl: " + ", ".join(f"{p.relative_to(KI)} ({p.stat().st_size / 1048576:.1f} MiB)" for p in nagyok))
    if len(fajlok) > FAJL_LIMIT:
        hiba(f"túl sok fájl: {len(fajlok)} (a korlát {FAJL_LIMIT})")
    ossz = sum(p.stat().st_size for p in fajlok)
    print(f"Kész: {KI}")
    print(f"  fájlok: {len(fajlok)}, összesen {ossz / 1e6:.1f} MB; a legnagyobb: "
          + ", ".join(f"{p.name} {p.stat().st_size / 1e6:.1f} MB" for p in sorted(fajlok, key=lambda p: -p.stat().st_size)[:3]))
    print("Ezt a 'kiadas' mappát kell a Cloudflare Pagesre feltölteni.")


if __name__ == "__main__":
    main()
