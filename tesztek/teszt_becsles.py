"""The guardian of the era estimate's accuracy. Run: py tesztek/teszt_becsles.py
It does not recompute anything: it reads the measurement report written by ev_becsles.py (data/varos/ev_becsles_jelentes.md),
which hides every building with a known year one by one, and measures whether the model hits it.
The test guards that after a change the accuracy does not fall below the present level.
Present values (Nov 2026): hit ~52%, off by at most 1 era ~76%, on non-protected buildings ~58%,
non-protected and outside the drawn zones ~50% (the zones were made knowing the years, so the measurement inside the zones is too good)."""
import re
from kozos_teszt import GYOKER, ellenoriz, figyelmeztet, vege

JELENTES = GYOKER / "data" / "varos" / "ev_becsles_jelentes.md"
# lower bounds (slightly below the present values, so that noise does not cause a false alarm)
MIN_TALALAT = 0.48
MIN_EGY_KORSZAK = 0.72
MIN_NEM_VEDETT = 0.54
MAX_KSH_ELTERES = 4.0  # percentage points
MIN_ZONAN_KIVUL = 0.46   # NOT protected, outside the drawn zones (Nov 2026: ~50%); this is the realistic number for most of the grey buildings


def szazalekok(sor):
    return [int(x) / 100 for x in re.findall(r"(\d+)%", sor)]


def main():
    print("[becsles] ev_becsles_jelentes.md")
    if not JELENTES.exists():
        figyelmeztet(f"nincs meg a jelentés: {JELENTES} (futtasd: py ev_becsles.py varos)")
        return vege("becsles")
    sorok = JELENTES.read_text(encoding="utf-8").splitlines()
    vegso = next((s for s in sorok if s.startswith("| a végső modell (egyenként elrejtve)")), None)
    if ellenoriz(vegso, "nem találom a jelentésben a 'végső modell' sort"):
        ta, ket, egy = szazalekok(vegso)[:3]
        ellenoriz(ta >= MIN_TALALAT, f"a találati arány lecsökkent: {ta:.0%} (alsó határ: {MIN_TALALAT:.0%})")
        ellenoriz(egy >= MIN_EGY_KORSZAK, f"a '±1 korszak' arány lecsökkent: {egy:.0%} (alsó határ: {MIN_EGY_KORSZAK:.0%})")
        print(f"  találat: {ta:.0%}, első kettő: {ket:.0%}, ±1 korszak: {egy:.0%}")
    nv = next((s for s in sorok if s.startswith("| NEM védett")), None)
    if ellenoriz(nv, "nem találom a 'NEM védett épületek' sort"):
        ta = szazalekok(nv)[0]
        ellenoriz(ta >= MIN_NEM_VEDETT, f"a nem védett épületek találati aránya lecsökkent: {ta:.0%} (alsó határ: {MIN_NEM_VEDETT:.0%})")
        print(f"  nem védett épületeken: {ta:.0%}")
    zk = next((s for s in sorok if s.startswith("| NEM védett, rajzolt zónán kívül")), None)
    if ellenoriz(zk, "nem találom a 'NEM védett, rajzolt zónán kívül' sort (régi jelentés? futtasd: py ev_becsles.py varos)"):
        ta = szazalekok(zk)[0]
        ellenoriz(ta >= MIN_ZONAN_KIVUL, f"a rajzolt zónán kívüli nem védett épületek találati aránya lecsökkent: {ta:.0%} (alsó határ: {MIN_ZONAN_KIVUL:.0%})")
        print(f"  nem védett, rajzolt zónán kívül: {ta:.0%}")
    # the KSH fit: the largest deviation from the district proportions (Nov 2026: 3.5 percentage points, because of the 'before 1867' rule)
    elter = [float(m.group(1)) for s in sorok for m in [re.search(r"\| [\d.]+ → ([\d.]+) \| x", s)] if m]
    if elter:
        ellenoriz(max(elter) <= MAX_KSH_ELTERES, f"a KSH-illesztés után egy kerület {max(elter):.1f} százalékponttal eltér (felső határ: {MAX_KSH_ELTERES})")
        print(f"  KSH: legnagyobb kerületi eltérés az illesztés után: {max(elter):.1f} százalékpont")
    # weak points per era (informative)
    for s in sorok:
        m = re.match(r"\| (1867 előtt|2011-től) \| (\d+) \| (\d+)%", s)
        if m and int(m.group(3)) < 10:
            figyelmeztet(f"a(z) '{m.group(1)}' korszakot a modell gyakorlatilag nem találja el ({m.group(3)}%, {m.group(2)} ismert épület)")
    return vege("becsles")


if __name__ == "__main__":
    raise SystemExit(main())
