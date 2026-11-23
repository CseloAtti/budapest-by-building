"""Filling in a missing address (e.g. of a corner house): the unmatched cards of the value register are tied to a location interpolated from the neighbouring house numbers.

Input:    data/ertekleltar_nem_parositott.csv (made by facts_inventory.py), data/ertekleltar_kartyak.json,
          data/varos/epuletek.geojson, data/varos/osm_cimek.csv, forras/utcanev_atnevezesek.csv
Output:   forras/ertekleltar_kezi_parositas.csv   - the table of the uncertain cards (YOU fill in THIS: write the building's identifier into the 'osm_azonosito' column, e.g. \"way 271003349\"; 'javasolt_osm' is the program's guess, for the 'valószínű' (probable) rows it is right with about 88% chance)
          data/varos/ertekleltar_sarok_kozelito.csv - textual era data ('1920-as évek') for the buildings matched this way
          data/tenyek/ertekleltar_sarok.csv       - the facts of the unambiguous (about 95% accurate) matches for assemble.py
          data/ertekleltar_sarok_javaslat.csv      - every unmatched card: status + candidates (for manual checking)

Method: for the card's "street N" address, we compute the place of the missing number from the known house numbers of the same street in the same district and of the same parity
(interpolating between two neighbours, extending from the two nearest neighbours at an end/corner house). Around that place (30 m) we regard as candidates the buildings
that have no other house number on the given street (a corner house typically has only the other street's address).
Automatic matching only if the candidate falls at the computed place (<5 m; with interpolation), and the second candidate is at least 15 m
farther (or the point is inside the candidate and the advantage is ≥ 8 m). The manual entries (forras/kezi_javitasok.csv) override this anyway.
Accuracy test: leaving out the address of the already matched buildings, the same rule found the building again in 93-98% of cases.

Run:       py facts_inventory.py   then   py facts_corner.py
"""
import collections
import csv
import json
import math
import re
from pathlib import Path

from common import write_facts
from facts_inventory import address_split
from century import text_year_range
from facts_oeny import clean_street

BUILDINGS = "data/varos/epuletek.geojson"
ADDRESSES = "data/varos/osm_cimek.csv"
ADDRESS_POINTS = "data/ertekleltar_cimpontok.csv"
CARDS = "data/ertekleltar_kartyak.json"
NOT_PAIRED = "data/ertekleltar_nem_parositott.csv"
RENAMING = "forras/utcanev_atnevezesek.csv"
OUTPUT = "data/tenyek/ertekleltar_sarok.csv"
APPROXIMATE = "data/varos/ertekleltar_sarok_kozelito.csv"   # data of the '1920-as évek' (1920s) kind (used by the estimator and the card; NOT an exact year)
SUGGESTION = "data/ertekleltar_sarok_javaslat.csv"
MANUAL_TABLE = "forras/ertekleltar_kezi_parositas.csv"
MANUAL_COLUMNS = ["kerulet", "cim", "hrsz", "epites_ideje", "tervezo", "allapot", "javasolt_osm", "jeloltek", "osm_azonosito", "megjegyzes"]
LAT0, LON0 = 47.5, 19.05
KX = 111320 * math.cos(math.radians(LAT0))
KY = 110574


def geometry():
    d = json.load(open(BUILDINGS, encoding="utf-8"))
    out = []
    for ft in d["features"]:
        pr, g = ft["properties"], ft["geometry"]
        if g["type"] == "Polygon":
            ring_ = g["coordinates"][0]
        elif g["type"] == "MultiPolygon":
            ring_ = max((p[0] for p in g["coordinates"]), key=len)
        else:
            continue
        pts = [((x - LON0) * KX, (y - LAT0) * KY) for x, y in ring_]
        a = cx = cy = 0.0
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            c = x1 * y2 - x2 * y1
            a += c; cx += (x1 + x2) * c; cy += (y1 + y2) * c
        if abs(a) < 1e-6:
            continue
        out.append((pr["osm_tipus"], int(pr["id"]), pr.get("kerulet"), bool(pr.get("resz")), abs(a) / 2, cx / (3 * a), cy / (3 * a), pts))
    return out


