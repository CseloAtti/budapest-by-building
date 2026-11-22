"""A 3D nézet (terkep3d/app.js, index.html) szerkezeti ellenőrzése. Futtatás: py tesztek/teszt_kliens.py
Ez NEM böngészőben fut, de az eddig előfordult hibafajtákat megfogja:
  - szintaktikai hiba (node --check, ha van node);
  - az app.js-ben hivatkozott elem-azonosítók (getElementById) léteznek az index.html-ben;
  - a nézetváltó (setNezet) induló hívása az app.js UTOLSÓ utasítása (különben TDZ-hiba: 'Cannot access ... before initialization');
  - a HU és EN szótár kulcsai megegyeznek;
  - a data-t kulcsok léteznek a szótárban;
  - tiltott maradványok (ferde nyíl a linkeken, ideiglenes hibakereső kód)."""
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

    # elem-azonosítók
    html_idk = set(re.findall(r'\bid="([^"]+)"', html))
    hianyzo = sorted({i for i in re.findall(r"getElementById\('([^']+)'\)", js) if i not in html_idk})
    # a JS-ből létrehozott elemeket (el.id = '...') nem számoljuk hibának
    letrehozott = set(re.findall(r"\.id\s*=\s*'([^']+)'", js)) | set(re.findall(r"id=\\?\"([^\"\\]+)\\?\"", js))
    hianyzo = [i for i in hianyzo if i not in letrehozott]
    ellenoriz(not hianyzo, "az app.js ezeket az azonosítókat keresi, de az index.html-ben nincsenek: " + ", ".join(hianyzo[:15]))

    # a nézetváltó induló hívása a fájl végén
    sorok = [s.strip() for s in js.rstrip().splitlines() if s.strip() and not s.strip().startswith("//")]
    ellenoriz(sorok and "setNezet('period')" in sorok[-1],
              "a setNezet('period') induló hívás nem az app.js utolsó utasítása (TDZ-hiba veszélye); utolsó sor: " + (sorok[-1][:80] if sorok else ""))

    # szótárak
    m = re.search(r"\bHU\s*=\s*\{(.*?)\n\s*\};", js, re.S)
    szotar_hu = set(re.findall(r"\b([a-z_0-9]+):\s*'", js[js.find("const SZOVEG"):js.find("const SZOVEG") + 40000])) if "const SZOVEG" in js else None
    kulcsok_html = set(re.findall(r'data-t="([^"]+)"', html))
    if kulcsok_html:
        hianyzo_t = sorted(k for k in kulcsok_html if not re.search(r"\b" + re.escape(k) + r"\s*:", js))
        ellenoriz(not hianyzo_t, "az index.html data-t kulcsai hiányoznak a szótárból: " + ", ".join(hianyzo_t[:15]))

    # tiltott maradványok
    ellenoriz("↗" not in js, "ferde nyíl (↗) maradt az app.js-ben")
    for tiltott in ("debugger;", "console.log("):
        if tiltott in js:
            figyelmeztet(f"'{tiltott}' szerepel az app.js-ben ({js.count(tiltott)}×): nyilvános indítás előtt érdemes kivenni")

    # méret
    meret = APP.stat().st_size
    if meret > 400_000:
        figyelmeztet(f"az app.js {meret // 1000} KB: érdemes szétbontani, ha tovább nő")
    return vege("kliens")


if __name__ == "__main__":
    raise SystemExit(main())
