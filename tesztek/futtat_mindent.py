"""Az összes ellenőrző teszt futtatása. A projekt mappájából:   py tesztek/futtat_mindent.py
Kilépési kód: 0 = minden rendben, 1 = legalább egy teszt hibát talált."""
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kozos_teszt

TESZTEK = ["teszt_kliens", "teszt_adatlapok", "teszt_adatok", "teszt_becsles", "teszt_becsles_kuszob", "teszt_helyi_kvota", "teszt_kereso", "teszt_reszek", "teszt_szerver", "teszt_letoltes", "teszt_felfedezo"]


def main():
    eredmeny = {}
    for nev in TESZTEK:
        kozos_teszt.HIBAK.clear()
        kozos_teszt.FIGYELMEZTETESEK.clear()
        try:
            eredmeny[nev] = importlib.import_module(nev).main()
        except FileNotFoundError as e:
            print(f"  kihagyva ({e.filename}): nincs meg a fájl")
            eredmeny[nev] = None
        print()
    print("Összegzés:")
    for nev, r in eredmeny.items():
        print(f"  {nev}: {'kihagyva' if r is None else ('SIKERES' if r == 0 else 'SIKERTELEN')}")
    return 1 if any(r for r in eredmeny.values() if r) else 0


if __name__ == "__main__":
    raise SystemExit(main())
