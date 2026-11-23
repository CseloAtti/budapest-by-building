"""rename_files.py - renames the project's code files and folders to English names, and rewrites every reference.

Run in the project folder (on the 'english-code' git branch, with everything committed):
    py rename_files.py            (dry run: prints what it WOULD do, changes nothing)
    py rename_files.py --apply    (does it: git mv + rewriting the references)
After that:  py tests\\run_all.py   and look at the 'leftover names' list printed at the end.
Delete this script when you are done (it is only needed once).
"""
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
APPLY = "--apply" in sys.argv
ROOT = Path(__file__).resolve().parent

# old module/file base name -> new base name  (the extension stays)
MAP = {}
for line in """adatlapok_keszites build_datasheets
budapest_letoltes download_budapest
cimek_letoltes download_addresses
commons_kepek commons_images
csempek_keszites build_tiles
duplikatok_kereso duplicate_finder
ertekleltar_telek2 inventory_plots2
ertekleltar_telek inventory_plots
ev_becsles year_estimate
felfedezo_keszites build_explore
geotiff_olvaso geotiff_reader
hidak_keszites build_bridges
kiadas_keszites build_release
kozos common
nem_epulet_felvetel non_building_import
osszeepit assemble
szazad century
szerkeszto_szerver editor_server
terulet_kozos area_common
utak_keszites build_roads
utcakep streetview
varos_osszeallitas city_assembly
viz_letoltes download_water
zonak_epuletbol zones_from_buildings
zonak_json_keszites build_zones_json
zonak_osm_jeloltek zones_osm_candidates
tenyek_bp100_kepek facts_bp100_images
tenyek_bp100_sarok facts_bp100_corner
tenyek_bp100 facts_bp100
tenyek_epforum_cikkek facts_epforum_articles
tenyek_epforum facts_epforum
tenyek_ertekleltar facts_inventory
tenyek_eubucco facts_eubucco
tenyek_ghsl facts_ghsl
tenyek_helyi_vedelem facts_local_protection
tenyek_kezi_korszak facts_manual_era
tenyek_kozepulet_nev facts_public_building_names
tenyek_lechner facts_lechner
tenyek_legenda facts_budapest_legend
tenyek_muemlek facts_monuments
tenyek_oeny_kezi facts_oeny_manual
tenyek_oeny_koord facts_oeny_coords
tenyek_oeny facts_oeny
tenyek_osm_cimkek facts_osm_tags
tenyek_romok facts_ruins
tenyek_sarok facts_corner
tenyek_szintterkep facts_storey_map
tenyek_telek2 facts_plots2
tenyek_veletlen_ev facts_assumed_year
tenyek_wikidata_api facts_wikidata_api
tenyek_wikidata_terulet facts_wikidata_area
tenyek_wikidata facts_wikidata
tenyek_wikipedia_ev facts_wikipedia_year
tenyek_wikipedia_lista_letolt facts_wikipedia_list_download
tenyek_wikipedia_lista facts_wikipedia_list
tenyek_wikipedia_temalista_letolt facts_wikipedia_topiclist_download
tenyek_wikipedia_terulet facts_wikipedia_area
zona_frissit zones_refresh
kiadas_feltoltes release_deploy
takaritas cleanup
zonak zones
futtat_mindent run_all
kozos_teszt test_common
teszt_adatlapok test_datasheets
teszt_adatok test_data
teszt_becsles_kuszob test_estimate_threshold
teszt_becsles test_estimate
teszt_felfedezo test_explore
teszt_helyi_kvota test_local_quota
teszt_kereso test_search
teszt_kliens test_client
teszt_letoltes test_download_size
teszt_megosztas test_sharing
teszt_reszek test_parts
teszt_szerver test_server
teszt_visszajelzes test_feedback""".splitlines():
    a, b = line.split()
    MAP[a] = b

# common words / names that also occur as ordinary identifiers or data names: these are rewritten ONLY in clear contexts
RISKY = {"kozos", "szazad", "utcakep", "zonak", "takaritas", "osszeepit", "ev_becsles"}
SAFE = [n for n in MAP if n not in RISKY]
ALL_ALT = "|".join(sorted(MAP, key=len, reverse=True))
SAFE_ALT = "|".join(sorted(SAFE, key=len, reverse=True))
TEXT_EXT = {".py", ".js", ".html", ".md", ".bat", ".jsonc", ".txt", ".css"}
DATA_EXT = r"csv|json|geojson|xlsx|md|txt|bin|png|gz"

FILE_RENAMES = {"terkep3d/hidak.js": "terkep3d/bridges.js",
                "tesztek/ATNEZES_TERV.md": "tests/REVIEW_PLAN.md"}


def git(*args):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r


def tracked():
    return [p for p in git("ls-files").stdout.splitlines() if p]


