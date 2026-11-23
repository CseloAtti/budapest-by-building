"""Checking the search on the real data (node is needed for it). Run: py tesztek/teszt_kereso.py
The error it catches: an OSM element made of several outlines (a relation, e.g. 'Home Center' with 4 outlines) appeared several times
among the hits of the search by name. The test extracts the keresoEpit() function of app.js, runs it on
terkep3d/data_varos/epuletek.json, and counts the repeated OSM identifiers."""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from kozos_teszt import GYOKER, ellenoriz, figyelmeztet, vege

APP = GYOKER / "terkep3d" / "app.js"
ADAT = GYOKER / "terkep3d" / "data_varos" / "epuletek.json"
JS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const f = src.slice(src.indexOf('function keresoEpit()'), src.indexOf('function keresoSzoveg()'));
const epuletek = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const normal = s => s.toLowerCase();
let keresoIndex;
eval(f + '; keresoEpit();');
const n = {};
for (const [gid] of keresoIndex) { const p = epuletek[gid]; if (p.hid) continue; const k = (p.osm_tipus || 'way') + ':' + p.id; n[k] = (n[k] || 0) + 1; }
const tobb = Object.entries(n).filter(([, c]) => c > 1);
console.log(JSON.stringify({ db: keresoIndex.length, tobb: tobb.length, pelda: tobb.slice(0, 3) }));
"""


def main():
    print("[kereso] keresoEpit az epuletek.json-on")
    node = shutil.which("node")
    if not node:
        figyelmeztet("nincs node a gépen: a kereső-teszt kimaradt")
        return vege("kereso")
    if not ADAT.exists():
        figyelmeztet(f"nincs meg: {ADAT}")
        return vege("kereso")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(JS)
    r = subprocess.run([node, f.name, str(APP), str(ADAT)], capture_output=True, text=True)
    Path(f.name).unlink(missing_ok=True)
    if not ellenoriz(r.returncode == 0, "a keresoEpit nem futott le: " + r.stderr.strip()[:300]):
        return vege("kereso")
    e = json.loads(r.stdout)
    ellenoriz(e["tobb"] == 0, f"{e['tobb']} OSM-elem többször szerepel a kereső találatai között (pl. {e['pelda']})")
    print(f"  kereshető tétel: {e['db']}, ismétlődő OSM-elem: {e['tobb']}")
    return vege("kereso")


if __name__ == "__main__":
    raise SystemExit(main())
