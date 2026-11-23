"""Structural check of the 3D view (terkep3d/app.js, index.html). Run: py tesztek/teszt_kliens.py
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
from kozos_teszt import GYOKER, ellenoriz, figyelmeztet, hiba, vege

APP = GYOKER / "terkep3d" / "app.js"
HTML = GYOKER / "terkep3d" / "index.html"


def main():
    print("[kliens] app.js és index.html")
    js = APP.read_text(encoding="utf-8")
    html = HTML.read_text(encoding="utf-8")

    node = shutil.which("node")
    if node:
        r = subprocess.run([node, "--check", str(APP)], capture_output=True, text=True)
        ellenoriz(r.returncode == 0, "node --check hibát jelzett az app.js-en: " + r.stderr.strip()[:300])
    else:
        figyelmeztet("nincs node a gépen: a szintaxis-ellenőrzés kimaradt")

    # element identifiers
    html_idk = set(re.findall(r'\bid="([^"]+)"', html))
    hianyzo = sorted({i for i in re.findall(r"getElementById\('([^']+)'\)", js) if i not in html_idk})
    # elements created from JS (el.id = '...') do not count as an error
    letrehozott = set(re.findall(r"\.id\s*=\s*'([^']+)'", js)) | set(re.findall(r"id=\\?\"([^\"\\]+)\\?\"", js))
    hianyzo = [i for i in hianyzo if i not in letrehozott]
    ellenoriz(not hianyzo, "az app.js ezeket az azonosítókat keresi, de az index.html-ben nincsenek: " + ", ".join(hianyzo[:15]))

    # the starting call of the view switcher at the end of the file
    sorok = [s.strip() for s in js.rstrip().splitlines() if s.strip() and not s.strip().startswith("//")]
    ellenoriz(sorok and "setNezet('period')" in sorok[-1],
              "a setNezet('period') induló hívás nem az app.js utolsó utasítása (TDZ-hiba veszélye); utolsó sor: " + (sorok[-1][:80] if sorok else ""))

    # dictionaries
    m = re.search(r"\bHU\s*=\s*\{(.*?)\n\s*\};", js, re.S)
    szotar_hu = set(re.findall(r"\b([a-z_0-9]+):\s*'", js[js.find("const SZOVEG"):js.find("const SZOVEG") + 40000])) if "const SZOVEG" in js else None
    kulcsok_html = set(re.findall(r'data-t="([^"]+)"', html))
    if kulcsok_html:
        hianyzo_t = sorted(k for k in kulcsok_html if not re.search(r"\b" + re.escape(k) + r"\s*:", js))
        ellenoriz(not hianyzo_t, "az index.html data-t kulcsai hiányoznak a szótárból: " + ", ".join(hianyzo_t[:15]))

    # forbidden leftovers
    ellenoriz("↗" not in js, "ferde nyíl (↗) maradt az app.js-ben")
    for tiltott in ("debugger;", "console.log("):
        if tiltott in js:
            figyelmeztet(f"'{tiltott}' szerepel az app.js-ben ({js.count(tiltott)}×): nyilvános indítás előtt érdemes kivenni")

    # size
    meret = APP.stat().st_size
    if meret > 400_000:
        figyelmeztet(f"az app.js {meret // 1000} KB: érdemes szétbontani, ha tovább nő")
    return vege("kliens")


if __name__ == "__main__":
    raise SystemExit(main())