class Map:
    def __init__(s, geo, addresses_path, atn):
        s.b={}      # (tip,id) -> dict
        s.grid=collections.defaultdict(list)
        for kind,i,kn,part,area_,cx,cy,pts in geo:
            if part: continue
            e=(kind,i); s.b[e]=dict(kn=kn,ter=area_,c=(cx,cy),pts=pts,cim=[])
            if area_>=25: s.grid[(int(cx//60),int(cy//60))].append(e)
        s.address=collections.defaultdict(lambda: collections.defaultdict(list))   # (u)->{(kn,szam)->[e]}
        s.street=collections.defaultdict(list)  # (u) -> [(kn,szam,e)]
        with open(addresses_path,encoding='utf-8-sig',newline='') as f:
            for r in csv.DictReader(f,delimiter=';'):
                e=(r['osm_tipus'],int(r['id']))
                if e not in s.b: continue
                u=clean_street(r['utca']); u=atn.get(u,u)
                for part in re.split(r'[;,]',r['hazszam'] or ''):
                    for m in re.findall(r'\d+',re.sub(r'[A-Za-z]','',part)) [:2]:
                        s.street[u].append((s.b[e]['kn'],int(m),e)); s.b[e]['cim'].append((u,int(m)))
    def near(s,p,R):
        cx,cy=p; out=[]
        for gx in range(int((cx-R)//60),int((cx+R)//60)+1):
            for gy in range(int((cy-R)//60),int((cy+R)//60)+1):
                for e in s.grid.get((gx,gy),()):
                    d=s.distance(e,p)
                    if d<=R: out.append((d,e))
        return sorted(out)
    def distance(s,e,p):
        pts=s.b[e]['pts']; x,y=p
        # inside?
        inside=False
        for (x1,y1),(x2,y2) in zip(pts,pts[1:]):
            if (y1>y)!=(y2>y) and x<(x2-x1)*(y-y1)/(y2-y1)+x1: inside=not inside
        if inside: return 0.0
        m=1e9
        for (x1,y1),(x2,y2) in zip(pts,pts[1:]):
            dx,dy=x2-x1,y2-y1; l=dx*dx+dy*dy
            t=0 if l==0 else max(0,min(1,((x-x1)*dx+(y-y1)*dy)/l))
            m=min(m,math.hypot(x-x1-t*dx,y-y1-t*dy))
        return m


    def load_points(s, path_):
        """data/ertekleltar_cimpontok.csv: OSM address points fetched from Overpass (node/way/relation with an addr:* tag), for the streets of the cards."""
        s.points = collections.defaultdict(list)
        if not Path(path_).exists():
            return
        with open(path_, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                m = re.match(r"^\s*(\d+)\s*([A-Za-z]?)(?:\s*[/]?\s*([A-Za-z]))?\s*(?:[-–]\s*(\d+))?", r["hazszam"])
                if not m:
                    continue
                a = int(m.group(1)); z = int(m.group(4)) if m.group(4) else a
                numbers_ = list(range(a, z + 1, 2)) if 1 < z - a <= 30 else [a, z] if z != a else [a]
                bet = (m.group(2) or m.group(3) or "").lower()
                for n in numbers_:
                    s.points[(s.base_street(clean_street(r["utca"])), n)].append((float(r["lat"]), float(r["lon"]), bet, r["osm_tipus"], int(r["osm_id"])))

    @staticmethod
    def base_street(x):
        for z in ("utca", "ut", "ter", "koz", "sor", "korut", "setany", "fasor", "lepcso", "park", "rakpart"):
            if x.endswith(z) and len(x) > len(z) + 2:
                return x[:-len(z)]
        return x

    def address_point(s, kn, u, house_no):
        """The OSM address point(s) matching the card's address -> the buildings under them [(dist, e, corner, area)]; only in the same district."""
        if not hasattr(s, "pontok"):
            return []
        m = re.match(r"(\d+)\s*/?\s*([a-z]?)", house_no)
        if not m:
            return []
        n, bet = int(m.group(1)), m.group(2)
        found = {}
        for lat, lon, b, kind, oid in s.points.get((s.base_street(u), n), ()):
            if bet and b and b != bet:
                continue
            p = ((lon - LON0) * KX, (lat - LAT0) * KY)
            if kind != "node" and (kind, oid) in s.b:
                d, e = 0.0, (kind, oid)
            else:
                k = [y for y in s.near(p, 10) if s.b[y[1]]["kn"] == kn]
                if not k:
                    continue
                # the address point is often on the street side, not on the building: the nearest building is needed if it is ≥ 4 m closer than the next one
                if k[0][0] > 8 or (len(k) > 1 and k[1][0] - k[0][0] < 4 and k[0][0] > 0):
                    for d, e in k[:2]:
                        if e not in found or d < found[e]:
                            found[e] = d
                    continue
                d, e = k[0]
            if s.b[e]["kn"] != kn:
                continue
            if e not in found or d < found[e]:
                found[e] = d
        return sorted((d, e, any(uu != u for uu, _ in s.b[e]["cim"]), s.b[e]["ter"]) for e, d in found.items())

    def street_resolve(s, u, kn):
        """Brings the card's street name to the form in the OSM addresses: utca/út swap, small spelling differences (Herman/Hermann). Returns: (key, remark)."""
        if any(k == kn for k, _, _ in s.street.get(u, ())):
            return u, ""
        ssz = ("utca", "ut", "ter", "koz", "sor", "korut", "setany", "fasor", "lepcso", "park", "rakpart", "sikatora", "liget")
        def base(x):
            for z in ssz:
                if x.endswith(z) and len(x) > len(z) + 2:
                    return x[:-len(z)]
            return x
        if not hasattr(s, "_alap"):
            s._alap = collections.defaultdict(set)
            for x, l in s.street.items():
                for k in {k for k, _, _ in l}:
                    s._alap[(k, base(x))].add(x)
        a = base(u)
        if len(s._alap.get((kn, a), ())) == 1:
            x = next(iter(s._alap[(kn, a)]))
            return x, f"utcanév-alak eltér: {u} -> {x}"
        import difflib
        near = difflib.get_close_matches(a, [b for (k, b) in s._alap if k == kn], n=2, cutoff=0.9)
        if len(near) == 1:
            x = next(iter(s._alap[(kn, near[0])]))
            return x, f"utcanév-alak eltér: {u} -> {x}"
        return None, ""
    def position(s,kn,u,n,exclude=None):
        """(point, mode) for the sought house number; None if there are not enough neighbours."""
        list_=[(sz,e) for k,sz,e in s.street.get(u,()) if (k==kn) and sz%2==n%2 and sz!=n and e!=exclude]
        if not list_:
            list_=[(sz,e) for k,sz,e in s.street.get(u,()) if sz%2==n%2 and sz!=n and e!=exclude and (k==kn)]
        if not list_: return None
        number=collections.defaultdict(list)
        for sz,e in list_: number[sz].append(s.b[e]['c'])
        pt={sz:(sum(c[0] for c in v)/len(v),sum(c[1] for c in v)/len(v)) for sz,v in number.items()}
        lower_=[x for x in pt if x<n]; upper_=[x for x in pt if x>n]
        L=max(lower_) if lower_ else None; U=min(upper_) if upper_ else None
        if L is not None and U is not None and U-L<=24:
            t=(n-L)/(U-L); a,b=pt[L],pt[U]
            return (a[0]+t*(b[0]-a[0]),a[1]+t*(b[1]-a[1])),'interpolált',(L,U)
        # extension from the two neighbouring known numbers
        if L is not None and U is None or (L is None and U is not None) or (L is not None and U is not None):
            if L is not None and (U is None or U-L>24):
                near=sorted(lower_,reverse=True)[:2]; direction=L
            else: near=sorted(upper_)[:2]; direction=U
            if near and abs(direction-n)<=10:
                a=pt[near[0]]
                if len(near)==2:
                    b=pt[near[1]]; k=(n-near[0])/(near[1]-near[0]); 
                    k=max(-3,min(3,k))
                    return (a[0]+k*(b[0]-a[0]),a[1]+k*(b[1]-a[1])),'kiterjesztett',(near[0],)
                return a,'egy szomszéd',(near[0],)
        return None
    def candidates(s,kn,u,n,exclude=None,R=30,itself=None):
        r=s.position(kn,u,n,exclude)
        if not r: return None,'nincs szomszéd',[]
        p,mode,info=r
        c=[]
        for d,e in s.near(p,R):
            b=s.b[e]
            if e!=itself and any(uu==u for uu,_ in b['cim']): continue      # it already appears on the street with another house number: another house
            if b['kn']!=kn and b['kn'] is not None and kn is not None and False: continue
            corner = any(uu != u for uu, _ in b['cim'])
            c.append((d,e,corner,b['ter']))
        return p,mode,c


def main():
    atn = {}
    try:
        with open(RENAMING, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                if r.get("regi") and r.get("uj") and "|" not in r["uj"]:
                    atn[clean_street(r["regi"])] = clean_street(r["uj"])
    except FileNotFoundError:
        pass
    T = Map(geometry(), ADDRESSES, atn)
    T.load_points(ADDRESS_POINTS)
    not_ = {(r["kerulet"], r["cim"].strip(), r["hrsz"].strip()) for r in csv.DictReader(open(NOT_PAIRED, encoding="utf-8-sig", newline=""), delimiter=";")}
    cards = [k for k in json.load(open(CARDS, encoding="utf-8")) if (str(k["kerulet"]), k["cim"].strip(), (k["hrsz"] or "").strip()) in not_]
    done, suggestion, stat, approximate = set(), [], collections.Counter(), set()
    key_k = lambda k: (str(k["kerulet"]), k["cim"].strip(), (k["hrsz"] or "").strip())

    def facts(k, e, remark):
        if k["ev"]:
            done.add((e[0], e[1], "ev", k["ev"], "ertekleltar", remark))
        elif k.get("korszak"):
            approximate.add((e[0], e[1], k["korszak"][0], k["korszak"][1], k["ev_szoveg"], k["forras"]))
        else:
            hold = text_year_range(k.get("ev_szoveg"))
            if hold:
                approximate.add((e[0], e[1], hold[0], hold[1], k["ev_szoveg"], k["forras"]))
        if k["tervezo"]:
            done.add((e[0], e[1], "tervezo", k["tervezo"], "ertekleltar", remark))
        if k["stilus"]:
            done.add((e[0], e[1], "stilus", k["stilus"], "ertekleltar", remark))
        protect = k["vedelem"]
        if protect and protect not in ("E", "Mk", "Mk / E", "-") and "javasolt" not in protect:
            done.add((e[0], e[1], "vedettseg_helyi", protect, "ertekleltar", remark))

    manual_rows = []
    if Path(MANUAL_TABLE).exists():
        with open(MANUAL_TABLE, encoding="utf-8-sig", newline="") as f:
            manual_rows = list(csv.DictReader(f, delimiter=";"))
    manual_has = {(r["kerulet"], r["cim"].strip(), r["hrsz"].strip()) for r in manual_rows}
    new_manual = []
    for k in cards:
        kn = k["kerulet"]
        part = [x for x in re.split(r"\s+[-–=]\s+|;", k["cim"].strip()) if x.strip()]
        state, result = "nincs házszám / utca", None
        numbered = False
        for x in part:
            u, house_nos = address_split(x)
            if not u or len(house_nos) != 1 or not re.fullmatch(r"\d+[a-z]?(?:/[a-z0-9]+)?", house_nos[0]):
                continue
            numbered = True
            u = atn.get(u, u)
            n = int(re.match(r"\d+", house_nos[0]).group(0))
            cp = T.address_point(kn, u, house_nos[0])
            if cp:
                result = (len(cp) == 1, False, "OSM címpont alapján", cp, x)
                break
            u2, street_remark = T.street_resolve(u, kn)
            if not u2:
                state = "ismeretlen utca az OSM-címek között"
                continue
            u = u2
            p, mode, c = T.candidates(kn, u, n)
            if not c:
                state = f"nincs jelölt ({mode})"
                continue
            first = c[0]
            res = 99 if len(c) == 1 else c[1][0] - first[0]
            auto = mode == "interpolált" and ((first[0] < 5 and res >= 15) or (first[0] < 1 and res >= 8))
            probable = False
            if not auto and mode == "interpolált":
                # corner-building rule: the nearest candidate that has an address on another street
                corners = [y for y in c if y[2]]
                if corners and corners[0][0] < 5:
                    rest = [y for y in c if y is not corners[0]]
                    r2 = 99 if not rest else rest[0][0] - corners[0][0]
                    if r2 >= 8:
                        c, auto = [corners[0]] + rest, True
                    elif corners[0][0] < 4 and r2 >= 4:
                        c, probable = [corners[0]] + rest, True
                elif first[0] < 4 and res >= 4:
                    probable = True
            result = (auto, probable, mode + (", " + street_remark if street_remark else ""), c, x)
            break
        if not result:
            stat[state] += 1
            suggestion.append([kn, k["cim"], k["hrsz"], k["ev_szoveg"], k["tervezo"], state, "", "", ""])
            if numbered and key_k(k) not in manual_has:
                new_manual.append([kn, k["cim"], k["hrsz"], k["ev_szoveg"], k["tervezo"], state, "", "", "", ""])
            continue
        auto, probable, mode, c, x = result
        sign = " | ".join(f"{e[0]} {e[1]} ({d:.0f} m{', saroképület' if sa else ''})" for d, e, sa, _ in c[:4])
        if auto:
            stat["automatikusan párosítva"] += 1
            e = c[0][1]
            facts(k, e, f"{k['forras']} (hiányzó cím '{x.strip()}': {mode} párosítva)" + (f", hrsz {k['hrsz']}" if k["hrsz"] else ""))
            suggestion.append([kn, k["cim"], k["hrsz"], k["ev_szoveg"], k["tervezo"], "automatikusan párosítva", f"{e[0]} {e[1]}", mode, sign])
        else:
            state = "valószínű (kézi megerősítés kell)" if probable else "bizonytalan, jelöltekkel"
            stat[state] += 1
            suggestion.append([kn, k["cim"], k["hrsz"], k["ev_szoveg"], k["tervezo"], state, "", mode, sign])
            if key_k(k) not in manual_has:
                new_manual.append([kn, k["cim"], k["hrsz"], k["ev_szoveg"], k["tervezo"], state, f"{c[0][1][0]} {c[0][1][1]}" if probable else "", sign, "", ""])
    # manual table: new rows to the end; facts based on the filled-in osm_azonosito
    head = MANUAL_COLUMNS
    if new_manual:
        new = not Path(MANUAL_TABLE).exists()
        Path(MANUAL_TABLE).parent.mkdir(exist_ok=True)
        with open(MANUAL_TABLE, "w" if new else "a", encoding="utf-8-sig" if new else "utf-8", newline="") as f:
            w = csv.writer(f, delimiter=";", lineterminator="\r\n")
            if new:
                w.writerow(head)
            w.writerows(new_manual)
        print(f"Kézi tábla: {len(new_manual)} új sor -> {MANUAL_TABLE}")
        with open(MANUAL_TABLE, encoding="utf-8-sig", newline="") as f:
            manual_rows = list(csv.DictReader(f, delimiter=";"))
    card_key = {key_k(k): k for k in cards}
    manual_count = 0
    for r in manual_rows:
        k = card_key.get((r["kerulet"], r["cim"].strip(), r["hrsz"].strip()))
        if not k:
            continue
        for part in re.split(r"[|;,\n]+", r.get("osm_azonosito") or ""):
            m = re.search(r"(?:(way|relation)[/ :]*)?(\d{3,})", part.strip(), flags=re.I)
            if m:
                facts(k, ((m.group(1) or "way").lower(), int(m.group(2))), f"{k['forras']} (kézi párosítás)" + (f", hrsz {k['hrsz']}" if k["hrsz"] else ""))
                manual_count += 1
    write_facts(OUTPUT, sorted(done, key=lambda s: (s[0], s[1], s[2])))
    with open(APPROXIMATE, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["osm_tipus", "id", "ev_tol", "ev_ig", "szoveg", "forras"])
        w.writerows(sorted(approximate, key=lambda r: (r[0], r[1])))
    with open(SUGGESTION, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["kerulet", "cim", "hrsz", "epites_ideje", "tervezo", "allapot", "osm_epulet", "modszer", "jeloltek"])
        w.writerows(suggestion)
    print(f"Feldolgozott nem párosított kártya: {len(cards)}")
    for a, n in stat.most_common():
        print(f"  {a}: {n}")
    print(f"Kézzel párosított (kitöltött osm_azonosito): {manual_count}")
    print(f"Tények: {len(done)} sor -> {OUTPUT};  közelítő korszakadat: {len(approximate)} -> {APPROXIMATE};  javaslatok: {SUGGESTION}")


if __name__ == "__main__":
    main()
