"""Structural check of the 3D view (terkep3d/app.js, index.html). Run: py tests/test_client.py
This does NOT run in a browser, but it catches the kinds of error that have occurred so far:
  - a syntax error (node --check, if node is available);
  - the element identifiers referenced in app.js (getElementById) exist in index.html;
  - the starting call of the view switcher (setNezet) is the LAST statement of app.js (otherwise a TDZ error: 'Cannot access ... before initialization');
  - the keys of the HU and EN dictionaries are the same;
  - the data-t keys exist in the dictionary;
  - forbidden leftovers (a slanted arrow on the links, temporary debugging code)."""
import re
import shutil
import subprocess
from test_common import ROOT, check, warn, error_, end_

APP = ROOT / "terkep3d" / "app.js"
HTML = ROOT / "terkep3d" / "index.html"


def main():
    print("[kliens] app.js és index.html")
    js = APP.read_text(encoding="utf-8")
    html = HTML.read_text(encoding="utf-8")

    node = shutil.which("node")
    if node:
        r = subprocess.run([node, "--check", str(APP)], capture_output=True, text=True)
        check(r.returncode == 0, "node --check hibát jelzett az app.js-en: " + r.stderr.strip()[:300])
    else:
        warn("nincs node a gépen: a szintaxis-ellenőrzés kimaradt")

    # element identifiers
    html_ids = set(re.findall(r'\bid="([^"]+)"', html))
    missing = sorted({i for i in re.findall(r"getElementById\('([^']+)'\)", js) if i not in html_ids})
    # elements created from JS (el.id = '...') do not count as an error
    created = set(re.findall(r"\.id\s*=\s*'([^']+)'", js)) | set(re.findall(r"id=\\?\"([^\"\\]+)\\?\"", js))
    missing = [i for i in missing if i not in created]
    check(not missing, "az app.js ezeket az azonosítókat keresi, de az index.html-ben nincsenek: " + ", ".join(missing[:15]))

    # the starting call of the view switcher at the end of the file
    rows = [s.strip() for s in js.rstrip().splitlines() if s.strip() and not s.strip().startswith("//")]
    check(rows and "setNezet('period')" in rows[-1],
              "a setNezet('period') induló hívás nem az app.js utolsó utasítása (TDZ-hiba veszélye); utolsó sor: " + (rows[-1][:80] if rows else ""))

    # dictionaries
    m = re.search(r"\bHU\s*=\s*\{(.*?)\n\s*\};", js, re.S)
    dict_hu = set(re.findall(r"\b([a-z_0-9]+):\s*'", js[js.find("const SZOVEG"):js.find("const SZOVEG") + 40000])) if "const SZOVEG" in js else None
    keys_html = set(re.findall(r'data-t="([^"]+)"', html))
    if keys_html:
        missing_t = sorted(k for k in keys_html if not re.search(r"\b" + re.escape(k) + r"\s*:", js))
        check(not missing_t, "az index.html data-t kulcsai hiányoznak a szótárból: " + ", ".join(missing_t[:15]))

    # forbidden leftovers
    check("↗" not in js, "ferde nyíl (↗) maradt az app.js-ben")
    for banned in ("debugger;", "console.log("):
        if banned in js:
            warn(f"'{banned}' szerepel az app.js-ben ({js.count(banned)}×): nyilvános indítás előtt érdemes kivenni")

    # size
    size = APP.stat().st_size
    if size > 400_000:
        warn(f"az app.js {size // 1000} KB: érdemes szétbontani, ha tovább nő")
    return end_("kliens")


if __name__ == "__main__":
    raise SystemExit(main())
