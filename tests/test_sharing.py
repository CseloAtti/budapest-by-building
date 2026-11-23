"""Checking the share preview (OG tags, the /en/ page) and the deep links.   Run: py tests/test_sharing.py"""
import re
import sys
from test_common import ROOT, check, warn, end_

sys.path.insert(0, str(ROOT))
import build_release as K


def main():
    print("[megosztas] OG-címkék, /en/ oldal, mélylinkek")
    html = (ROOT / "terkep3d" / "index.html").read_text(encoding="utf-8")
    check(html.count("<!--OG-->") == 1 and html.count("<!--/OG-->") == 1, "az index.html-ben nincs pontosan egy <!--OG--> blokk")
    for c in ("og:title", "og:description", "og:image", "og:url", "twitter:card", 'name="description"', 'rel="canonical"'):
        check(c in html, f"hiányzik az index.html-ből: {c}")
    check(html.count("<title>") == 1, "az index.html-ben több <title> van")
    en = K.en_page(html)
    check('<html lang="en">' in en and '<base href="/">' in en, "az /en/ oldalon hiányzik a lang=en vagy a <base href>")
    check("megosztas_en.png" in en and "megosztas_hu.png" not in en, "az /en/ oldal nem az angol képet használja")
    check(not re.search(r"épületeinek|hu_HU|Cselovszki Attila", en), "az /en/ oldalon magyar előnézeti szöveg maradt")
    check(en.count("<title>") == 1 and "https://budapestbuildings.com/en/" in en, "az /en/ oldal címe/canonical hibás")
    for image in ("megosztas_hu.png", "megosztas_en.png"):
        if not (ROOT / "terkep3d" / image).exists():
            warn(f"hiányzik a terkep3d/{image} (1200x630) - kép nélkül nincs nagy előnézet")
    js = (ROOT / "terkep3d" / "app.js").read_text(encoding="utf-8")
    for p in ("get('lang')", "?tab=", "?architect=", "?estate=", "epiteszValaszt(e.k)", "lakValaszt(z.nev)", "melyLinkNincs"):
        check(p in js, f"az app.js-ből hiányzik a mélylink-rész: {p}")
    return end_("test_sharing")


if __name__ == "__main__":
    raise SystemExit(main())
