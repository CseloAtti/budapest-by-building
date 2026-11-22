"""A helyi kvóta ellenőrzése (ev_becsles.kvota_kiosztas, tomeg_illesztes). Futtatás: py tesztek/teszt_helyi_kvota.py
A hiba, amit megfog: ha egy környéken minden ház egyformán '20% régi, 80% új', a legvalószínűbb korszakra kerekítés
MINDEN házat újnak fest (Pesthidegkút: 986 várt régi házból 23 látszott). A kvótás kiosztásnak kb. 20%-ot régire kell festenie,
a régi korszakot pedig a sorrendben elöl álló (pl. főúthoz közelebbi) házak kapják. Nem kell hozzá adatfájl, gyors."""
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
    sorrend = {i: i for i in hazak}                                     # kisebb = "idősebbnek látszik" (pl. közelebb a főúthoz)
    pont = eb.kvota_kiosztas(hazak, hazak, R, Q, sulyok, lambda i: sorrend[i], set())
    kor = {i: max(range(K), key=lambda x: pont[i][x]) for i in hazak}
    regi = [i for i in hazak if kor[i] == 2]
    ellenoriz(8 <= len(regi) <= 12, f"20% régi háznak kellene lennie (kb. 10 az 50-ből), ennyi lett: {len(regi)}")
    ellenoriz(all(kor[i] in (2, 5) for i in hazak), "csak a két lehetséges korszak jöhet ki")
    ellenoriz(regi and max(regi) < 20, f"a régi korszakot a sorrend elején álló házaknak kell kapniuk, ezek kapták: {regi}")
    # a tiltott '1867 előtt' korszakot senki nem kaphatja meg
    Q0 = {i: [0.3, 0.7, 0, 0, 0, 0, 0] for i in hazak}
    R0 = [sum(sulyok[i] * Q0[i][c] for i in hazak) for c in range(K)]
    p0 = eb.kvota_kiosztas(hazak, hazak, R0, Q0, sulyok, lambda i: i, set(hazak))
    ellenoriz(all(max(range(K), key=lambda x: p0[i][x]) != 0 for i in hazak), "a tiltott '1867 előtt' korszakot egy ház megkapta")
    return vege("helyi_kvota")


if __name__ == "__main__":
    raise SystemExit(main())
