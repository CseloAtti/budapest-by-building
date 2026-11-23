"""Checking the threshold of the confidence bands (ev_becsles.bizonyossagi_kuszob). Run: py tesztek/teszt_becsles_kuszob.py
The error it catches: the threshold of the 'medium' band used to be computed with a cumulative hit rate (the hits of the 'high' band
were also counted), so the report wrote '>=70%' for a band that was really ~52%. Here, with invented data, we check
whether the band's OWN hit rate meets the target. No data file is needed, it is fast."""
import sys
from kozos_teszt import GYOKER, ellenoriz, vege

sys.path.insert(0, str(GYOKER))


def main():
    print("[becsles_kuszob] bizonyossagi_kuszob")
    import ev_becsles as eb
    # 100 'high' guesses (p=0.99, all hit), then 100 guesses at p=0.95 with a 50% hit rate, then 100 guesses at p=0.5 with 20%
    egyed = [(0.99, True)] * 100 + [(0.95, i % 2 == 0) for i in range(100)] + [(0.5, i % 5 == 0) for i in range(100)]
    k_magas = eb.bizonyossagi_kuszob(egyed, 0.85)
    ellenoriz(k_magas == 0.99, f"a 'magas' küszöb 0.99 kellene legyen, ez lett: {k_magas}")
    k_koz = eb.bizonyossagi_kuszob(egyed, 0.70, felso=k_magas)
    # the 0.95 band on its own is only 50%: it cannot be 'medium' (the old, cumulative computation would have given 0.95: (100+50)/200 = 75%)
    ellenoriz(k_koz is None, f"a 'közepes' sáv küszöbe None kellene legyen (a sáv csak 50%-os), ez lett: {k_koz}")
    # if the middle band is 80%, then it should be medium
    egyed2 = [(0.99, True)] * 100 + [(0.95, i % 5 != 0) for i in range(100)] + [(0.5, False)] * 100
    k2 = eb.bizonyossagi_kuszob(egyed2, 0.70, felso=0.99)
    ellenoriz(k2 == 0.95, f"80%-os középső sávnál a küszöb 0.95 kellene legyen, ez lett: {k2}")
    # little data (under 20) gives no threshold
    ellenoriz(eb.bizonyossagi_kuszob([(0.9, True)] * 10, 0.5) is None, "20-nál kevesebb épületből nem szabad küszöböt adni")
    return vege("becsles_kuszob")


if __name__ == "__main__":
    raise SystemExit(main())
