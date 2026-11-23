"""Checking the local quota (year_estimate.kvota_kiosztas, tomeg_illesztes). Run: py tests/test_local_quota.py
The error it catches: if in a neighbourhood every house is equally '20% old, 80% new', rounding to the most probable era
paints EVERY house new (Pesthidegkút: of 986 expected old houses 23 showed up). The quota allocation has to paint about 20% old,
and the old era goes to the houses at the front of the order (e.g. closer to the main road). No data file is needed, it is fast."""
import sys
from test_common import ROOT, check, end_

sys.path.insert(0, str(ROOT))


def main():
    print("[helyi_kvota] kvota_kiosztas")
    import year_estimate as eb
    K = eb.K
    n = 50
    houses = list(range(n))
    Q = {i: [0.0, 0.0, 0.2, 0.0, 0.0, 0.8, 0.0] for i in houses}       # 20% 1919–1944, 80% 1990–2010
    weights = [100.0] * n
    R = [sum(weights[i] * Q[i][c] for i in houses) for c in range(K)]
    order = {i: i for i in houses}                                     # smaller = "looks older" (e.g. closer to the main road)
    point = eb.allocate_quota(houses, houses, R, Q, weights, lambda i: order[i], set())
    era = {i: max(range(K), key=lambda x: point[i][x]) for i in houses}
    old = [i for i in houses if era[i] == 2]
    check(8 <= len(old) <= 12, f"20% régi háznak kellene lennie (kb. 10 az 50-ből), ennyi lett: {len(old)}")
    check(all(era[i] in (2, 5) for i in houses), "csak a két lehetséges korszak jöhet ki")
    check(old and max(old) < 20, f"a régi korszakot a sorrend elején álló házaknak kell kapniuk, ezek kapták: {old}")
    # nobody can get the forbidden 'before 1867' era
    Q0 = {i: [0.3, 0.7, 0, 0, 0, 0, 0] for i in houses}
    R0 = [sum(weights[i] * Q0[i][c] for i in houses) for c in range(K)]
    p0 = eb.allocate_quota(houses, houses, R0, Q0, weights, lambda i: i, set(houses))
    check(all(max(range(K), key=lambda x: p0[i][x]) != 0 for i in houses), "a tiltott '1867 előtt' korszakot egy ház megkapta")
    return end_("helyi_kvota")


if __name__ == "__main__":
    raise SystemExit(main())
