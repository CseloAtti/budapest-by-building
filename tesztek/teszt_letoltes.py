"""A letöltési méret csökkentésének ellenőrzése. Futtatás: py tesztek/teszt_letoltes.py  (a node-os részekhez node kell)

1. A háttérszálak (worker.js) a kis vendor/haromszogeles.js-t töltik be, nem a teljes, 1,46 MB-os three.core.js-t
   (azt korábban minden háttérszál külön letöltötte: 4 + 1 = 5 letöltés, 7,3 MB).
   - a haromszogeles.js kivonata betűre egyezik a three.core.js-ben lévő earcut / ShapeUtils résszel;
   - a valódi tiles.bin minden csempéjére a régi és az új worker ugyanazt a hálót (csúcsok, háromszögek) adja.
2. A nyilvános kiadásban a tiles.bin és a terrain.bin gzip-pel tömörítve van; az app.js binarisBetolt függvénye
   a tömörített és a tömörítetlen fájlból is ugyanazt a bájtsort adja vissza.
3. A kiadás epuletek.json-jából elhagyott "osm_tipus": "way" mezőn kívül semmi sem változik."""
import gzip
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from kozos_teszt import GYOKER, ellenoriz, figyelmeztet, vege

T3 = GYOKER / "terkep3d"
CORE = T3 / "vendor" / "three.core.js"
KIS = T3 / "vendor" / "haromszogeles.js"
WORKER = T3 / "worker.js"
ADAT = T3 / "data_varos"

OSSZEVET = r"""
import fs from 'fs';
const [dir, mappa] = process.argv.slice(2);
const A = await import(dir + '/w_regi.mjs'), B = await import(dir + '/w_uj.mjs');
const cfg = JSON.parse(fs.readFileSync(mappa + '/budapest.json', 'utf8'));
const pack = fs.readFileSync(mappa + '/tiles.bin');
let n = 0, rossz = 0, tri = 0;
const eq = (x, y) => x.length === y.length && x.every((v, i) => v === y[i]);
for (const t of cfg.tiles) {
  const buf = pack.buffer.slice(pack.byteOffset + t.offset, pack.byteOffset + t.offset + t.length);
  const a = A.build(A.parse(buf)), b = B.build(B.parse(buf));
  if (!(eq(a.pos, b.pos) && eq(a.idx, b.idx) && eq(a.bld, b.bld) && eq(a.attr, b.attr))) rossz++;
  n++; tri += a.idx.length / 3;
}
console.log(JSON.stringify({ csempe: n, elteres: rossz, haromszog: tri }));
"""

