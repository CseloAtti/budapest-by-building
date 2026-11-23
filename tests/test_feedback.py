"""Source check of the behaviours fixed on the basis of tester feedback (on the text of app.js; it does not start a browser).   Run: py tests/test_feedback.py"""
from test_common import GYOKER, ellenoriz, vege


def main():
    print("[visszajelzes] galéria sorrend, mobil építész-menü, fülváltás, kamera-csillapítás")
    js = (GYOKER / "terkep3d" / "app.js").read_text(encoding="utf-8")
    ellenoriz("mut(ujabbDia())" in js and "mut(0);\n  hely.hidden" not in js, "a galéria nem a legújabb képpel indul (mut(0) maradt)")
    ellenoriz("function mobilMenuZar" in js and "if (innerWidth <= 700) mobilMenuZar();" in js, "mobilon az épület kiválasztásakor nem zárul be az építész-kártya és a főpanel")
    ellenoriz("var aktNezet" in js and "aktNezet !== n" in js and "archSzuro = null; archZonaAzon = new Set(); hazKiem = false; epAktiv = null" in js, "fülváltáskor nem törlődik az előző fül szűrése (halvány épületek)")
    ellenoriz("if (!document.getElementById('nez-arch').hidden) archKivalaszt(archKiv)" in js, "az archRender után nincs őrfeltétel (régi szűrés visszatérhet)")
    ellenoriz("if (document.getElementById('nez-epitesz').hidden) return;" in js, "az epiteszNezet várakozása után nincs őrfeltétel")
    ellenoriz("controls.dampingFactor = " in js and "setPixelRatio(1)" in js, "nincs időalapú kamera-csillapítás / lassú gépen a képpont-arány csökkentése")
    return vege("test_feedback")


if __name__ == "__main__":
    raise SystemExit(main())
