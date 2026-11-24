"""Source check of the behaviours fixed on the basis of tester feedback (on the text of app.js; it does not start a browser).   Run: py tests/test_feedback.py"""
from test_common import ROOT, check, end_


def main():
    print("[visszajelzes] galéria sorrend, mobil építész-menü, fülváltás, kamera-csillapítás")
    js = (ROOT / "terkep3d" / "app.js").read_text(encoding="utf-8")
    check("mut(ujabbDia())" in js and "mut(0);\n  hely.hidden" not in js, "a galéria nem a legújabb képpel indul (mut(0) maradt)")
    check("function mobilMenuZar" in js and "if (innerWidth <= 700) mobilMenuZar();" in js, "mobilon az épület kiválasztásakor nem zárul be az építész-kártya és a főpanel")
    check("var aktNezet" in js and "aktNezet !== n" in js and "archSzuro = null; archZonaAzon = new Set(); hazKiem = false; epAktiv = null" in js, "fülváltáskor nem törlődik az előző fül szűrése (halvány épületek)")
    check("if (!document.getElementById('nez-arch').hidden) archKivalaszt(archKiv)" in js, "az archRender után nincs őrfeltétel (régi szűrés visszatérhet)")
    check("if (document.getElementById('nez-epitesz').hidden) return;" in js, "az epiteszNezet várakozása után nincs őrfeltétel")
    check("if (!document.getElementById('nez-lakotelep').hidden) { el.hidden = true; return; }" in js, "a lakótelep Wikipedia-popupjának bezárása visszaállítja a kamerát (a kijelölt lakótelepnél maradnia kell)")
    check("controls.dampingFactor = " in js and "setPixelRatio(1)" in js, "nincs időalapú kamera-csillapítás / lassú gépen a képpont-arány csökkentése")
    html = (ROOT / "terkep3d" / "index.html").read_text(encoding="utf-8")
    check('id="iranytu"' in html and 'id="mod2d"' in html and 'id="iranytu-tu"' in html, "az index.html-ből hiányzik az iránytű vagy a 2D/3D gomb")
    check("function mod2dBeallit" in js and "controls.enableRotate = false" in js and "iranytuFrissit();" in js and "navSzoveg();" in js, "az app.js-ből hiányzik a 2D mód vagy az iránytű frissítése")
    check("if (mod2d) c1.set(h.x, d, h.z);" in js, "2D módban a kezdőnézet nem felülnézet")
    return end_("test_feedback")


if __name__ == "__main__":
    raise SystemExit(main())
