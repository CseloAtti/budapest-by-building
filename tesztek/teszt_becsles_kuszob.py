"""A bizonyossági sávok küszöbének ellenőrzése (ev_becsles.bizonyossagi_kuszob). Futtatás: py tesztek/teszt_becsles_kuszob.py
A hiba, amit megfog: a 'közepes' sáv küszöbét korábban halmozott találati aránnyal számolta (a 'magas' sáv találatai is
beleszámítottak), ezért a jelentés '>=70%'-ot írt egy valójában ~52%-os sávra. Itt kitalált adattal ellenőrizzük,
hogy a sáv SAJÁT találati aránya teljesíti-e a célt. Nem kell hozzá adatfájl, gyors."""
import sys
from kozos_teszt import GYOKER, ellenoriz, vege

sys.path.insert(0, str(GYOKER))


def main():
    print("[becsles_kuszob] bizonyossagi_kuszob")
    import ev_becsles as eb
    # 100 'magas' tipp (p=0.99, mind talál), majd 100 tipp p=0.95 mellett 50%-os találattal, majd 100 tipp p=0.5, 20%-kal
    egyed = [(0.99, True)] * 100 + [(0.95, i % 2 == 0) for i in range(100)] + [(0.5, i % 5 == 0) for i in range(100)]
    k_magas = eb.bizonyossagi_kuszob(egyed, 0.85)
    ellenoriz(k_magas == 0.99, f"a 'magas' küszöb 0.99 kellene legyen, ez lett: {k_magas}")
    k_koz = eb.bizonyossagi_kuszob(egyed, 0.70, felso=k_magas)
    # a 0.95-ös sáv önmagában csak 50%-os: nem lehet 'közepes' (a régi, halmozott számolás 0.95-öt adott volna: (100+50)/200 = 75%)
    ellenoriz(k_koz is None, f"a 'közepes' sáv küszöbe None kellene legyen (a sáv csak 50%-os), ez lett: {k_koz}")
    # ha a középső sáv 80%-os, akkor legyen közepes
    egyed2 = [(0.99, True)] * 100 + [(0.95, i % 5 != 0) for i in range(100)] + [(0.5, False)] * 100
    k2 = eb.bizonyossagi_kuszob(egyed2, 0.70, felso=0.99)
    ellenoriz(k2 == 0.95, f"80%-os középső sávnál a küszöb 0.95 kellene legyen, ez lett: {k2}")
    # kevés adat (20 alatt) nem ad küszöböt
    ellenoriz(eb.bizonyossagi_kuszob([(0.9, True)] * 10, 0.5) is None, "20-nál kevesebb épületből nem szabad küszöböt adni")
    return vege("becsles_kuszob")


if __name__ == "__main__":
    raise SystemExit(main())
