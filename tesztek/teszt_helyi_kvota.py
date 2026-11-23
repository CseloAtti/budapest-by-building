"""Checking the local quota (ev_becsles.kvota_kiosztas, tomeg_illesztes). Run: py tesztek/teszt_helyi_kvota.py
The error it catches: if in a neighbourhood every house is equally '20% old, 80% new', rounding to the most probable era
paints EVERY house new (Pesthidegkút: of 986 expected old houses 23 showed up). The quota allocation has to paint about 20% old,
and the old era goes to the houses at the front of the order (e.g. closer to the main road). No data file is needed, it is fast."""
import sys
from kozos_teszt import GYOKER, ellenoriz, vege

sys.path.insert(0, str(GYOKER))


def main():
    print("[helyi_kvota] kvota_kiosztas")
    import ev_becsles as eb
    K = eb.K
    n = 50
    hazak = list(range(n))
    Q = {i: [0.0, 0.0, 0.2, 0.0, 0.0, 0.8, 0.0] for i in hazak}       # 20% 1919–1944, 80% 1990–2010
    sulyok = [100.0] * n
    R = [sum(sulyok[i] * Q[i][c] for i in hazak) for c in range(K)]
    sorrend = {i: i for i in hazak}                                     # smaller = "looks older" (e.g. closer to the main road)
    pont = eb.kvota_kiosztas(hazak, hazak, R, Q, sulyok, lambda i: sorrend[i], set())
    kor = {i: max(range(K), key=lambda x: pont[i][x]) for i in hazak}
    regi = [i for i in hazak if kor[i] == 2]
    ellenoriz(8 <= len(regi) <= 12, f"20% régi háznak kellene lennie (kb. 10 az 50-ből), ennyi lett: {len(regi)}")
    ellenoriz(all(kor[i] in (2, 5) for i in hazak), "csak a két lehetséges korszak jöhet ki")
    ellenoriz(regi and max(regi) < 20, f"a régi korszakot a sorrend elején álló házaknak kell kapniuk, ezek kapták: {regi}")
    # nobody can get the forbidden 'before 1867' era
    Q0 = {i: [0.3, 0.7, 0, 0, 0, 0, 0] for i in hazak}
    R0 = [sum(sulyok[i] * Q0[i][c] for i in hazak) for c in range(K)]
    p0 = eb.kvota_kiosztas(hazak, hazak, R0, Q0, sulyok, lambda i: i, set(hazak))
    ellenoriz(all(max(range(K), key=lambda x: p0[i][x]) != 0 for i in hazak), "a tiltott '1867 előtt' korszakot egy ház megkapta")
    return vege("helyi_kvota")


if __name__ == "__main__":
    raise SystemExit(main())
