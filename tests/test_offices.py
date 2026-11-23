"""Checking that the architecture offices leave the designer field and go to the 'iroda' (office) field (assemble.py: split_offices).
Run: py tests/test_offices.py. It also checks that the office list file exists and that the card shows the new fields."""
import sys
from test_common import ROOT, check, end_

sys.path.insert(0, str(ROOT))


def main():
    print("[irodak] a cégnevek átkerülnek a tervező mezőből az iroda mezőbe")
    import assemble
    keys, joined = assemble.load_offices(ROOT / "forras" / "epitesz_irodak.csv")
    check(len(keys) > 50, "az epitesz_irodak.csv-ből nem töltődött be elég iroda")
    check("archikon" in keys, "az Archikon nincs az irodák között")

    def run(tervezo, iroda=None):
        pr = {"tervezo": tervezo, "tervezo_forras": "oeny"}
        if iroda:
            pr["iroda"] = iroda
        assemble.split_offices([{"properties": pr}], keys, joined)
        return pr

    p = run("Nagy Csaba, Pólus Károly, Archikon")
    check(p.get("tervezo") == "Nagy Csaba, Pólus Károly" and p.get("iroda") == "Archikon", f"személyek + iroda: {p}")
    p = run("Archikon, Nagy Csaba")
    check(p.get("tervezo") == "Nagy Csaba" and p.get("iroda") == "Archikon", f"az iroda elöl áll: {p}")
    p = run("Just Lajos és Vajda Béla")
    check(p.get("tervezo") == "Just Lajos és Vajda Béla" and "iroda" not in p, f"két személy ' és ' között változatlan: {p}")
    p = run("Archikon")
    check("tervezo" not in p and "tervezo_forras" not in p and p.get("iroda") == "Archikon", f"csak iroda: a tervező mező törlődik: {p}")
    p = run("Zsuffa és Kalmár Építész Műterem, Szabó Levente")
    check(p.get("iroda") == "Zsuffa és Kalmár Építész Műterem" and p.get("tervezo") == "Szabó Levente", f"' és ' tartalmú iroda egy név marad: {p}")
    p = run("Nagy Csaba, Archikon", iroda="Archikon")
    check(p.get("iroda") == "Archikon", f"a kézi és a talált iroda nem duplázódik: {p}")
    p = run("Nagy Csaba, Archikon", iroda="Másik Iroda")
    check(p.get("iroda") == "Másik Iroda, Archikon", f"a kézi iroda megmarad, a talált hozzáfűződik: {p}")
    p = run("Feszl Frigyes")
    check(p.get("tervezo") == "Feszl Frigyes" and "iroda" not in p, f"személy érintetlen: {p}")

    js = (ROOT / "terkep3d" / "app.js").read_text(encoding="utf-8")
    check("p.iroda" in js and "p.iroda_link" in js, "az app.js nem jeleníti meg az iroda / iroda_link mezőt")
    check("rel=\"nofollow noopener noreferrer\"" in js, "az iroda-link nincs nofollow-val ellátva")
    check("iroda_link" in (ROOT / "build_tiles.py").read_text(encoding="utf-8"), "a build_tiles.py nem viszi át az iroda_link mezőt")
    return end_("irodak")


if __name__ == "__main__":
    raise SystemExit(main())
