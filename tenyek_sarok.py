"""Hiányzó (pl. sarokházi) cím pótlása: az értékleltár nem párosított kártyáit a szomszédos házszámok alapján interpolált helyhez kötjük.

Bemenet:  data/ertekleltar_nem_parositott.csv (a tenyek_ertekleltar.py készíti), data/ertekleltar_kartyak.json,
          data/varos/epuletek.geojson, data/varos/osm_cimek.csv, forras/utcanev_atnevezesek.csv
Kimenet:  forras/ertekleltar_kezi_parositas.csv   - a bizonytalan kártyák táblázata (EZT töltöd ki: az 'osm_azonosito' oszlopba írd az épület azonosítóját, pl. \"way 271003349\"; a 'javasolt_osm' a program tippje, a 'valószínű' soroknál kb. 88% eséllyel jó)
          data/varos/ertekleltar_sarok_kozelito.csv - szöveges korszakadatok ('1920-as évek') az így párosított épületekre
          data/tenyek/ertekleltar_sarok.csv       - az egyértelmű (kb. 95%-os pontosságú) párosítások tényei az osszeepit.py-hoz
          data/ertekleltar_sarok_javaslat.csv      - minden nem párosított kártya: állapot + jelöltek (kézi ellenőrzéshez)

Módszer: a kártya "utca N" címéhez az utca azonos kerületi, azonos paritású ismert házszámaiból kiszámoljuk a hiányzó szám helyét
(két szomszéd között interpolálva, a vég-/sarokháznál a két legközelebbi szomszédból kiterjesztve). A hely körül (30 m) azokat
az épületeket tekintjük jelöltnek, amelyeknek az adott utcán nincs másik házszámuk (a sarokháznak jellemzően csak a másik utca címe van meg).
Automatikus párosítás csak akkor, ha a jelölt a számított helyre esik (<5 m; interpolációnál), és a második jelölt legalább 15 m-rel
messzebb van (vagy a pont a jelölt belsejében van és az előny ≥ 8 m). A kézi bejegyzések (forras/kezi_javitasok.csv) ezt úgyis felülírják.
Pontosság-teszt: a már párosított épületek címét kivéve ugyanezzel a szabállyal 93-98%-ban visszatalált az épületre.

Futtatás:  py tenyek_ertekleltar.py   utána   py tenyek_sarok.py
"""
import collections
import csv
import json
import math
import re
from pathlib import Path

from kozos import tenyek_irasa
from tenyek_ertekleltar import cim_felbontas
from szazad import szoveg_evtartomany
from tenyek_oeny import tisztit_utca

EPULETEK = "data/varos/epuletek.geojson"
CIMEK = "data/varos/osm_cimek.csv"
CIMPONTOK = "data/ertekleltar_cimpontok.csv"
KARTYAK = "data/ertekleltar_kartyak.json"
NEM_PAROSITOTT = "data/ertekleltar_nem_parositott.csv"
ATNEVEZES = "forras/utcanev_atnevezesek.csv"
KIMENET = "data/tenyek/ertekleltar_sarok.csv"
KOZELITO = "data/varos/ertekleltar_sarok_kozelito.csv"   # '1920-as évek' jellegű adatok (a becslő és a kártya használja; NEM pontos év)
JAVASLAT = "data/ertekleltar_sarok_javaslat.csv"
KEZI_TABLA = "forras/ertekleltar_kezi_parositas.csv"
KEZI_OSZLOPOK = ["kerulet", "cim", "hrsz", "epites_ideje", "tervezo", "allapot", "javasolt_osm", "jeloltek", "osm_azonosito", "megjegyzes"]
LAT0, LON0 = 47.5, 19.05
KX = 111320 * math.cos(math.radians(LAT0))
KY = 110574


def geometria():
    d = json.load(open(EPULETEK, encoding="utf-8"))
    out = []
    for ft in d["features"]:
        pr, g = ft["properties"], ft["geometry"]
        if g["type"] == "Polygon":
            gyuru = g["coordinates"][0]
        elif g["type"] == "MultiPolygon":
            gyuru = max((p[0] for p in g["coordinates"]), key=len)
        else:
            continue
        pts = [((x - LON0) * KX, (y - LAT0) * KY) for x, y in gyuru]
        a = cx = cy = 0.0
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            c = x1 * y2 - x2 * y1
            a += c; cx += (x1 + x2) * c; cy += (y1 + y2) * c
        if abs(a) < 1e-6:
            continue
        out.append((pr["osm_tipus"], int(pr["id"]), pr.get("kerulet"), bool(pr.get("resz")), abs(a) / 2, cx / (3 * a), cy / (3 * a), pts))
    return out


