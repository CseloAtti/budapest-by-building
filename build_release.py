"""The public website's package -> the release/ folder (this is what must be uploaded to Cloudflare).
Run (in the project folder):   py build_release.py

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
Uses only the Python standard library. The release/ folder is recreated on every run (its old content is deleted)."""
import gzip
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_explore

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "terkep3d"
OUT = ROOT / "release"
MARKER = ".kiadas_mappa"                   # by this we recognise that we created the folder (we delete only such)
LIMIT = 25 * 1024 * 1024                    # Cloudflare: at most 25 MiB per file
COUNT_TARGET = 15 * 1024 * 1024                # target size of one data piece (well below the limit)
FILE_LIMIT = 20000

# the files and folders needed by the viewer (relative to the terkep3d folder)
FILES = ["index.html", "app.js", "styles.css", "worker.js", "bridges.js", "adatlapok.json", "epitesz.json", "epitesz_dijak.json",
          "favicon.svg", "epitesz_elete.json", "epitesz_korok_kezi.json", "epitesz_kizart.json", "kerulethatarok.json", "zonak.json",
          "LICENSE-amsterdam.txt", "LICENSE-threejs.txt", "megosztas_hu.png", "megosztas_en.png"]
FOLDERS = ["vendor", "arculat"]
IMAGES_OUT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"}
DATA = "data_varos"


EN_OG = {
    "title": "Age of Budapest's buildings - interactive 3D map",
    "desc": "About 260,000 Budapest buildings in 3D, coloured by construction year, architect and style - watch how the city grew.",
    "img": "megosztas_en.png",
    "url": "https://budapestbuildings.com/en/",
    "alt": "3D map of Budapest, building by building, coloured by construction year",
}


def en_page(html):
    """An English entry page (/en/) from the Hungarian home page: its own title/description/share image, English interface (html lang), <base href="/"> for the relative paths."""
    m = re.search(r"<!--OG-->.*?<!--/OG-->", html, flags=re.S)
    if not m:
        error_("az index.html-ből hiányzik a <!--OG--> ... <!--/OG--> blokk.")
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


def error_(message):
    sys.exit("HIBA: " + message)


def swap(text_, old, new, name_):
    if text_.count(old) != 1:
        error_(f"nem találom az app.js-ben a(z) '{name_}' részt pontosan egyszer (az app.js közben megváltozott: a build_release.py-t frissíteni kell).")
    return text_.replace(old, new, 1)


def slim(ep):
    """Dropping the default fields from the building list (the viewer reads it the same way): "osm_tipus": "way"."""
    return [{k: v for k, v in p.items() if not (k == "osm_tipus" and v == "way")} if isinstance(p, dict) else p for p in ep]


def gzip_write(source, target):
    """A binary file gzip-compressed, with the same name (mtime=0: the same input always gives the same output)."""
    data_ = source.read_bytes()
    target.write_bytes(gzip.compress(data_, compresslevel=9, mtime=0))
    return len(data_), target.stat().st_size


