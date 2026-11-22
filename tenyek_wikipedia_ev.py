"""A Wikipédia-cikkek szövegéből kiolvassa az építés évét -> data/tenyek/wikipedia_szoveg.csv (+ data/varos/wikipedia_kozelito.csv)

Mely épületekre: amelyeknek saját Wikipédia-cikkük van (a 'wikipedia' mező; a zónától örökölt 'wikipedia_zona' nem számít).
Az évet csak azoknál írjuk ki, amelyeknek még nincs építési évük (vagy az évük eddig is ebből a forrásból jött).
A többinél csak összevetjük a kiolvasást a meglévő évvel: ez adja a megbízhatósági mutatót a jelentésben.

Mit olvas ki (a cikk bevezető szakaszából, a 0. szakaszból):
  1. az infobox építésre utaló mezői ('építés ideje', 'építés éve', 'felszentelés' stb.);
  2. ha nincs: a bevezető azon mondata, amelyben 'épült / építették / felszentelték / átadták / megnyitották' áll és évszám van
     (az átépítést, felújítást, bővítést, lebontást említő mondatot kihagyja).
Tartomány ('1893–1896') esetén az első évet veszi (az eredeti építést). Ha nincs évszám, de a szöveg századra / évtizedre utal
('a 18. században', '1930-as évek'), a szazad.py szabályai szerint közelítő tartomány lesz belőle (data/varos/wikipedia_kozelito.csv).

Védelmek: ha egy cikk háromnál több épülethez tartozik (telep, park, intézményi cikk), kihagyjuk; az évnek 1000 és ma között kell lennie.
A forrás neve: wikipedia_szoveg (a forras/prioritas.json-ban az 'ev' listában, a wikidata_kozeli után, az eubucco előtt).

Futtatás:  py tenyek_wikipedia_ev.py varos        (a letöltések a data/cache/wikipedia_szoveg.json-ban maradnak, újrafuttatáskor nem kérdez újra)
Önellenőrzés (hálózat nélkül):  py tenyek_wikipedia_ev.py teszt
"""
import csv
import json
import re
import sys
import time
import urllib.parse
from collections import Counter, defaultdict
from pathlib import Path

from kozos import http_json, tenyek_irasa
from szazad import szoveg_evtartomany

VAROS = len(sys.argv) > 1 and sys.argv[1] == "varos"
EPULETEK = "data/varos/epuletek_vegleges.geojson" if VAROS else "data/belvaros_epuletek_vegleges.geojson"
KIMENET = "data/tenyek/wikipedia_szoveg.csv"
KOZELITO = "data/varos/wikipedia_kozelito.csv"
JELENTES = "data/varos/wikipedia_ev_jelentes.md"
CACHE = Path("data/cache/wikipedia_szoveg.json")
API = "https://hu.wikipedia.org/w/api.php"
CSOPORT = 10
SZUNET_MP = 2
LEGFELJEBB_EPULET = 3
MA = 2026
FORRAS = "wikipedia_szoveg"

INFOBOX_MEZOK = ["építés ideje", "építés éve", "építési idő", "építés", "építési év", "építés kezdete", "épült",
                 "felszentelés", "felszentelés ideje", "felszentelés éve", "megnyitás", "megnyitás ideje", "átadás", "átadás ideje",
                 "befejezés", "elkészült", "avatás", "építtetés ideje", "alapkőletétel"]
SZAVAK_EPULT = re.compile(r"\b(épült|épített|építették|építtette|építtették|építette|emelték|emeltette|felszentelték|felépítették|"
                          r"felépült|átadták|megnyitották|elkészült|befejezték|avatták|alapkövét|alapkövét)\b", re.I)
KIZARO = re.compile(r"átépít|felújít|bővít|lebont|elpusztul|megsemmisül|restaurál|újjáépít|újjáépül|kibővít|helyreállít|"
                    r"megrongálód|lerombol|leég|kiég|romos|modernizál|átalakít|beépít", re.I)
EV = re.compile(r"(?<!\d)(1[0-9]{3}|20[0-2][0-9])(?!\d)(?!-?(?:as|es|os|ös)\b)")


def tisztit(s):
    """Wikiszöveg -> sima szöveg (sablonok, hivatkozások, jelölők nélkül)."""
    s = re.sub(r"<ref[^>/]*/>", " ", s)
    s = re.sub(r"<ref[^>]*>.*?</ref>", " ", s, flags=re.S)
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.S)
    for _ in range(4):                                   # beágyazott sablonok kívülről befelé
        s = re.sub(r"\{\{[^{}]*\}\}", " ", s)
    s = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"\[https?://[^\s\]]+\s*([^\]]*)\]", r"\1", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace("'''", "").replace("''", "").replace("&nbsp;", " ").replace("&ndash;", "–")
    return re.sub(r"\s+", " ", s).strip()