class Terkep:
    def __init__(s, geo, cimek_ut, atn):
        s.b={}      # (tip,id) -> dict
        s.racs=collections.defaultdict(list)
        for tip,i,kn,resz,ter,cx,cy,pts in geo:
            if resz: continue
            e=(tip,i); s.b[e]=dict(kn=kn,ter=ter,c=(cx,cy),pts=pts,cim=[])
            if ter>=25: s.racs[(int(cx//60),int(cy//60))].append(e)
        s.cim=collections.defaultdict(lambda: collections.defaultdict(list))   # (u)->{(kn,szam)->[e]}
        s.utca=collections.defaultdict(list)  # (u) -> [(kn,szam,e)]
        with open(cimek_ut,encoding='utf-8-sig',newline='') as f:
            for r in csv.DictReader(f,delimiter=';'):
                e=(r['osm_tipus'],int(r['id']))
                if e not in s.b: continue
                u=tisztit_utca(r['utca']); u=atn.get(u,u)
                for resz in re.split(r'[;,]',r['hazszam'] or ''):
                    for m in re.findall(r'\d+',re.sub(r'[A-Za-z]','',resz)) [:2]:
                        s.utca[u].append((s.b[e]['kn'],int(m),e)); s.b[e]['cim'].append((u,int(m)))
    def kozel(s,p,R):
        cx,cy=p; out=[]
        for gx in range(int((cx-R)//60),int((cx+R)//60)+1):
            for gy in range(int((cy-R)//60),int((cy+R)//60)+1):
                for e in s.racs.get((gx,gy),()):
                    d=s.tav(e,p)
                    if d<=R: out.append((d,e))
        return sorted(out)
    def tav(s,e,p):
        pts=s.b[e]['pts']; x,y=p
        # belül?
        bent=False
        for (x1,y1),(x2,y2) in zip(pts,pts[1:]):
            if (y1>y)!=(y2>y) and x<(x2-x1)*(y-y1)/(y2-y1)+x1: bent=not bent
        if bent: return 0.0
        m=1e9
        for (x1,y1),(x2,y2) in zip(pts,pts[1:]):
            dx,dy=x2-x1,y2-y1; l=dx*dx+dy*dy
            t=0 if l==0 else max(0,min(1,((x-x1)*dx+(y-y1)*dy)/l))
            m=min(m,math.hypot(x-x1-t*dx,y-y1-t*dy))
        return m


    def pontok_betoltese(s, ut):
        """data/ertekleltar_cimpontok.csv: az Overpass-ból lekért OSM címpontok (csomópont/út/reláció addr:* címkével), a kártyák utcáira."""
        s.pontok = collections.defaultdict(list)
        if not Path(ut).exists():
            return
        with open(ut, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                m = re.match(r"^\s*(\d+)\s*([A-Za-z]?)(?:\s*[/]?\s*([A-Za-z]))?\s*(?:[-–]\s*(\d+))?", r["hazszam"])
                if not m:
                    continue
                a = int(m.group(1)); z = int(m.group(4)) if m.group(4) else a
                szamok = list(range(a, z + 1, 2)) if 1 < z - a <= 30 else [a, z] if z != a else [a]
                bet = (m.group(2) or m.group(3) or "").lower()
                for n in szamok:
                    s.pontok[(s.alap_utca(tisztit_utca(r["utca"])), n)].append((float(r["lat"]), float(r["lon"]), bet, r["osm_tipus"], int(r["osm_id"])))

    @staticmethod
    def alap_utca(x):
        for z in ("utca", "ut", "ter", "koz", "sor", "korut", "setany", "fasor", "lepcso", "park", "rakpart"):
            if x.endswith(z) and len(x) > len(z) + 2:
                return x[:-len(z)]
        return x

    def cimpont(s, kn, u, hsz):
        """A kártya címének megfelelő OSM-címpont(ok) -> az alattuk lévő épületek [(tav, e, sarok, terulet)]; csak az azonos kerületben."""
        if not hasattr(s, "pontok"):
            return []
        m = re.match(r"(\d+)\s*/?\s*([a-z]?)", hsz)
        if not m:
            return []
        n, bet = int(m.group(1)), m.group(2)
        talalt = {}
        for lat, lon, b, tip, oid in s.pontok.get((s.alap_utca(u), n), ()):
            if bet and b and b != bet:
                continue
            p = ((lon - LON0) * KX, (lat - LAT0) * KY)
            if tip != "node" and (tip, oid) in s.b:
                d, e = 0.0, (tip, oid)
            else:
                k = [y for y in s.kozel(p, 10) if s.b[y[1]]["kn"] == kn]
                if not k:
                    continue
                # a címpont gyakran az utcai oldalon áll, nem az épületen: a legközelebbi épület kell, ha ≥ 4 m-rel közelebb van a következőnél
                if k[0][0] > 8 or (len(k) > 1 and k[1][0] - k[0][0] < 4 and k[0][0] > 0):
                    for d, e in k[:2]:
                        if e not in talalt or d < talalt[e]:
                            talalt[e] = d
                    continue
                d, e = k[0]
            if s.b[e]["kn"] != kn:
                continue
            if e not in talalt or d < talalt[e]:
                talalt[e] = d
        return sorted((d, e, any(uu != u for uu, _ in s.b[e]["cim"]), s.b[e]["ter"]) for e, d in talalt.items())

    def utca_feloldas(s, u, kn):
        """A kártya utcanevét az OSM-címekben szereplő alakra viszi: utca/út csere, apró betűeltérés (Herman/Hermann). Visszaad: (kulcs, megjegyzés)."""
        if any(k == kn for k, _, _ in s.utca.get(u, ())):
            return u, ""
        ssz = ("utca", "ut", "ter", "koz", "sor", "korut", "setany", "fasor", "lepcso", "park", "rakpart", "sikatora", "liget")
        def alap(x):
            for z in ssz:
                if x.endswith(z) and len(x) > len(z) + 2:
                    return x[:-len(z)]
            return x
        if not hasattr(s, "_alap"):
            s._alap = collections.defaultdict(set)
            for x, l in s.utca.items():
                for k in {k for k, _, _ in l}:
                    s._alap[(k, alap(x))].add(x)
        a = alap(u)
        if len(s._alap.get((kn, a), ())) == 1:
            x = next(iter(s._alap[(kn, a)]))
            return x, f"utcanév-alak eltér: {u} -> {x}"
        import difflib
        kozel = difflib.get_close_matches(a, [b for (k, b) in s._alap if k == kn], n=2, cutoff=0.9)
        if len(kozel) == 1:
            x = next(iter(s._alap[(kn, kozel[0])]))
            return x, f"utcanév-alak eltér: {u} -> {x}"
        return None, ""
    def pozicio(s,kn,u,n,kizar=None):
        """(pont, mód) a keresett házszámhoz; None ha nincs elég szomszéd."""
        lista=[(sz,e) for k,sz,e in s.utca.get(u,()) if (k==kn) and sz%2==n%2 and sz!=n and e!=kizar]
        if not lista:
            lista=[(sz,e) for k,sz,e in s.utca.get(u,()) if sz%2==n%2 and sz!=n and e!=kizar and (k==kn)]
        if not lista: return None
        szam=collections.defaultdict(list)
        for sz,e in lista: szam[sz].append(s.b[e]['c'])
        pt={sz:(sum(c[0] for c in v)/len(v),sum(c[1] for c in v)/len(v)) for sz,v in szam.items()}
        also=[x for x in pt if x<n]; felso=[x for x in pt if x>n]
        L=max(also) if also else None; U=min(felso) if felso else None
        if L is not None and U is not None and U-L<=24:
            t=(n-L)/(U-L); a,b=pt[L],pt[U]
            return (a[0]+t*(b[0]-a[0]),a[1]+t*(b[1]-a[1])),'interpolált',(L,U)
        # kiterjesztés a szomszédos két ismert számból
        if L is not None and U is None or (L is None and U is not None) or (L is not None and U is not None):
            if L is not None and (U is None or U-L>24):
                kozel=sorted(also,reverse=True)[:2]; irany=L
            else: kozel=sorted(felso)[:2]; irany=U
            if kozel and abs(irany-n)<=10:
                a=pt[kozel[0]]
                if len(kozel)==2:
                    b=pt[kozel[1]]; k=(n-kozel[0])/(kozel[1]-kozel[0]); 
                    k=max(-3,min(3,k))
                    return (a[0]+k*(b[0]-a[0]),a[1]+k*(b[1]-a[1])),'kiterjesztett',(kozel[0],)
                return a,'egy szomszéd',(kozel[0],)
        return None
    def jeloltek(s,kn,u,n,kizar=None,R=30,onmaga=None):
        r=s.pozicio(kn,u,n,kizar)
        if not r: return None,'nincs szomszéd',[]
        p,mod,info=r
        c=[]
        for d,e in s.kozel(p,R):
            b=s.b[e]
            if e!=onmaga and any(uu==u for uu,_ in b['cim']): continue      # az utcán már másik házszámmal szerepel: másik ház
            if b['kn']!=kn and b['kn'] is not None and kn is not None and False: continue
            sarok = any(uu != u for uu, _ in b['cim'])
            c.append((d,e,sarok,b['ter']))
        return p,mod,c


def main():
    atn = {}
    try:
        with open(ATNEVEZES, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                if r.get("regi") and r.get("uj") and "|" not in r["uj"]:
                    atn[tisztit_utca(r["regi"])] = tisztit_utca(r["uj"])
    except FileNotFoundError:
        pass
    T = Terkep(geometria(), CIMEK, atn)
    T.pontok_betoltese(CIMPONTOK)
    nem = {(r["kerulet"], r["cim"].strip(), r["hrsz"].strip()) for r in csv.DictReader(open(NEM_PAROSITOTT, encoding="utf-8-sig", newline=""), delimiter=";")}
    kartyak = [k for k in json.load(open(KARTYAK, encoding="utf-8")) if (str(k["kerulet"]), k["cim"].strip(), (k["hrsz"] or "").strip()) in nem]
    kesz, javaslat, stat, kozelito = set(), [], collections.Counter(), set()
    kulcs_k = lambda k: (str(k["kerulet"]), k["cim"].strip(), (k["hrsz"] or "").strip())

    def tenyek(k, e, megj):
        if k["ev"]:
            kesz.add((e[0], e[1], "ev", k["ev"], "ertekleltar", megj))
        elif k.get("korszak"):
            kozelito.add((e[0], e[1], k["korszak"][0], k["korszak"][1], k["ev_szoveg"], k["forras"]))
        else:
            tart = szoveg_evtartomany(k.get("ev_szoveg"))
            if tart:
                kozelito.add((e[0], e[1], tart[0], tart[1], k["ev_szoveg"], k["forras"]))
        if k["tervezo"]:
            kesz.add((e[0], e[1], "tervezo", k["tervezo"], "ertekleltar", megj))
        if k["stilus"]:
            kesz.add((e[0], e[1], "stilus", k["stilus"], "ertekleltar", megj))
        ved = k["vedelem"]
        if ved and ved not in ("E", "Mk", "Mk / E", "-") and "javasolt" not in ved:
            kesz.add((e[0], e[1], "vedettseg_helyi", ved, "ertekleltar", megj))

    kezi_sorok = []
    if Path(KEZI_TABLA).exists():
        with open(KEZI_TABLA, encoding="utf-8-sig", newline="") as f:
            kezi_sorok = list(csv.DictReader(f, delimiter=";"))
    kezi_van = {(r["kerulet"], r["cim"].strip(), r["hrsz"].strip()) for r in kezi_sorok}
    uj_kezi = []
    for k in kartyak:
        kn = k["kerulet"]
        resz = [x for x in re.split(r"\s+[-–=]\s+|;", k["cim"].strip()) if x.strip()]
        allapot, ered = "nincs házszám / utca", None
        szamos = False
        for x in resz:
            u, hszok = cim_felbontas(x)
            if not u or len(hszok) != 1 or not re.fullmatch(r"\d+[a-z]?(?:/[a-z0-9]+)?", hszok[0]):
                continue
            szamos = True
            u = atn.get(u, u)
            n = int(re.match(r"\d+", hszok[0]).group(0))
            cp = T.cimpont(kn, u, hszok[0])
            if cp:
                ered = (len(cp) == 1, False, "OSM címpont alapján", cp, x)
                break
            u2, utcamegj = T.utca_feloldas(u, kn)
            if not u2:
                allapot = "ismeretlen utca az OSM-címek között"
                continue
            u = u2
            p, mod, c = T.jeloltek(kn, u, n)
            if not c:
                allapot = f"nincs jelölt ({mod})"
                continue
            elso = c[0]
            res = 99 if len(c) == 1 else c[1][0] - elso[0]
            auto = mod == "interpolált" and ((elso[0] < 5 and res >= 15) or (elso[0] < 1 and res >= 8))
            valoszinu = False
            if not auto and mod == "interpolált":
                # saroképület-szabály: a legközelebbi olyan jelölt, amelynek másik utcán van címe
                sarkok = [y for y in c if y[2]]
                if sarkok and sarkok[0][0] < 5:
                    tobbi = [y for y in c if y is not sarkok[0]]
                    r2 = 99 if not tobbi else tobbi[0][0] - sarkok[0][0]
                    if r2 >= 8:
                        c, auto = [sarkok[0]] + tobbi, True
                    elif sarkok[0][0] < 4 and r2 >= 4:
                        c, valoszinu = [sarkok[0]] + tobbi, True
                elif elso[0] < 4 and res >= 4:
                    valoszinu = True
            ered = (auto, valoszinu, mod + (", " + utcamegj if utcamegj else ""), c, x)
            break
        if not ered:
            stat[allapot] += 1
            javaslat.append([kn, k["cim"], k["hrsz"], k["ev_szoveg"], k["tervezo"], allapot, "", "", ""])
            if szamos and kulcs_k(k) not in kezi_van:
                uj_kezi.append([kn, k["cim"], k["hrsz"], k["ev_szoveg"], k["tervezo"], allapot, "", "", "", ""])
            continue
        auto, valoszinu, mod, c, x = ered
        jel = " | ".join(f"{e[0]} {e[1]} ({d:.0f} m{', saroképület' if sa else ''})" for d, e, sa, _ in c[:4])
        if auto:
            stat["automatikusan párosítva"] += 1
            e = c[0][1]
            tenyek(k, e, f"{k['forras']} (hiányzó cím '{x.strip()}': {mod} párosítva)" + (f", hrsz {k['hrsz']}" if k["hrsz"] else ""))
            javaslat.append([kn, k["cim"], k["hrsz"], k["ev_szoveg"], k["tervezo"], "automatikusan párosítva", f"{e[0]} {e[1]}", mod, jel])
        else:
            allapot = "valószínű (kézi megerősítés kell)" if valoszinu else "bizonytalan, jelöltekkel"
            stat[allapot] += 1
            javaslat.append([kn, k["cim"], k["hrsz"], k["ev_szoveg"], k["tervezo"], allapot, "", mod, jel])
            if kulcs_k(k) not in kezi_van:
                uj_kezi.append([kn, k["cim"], k["hrsz"], k["ev_szoveg"], k["tervezo"], allapot, f"{c[0][1][0]} {c[0][1][1]}" if valoszinu else "", jel, "", ""])
    # kézi tábla: új sorok a végére; a kitöltött osm_azonosito alapján tények
    fej = KEZI_OSZLOPOK
    if uj_kezi:
        uj = not Path(KEZI_TABLA).exists()
        Path(KEZI_TABLA).parent.mkdir(exist_ok=True)
        with open(KEZI_TABLA, "w" if uj else "a", encoding="utf-8-sig" if uj else "utf-8", newline="") as f:
            w = csv.writer(f, delimiter=";", lineterminator="\r\n")
            if uj:
                w.writerow(fej)
            w.writerows(uj_kezi)
        print(f"Kézi tábla: {len(uj_kezi)} új sor -> {KEZI_TABLA}")
        with open(KEZI_TABLA, encoding="utf-8-sig", newline="") as f:
            kezi_sorok = list(csv.DictReader(f, delimiter=";"))
    kartya_kulcs = {kulcs_k(k): k for k in kartyak}
    kezi_db = 0
    for r in kezi_sorok:
        k = kartya_kulcs.get((r["kerulet"], r["cim"].strip(), r["hrsz"].strip()))
        if not k:
            continue
        for resz in re.split(r"[|;,\n]+", r.get("osm_azonosito") or ""):
            m = re.search(r"(?:(way|relation)[/ :]*)?(\d{3,})", resz.strip(), flags=re.I)
            if m:
                tenyek(k, ((m.group(1) or "way").lower(), int(m.group(2))), f"{k['forras']} (kézi párosítás)" + (f", hrsz {k['hrsz']}" if k["hrsz"] else ""))
                kezi_db += 1
    tenyek_irasa(KIMENET, sorted(kesz, key=lambda s: (s[0], s[1], s[2])))
    with open(KOZELITO, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["osm_tipus", "id", "ev_tol", "ev_ig", "szoveg", "forras"])
        w.writerows(sorted(kozelito, key=lambda r: (r[0], r[1])))
    with open(JAVASLAT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["kerulet", "cim", "hrsz", "epites_ideje", "tervezo", "allapot", "osm_epulet", "modszer", "jeloltek"])
        w.writerows(javaslat)
    print(f"Feldolgozott nem párosított kártya: {len(kartyak)}")
    for a, n in stat.most_common():
        print(f"  {a}: {n}")
    print(f"Kézzel párosított (kitöltött osm_azonosito): {kezi_db}")
    print(f"Tények: {len(kesz)} sor -> {KIMENET};  közelítő korszakadat: {len(kozelito)} -> {KOZELITO};  javaslatok: {JAVASLAT}")


if __name__ == "__main__":
    main()
