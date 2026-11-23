"""The public website's package -> the kiadas/ folder (this is what must be uploaded to Cloudflare).
Run (in the project folder):   py kiadas_keszites.py

What does it do?
  1. Assembles the files NEEDED by the viewer (without the editor, the development data and the large source files).
  2. Splits epuletek.json into smaller pieces (Cloudflare allows at most 25 MiB per file), and drops from it
     the default "osm_tipus": "way" field (for a missing field the viewer takes 'way' anyway).
     The .bin files (tiles.bin, terrain.bin) are compressed with gzip: Cloudflare does not compress these by itself, but it does compress JSON.
     The viewer (app.js, binarisBetolt) recognises and unpacks the compressed file; the file name does not change.
  3. In the RELEASE COPY (the original terkep3d/app.js stays untouched) it rewrites:
       - the loading, so that it reads the split data files,
       - the editor's activation (the public site has no editor).
  4. Checks the size limits, and prints the release's size.
Uses only the Python standard library. The kiadas/ folder is recreated on every run (its old content is deleted)."""
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
MARKER = ".kiadas_mappa"                   # by this we recognise that we created the folder (we delete only such)
LIMIT = 25 * 1024 * 1024                    # Cloudflare: at most 25 MiB per file
DARAB_CEL = 15 * 1024 * 1024                # target size of one data piece (well below the limit)
FAJL_LIMIT = 20000

# the files and folders needed by the viewer (relative to the terkep3d folder)
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
    """An English entry page (/en/) from the Hungarian home page: its own title/description/share image, English interface (html lang), <base href="/"> for the relative paths."""
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
    """Dropping the default fields from the building list (the viewer reads it the same way): "osm_tipus": "way"."""
    return [{k: v for k, v in p.items() if not (k == "osm_tipus" and v == "way")} if isinstance(p, dict) else p for p in ep]


def gzip_iras(forras, cel):
    """A binary file gzip-compressed, with the same name (mtime=0: the same input always gives the same output)."""
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

    # 1. simple copies
    for f in FAJLOK:
        if not (FORRAS / f).exists():
            print(f"  figyelem: hiányzik a {f}, kimarad")
            continue
        shutil.copy2(FORRAS / f, KI / f)
    for m in MAPPAK:
        if (FORRAS / m).exists():
            shutil.copytree(FORRAS / m, KI / m)
    # images: only the image files (the kepek.csv files are needed for editing, not for the visitor)
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

    # 2. the data folder, epuletek.json split
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

    # 3. the release app.js
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

    # 3b. text pages for search engines and sharing (explore/, e/, sitemap.xml, robots.txt); the About text on the map links to them
    config = json.loads((adat_be / "budapest.json").read_text(encoding="utf-8"))
    szoveg = felfedezo_keszites.keszit(KI, ep_teljes, config["periods"], js)
    print(f"  szöveges oldalak: {szoveg['epulet']} épület, {szoveg['korszak']} korszak, {szoveg['epitesz']} építész ({szoveg['oldal']} oldal)")

    # 3c. English entry page (/en/): social sites do not run JS, so the English preview needs a separate HTML
    (KI / "en").mkdir()
    (KI / "en" / "index.html").write_text(en_oldal((KI / "index.html").read_text(encoding="utf-8")), encoding="utf-8")
    for kep in ("megosztas_hu.png", "megosztas_en.png"):
        if not (KI / kep).exists():
            print(f"  FIGYELEM: hiányzik a terkep3d/{kep} (1200x630 megosztási kép) - addig a megosztott linkeknek nem lesz képe")

    # 4. cache headers (Cloudflare)
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

    # 5. check
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