def infobox_ertekek(wt):
    """{mező: nyers érték} az infobox-sablon sorai közül (csak az építésre utaló mezők)."""
    ki = {}
    for m in re.finditer(r"^\s*\|\s*([^=|\n]+?)\s*=\s*(.*?)(?=^\s*\||^\s*\}\}|\Z)", wt, flags=re.M | re.S):
        mezo = m.group(1).strip().lower()
        if mezo in INFOBOX_MEZOK and mezo not in ki:
            ertek = tisztit(m.group(2))
            if ertek:
                ki[mezo] = ertek
    return ki


def mondatok(wt):
    """A bevezető szakasz sima szövege mondatokra bontva (az infobox-sablon kihagyásával)."""
    s = tisztit(wt)
    s = re.sub(r"^=+[^=]+=+", " ", s, flags=re.M)
    return [x.strip() for x in re.split(r"(?<=[a-záéíóöőúüű\)\]])\.\s+(?=[A-ZÁÉÍÓÖŐÚÜŰ])", s) if x.strip()]


def kiolvas(wt):
    """-> (ev, ev_tol, ev_ig, honnan, idezet) vagy None. Pontos évnél ev_tol = ev_ig = ev, közelítőnél ev = None."""
    # 1. infobox
    for mezo, ertek in infobox_ertekek(wt).items():
        e = EV.findall(ertek)
        if e:
            return int(e[0]), int(e[0]), int(e[0]), f"infobox: {mezo}", ertek[:120]
        r = szoveg_evtartomany(ertek)
        if r:
            return None, r[0], r[1], f"infobox: {mezo}", ertek[:120]
    # 2. bevezető mondatok
    klauzak = [k for m in mondatok(wt)[:12] for k in re.split(r"[;,]\s+|\s+(?:de|majd|ám|azonban)\s+", m)]
    for m in klauzak:
        if not SZAVAK_EPULT.search(m) or KIZARO.search(m):
            continue
        e = EV.findall(m)
        e = [int(x) for x in e if 1000 <= int(x) <= MA]
        if e:
            return e[0], e[0], e[0], "bevezető mondat", m[:160]
        r = szoveg_evtartomany(m)
        if r:
            return None, r[0], r[1], "bevezető mondat", m[:160]
    return None


def cimek_listaja(wikipedia):
    """'hu:Cím|hu:Más cím|en:Title' -> a magyar címek (legfeljebb 3)."""
    ki = []
    for x in str(wikipedia or "").split("|"):
        x = x.strip()
        if x.startswith("hu:"):
            ki.append(x[3:].strip())
        elif ":" not in x[:4] and x:
            ki.append(x)
    return ki[:3]


