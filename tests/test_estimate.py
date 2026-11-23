"""The guardian of the era estimate's accuracy. Run: py tests/test_estimate.py
It does not recompute anything: it reads the measurement report written by year_estimate.py (data/varos/ev_becsles_jelentes.md),
which hides every building with a known year one by one, and measures whether the model hits it.
The test guards that after a change the accuracy does not fall below the present level.
Present values (Nov 2026): hit ~52%, off by at most 1 era ~76%, on non-protected buildings ~58%,
non-protected and outside the drawn zones ~50% (the zones were made knowing the years, so the measurement inside the zones is too good)."""
import re
from test_common import ROOT, check, warn, end_

REPORT = ROOT / "data" / "varos" / "ev_becsles_jelentes.md"
# lower bounds (slightly below the present values, so that noise does not cause a false alarm)
MIN_HIT = 0.48
MIN_ONE_ERA = 0.72
MIN_NOT_PROTECTED = 0.54
MAX_KSH_DEVIATION = 4.0  # percentage points
MIN_IN_ZONE_OUTSIDE = 0.46   # NOT protected, outside the drawn zones (Nov 2026: ~50%); this is the realistic number for most of the grey buildings


def percentages(row):
    return [int(x) / 100 for x in re.findall(r"(\d+)%", row)]


def main():
    print("[becsles] ev_becsles_jelentes.md")
    if not REPORT.exists():
        warn(f"nincs meg a jelentés: {REPORT} (futtasd: py year_estimate.py varos)")
        return end_("becsles")
    rows = REPORT.read_text(encoding="utf-8").splitlines()
    final = next((s for s in rows if s.startswith("| a végső modell (egyenként elrejtve)")), None)
    if check(final, "nem találom a jelentésben a 'végső modell' sort"):
        ta, ket, one = percentages(final)[:3]
        check(ta >= MIN_HIT, f"a találati arány lecsökkent: {ta:.0%} (alsó határ: {MIN_HIT:.0%})")
        check(one >= MIN_ONE_ERA, f"a '±1 korszak' arány lecsökkent: {one:.0%} (alsó határ: {MIN_ONE_ERA:.0%})")
        print(f"  találat: {ta:.0%}, első kettő: {ket:.0%}, ±1 korszak: {one:.0%}")
    nv = next((s for s in rows if s.startswith("| NEM védett")), None)
    if check(nv, "nem találom a 'NEM védett épületek' sort"):
        ta = percentages(nv)[0]
        check(ta >= MIN_NOT_PROTECTED, f"a nem védett épületek találati aránya lecsökkent: {ta:.0%} (alsó határ: {MIN_NOT_PROTECTED:.0%})")
        print(f"  nem védett épületeken: {ta:.0%}")
    zk = next((s for s in rows if s.startswith("| NEM védett, rajzolt zónán kívül")), None)
    if check(zk, "nem találom a 'NEM védett, rajzolt zónán kívül' sort (régi jelentés? futtasd: py year_estimate.py varos)"):
        ta = percentages(zk)[0]
        check(ta >= MIN_IN_ZONE_OUTSIDE, f"a rajzolt zónán kívüli nem védett épületek találati aránya lecsökkent: {ta:.0%} (alsó határ: {MIN_IN_ZONE_OUTSIDE:.0%})")
        print(f"  nem védett, rajzolt zónán kívül: {ta:.0%}")
    # the KSH fit: the largest deviation from the district proportions (Nov 2026: 3.5 percentage points, because of the 'before 1867' rule)
    differs = [float(m.group(1)) for s in rows for m in [re.search(r"\| [\d.]+ → ([\d.]+) \| x", s)] if m]
    if differs:
        check(max(differs) <= MAX_KSH_DEVIATION, f"a KSH-illesztés után egy kerület {max(differs):.1f} százalékponttal eltér (felső határ: {MAX_KSH_DEVIATION})")
        print(f"  KSH: legnagyobb kerületi eltérés az illesztés után: {max(differs):.1f} százalékpont")
    # weak points per era (informative)
    for s in rows:
        m = re.match(r"\| (1867 előtt|2011-től) \| (\d+) \| (\d+)%", s)
        if m and int(m.group(3)) < 10:
            warn(f"a(z) '{m.group(1)}' korszakot a modell gyakorlatilag nem találja el ({m.group(3)}%, {m.group(2)} ismert épület)")
    return end_("becsles")


if __name__ == "__main__":
    raise SystemExit(main())
