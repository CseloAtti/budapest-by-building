"""
ev_becsles.py - a szürke (ismeretlen építési évű) épületek korszakának BECSLÉSE.

Futtatás (a projekt mappájában):   py ev_becsles.py

Csak a Python alap könyvtárát használja (nincs pip install).

Mit csinál?
  1. Beolvassa a data/belvaros_epuletek_vegleges.geojson-t. Ahol van ismert év (ev), az
     "címkézett" épület; ahol nincs, azt becsüljük.
  2. Minden szürke épületre kiszámol egy valószínűség-eloszlást a 7 korszak fölött, négy
     bizonyítékból:
        szomszédok   - a közeli, ismert korú épületek (a közvetlenül összeépültek erősebben)
        utca         - az ugyanazon utcán lévő, ismert korú épületek
        alak         - szintszám, alapterület, épülettípus (naiv Bayes)
        zóna         - forras/varosfejlodes.json (a forrásolt zóna teljes, az ellenőrizendő 0,4 súllyal)
  3. A bizonyítékok súlyait az ismert épületeken méri ki: minden ismert épületet egyenként
     "elrejt", és megnézi, eltalálná-e. A mérésről jelentés készül.
  4. A becslés KÜLÖN fájlba kerül (data/ev_becsles.csv), az 'ev' mezőt soha nem írja át.

Kimenetek:
  data/ev_becsles.csv            - a becslés épületenként
  data/ev_becsles_jelentes.md    - mérési jelentés (pontosság, kalibráció, ablációk)
  data/ev_becsles_munkalista.csv - mely szürke épületeket érdemes kézzel utánanézni
"""
import csv
import json
import math
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

GYOKER = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
ADAT = GYOKER / "data"

# Azonos az index.html KORSZAKOK tömbjével (ha ott változik, itt is át kell írni).
KORSZAKOK = [
    (1, 1847, "1848 előtt"),
    (1848, 1918, "1848–1918"),
    (1919, 1944, "1919–1944"),
    (1945, 1956, "1945–1956"),
    (1957, 1989, "1957–1989"),
    (1990, 2010, "1990–2010"),
    (2011, 9999, "2011-től"),
]
K = len(KORSZAKOK)

SZOMSZED_SUGAR = 150.0     # m: eddig számít egy ismert épület szomszédnak
SZOMSZED_LECSENGES = 40.0  # m: a súly exp(-d/40)
ERINTKEZES_M = 1.0         # m: ha két épületnek van 1 m-en belüli csúcsa, összeépültnek vesszük
ERINTKEZES_SZORZO = 3.0
BLOKK_M = 300.0            # m: a "blokk-kizárásos" próba rácsmérete


def korszak_index(ev):
    for i, (tol, ig, _) in enumerate(KORSZAKOK):
        if tol <= ev <= ig:
            return i
    return None


