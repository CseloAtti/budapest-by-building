"""A korszakbecslés pontosságának őrzője. Futtatás: py tesztek/teszt_becsles.py
Nem számol újra semmit: az ev_becsles.py által írt mérési jelentést (data/varos/ev_becsles_jelentes.md) olvassa,
amely minden ismert évű épületet egyenként elrejt, és megméri, eltalálja-e a modell.
A teszt azt őrzi, hogy egy módosítás után a pontosság ne romoljon a mostani szint alá.
Mostani érték (2026.11.): találat ~52%, legfeljebb 1 korszakot téved ~76%, nem védett épületeken ~58%,
nem védett és rajzolt zónán kívül ~50% (a zónák a tudott évek ismeretében készültek, ezért a zónán belüli mérés túl jó)."""
import re
from kozos_teszt import GYOKER, ellenoriz, figyelmeztet, vege

JELENTES = GYOKER / "data" / "varos" / "ev_becsles_jelentes.md"
# alsó határok (a mostani értékek kicsit alatt, hogy a zaj ne okozzon hamis riasztást)
MIN_TALALAT = 0.48
MIN_EGY_KORSZAK = 0.72
MIN_NEM_VEDETT = 0.54
MAX_KSH_ELTERES = 4.0  # százalékpont
MIN_ZONAN_KIVUL = 0.46   # NEM védett, rajzolt zónán kívül (2026.11.: ~50%); ez a reális szám a szürke épületek többségére


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
    # a KSH-illesztés: a kerületi arányoktól való legnagyobb eltérés (2026.11.: 3,5 százalékpont, az '1867 előtt' szabály miatt)
    elter = [float(m.group(1)) for s in sorok for m in [re.search(r"\| [\d.]+ → ([\d.]+) \| x", s)] if m]
    if elter:
        ellenoriz(max(elter) <= MAX_KSH_ELTERES, f"a KSH-illesztés után egy kerület {max(elter):.1f} százalékponttal eltér (felső határ: {MAX_KSH_ELTERES})")
        print(f"  KSH: legnagyobb kerületi eltérés az illesztés után: {max(elter):.1f} százalékpont")
    # korszakonkénti gyenge pontok (tájékoztató)
    for s in sorok:
        m = re.match(r"\| (1867 előtt|2011-től) \| (\d+) \| (\d+)%", s)
        if m and int(m.group(3)) < 10:
            figyelmeztet(f"a(z) '{m.group(1)}' korszakot a modell gyakorlatilag nem találja el ({m.group(3)}%, {m.group(2)} ismert épület)")
    return vege("becsles")


if __name__ == "__main__":
    raise SystemExit(main())