def rewrite(path, text, stats):
    ext = Path(path).suffix.lower()
    base = Path(path).name

    def sub(pattern, repl, t, key, flags=0):
        n = [0]

        def f(m):
            n[0] += 1
            return repl(m)
        t2 = re.sub(pattern, f, t, flags=flags)
        if n[0]:
            stats[key] = stats.get(key, 0) + n[0]
        return t2

    if base == ".gitignore":
        return sub(r"(?m)^kiadas/$", lambda m: "release/\nkiadas/", text, "gitignore")
    t = text
    # 1. file names with an extension: name.py / name.bat / name.html
    t = sub(r"(?<![\w])(%s)(?=\.(?:py|bat|html)\b)" % ALL_ALT, lambda m: MAP[m.group(1)], t, "file names")
    # 2. bridges.js
    t = sub(r"(?<![\w])hidak\.js\b", lambda m: "bridges.js", t, "hidak.js")
    # 3. the unambiguous (long) names anywhere (comments, lists of test names, imports, attributes)
    t = sub(r"(?<![\w])(%s)(?![\w])(?!\.(?:%s)\b)" % (SAFE_ALT, DATA_EXT), lambda m: MAP[m.group(1)], t, "names")
    if ext == ".py":
        # 4. imports of the ambiguous names
        t = sub(r"(?m)^(\s*)(from|import)(\s+)(%s)\b" % ALL_ALT, lambda m: m.group(1) + m.group(2) + m.group(3) + MAP[m.group(4)], t, "imports")
        # 5. module attribute uses of the ambiguous names (utcakep.szamol, ev_becsles.kvota_kiosztas)
        t = sub(r"(?<![\w])(utcakep|ev_becsles)\.(?=[A-Za-z_])(?!(?:py|csv|md|json|geojson)\b)", lambda m: MAP[m.group(1)] + ".", t, "attributes")
    # 6. folders
    t = sub(r"(?<![\w])tesztek(?=[/\\])", lambda m: "tests", t, "folder tests")
    if ext in {".py", ".bat", ".md", ".jsonc"}:
        t = sub(r"(?<=[\"'/\\\s`(])kiadas(?=[/\"'\\\s`)]|$)", lambda m: "release", t, "folder release", flags=re.M)
    return t


def main():
    if git("rev-parse", "--is-inside-work-tree").stdout.strip() != "true":
        print("This is not a git repository."); return 1
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    dirty = git("status", "--porcelain").stdout.strip()
    print(f"Branch: {branch}")
    if dirty and APPLY:
        print("There are uncommitted changes. Commit them first (git add -A, git commit), then run again."); print(dirty[:600]); return 1
    files = tracked()
    # ---- planned renames
    ren = {}
    for p in files:
        name = Path(p).name
        if "/" not in p:
            stem, ext = Path(p).stem, Path(p).suffix
            if stem in MAP and ext in {".py", ".bat", ".html"}:
                ren[p] = MAP[stem] + ext
        elif p.startswith("tesztek/"):
            stem, ext = Path(p).stem, Path(p).suffix
            new = MAP.get(stem, stem) + ext if ext == ".py" else name
            ren[p] = FILE_RENAMES.get(p, "tests/" + new)
        elif p in FILE_RENAMES:
            ren[p] = FILE_RENAMES[p]
    for old, new in ren.items():
        if old != new and (ROOT / new).exists() and new not in ren:
            print(f"STOP: the target already exists: {new}"); return 1
    print(f"\n{len([1 for o, n in ren.items() if o != n])} files to rename, for example:")
    for o, n in list(ren.items())[:200]:
        if o != n:
            print(f"   {o}  ->  {n}")
    # ---- planned rewrites
    changes = {}
    skipped = []
    for p in files:
        if Path(p).suffix.lower() not in TEXT_EXT and Path(p).name != ".gitignore":
            continue
        if Path(p).name.upper().startswith("LICENSE") or Path(p).name == "rename_files.py":
            continue
        try:
            raw = (ROOT / p).read_bytes().decode("utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            skipped.append(p); continue
        stats = {}
        new = rewrite(p, raw, stats)
        if new != raw:
            changes[p] = (new, stats)
    print(f"\nReferences rewritten in {len(changes)} files:")
    for p, (_, stats) in sorted(changes.items()):
        print(f"   {p}: " + ", ".join(f"{k} {v}" for k, v in stats.items()))
    if skipped:
        print("\nSkipped (not readable as UTF-8):", ", ".join(skipped))
    if not APPLY:
        print("\nDRY RUN: nothing was changed. If it looks right:  py rename_files.py --apply")
        return 0
    # ---- apply: folder first, then files, then contents
    if (ROOT / "tesztek").is_dir():
        if (ROOT / "tests").exists():
            print("STOP: the 'tests' folder already exists."); return 1
        r = git("mv", "tesztek", "tests")
        if r.returncode:
            print("git mv tesztek tests failed:", r.stderr); return 1
    for old, new in ren.items():
        cur = ("tests/" + old.split("/", 1)[1]) if old.startswith("tesztek/") else old
        if cur == new:
            continue
        r = git("mv", cur, new)
        if r.returncode:
            print(f"git mv {cur} {new} failed:", r.stderr); return 1
    for p, (new, _) in changes.items():
        target = ren.get(p, p)
        (ROOT / target).write_bytes(new.encode("utf-8"))
    print("\nDone. Renames and rewrites are in the working tree (nothing is committed).")
    # ---- leftover check
    print("\nLeftover old names (check these by hand):")
    left = 0
    pat_safe = re.compile(r"(?<![\w])(%s)(?![\w])(?!\.(?:%s)\b)" % (SAFE_ALT, DATA_EXT))
    pat_risky = re.compile(r"(?<![\w])(kozos|szazad|utcakep|zonak|takaritas)(?:\.(?:py|bat|html)\b)|(?:from|import)\s+(kozos|szazad|utcakep|osszeepit|ev_becsles)\b")
    for p in tracked():
        if Path(p).suffix.lower() not in TEXT_EXT and Path(p).name != ".gitignore":
            continue
        if Path(p).name == "rename_files.py":
            continue
        try:
            txt = (ROOT / p).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for i, ln in enumerate(txt.splitlines(), 1):
            if pat_safe.search(ln) or pat_risky.search(ln):
                left += 1
                if left <= 60:
                    print(f"   {p}:{i}: {ln.strip()[:110]}")
    print(f"   ({left} lines)" if left else "   none")
    print("\nNext:  py tests\\run_all.py     then     git add -A     git commit -m \"Rename code files to English\"")
    print("The old 'kiadas' folder (generated) can be deleted by hand; the new one is 'release'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