def main():
    if not SOURCE.exists():
        error_(f"nincs meg a {SOURCE} mappa; a projekt mappájából futtasd.")
    if OUT.exists():
        if not (OUT / MARKER).exists():
            error_(f"a {OUT} mappa már létezik, és nem ez a szkript hozta létre; nevezd át vagy töröld, majd futtasd újra.")
        shutil.rmtree(OUT)
    OUT.mkdir()
    (OUT / MARKER).write_text("A build_release.py hozta létre; biztonságosan törölhető.\n", encoding="utf-8")

    # 1. simple copies
    for f in FILES:
        if not (SOURCE / f).exists():
            print(f"  figyelem: hiányzik a {f}, kimarad")
            continue
        shutil.copy2(SOURCE / f, OUT / f)
    for m in FOLDERS:
        if (SOURCE / m).exists():
            shutil.copytree(SOURCE / m, OUT / m)
    # images: only the image files (the kepek.csv files are needed for editing, not for the visitor)
    images = SOURCE / "kepek"
    if images.exists():
        count_ = 0
        for p in images.rglob("*"):
            if p.is_file() and p.suffix.lower() in IMAGES_OUT:
                target = OUT / "kepek" / p.relative_to(images)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, target)
                count_ += 1
        print(f"  adatlap-képek: {count_} fájl")

    # 2. the data folder, epuletek.json split
    data_be = SOURCE / DATA
    data_out = OUT / DATA
    data_out.mkdir()
    for p in data_be.iterdir():
        if not p.is_file() or p.name == "epuletek.json":
            continue
        if p.suffix == ".bin":
            before, after = gzip_write(p, data_out / p.name)
            print(f"  {p.name}: {before / 1e6:.1f} MB -> gzip {after / 1e6:.1f} MB")
        else:
            shutil.copy2(p, data_out / p.name)
    ep_full = json.loads((data_be / "epuletek.json").read_text(encoding="utf-8"))
    ep = slim(ep_full)
    full = len(json.dumps(ep, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    n = max(1, math.ceil(full / COUNT_TARGET))
    size = math.ceil(len(ep) / n)
    for i in range(n):
        part = ep[i * size:(i + 1) * size]
        (data_out / f"epuletek_{i}.json").write_text(json.dumps(part, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  epuletek.json: {len(ep)} épület, {full / 1e6:.1f} MB -> {n} darab")

    # 3. the release app.js
    js = (SOURCE / "app.js").read_text(encoding="utf-8")
    js = swap(js, "fetch(`${DATA}/epuletek.json`).then(r => r.json()),",
               f"Promise.all(Array.from({{ length: {n} }}, (_, i) => fetch(`${{DATA}}/epuletek_${{i}}.json`).then(r => r.json()))).then(a => a.flat()),",
               "épületek betöltése")
    js = swap(js, """fetch('/api/ping', { cache: 'no-store' }).then(r => r.json()).then(d => {
  szerkeszto = !!d.szerkeszto;
  if (szerkeszto) { szerkPanel(); window.__dbg = { nezet: nezetErtekek, uniforms, camera, controls, pick, rogzit, bezar, epuletek, config }; }
}).catch(() => {});""", "/* nyilvános kiadás: nincs szerkesztő (és nincs window.__dbg) */", "szerkesztő bekapcsolása")
    (OUT / "app.js").write_text(js, encoding="utf-8")
    node = shutil.which("node")
    if node:
        r = subprocess.run([node, "--check", str(OUT / "app.js")], capture_output=True, text=True)
        if r.returncode:
            error_("a kiadási app.js szintaktikailag hibás: " + r.stderr[:300])

    # 3b. text pages for search engines and sharing (explore/, e/, sitemap.xml, robots.txt); the About text on the map links to them
    config = json.loads((data_be / "budapest.json").read_text(encoding="utf-8"))
    text_ = build_explore.make(OUT, ep_full, config["periods"], js)
    print(f"  szöveges oldalak: {text_['epulet']} épület, {text_['korszak']} korszak, {text_['epitesz']} építész ({text_['oldal']} oldal)")

    # 3c. English entry page (/en/): social sites do not run JS, so the English preview needs a separate HTML
    (OUT / "en").mkdir()
    (OUT / "en" / "index.html").write_text(en_page((OUT / "index.html").read_text(encoding="utf-8")), encoding="utf-8")
    for image in ("megosztas_hu.png", "megosztas_en.png"):
        if not (OUT / image).exists():
            print(f"  FIGYELEM: hiányzik a terkep3d/{image} (1200x630 megosztási kép) - addig a megosztott linkeknek nem lesz képe")

    # 4. cache headers (Cloudflare)
    (OUT / "_headers").write_text(
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
    files = [p for p in OUT.rglob("*") if p.is_file()]
    large_ = [p for p in files if p.stat().st_size > LIMIT]
    if large_:
        error_("25 MiB-nál nagyobb fájl: " + ", ".join(f"{p.relative_to(OUT)} ({p.stat().st_size / 1048576:.1f} MiB)" for p in large_))
    if len(files) > FILE_LIMIT:
        error_(f"túl sok fájl: {len(files)} (a korlát {FILE_LIMIT})")
    total = sum(p.stat().st_size for p in files)
    print(f"Kész: {OUT}")
    print(f"  fájlok: {len(files)}, összesen {total / 1e6:.1f} MB; a legnagyobb: "
          + ", ".join(f"{p.name} {p.stat().st_size / 1e6:.1f} MB" for p in sorted(files, key=lambda p: -p.stat().st_size)[:3]))
    print("Ezt a 'release' mappát kell a Cloudflare Pagesre feltölteni.")


if __name__ == "__main__":
    main()
