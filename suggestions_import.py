"""Adds the accepted "I know more" suggestions (the CSV made by suggestions_export.py) to the manual corrections,
forras/kezi_javitasok.csv, in the format the editor uses. Manual corrections always win in assemble.py.

    py suggestions_import.py suggestions\\javaslatok_20261123_2222.csv            adds every row of the file
    py suggestions_import.py suggestions\\javaslatok_20261123_2222.csv --dry-run  only shows what would be added
    py suggestions_import.py <file.csv> --skip 1,4                                leaves out the rows with these suggestion ids

Mapping: nev -> nev, ev -> ev (a single year; for a range the LAST year, and the given range is noted in the comment), tervezo -> tervezo,
iroda -> iroda (architecture office), leiras -> about, link -> linkek (the "Sources" section of the card), or, if the sender ticked that the link
is the office's own page (iroda_oldal = 1), link -> iroda_link (the "Learn more" section). An office name typed into tervezo is moved to the iroda field
by assemble.py anyway. Rows that are already in the file are not added twice.
After it, rebuild: zones_refresh.bat  (assemble, year_estimate, assemble, build_tiles)."""
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "forras" / "kezi_javitasok.csv"
FIELDS = {"nev": "nev", "ev": "ev", "tervezo": "tervezo", "iroda": "iroda", "leiras": "about", "link": "linkek"}


def clean(v):
    s = (v or "").strip()
    return s[1:] if s[:1] == "'" and s[1:2] in ("=", "+", "-", "@") else s       # removes the apostrophe the export put in front


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    skip = set()
    if "--skip" in sys.argv:
        skip = {x.strip() for x in sys.argv[sys.argv.index("--skip") + 1].split(",")}
        args = [a for a in args if a != sys.argv[sys.argv.index("--skip") + 1]]
    if not args:
        sys.exit(__doc__)
    src = Path(args[0])
    with open(src, encoding="utf-8-sig", newline="") as f:
        sugg = list(csv.DictReader(f))
    existing = []
    if TARGET.exists():
        with open(TARGET, encoding="utf-8-sig", newline="") as f:
            existing = list(csv.DictReader(f, delimiter=";"))
    have = {(r["osm_tipus"], r["id"], r["mezo"], r["ertek"]) for r in existing}
    by_field = {(r["osm_tipus"], r["id"], r["mezo"]): r["ertek"] for r in existing}
    new = []
    for s in sugg:
        if s.get("id") in skip:
            continue
        tip, oid = s["osm_tipus"], s["osm_id"]
        day = (s.get("ido") or "")[:10]
        note = f"Felhasználói javaslat #{s['id']} ({day})"
        for src_field, mezo in FIELDS.items():
            v = clean(s.get(src_field))
            if src_field == "link" and (s.get("iroda_oldal") or "").strip() == "1":
                mezo = "iroda_link"          # the office's own page about the building: "Learn more" section
            if not v:
                continue
            m = note
            if mezo == "ev":
                years = re.findall(r"\d{4}", v)
                if not years:
                    print(f"  kihagyva (nincs évszám): #{s['id']} ev={v!r}")
                    continue
                end = years[-1]
                short = re.search(r"(\d{4})\s*[-–—/]\s*(\d{2})(?!\d)", v)          # a range with a shortened end year: 1978-84 -> 1984
                if short:
                    first = short.group(1)
                    end = first[:2] + short.group(2)
                    if int(end) < int(first):
                        end = str(int(end) + 100)
                if v.strip(" .") != end:
                    m += f"; a megadott érték: {v}"
                v = end
            if (tip, oid, mezo, v) in have:
                print(f"  már megvan: {tip} {oid} {mezo}={v}")
                continue
            old = by_field.get((tip, oid, mezo))
            if old is not None and old != v:
                print(f"  FIGYELEM: {tip} {oid} {mezo}: eddig {old!r}, a javaslat {v!r} (a kézi sorok közül mindkettő bekerül)")
            new.append([tip, oid, mezo, v, "kezi", m, "", ""])
            have.add((tip, oid, mezo, v))
    for r in new:
        print("  +", ";".join(r[:5]), "|", r[5])
    print(f"{len(new)} új sor" + (" (próba, nem írtam a fájlba)" if dry else ""))
    if dry or not new:
        return 0
    raw = TARGET.read_bytes() if TARGET.exists() else b""
    with open(TARGET, "a", encoding="utf-8", newline="") as f:
        if raw and not raw.endswith(b"\n"):
            f.write("\r\n")
        csv.writer(f, delimiter=";", lineterminator="\r\n").writerows(new)
    print(f"hozzáfűzve: {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
