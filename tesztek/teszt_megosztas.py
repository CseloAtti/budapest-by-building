"""Checking the share preview (OG tags, the /en/ page) and the deep links.   Run: py tesztek/teszt_megosztas.py"""
import re
import sys
from kozos_teszt import GYOKER, ellenoriz, figyelmeztet, vege

sys.path.insert(0, str(GYOKER))
import kiadas_keszites as K


def main():
    print("[megosztas] OG-címkék, /en/ oldal, mélylinkek")
    html = (GYOKER / "terkep3d" / "index.html").read_text(encoding="utf-8")
    ellenoriz(html.count("<!--OG-->") == 1 and html.count("<!--/OG-->") == 1, "az index.html-ben nincs pontosan egy <!--OG--> blokk")
    for c in ("og:title", "og:description", "og:image", "og:url", "twitter:card", 'name="description"', 'rel="canonical"'):
        ellenoriz(c in html, f"hiányzik az index.html-ből: {c}")
    ellenoriz(html.count("<title>") == 1, "az index.html-ben több <title> van")
    en = K.en_oldal(html)
    ellenoriz('<html lang="en">' in en and '<base href="/">' in en, "az /en/ oldalon hiányzik a lang=en vagy a <base href>")
    ellenoriz("megosztas_en.png" in en and "megosztas_hu.png" not in en, "az /en/ oldal nem az angol képet használja")
    ellenoriz(not re.search(r"épületeinek|hu_HU|Cselovszki Attila", en), "az /en/ oldalon magyar előnézeti szöveg maradt")
    ellenoriz(en.count("<title>") == 1 and "https://budapestbuildings.com/en/" in en, "az /en/ oldal címe/canonical hibás")
    for kep in ("megosztas_hu.png", "megosztas_en.png"):
        if not (GYOKER / "terkep3d" / kep).exists():
            figyelmeztet(f"hiányzik a terkep3d/{kep} (1200x630) - kép nélkül nincs nagy előnézet")
    js = (GYOKER / "terkep3d" / "app.js").read_text(encoding="utf-8")
    for p in ("get('lang')", "?tab=", "?architect=", "?estate=", "epiteszValaszt(e.k)", "lakValaszt(z.nev)", "melyLinkNincs"):
        ellenoriz(p in js, f"az app.js-ből hiányzik a mélylink-rész: {p}")
    return vege("teszt_megosztas")


if __name__ == "__main__":
    raise SystemExit(main())
