"""Checking the reduction of the download size. Run: py tests/test_download_size.py  (node is needed for the node parts)

1. The background threads (worker.js) load the small vendor/haromszogeles.js, not the whole 1.46 MB three.core.js
   (earlier every background thread downloaded that separately: 4 + 1 = 5 downloads, 7.3 MB).
   - the digest of haromszogeles.js matches, letter for letter, the earcut / ShapeUtils part in three.core.js;
   - for every tile of the real tiles.bin the old and the new worker give the same mesh (vertices, triangles).
2. In the public release tiles.bin and terrain.bin are gzip-compressed; the binarisBetolt function of app.js
   returns the same byte sequence from the compressed and from the uncompressed file.
3. Apart from the "osm_tipus": "way" field left out of the release's epuletek.json, nothing changes."""
import gzip
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from test_common import ROOT, check, warn, end_

T3 = ROOT / "terkep3d"
CORE = T3 / "vendor" / "three.core.js"
SMALL = T3 / "vendor" / "haromszogeles.js"
WORKER = T3 / "worker.js"
DATA = T3 / "data_varos"

COMPARE = r"""
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

LOAD = r"""
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


def extract(text_):
    """The earcut + ShapeUtils part (from the '/* eslint-disable */ ... earcut' line to the end of the addContour function)."""
    L = text_.split("\n")
    i = next(n for n, s in enumerate(L) if s.startswith("/* eslint-disable */") and "earcut" in L[n + 1])
    j = next(n for n, s in enumerate(L) if s.startswith("function addContour("))
    k = next(n for n in range(j, len(L)) if L[n] == "}")
    return "\n".join(L[i:k + 1])


def worker_variant(target, import_name, output):
    s = WORKER.read_text(encoding="utf-8")
    s = s.replace("'./vendor/haromszogeles.js'", f"'./{import_name}'").replace("'./vendor/three.core.js'", f"'./{import_name}'")
    s = s[:s.index("self.onmessage")] + "\nexport { parse, build };\n"
    (target / output).write_text(s, encoding="utf-8")


def main():
    print("[letoltes] háromszögelés kivonata, tömörített bináris betöltés, karcsúsított épületlista")
    w = WORKER.read_text(encoding="utf-8")
    imports = [s for s in w.splitlines() if s.startswith("import ")]
    check(not any("three.core.js'" in s or "three.module.js'" in s for s in imports), "a worker.js még mindig a teljes three.js-t importálja")
    check("'./vendor/haromszogeles.js'" in w, "a worker.js nem a vendor/haromszogeles.js-t importálja")
    check(SMALL.exists(), f"nincs meg: {SMALL}")
    if CORE.exists() and SMALL.exists():
        check(extract(SMALL.read_text(encoding="utf-8")) == extract(CORE.read_text(encoding="utf-8")),
                  "a haromszogeles.js kivonata eltér a three.core.js-ben lévőtől (a three.js frissült? másold át újra)")

    node = shutil.which("node")
    if not node:
        warn("nincs node a gépen: a hálók összevetése és a betöltés-teszt kimaradt")
    elif not (DATA / "tiles.bin").exists():
        warn(f"nincs meg: {DATA / 'tiles.bin'}")
    else:
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            shutil.copy(CORE, d / "three.core.mjs")
            shutil.copy(SMALL, d / "haromszogeles.mjs")
            worker_variant(d, "three.core.mjs", "w_regi.mjs")
            worker_variant(d, "haromszogeles.mjs", "w_uj.mjs")
            (d / "osszevet.mjs").write_text(COMPARE, encoding="utf-8")
            r = subprocess.run([node, str(d / "osszevet.mjs"), d.as_uri(), str(DATA)], capture_output=True, text=True)
            if check(r.returncode == 0, "a hálók összevetése nem futott le: " + r.stderr.strip()[:300]):
                e = json.loads(r.stdout)
                check(e["elteres"] == 0, f"{e['elteres']} csempén eltér a régi és az új worker hálója")
                print(f"  csempe: {e['csempe']}, háromszög: {e['haromszog']}, eltérő csempe: {e['elteres']}")

            raw = DATA / ("terrain.bin" if (DATA / "terrain.bin").exists() else "tiles.bin")
            compressed = d / "tomor.bin"
            compressed.write_bytes(gzip.compress(raw.read_bytes(), compresslevel=9, mtime=0))
            (d / "betolt.js").write_text(LOAD, encoding="utf-8")
            r = subprocess.run([node, str(d / "betolt.js"), str(T3 / "app.js"), str(raw), str(compressed)], capture_output=True, text=True)
            if check(r.returncode == 0, "a binarisBetolt nem futott le: " + r.stderr.strip()[:300]):
                e = json.loads(r.stdout)
                check(e["egyezik"], f"a binarisBetolt nem az eredeti bájtsort adta vissza ({e})")
                print(f"  {raw.name}: {e['nyers']} bájt; gzip {compressed.stat().st_size} bájt; kibontva egyezik: {e['egyezik']}")

    # the release's helper functions
    sys.path.insert(0, str(ROOT))
    import build_release as K
    sample = [{"id": 1, "osm_tipus": "way", "kor": 3}, {"id": 2, "osm_tipus": "relation", "kor": 1}, {"id": 3, "kor": 2, "nev": "way"}]
    check(K.slim(sample) == [{"id": 1, "kor": 3}, {"id": 2, "osm_tipus": "relation", "kor": 1}, {"id": 3, "kor": 2, "nev": "way"}],
              "a karcsusit nem csak a \"osm_tipus\": \"way\" mezőt hagyta el")
    with tempfile.TemporaryDirectory() as d:
        a, b = Path(d) / "a.bin", Path(d) / "b.bin"
        a.write_bytes(bytes(range(256)) * 100 + b"\0" * 5000)
        K.gzip_write(a, b)
        check(gzip.decompress(b.read_bytes()) == a.read_bytes(), "a gzip_iras kimenete kibontva nem az eredeti")
    if (DATA / "epuletek.json").exists():
        ep = json.loads((DATA / "epuletek.json").read_text(encoding="utf-8"))
        out = K.slim(ep)
        restore = [{**({"osm_tipus": "way"} if "osm_tipus" not in p else {}), **p} for p in out]
        check(all(p.get("osm_tipus", "way") == q.get("osm_tipus", "way") and {k: v for k, v in p.items() if k != "osm_tipus"} == {k: v for k, v in q.items() if k != "osm_tipus"}
                      for p, q in zip(ep, restore)) and len(ep) == len(out),
                  "a karcsúsított épületlista a valódi adaton nem ugyanazt jelenti, mint az eredeti")
        print(f"  epuletek.json: {len(ep)} épület, ebből 'way' mező elhagyva: {sum(1 for p in ep if p.get('osm_tipus') == 'way')}")
    return end_("letoltes")


if __name__ == "__main__":
    raise SystemExit(main())