def letoltes(cimek):
    """{cím: a cikk 0. szakaszának wikiszövege vagy None}; a gyorsítótárat használja."""
    try:
        cache = json.loads(CACHE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        cache = {}
    hianyzik = [c for c in cimek if c not in cache]
    print(f"Cikkek: {len(cimek)}, ebből letöltendő: {len(hianyzik)}")
    for i in range(0, len(hianyzik), CSOPORT):
        csoport = hianyzik[i:i + CSOPORT]
        url = API + "?" + urllib.parse.urlencode({
            "action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main", "rvsection": 0,
            "titles": "|".join(csoport), "redirects": 1, "format": "json", "formatversion": 2})
        adat = http_json(url).get("query", {})
        atiranyit = {x["from"]: x["to"] for x in adat.get("redirects", [])}
        atiranyit.update({x["from"]: x["to"] for x in adat.get("normalized", []) if x["from"] not in atiranyit})
        szovegek = {}
        for p in adat.get("pages", []):
            rev = p.get("revisions") or []
            szovegek[p.get("title")] = rev[0]["slots"]["main"]["content"] if rev else None
        for c in csoport:
            cel = c
            for _ in range(3):
                cel = atiranyit.get(cel, cel)
            cache[c] = szovegek.get(cel)
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        print(f"  letöltve: {min(i + CSOPORT, len(hianyzik))}/{len(hianyzik)}")
        time.sleep(SZUNET_MP)
    return cache


def main():
    print("Épületek beolvasása...")
    with open(EPULETEK, encoding="utf-8") as f:
        feats = json.load(f)["features"]
    epuletek = []                       # (osm_tipus, id, [címek], ev, ev_forras, nev)
    for ft in feats:
        p = ft["properties"]
        if p.get("wikipedia") and not p.get("wikipedia_zona") and not p.get("rom"):
            cimek = cimek_listaja(p["wikipedia"])
            if cimek:
                epuletek.append((p["osm_tipus"], p["id"], cimek, p.get("ev"), p.get("ev_forras"), p.get("nev") or ""))
    del feats
    print(f"Saját Wikipédia-cikkes épület: {len(epuletek)}")

    cikk_epuletei = defaultdict(set)
    for t, i, cimek, *_ in epuletek:
        for c in cimek:
            cikk_epuletei[c].add((t, i))
    cache = letoltes(sorted(cikk_epuletei))

    kiolv = {c: (kiolvas(sz) if sz else None) for c, sz in cache.items() if c in cikk_epuletei}

    sorok, kozelitok = [], []
    stat = Counter()
    egyezes = []                       # meglévő évvel összevetve: (különbség)
    kihagyott_sok = []
    for t, i, cimek, ev, ev_forras, nev in epuletek:
        talalat = None
        for c in cimek:
            if len(cikk_epuletei[c]) > LEGFELJEBB_EPULET:
                stat["kihagyva: a cikk túl sok épülethez tartozik"] += 1
                if c not in kihagyott_sok:
                    kihagyott_sok.append(c)
                continue
            k = kiolv.get(c)
            if k:
                talalat = (c, k)
                break
        if not talalat:
            stat["nincs kiolvasható építési idő"] += 1
            continue
        c, (ev_k, tol, ig, honnan, idezet) = talalat
        van_ev = ev not in (None, "") and ev_forras != FORRAS
        if van_ev:
            if ev_k is not None:
                try:
                    egyezes.append(abs(int(ev) - ev_k))
                except (TypeError, ValueError):
                    pass
            stat["van már évük (csak összevetés)"] += 1
            continue
        megj = f"Wikipédia: {c} ({honnan}): „{idezet}”"
        if ev_k is not None and 1000 <= ev_k <= MA:
            sorok.append((t, i, "ev", ev_k, FORRAS, megj))
            stat["új pontos év" + (" (infoboxból)" if honnan.startswith("infobox") else " (mondatból)")] += 1
        elif ev_k is None:
            kozelitok.append([t, i, tol, ig, idezet[:80], "Wikipédia-cikk szövege: " + c])
            stat["új közelítő évtartomány"] += 1
    tenyek_irasa(KIMENET, sorted(sorok, key=lambda s: (s[0], s[1])))
    Path(KOZELITO).parent.mkdir(parents=True, exist_ok=True)
    with open(KOZELITO, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["osm_tipus", "id", "ev_tol", "ev_ig", "szoveg", "forras"])
        w.writerows(kozelitok)

    jo2 = sum(1 for x in egyezes if x <= 2)
    sor = [f"# Wikipédia-szövegből kiolvasott építési évek\n",
           f"Saját cikkes épület: {len(epuletek)}; letöltött cikk: {len(cikk_epuletei)}\n"]
    for k, v in sorted(stat.items()):
        sor.append(f"- {k}: {v}\n")
    if egyezes:
        sor.append(f"\n**Megbízhatóság:** a már évvel rendelkező épületeknél a kiolvasás {len(egyezes)} esetben ért össze "
                   f"a meglévő évvel, ebből {jo2} ({jo2 / len(egyezes):.0%}) esett ±2 éven belülre.\n")
    if kihagyott_sok:
        sor.append("\nKihagyott cikkek (több mint %d épületre mutatnak): %s\n" % (LEGFELJEBB_EPULET, "; ".join(kihagyott_sok[:40])))
    Path(JELENTES).write_text("".join(sor), encoding="utf-8")
    print("".join(sor))
    print(f"Mentve: {KIMENET}, {KOZELITO}, {JELENTES}")
    print("Következő lépés:  py osszeepit.py varos  ->  py ev_becsles.py varos  ->  py osszeepit.py varos  ->  py csempek_keszites.py varos")


def teszt():
    minta = """{{Templom infobox
| név = Teszt-templom
| építés ideje = 1893–1896<ref>valami</ref>
| felszentelés = [[1897]]
}}
A '''Teszt-templom''' [[Budapest]] [[XIX. kerülete|XIX. kerületében]] áll. A templom 1850-ben épült, de 1944-ben lebombázták.
"""
    assert kiolvas(minta)[:3] == (1893, 1893, 1893), kiolvas(minta)
    m2 = """{{Infobox
| név = X
}}
A '''X-kápolna''' Budapesten található. A kápolnát 1759-ben építették, 1810-ben felújították. A XIX. század végén bővítették.
"""
    assert kiolvas(m2)[:3] == (1759, 1759, 1759), kiolvas(m2)
    m3 = """{{Infobox
| építés ideje = XIX. század második fele
}}
Valami."""
    r = kiolvas(m3)
    assert r[0] is None and r[1:3] == (1851, 1900), r
    m4 = """A '''Y-ház''' ma múzeum. A felújítás 1990-ben fejeződött be. Az épület az 1930-as évek elején épült."""
    r = kiolvas(m4)
    assert r and r[0] is None and r[1:3] == (1930, 1933), r
    m5 = "A '''Z''' egy intézmény. 1860-ban alapították. Az épületet 1902-ben avatták fel."
    assert kiolvas(m5)[:3] == (1902, 1902, 1902), kiolvas(m5)
    assert kiolvas("Semmi évszám itt.") is None
    assert cimek_listaja("hu:A|en:B|hu:C (Kispest)") == ["A", "C (Kispest)"]
    print("Önellenőrzés rendben.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "teszt":
        teszt()
    else:
        main()