def egyszerusit(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return "".join(c for c in s if c.isalnum())


# ---------------------------------------------------------------- beolvasás
def epuletek_beolvasasa():
    g = json.load(open(ADAT / "belvaros_epuletek_vegleges.geojson", encoding="utf-8"))
    lista = []
    for f in g["features"]:
        p = f["properties"]
        if p.get("resz"):
            continue  # épületrészeket nem becslünk (öröklik a szülő épületet)
        geo = f["geometry"]
        if geo["type"] == "Polygon":
            gyuru = geo["coordinates"][0]
        elif geo["type"] == "MultiPolygon":
            gyuru = geo["coordinates"][0][0]
        else:
            continue
        pts = [((x - 19.05) * math.cos(math.radians(47.5)) * 111320.0, (y - 47.5) * 110574.0)
               for x, y in gyuru]
        a2 = cx = cy = 0.0
        for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
            c = x0 * y1 - x1 * y0
            a2 += c
            cx += (x0 + x1) * c
            cy += (y0 + y1) * c
        if abs(a2) < 1e-6:
            continue
        terulet = abs(a2) / 2
        kerulet = sum(math.dist(a, b) for a, b in zip(pts, pts[1:] + pts[:1]))
        ev = p.get("ev")
        try:
            ev = int(ev) if ev not in (None, "") else None
        except (TypeError, ValueError):
            ev = None
        lista.append({
            "kulcs": (p.get("osm_tipus") or "way", int(p["id"])),
            "x": cx / (3 * a2), "y": cy / (3 * a2), "pts": pts,
            "terulet": terulet, "kompakt": 4 * math.pi * terulet / (kerulet ** 2),
            "szintek": p.get("szintek"), "magassag": p.get("magassag"),
            "tipus": p.get("tipus") or "yes", "ev": ev,
            "kor": korszak_index(ev) if ev else None,
            "vedett": bool(p.get("vedettseg")), "nev": p.get("nev") or "",
        })
    return lista


def utcak_beolvasasa(epuletek):
    atnev = {}
    ut = GYOKER / "forras" / "utcanev_atnevezesek.csv"
    if ut.exists():
        for r in csv.DictReader(open(ut, encoding="utf-8-sig"), delimiter=";"):
            if "|" not in (r["uj"] or ""):
                atnev[egyszerusit(r["regi"])] = r["uj"]
    cimek = {}
    ut = ADAT / "osm_cimek.csv"
    if ut.exists():
        for r in csv.DictReader(open(ut, encoding="utf-8-sig"), delimiter=";"):
            k = (r["osm_tipus"], int(r["id"]))
            u = atnev.get(egyszerusit(r["utca"]), r["utca"])
            cimek.setdefault(k, egyszerusit(u))
    for e in epuletek:
        e["utca"] = cimek.get(e["kulcs"])


def zonak_beolvasasa():
    ut = GYOKER / "forras" / "varosfejlodes.json"
    if not ut.exists():
        return {}
    d = json.load(open(ut, encoding="utf-8"))
    sulyok = d.get("_sulyok", {"forrasolt": 1.0, "ellenorizendo": 0.4})
    utca_zona = {}
    for z in d["zonak"]:
        if z.get("tipus") != "utcak" or not z.get("idoszak"):
            continue  # a sokszög-zónákhoz még nincs határ rajzolva
        tol, ig = z["idoszak"]
        atfedes = []
        for a, b, _ in KORSZAKOK:
            o = max(0, min(ig, b) - max(tol, a) + 1)
            atfedes.append(o / (ig - tol + 1))
        eloszlas = [0.9 * x + 0.1 / K for x in atfedes]
        for u in z["utcak"]:
            utca_zona[egyszerusit(u)] = (z["id"], eloszlas, sulyok.get(z["allapot"], 0.4))
    return utca_zona


# ---------------------------------------------------------------- térbeli kapcsolatok
def szomszedok_epitese(ep):
    n = len(ep)
    cella = defaultdict(list)
    for i, e in enumerate(ep):
        cella[(int(e["x"] // SZOMSZED_SUGAR), int(e["y"] // SZOMSZED_SUGAR))].append(i)
    csucs = defaultdict(set)
    for i, e in enumerate(ep):
        for x, y in e["pts"]:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    pass
            csucs[(int(x // 2), int(y // 2))].add(i)
    erint = [set() for _ in range(n)]
    for i, e in enumerate(ep):
        for x, y in e["pts"]:
            cx, cy = int(x // 2), int(y // 2)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for j in csucs.get((cx + dx, cy + dy), ()):
                        if j != i and j not in erint[i]:
                            if any(math.dist((x, y), q) <= ERINTKEZES_M for q in ep[j]["pts"]):
                                erint[i].add(j)
                                erint[j].add(i)
    szomsz = []
    for i, e in enumerate(ep):
        cx, cy = int(e["x"] // SZOMSZED_SUGAR), int(e["y"] // SZOMSZED_SUGAR)
        sor = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in cella.get((cx + dx, cy + dy), ()):
                    if j == i:
                        continue
                    d = math.dist((e["x"], e["y"]), (ep[j]["x"], ep[j]["y"]))
                    if d <= SZOMSZED_SUGAR:
                        sor.append((j, d, j in erint[i]))
        szomsz.append(sor)
    return szomsz


# ---------------------------------------------------------------- alak-jellemzők
def tipus_csoport(t):
    if t == "apartments":
        return "lakoepulet"
    if t in ("yes", "residential", "house"):
        return "altalanos"
    if t in ("office", "commercial", "retail", "hotel"):
        return "kereskedelmi"
    return "kozint_egyeb"


def jellemzok(e):
    sz = e["szintek"]
    try:
        sz = float(sz)
    except (TypeError, ValueError):
        sz = None
    if sz is None:
        szs = "?"
    elif sz <= 2:
        szs = "1-2"
    elif sz <= 4:
        szs = "3-4"
    elif sz <= 5:
        szs = "5"
    elif sz <= 6:
        szs = "6"
    else:
        szs = "7+"
    t = e["terulet"]
    ter = "<150" if t < 150 else "<300" if t < 300 else "<600" if t < 600 else "<1200" if t < 1200 else "1200+"
    kom = "kompakt" if e["kompakt"] > 0.6 else "tagolt"
    return {"szint": szs, "terulet": ter, "tipus": tipus_csoport(e["tipus"]), "forma": kom}


FELT_ERTEKEK = {  # a laplace-simításhoz: hány lehetséges érték van
    "szint": 6, "terulet": 5, "tipus": 4, "forma": 2,
}


class Modell:
    """A címkézett épületekből számolt táblák (osztály-gyakoriságok, alak-táblák)."""

    def __init__(self, ep, tanito):
        self.ep = ep
        self.tanito = set(tanito)
        self.db = [0] * K
        self.alak = {f: [Counter() for _ in range(K)] for f in FELT_ERTEKEK}
        self.jell = {}
        for i in self.tanito:
            self.hozzaad(i, +1)

    def hozzaad(self, i, elojel):
        e = self.ep[i]
        y = e["kor"]
        self.db[y] += elojel
        j = self.jell.get(i) or jellemzok(e)
        self.jell[i] = j
        for f, v in j.items():
            self.alak[f][y][v] += elojel

    def alapeloszlas(self, kizart=()):
        db = list(self.db)
        for i in kizart:
            if i in self.tanito:
                db[self.ep[i]["kor"]] -= 1
        ossz = sum(db)
        return [(c + 1) / (ossz + K) for c in db]


def komponensek(i, ep, szomsz, m, utca_index, zonak, kizart):
    """Visszaadja az i. épület négy bizonyítékát log-valószínűségként (K hosszú listák).
    kizart: azok az indexek, amelyek címkéjét nem szabad látnia (önmaga, ill. a blokk)."""
    e = ep[i]
    kiz = set(kizart) | {i}
    alap = m.alapeloszlas(kiz)
    # szomszédok
    N = [0.0] * K
    for j, d, erint in szomsz[i]:
        if j in kiz or j not in m.tanito:
            continue
        w = math.exp(-d / SZOMSZED_LECSENGES) * (ERINTKEZES_SZORZO if erint else 1.0)
        N[ep[j]["kor"]] += w
    ossz = sum(N)
    a = 0.5
    lN = [math.log((N[y] + a * alap[y]) / (ossz + a)) for y in range(K)]
    # utca
    lS = [0.0] * K
    if e["utca"]:
        C = [0] * K
        for j in utca_index.get(e["utca"], ()):
            if j not in kiz and j in m.tanito:
                C[ep[j]["kor"]] += 1
        n = sum(C)
        lS = [math.log((C[y] + 2 * alap[y]) / (n + 2)) for y in range(K)]
    # alak (naiv Bayes)
    j = jellemzok(e)
    db = list(m.db)
    for t in kiz:
        if t in m.tanito:
            db[ep[t]["kor"]] -= 1
    lF = [0.0] * K
    for f, v in j.items():
        for y in range(K):
            c = m.alak[f][y][v]
            for t in kiz:
                if t in m.tanito and ep[t]["kor"] == y and m.jell[t][f] == v:
                    c -= 1
            lF[y] += math.log((c + 1) / (db[y] + FELT_ERTEKEK[f]))
    # zóna
    lZ = [0.0] * K
    zsuly = 0.0
    z = zonak.get(e["utca"]) if e["utca"] else None
    if z:
        lZ = [math.log(p) for p in z[1]]
        zsuly = z[2]
    l0 = [math.log(p) for p in alap]
    return {"0": l0, "N": lN, "S": lS, "F": lF, "Z": lZ, "zsuly": zsuly}


def eloszlas(k, w):
    s = []
    for y in range(K):
        s.append(w["0"] * k["0"][y] + w["N"] * k["N"][y] + w["S"] * k["S"][y]
                 + w["F"] * k["F"][y] + w["Z"] * k["zsuly"] * k["Z"][y])
    mx = max(s)
    ex = [math.exp(v - mx) for v in s]
    t = sum(ex)
    return [v / t for v in ex]


# ---------------------------------------------------------------- mérés
def metrikak(par):
    """par: [(igazi_index, eloszlas)] -> szótár"""
    if not par:
        return {"n": 0}
    n = len(par)
    pont = sum(1 for y, p in par if max(range(K), key=lambda q: p[q]) == y)
    top2 = sum(1 for y, p in par if y in sorted(range(K), key=lambda q: -p[q])[:2])
    ll = -sum(math.log(max(p[y], 1e-9)) for y, p in par) / n
    # egy korszakot lépő tévedés: az igazihoz képest szomszédos korszak
    kozel = sum(1 for y, p in par if abs(max(range(K), key=lambda q: p[q]) - y) <= 1)
    return {"n": n, "pontossag": pont / n, "top2": top2 / n, "logloss": ll, "legfeljebb_1_korszak_tevedes": kozel / n}


def sulyok_racs():
    for wn in (0.0, 0.5, 1.0, 1.5):
        for ws in (0.0, 0.3, 0.6):
            for wf in (0.0, 0.3, 0.6, 1.0):
                for wz in (0.0, 0.5, 1.0):
                    for w0 in (0.0, 0.5, 1.0):
                        yield {"0": w0, "N": wn, "S": ws, "F": wf, "Z": wz}


def kiertekel(rendezett, komp, w):
    return [(ep_y, eloszlas(k, w)) for ep_y, k in zip(rendezett, komp)]


def main():
    ep = epuletek_beolvasasa()
    utcak_beolvasasa(ep)
    zonak = zonak_beolvasasa()
    szomsz = szomszedok_epitese(ep)
    cimkezett = [i for i, e in enumerate(ep) if e["kor"] is not None]
    szurke = [i for i, e in enumerate(ep) if e["kor"] is None]
    utca_index = defaultdict(list)
    for i, e in enumerate(ep):
        if e["utca"]:
            utca_index[e["utca"]].append(i)
    m = Modell(ep, cimkezett)

    # --- 1) "egyenként elrejtős" komponensek
    kp_loo = {i: komponensek(i, ep, szomsz, m, utca_index, zonak, ()) for i in cimkezett}
    # --- 2) blokk-kizárásos komponensek (szigorúbb próba)
    blokk = defaultdict(list)
    for i in cimkezett:
        blokk[(int(ep[i]["x"] // BLOKK_M), int(ep[i]["y"] // BLOKK_M))].append(i)
    kp_blokk = {}
    for b, tagok in blokk.items():
        for i in tagok:
            kp_blokk[i] = komponensek(i, ep, szomsz, m, utca_index, zonak, tagok)

    # --- 3) súlyok keresztillesztése: az egyik fél térbeli blokkjain hangolunk, a másikon mérünk
    def fel(i):
        b = (int(ep[i]["x"] // BLOKK_M), int(ep[i]["y"] // BLOKK_M))
        return (b[0] * 7 + b[1] * 13) % 2

    def legjobb_suly(indexek):
        legjobb = None
        for w in sulyok_racs():
            ll = metrikak([(ep[i]["kor"], eloszlas(kp_loo[i], w)) for i in indexek])["logloss"]
            if legjobb is None or ll < legjobb[0]:
                legjobb = (ll, w)
        return legjobb[1]

    A = [i for i in cimkezett if fel(i) == 0]
    B = [i for i in cimkezett if fel(i) == 1]
    wA, wB = legjobb_suly(A), legjobb_suly(B)
    keresztillesztett = [(ep[i]["kor"], eloszlas(kp_loo[i], wA)) for i in B] + \
                        [(ep[i]["kor"], eloszlas(kp_loo[i], wB)) for i in A]
    w_vegso = legjobb_suly(cimkezett)

    # --- 4) jelentés
    ures = {"0": 0, "N": 0, "S": 0, "F": 0, "Z": 0}
    alap_csak = dict(ures, **{"0": 1.0})
    sor = {}
    sor["a legtöbbször előforduló korszak tippelése"] = metrikak([(ep[i]["kor"], eloszlas(kp_loo[i], alap_csak)) for i in cimkezett])
    sor["a végső modell (egyenként elrejtve)"] = metrikak([(ep[i]["kor"], eloszlas(kp_loo[i], w_vegso)) for i in cimkezett])
    sor["a végső modell (keresztillesztett súlyokkal)"] = metrikak(keresztillesztett)
    sor["a végső modell (300 m-es blokk kizárva)"] = metrikak([(ep[i]["kor"], eloszlas(kp_blokk[i], w_vegso)) for i in cimkezett])
    abl = {}
    for nev, kulcs in (("szomszédok nélkül", "N"), ("utca nélkül", "S"), ("alak nélkül", "F"), ("zóna nélkül", "Z"), ("alapeloszlás nélkül", "0")):
        w = dict(w_vegso)
        w[kulcs] = 0.0
        abl[nev] = metrikak([(ep[i]["kor"], eloszlas(kp_loo[i], w)) for i in cimkezett])

    nem_vedett = [i for i in cimkezett if not ep[i]["vedett"]]
    alcsoport = {
        "védett épületek": metrikak([(ep[i]["kor"], eloszlas(kp_loo[i], w_vegso)) for i in cimkezett if ep[i]["vedett"]]),
        "NEM védett épületek": metrikak([(ep[i]["kor"], eloszlas(kp_loo[i], w_vegso)) for i in nem_vedett]),
    }
    korszakonkent = {}
    for y in range(K):
        par = [(ep[i]["kor"], eloszlas(kp_loo[i], w_vegso)) for i in cimkezett if ep[i]["kor"] == y]
        if par:
            talalt = sum(1 for yy, p in par if max(range(K), key=lambda q: p[q]) == yy)
            korszakonkent[y] = (len(par), talalt / len(par))
    zsor = Counter()
    for i in cimkezett:
        zsor["zónával" if kp_loo[i]["zsuly"] > 0 else "zóna nélkül"] += 1
    ossz_szurke_zona = sum(1 for i in szurke if zonak.get(ep[i]["utca"]))

    # zavaró mátrix és kalibráció
    zav = [[0] * K for _ in range(K)]
    kal = defaultdict(lambda: [0, 0])
    for i in cimkezett:
        p = eloszlas(kp_loo[i], w_vegso)
        top = max(range(K), key=lambda q: p[q])
        zav[ep[i]["kor"]][top] += 1
        sav = min(int(p[top] * 10), 9) / 10
        kal[sav][0] += 1
        kal[sav][1] += (top == ep[i]["kor"])
    # bizonyossági küszöbök
    egyed = sorted(((max(eloszlas(kp_loo[i], w_vegso)),
                     max(range(K), key=lambda q: eloszlas(kp_loo[i], w_vegso)[q]) == ep[i]["kor"])
                    for i in cimkezett), reverse=True)

    def kuszob(cel):
        legjobb = None
        talalt = 0
        for n, (p, ok) in enumerate(egyed, 1):
            talalt += ok
            if talalt / n >= cel and n >= 20:
                legjobb = p
        return legjobb

    k_magas, k_kozepes = kuszob(0.85), kuszob(0.70)

    # --- 5) a szürke épületek becslése
    ut_becsles = ADAT / "ev_becsles.csv"
    szur_eredmeny = []
    for i in szurke:
        k = komponensek(i, ep, szomsz, m, utca_index, zonak, ())
        p = eloszlas(k, w_vegso)
        top = max(range(K), key=lambda q: p[q])
        szomsz_db = sum(1 for j, d, _ in szomsz[i] if d <= 60 and j in m.tanito)
        if k_magas is not None and p[top] >= k_magas:
            biz = "magas"
        elif k_kozepes is not None and p[top] >= k_kozepes:
            biz = "kozepes"
        else:
            biz = "alacsony"
        ent = -sum(v * math.log(v) for v in p if v > 0)
        ism_szomsz_60 = szomsz_db
        osszes_szomsz_60 = sum(1 for j, d, _ in szomsz[i] if d <= 60)
        indok = f"{ism_szomsz_60} ismert korú szomszéd 60 m-en belül"
        if ep[i]["utca"] and zonak.get(ep[i]["utca"]):
            indok += f"; zóna: {zonak[ep[i]['utca']][0]}"
        szur_eredmeny.append((i, p, top, biz, ent, osszes_szomsz_60 - ism_szomsz_60, indok))

    with open(ut_becsles, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["osm_tipus", "id", "becsult_korszak", "valoszinuseg", "bizonyossag"]
                   + [f"p_{k[2]}" for k in KORSZAKOK] + ["indoklas"])
        for i, p, top, biz, ent, _, indok in szur_eredmeny:
            w.writerow([ep[i]["kulcs"][0], ep[i]["kulcs"][1], KORSZAKOK[top][2], f"{p[top]:.2f}", biz]
                       + [f"{v:.3f}" for v in p] + [indok])

    with open(ADAT / "ev_becsles_munkalista.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["osm_tipus", "id", "nev", "becsult_korszak", "valoszinuseg", "bizonyossag",
                    "ismeretlen_szomszed_60m", "bizonytalansag", "terulet_m2", "miert"])
        sor_w = sorted(szur_eredmeny, key=lambda r: -(r[4] * (1 + r[5]) * math.sqrt(ep[r[0]]["terulet"])))
        for i, p, top, biz, ent, isz, indok in sor_w[:300]:
            w.writerow([ep[i]["kulcs"][0], ep[i]["kulcs"][1], ep[i]["nev"], KORSZAKOK[top][2],
                        f"{p[top]:.2f}", biz, isz, f"{ent:.2f}", int(ep[i]["terulet"]),
                        "bizonytalan és sok ismeretlen szomszéd veszi körül: egy kézi adat sokat javít"])

    def pct(x):
        return f"{100 * x:.0f}%"

    def sort(nev, d):
        return f"| {nev} | {d['n']} | {pct(d['pontossag'])} | {pct(d['top2'])} | {pct(d['legfeljebb_1_korszak_tevedes'])} | {d['logloss']:.2f} |"

    fej = "| | db | találat | az első kettő között | legfeljebb 1 korszakot téved | log-veszteség (kisebb a jobb) |\n|---|---|---|---|---|---|"
    s = []
    s.append("# Építési korszak becslés: mérési jelentés\n")
    s.append(f"Címkézett (ismert évű) épület: **{len(cimkezett)}**; szürke, becsült: **{len(szurke)}**; épületrészt nem becslünk.\n")
    s.append("A mérés úgy megy, hogy minden ismert épületet egyenként elrejtünk, és megnézzük, eltalálná-e a modell.\n")
    s.append("## Fő eredmények\n\n" + fej)
    for nev, d in sor.items():
        s.append(sort(nev, d))
    s.append("\n## Mit ad az egyes bizonyíték? (a végső modellből kihagyva)\n\n" + fej)
    for nev, d in abl.items():
        s.append(sort(nev, d))
    s.append(f"\nVégső súlyok: {w_vegso}\n")
    s.append("\n## Védett és nem védett épületek külön\n\nAz ismert évű épületek jelentős része védett, a szürkék többsége viszont nem az, ezért a *nem védett* sor a reálisabb.\n\n" + fej)
    for nev, d in alcsoport.items():
        s.append(sort(nev, d))
    s.append("\n## Korszakonként: hányat talál el?\n\n| korszak | ismert db | találat |\n|---|---|---|")
    for y, (n, a) in korszakonkent.items():
        s.append(f"| {KORSZAKOK[y][2]} | {n} | {pct(a)} |")
    s.append("\nA 1945 utáni korszakoknál kevés az ismert példa, ezért ott a becslés megbízhatatlanabb.\n")
    s.append("## Kalibráció: amit a modell X%-osra mond, az valójában mennyi?\n\n| a modell biztonsága | db | tényleges találat |\n|---|---|---|")
    for sav in sorted(kal):
        n, t = kal[sav]
        s.append(f"| {int(sav * 100)}–{int(sav * 100) + 10}% | {n} | {pct(t / n)} |")
    s.append(f"\nBizonyossági sávok: **magas** ≥ {k_magas and round(k_magas, 2)} (mért találat ≥ 85%), "
             f"**közepes** ≥ {k_kozepes and round(k_kozepes, 2)} (≥ 70%), különben **alacsony**.\n")
    sav_sor = []
    for nev, lo, hi in (("magas", k_magas, 2), ("közepes", k_kozepes, k_magas), ("alacsony", 0, k_kozepes)):
        if lo is None or hi is None:
            continue
        a = [(ep[i]["kor"], eloszlas(kp_loo[i], w_vegso)) for i in nem_vedett]
        a = [(y, p) for y, p in a if lo <= max(p) < hi]
        if a:
            t = sum(1 for y, p in a if max(range(K), key=lambda q: p[q]) == y)
            sav_sor.append(f"- {nev}: {len(a)} nem védett ismert épületből {pct(t / len(a))} találat")
    s.append("A bizonyossági sávok tényleges találata csak a NEM védett épületeken:\n\n" + "\n".join(sav_sor) + "\n")
    s.append("## Zavaró mátrix (sor: igazi, oszlop: becsült)\n\n| | " + " | ".join(k[2] for k in KORSZAKOK) + " |\n|---|" + "---|" * K)
    for y in range(K):
        s.append(f"| {KORSZAKOK[y][2]} | " + " | ".join(str(v) for v in zav[y]) + " |")
    s.append("\n## A szürke épületek becslése\n")
    szamlalo = Counter((KORSZAKOK[t][2], b) for _, _, t, b, _, _, _ in szur_eredmeny)
    s.append("| korszak | magas | közepes | alacsony |\n|---|---|---|---|")
    for _, _, nev in KORSZAKOK:
        s.append(f"| {nev} | {szamlalo[(nev, 'magas')]} | {szamlalo[(nev, 'kozepes')]} | {szamlalo[(nev, 'alacsony')]} |")
    s.append(f"\nZóna-támpont {ossz_szurke_zona} szürke épületnél érvényes (utca-egyezés alapján).\n")
    s.append("## Amit nem tud a modell\n\n"
             "- A tanítóadat torz: sok az 1848–1918-as és a védett épület, kevés az 1945 utáni.\n"
             "- A zónák csak az utcát nézik, a háborús pótlásokat és későbbi beépítéseket nem.\n"
             "- A kortárs és modernista épületek listái (később) fogják javítani a 1945 utáni korszakokat.\n"
             "- A becslés soha nem kerül az `ev` mezőbe, és a térképen külön, halványabb rétegként látszik.\n")
    (ADAT / "ev_becsles_jelentes.md").write_text("\n".join(s), encoding="utf-8")
    print("\n".join(s))


if __name__ == "__main__":
    main()
