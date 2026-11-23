"""Downloads the "I know more" suggestions from the Cloudflare D1 database into a CSV file you can check in Excel.

    py suggestions_export.py            the new suggestions (status 'uj'), into suggestions/javaslatok_<date>.csv
    py suggestions_export.py --all      every suggestion
    py suggestions_export.py --mark     after the export, the exported rows get the status 'exportalt' (so they are not exported again)

Needs: npx / wrangler, and a Cloudflare login (npx wrangler login). The file goes to the (git-ignored) suggestions/ folder.
Cells that start with = + - @ get an apostrophe in front, so that a spreadsheet never runs them as a formula."""
import csv
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = "budapest-suggestions"
COLUMNS = ["id", "ido", "osm_tipus", "osm_id", "lat", "lon", "cim", "nev", "ev", "tervezo", "iroda", "leiras", "link", "iroda_oldal", "nyelv", "allapot"]


def d1(sql):
    r = subprocess.run(["npx", "--yes", "wrangler", "d1", "execute", DB, "--remote", "--json", "--command", sql],
                       capture_output=True, text=True, encoding="utf-8", cwd=ROOT, shell=(sys.platform == "win32"))
    if r.returncode != 0:
        sys.exit("HIBA a wrangler futtatásakor:\n" + (r.stderr or r.stdout).strip()[-1500:])
    text = r.stdout
    start = min([i for i in (text.find("["), text.find("{")) if i >= 0], default=-1)
    try:
        data = json.loads(text[start:])
    except ValueError:
        sys.exit("A wrangler kimenete nem olvasható:\n" + text.strip()[-1500:])
    return data[0].get("results", []) if isinstance(data, list) and data else []


def safe(v):
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def main():
    everything = "--all" in sys.argv
    rows = d1("SELECT " + ", ".join(COLUMNS) + " FROM javaslatok" + ("" if everything else " WHERE allapot = 'uj'") + " ORDER BY id")
    if not rows:
        print("Nincs új javaslat.")
        return 0
    out = ROOT / "suggestions"
    out.mkdir(exist_ok=True)
    path = out / f"javaslatok_{datetime.now():%Y%m%d_%H%M}.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow([safe(r.get(c)) for c in COLUMNS])
    print(f"{len(rows)} javaslat -> {path}")
    if "--mark" in sys.argv:
        ids = ", ".join(str(int(r["id"])) for r in rows)
        d1(f"UPDATE javaslatok SET allapot = 'exportalt' WHERE id IN ({ids})")
        print("Az exportált sorok állapota: exportalt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
