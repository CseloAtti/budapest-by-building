"""Közös segédek az ellenőrző tesztekhez (csak a Python alap könyvtárát használja)."""
import sys
from pathlib import Path

GYOKER = Path(__file__).resolve().parent.parent       # a projekt mappája
HIBAK = []
FIGYELMEZTETESEK = []


def hiba(uzenet):
    HIBAK.append(uzenet)
    print("  HIBA:", uzenet)


def figyelmeztet(uzenet):
    FIGYELMEZTETESEK.append(uzenet)
    print("  figyelem:", uzenet)


def ellenoriz(feltetel, uzenet):
    if not feltetel:
        hiba(uzenet)
    return bool(feltetel)


def vege(nev):
    print(f"[{nev}] {'SIKERES' if not HIBAK else 'SIKERTELEN: ' + str(len(HIBAK)) + ' hiba'}"
          f"{', ' + str(len(FIGYELMEZTETESEK)) + ' figyelmeztetés' if FIGYELMEZTETESEK else ''}")
    return 1 if HIBAK else 0