BETOLT = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const f = src.slice(src.indexOf('async function binarisBetolt('), src.indexOf('let terepMesh'));
const fajlok = { '/nyers': fs.readFileSync(process.argv[3]), '/tomor': fs.readFileSync(process.argv[4]) };
globalThis.fetch = async url => new Response(fajlok[url]);
eval(f + '; globalThis.binarisBetolt = binarisBetolt;');
(async () => {
  const a = Buffer.from(await binarisBetolt('/nyers')), b = Buffer.from(await binarisBetolt('/tomor'));
  console.log(JSON.stringify({ nyers: a.length, kibontott: b.length, egyezik: a.equals(fajlok['/nyers']) && b.equals(fajlok['/nyers']) }));
})();
"""


def kivonat(szoveg):
    """Az earcut + ShapeUtils rész (a '/* eslint-disable */ ... earcut' sortól az addContour függvény végéig)."""
    L = szoveg.split("\n")
    i = next(n for n, s in enumerate(L) if s.startswith("/* eslint-disable */") and "earcut" in L[n + 1])
    j = next(n for n, s in enumerate(L) if s.startswith("function addContour("))
    k = next(n for n in range(j, len(L)) if L[n] == "}")
    return "\n".join(L[i:k + 1])


def worker_valtozat(cel, import_nev, kimenet):
    s = WORKER.read_text(encoding="utf-8")
    s = s.replace("'./vendor/haromszogeles.js'", f"'./{import_nev}'").replace("'./vendor/three.core.js'", f"'./{import_nev}'")
    s = s[:s.index("self.onmessage")] + "\nexport { parse, build };\n"
    (cel / kimenet).write_text(s, encoding="utf-8")


def main():
    print("[letoltes] háromszögelés kivonata, tömörített bináris betöltés, karcsúsított épületlista")
    w = WORKER.read_text(encoding="utf-8")
    importok = [s for s in w.splitlines() if s.startswith("import ")]
    ellenoriz(not any("three.core.js'" in s or "three.module.js'" in s for s in importok), "a worker.js még mindig a teljes three.js-t importálja")
    ellenoriz("'./vendor/haromszogeles.js'" in w, "a worker.js nem a vendor/haromszogeles.js-t importálja")
    ellenoriz(KIS.exists(), f"nincs meg: {KIS}")
    if CORE.exists() and KIS.exists():
        ellenoriz(kivonat(KIS.read_text(encoding="utf-8")) == kivonat(CORE.read_text(encoding="utf-8")),
                  "a haromszogeles.js kivonata eltér a three.core.js-ben lévőtől (a three.js frissült? másold át újra)")

    node = shutil.which("node")
    if not node:
        figyelmeztet("nincs node a gépen: a hálók összevetése és a betöltés-teszt kimaradt")
    elif not (ADAT / "tiles.bin").exists():
        figyelmeztet(f"nincs meg: {ADAT / 'tiles.bin'}")
    else:
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            shutil.copy(CORE, d / "three.core.mjs")
            shutil.copy(KIS, d / "haromszogeles.mjs")
            worker_valtozat(d, "three.core.mjs", "w_regi.mjs")
            worker_valtozat(d, "haromszogeles.mjs", "w_uj.mjs")
            (d / "osszevet.mjs").write_text(OSSZEVET, encoding="utf-8")
            r = subprocess.run([node, str(d / "osszevet.mjs"), d.as_uri(), str(ADAT)], capture_output=True, text=True)
            if ellenoriz(r.returncode == 0, "a hálók összevetése nem futott le: " + r.stderr.strip()[:300]):
                e = json.loads(r.stdout)
                ellenoriz(e["elteres"] == 0, f"{e['elteres']} csempén eltér a régi és az új worker hálója")
                print(f"  csempe: {e['csempe']}, háromszög: {e['haromszog']}, eltérő csempe: {e['elteres']}")

            nyers = ADAT / ("terrain.bin" if (ADAT / "terrain.bin").exists() else "tiles.bin")
            tomor = d / "tomor.bin"
            tomor.write_bytes(gzip.compress(nyers.read_bytes(), compresslevel=9, mtime=0))
            (d / "betolt.js").write_text(BETOLT, encoding="utf-8")
            r = subprocess.run([node, str(d / "betolt.js"), str(T3 / "app.js"), str(nyers), str(tomor)], capture_output=True, text=True)
            if ellenoriz(r.returncode == 0, "a binarisBetolt nem futott le: " + r.stderr.strip()[:300]):
                e = json.loads(r.stdout)
                ellenoriz(e["egyezik"], f"a binarisBetolt nem az eredeti bájtsort adta vissza ({e})")
                print(f"  {nyers.name}: {e['nyers']} bájt; gzip {tomor.stat().st_size} bájt; kibontva egyezik: {e['egyezik']}")

    # a kiadás segédfüggvényei
    sys.path.insert(0, str(GYOKER))
    import kiadas_keszites as K
    minta = [{"id": 1, "osm_tipus": "way", "kor": 3}, {"id": 2, "osm_tipus": "relation", "kor": 1}, {"id": 3, "kor": 2, "nev": "way"}]
    ellenoriz(K.karcsusit(minta) == [{"id": 1, "kor": 3}, {"id": 2, "osm_tipus": "relation", "kor": 1}, {"id": 3, "kor": 2, "nev": "way"}],
              "a karcsusit nem csak a \"osm_tipus\": \"way\" mezőt hagyta el")
    with tempfile.TemporaryDirectory() as d:
        a, b = Path(d) / "a.bin", Path(d) / "b.bin"
        a.write_bytes(bytes(range(256)) * 100 + b"\0" * 5000)
        K.gzip_iras(a, b)
        ellenoriz(gzip.decompress(b.read_bytes()) == a.read_bytes(), "a gzip_iras kimenete kibontva nem az eredeti")
    if (ADAT / "epuletek.json").exists():
        ep = json.loads((ADAT / "epuletek.json").read_text(encoding="utf-8"))
        ki = K.karcsusit(ep)
        visszaall = [{**({"osm_tipus": "way"} if "osm_tipus" not in p else {}), **p} for p in ki]
        ellenoriz(all(p.get("osm_tipus", "way") == q.get("osm_tipus", "way") and {k: v for k, v in p.items() if k != "osm_tipus"} == {k: v for k, v in q.items() if k != "osm_tipus"}
                      for p, q in zip(ep, visszaall)) and len(ep) == len(ki),
                  "a karcsúsított épületlista a valódi adaton nem ugyanazt jelenti, mint az eredeti")
        print(f"  epuletek.json: {len(ep)} épület, ebből 'way' mező elhagyva: {sum(1 for p in ep if p.get('osm_tipus') == 'way')}")
    return vege("letoltes")


if __name__ == "__main__":
    raise SystemExit(main())
