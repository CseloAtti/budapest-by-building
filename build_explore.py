"""Text (JavaScript-free) pages for search and sharing -> release/explore/ and release/e/
Called by build_release.py; it does not need to be run on its own.

What is made?
  /explore/                      home page: table of eras, list of architects
  /explore/era/<slug>/           the buildings of one era (only those with a known year)
  /explore/architect/<slug>/     the buildings of one designer
  /e/<w|r><OSM-id>/              the data page of one building (only where there is a known construction year, designer or link)
  /sitemap.xml, /robots.txt      for search engines
A building gets a page if it is NOT a building part, HAS a name or address, and at least one of these is true:
  known construction year, designer, Budapest100 / Építészfórum / Budapest Legendák / E-Örökség (OENY) / Wikidata link,
  or its own (not inherited from the estate) Wikipedia article."""
import html
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

ALAP_URL = "https://budapestbuildings.com"
OLDAL_NEV = "Budapest épületei"
MIN_EPITESZ_DB = 4          # for fewer buildings than this no designer page is made
EV_FORRAS = {"start_date": "OpenStreetMap", "budapest100": "Budapest100", "wikipedia_lista": "Wikipédia",
             "wikidata": "Wikidata", "oeny": "E-Örökség (OENY)", "lechner": "Lechner Tudásközpont", "kezi": "kézi javítás"}
VEDETTSEG = {"M": "műemlék", "MJ": "műemlék jellegű", "VK": "városképi jelentőségű", "MK": "műemléki környezet",
             "MJT": "műemléki jelentőségű terület", "HV": "helyi védelem"}

CSS = """body{margin:0;font:16px/1.55 "Helvetica Neue",Arial,sans-serif;color:#111;background:#f4f6f7}
main{max-width:760px;margin:0 auto;padding:20px 16px 48px}
a{color:#111}h1{font-size:28px;line-height:1.2;margin:.2em 0 .1em}h2{font-size:19px;margin:1.6em 0 .4em}
.k{color:#5d6266;margin:0 0 1em}.ter{display:inline-block;margin:6px 0 14px;padding:9px 16px;border-radius:999px;background:#000;color:#fff;text-decoration:none;font-weight:600}
.lap{background:#fff;border-radius:12px;padding:6px 18px 14px;box-shadow:0 0 0 1px #cfd5d8}
dl{display:grid;grid-template-columns:max-content 1fr;gap:6px 18px;margin:12px 0}dt{color:#5d6266}dd{margin:0}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #e1e5e7}td.sz,th.sz{text-align:right}
ul{padding-left:20px}li{margin:3px 0}footer{margin-top:28px;font-size:13px;color:#5d6266}nav{font-size:14px;margin-bottom:8px}"""


def e(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def szlug(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "x"


def gazd(p):
    return ("r" if p.get("osm_tipus") == "relation" else "w") + str(p["id"])


def cim_elso(p):
    return str(p.get("cim") or "").split(";")[0].strip()


def cim_cikk(p):
    return str(p.get("nev") or "").strip() or cim_elso(p)


def sajat_wikipedia(p):
    w = p.get("wikipedia")
    if not w or p.get("wikipedia_zona"):
        return []
    return [x.strip()[3:] if x.strip().startswith("hu:") else x.strip() for x in str(w).split("|") if x.strip()]


def kell_oldal(p):
    if p.get("resz") or not cim_cikk(p):
        return False
    return bool(p.get("ev") or p.get("tervezo") or p.get("budapest100_url") or p.get("epforum_url") or p.get("legenda_url")
                or p.get("oeny_azonosito") or p.get("wikidata_id") or sajat_wikipedia(p))


def tervezok(p):
    return [x.strip() for x in re.split(r"\s*(?:,|;|\bés\b)\s*", str(p.get("tervezo") or "")) if x.strip()]


def tipus_szotar(app_js):
    """The TIPUS_HU dictionary from app.js (so that the type names appear in Hungarian just as on the map)."""
    m = re.search(r"var TIPUS_HU = \{(.*?)\};", app_js, re.S)
    return dict(re.findall(r"(\w+):\s*'([^']*)'", m.group(1))) if m else {}


def tipus_nev(v, szotar):
    r = [szotar.get(x.strip(), x.strip()) for x in str(v or "").split(";") if x.strip() and x.strip() != "yes"]
    return ", ".join(r)


def oldal(cim, leiras, torzs, url, jsonld=None):
    ld = ""
    if jsonld:
        ld = '<script type="application/ld+json">' + json.dumps(jsonld, ensure_ascii=False).replace("<", "\\u003c") + "</script>"
    return f"""<!doctype html>
<html lang="hu"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(cim)} | {OLDAL_NEV}</title>
<meta name="description" content="{e(leiras)}">
<link rel="canonical" href="{ALAP_URL}{url}">
<meta property="og:title" content="{e(cim)}"><meta property="og:description" content="{e(leiras)}"><meta property="og:type" content="website"><meta property="og:url" content="{ALAP_URL}{url}"><meta property="og:image" content="{ALAP_URL}/megosztas_hu.png"><meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="/favicon.svg" type="image/svg+xml"><style>{CSS}</style>{ld}</head><body><main>
<nav><a href="/explore/">{OLDAL_NEV}: szöveges változat</a></nav>
{torzs}
<footer>Adatok: © OpenStreetMap közreműködők (ODbL), Budapest100, Építészfórum, Budapest Legendák, E-Örökség (OENY), Wikipédia. Az építési évek egy része gyűjtött adat, nem hivatalos nyilvántartás. <a href="/">Vissza az interaktív 3D térképre</a>.</footer>
</main></body></html>
"""


def epulet_oldal(p, szotar, kor_lista, ep_szlug):
    gid = gazd(p)
    cim = cim_cikk(p)
    cimsor = cim_elso(p)
    sorok = []
    if p.get("ev"):
        fr = EV_FORRAS.get(p.get("ev_forras"))
        sorok.append(("Építés éve", f"{e(p['ev'])}" + (f" <small>(forrás: {e(fr)})</small>" if fr else "")))
    if p.get("tervezo"):
        linkek = []
        for n in tervezok(p):
            linkek.append(f'<a href="/explore/architect/{ep_szlug[n]}/">{e(n)}</a>' if n in ep_szlug else e(n))
        sorok.append(("Tervező", ", ".join(linkek) if linkek else e(p["tervezo"])))
    if p.get("stilus"):
        sorok.append(("Stílus", e(p["stilus"])))
    t = tipus_nev(p.get("tipus"), szotar)
    if t:
        sorok.append(("Típus", e(t)))
    kod = p.get("vedettseg") or ("HV" if p.get("vedettseg_helyi") else "")
    if kod:
        v = VEDETTSEG.get(kod, kod) + (f" (törzsszám {p['muemlek_torzsszam']})" if p.get("muemlek_torzsszam") and kod != "HV" else "")
        sorok.append(("Védettség", e(v)))
    if cimsor:
        sorok.append(("Cím", e(cimsor)))
    dl = "<dl>" + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in sorok) + "</dl>" if sorok else ""
    tobb = []
    if p.get("budapest100_url"):
        tobb.append(("Budapest100", p["budapest100_url"]))
    if p.get("epforum_url"):
        tobb.append(("Építészfórum", p["epforum_url"]))
    if p.get("legenda_url"):
        tobb.append(("Budapest Legendák", p["legenda_url"]))
    for a in str(p.get("oeny_azonosito") or "").split("|"):
        if re.fullmatch(r"\d{1,8}", a):
            tobb.append(("E-Örökség (OENY)", f"https://www.oeny.hu/oeny/eorok/public/monument/{a}"))
    for w in sajat_wikipedia(p):
        tobb.append((f"Wikipédia: {w}", "https://hu.wikipedia.org/wiki/" + quote(w.replace(" ", "_"))))
    if p.get("wikidata_id"):
        tobb.append(("Wikidata", f"https://www.wikidata.org/wiki/{quote(str(p['wikidata_id']))}"))
    gm = "https://www.google.com/maps/search/?api=1&query=" + quote(f"{cimsor}, Budapest" if cimsor else f"{p['lat']},{p['lon']}")
    tobb.append(("Google Térkép", gm))
    tobb_html = "<h2>Tudj meg többet</h2><ul>" + "".join(f'<li><a href="{e(u)}" rel="noopener">{e(n)}</a></li>' for n, u in tobb) + "</ul>"
    kor = ""
    if p.get("ev") and kor_lista:
        for sz, a, b, cimke in kor_lista:
            if a <= int(p["ev"]) <= b:
                kor = f'<p>Korszak: <a href="/explore/era/{sz}/">{e(cimke)}</a></p>'
                break
    mondat = f"{cim}" + (f" ({cimsor})" if cimsor and cimsor != cim else "") + " Budapest egyik épülete"
    if p.get("ev"):
        mondat += f", építési éve: {p['ev']}"
    if p.get("tervezo"):
        mondat += f", tervezője: {p['tervezo']}"
    mondat += "."
    url = f"/e/{gid}/"
    ld = {"@context": "https://schema.org", "@type": "Place", "name": cim,
          "geo": {"@type": "GeoCoordinates", "latitude": p["lat"], "longitude": p["lon"]}}
    if cimsor:
        ld["address"] = {"@type": "PostalAddress", "streetAddress": cimsor, "addressLocality": "Budapest", "addressCountry": "HU"}
    torzs = f"""<h1>{e(cim)}</h1>
<p class="k">{e(cimsor) + ", " if cimsor else ""}Budapest</p>
<a class="ter" href="/?e={gid}">Megnyitás a 3D térképen</a>
<div class="lap"><p>{e(mondat)}</p>{dl}{kor}{tobb_html}</div>"""
    return url, oldal(cim + (f" – {cimsor}" if cimsor and cimsor != cim else ""), mondat, torzs, url, ld)


def keszit(ki, epuletek, korszakok, app_js=""):
    """ki: the release/ folder; epuletek: the FULL building list; korszakok: the 'periods' list of budapest.json.
    Returns: the number of pages made, in a dictionary."""
    ki = Path(ki)
    szotar = tipus_szotar(app_js)
    # eras: (slug, from, to, label)
    kor_lista = []
    for k in korszakok:
        a, b = int(k["from"]), int(k["to"])
        kor_lista.append((szlug(k["label"]), a, b, k["label"]))
    lista = [p for p in epuletek if isinstance(p, dict) and kell_oldal(p)]
    # architect slugs (with at least MIN_EPITESZ_DB buildings)
    db = defaultdict(list)
    for p in lista:
        for n in set(tervezok(p)):
            db[n].append(p)
    ep_szlug, hasznalt = {}, set()
    for n in sorted(db, key=lambda x: (-len(db[x]), x)):
        if len(db[n]) < MIN_EPITESZ_DB:
            continue
        sz, i = szlug(n), 2
        alap = sz
        while sz in hasznalt:
            sz, i = f"{alap}-{i}", i + 1
        hasznalt.add(sz)
        ep_szlug[n] = sz
    urlok = ["/", "/explore/"]

    def ir(url, tartalom):
        f = ki / url.strip("/") / "index.html"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(tartalom, encoding="utf-8")
        urlok.append(url)

    # building pages
    for p in lista:
        url, t = epulet_oldal(p, szotar, kor_lista, ep_szlug)
        ir(url, t)
    # korszakoldalak
    kor_db = {}
    for sz, a, b, cimke in kor_lista:
        tagok = sorted((p for p in lista if p.get("ev") and a <= int(p["ev"]) <= b), key=lambda p: (int(p["ev"]), cim_cikk(p)))
        kor_db[sz] = len(tagok)
        if not tagok:
            continue
        li = "".join(f'<li>{e(p["ev"])} – <a href="/e/{gazd(p)}/">{e(cim_cikk(p))}</a>{" (" + e(cim_elso(p)) + ")" if p.get("nev") and cim_elso(p) else ""}</li>' for p in tagok)
        torzs = f"<h1>{e(cimke)}</h1><p class=\"k\">{len(tagok)} épület ismert építési évvel</p><div class=\"lap\"><ul>{li}</ul></div>"
        ir(f"/explore/era/{sz}/", oldal(cimke, f"{cimke}: {len(tagok)} budapesti épület ismert építési évvel.", torzs, f"/explore/era/{sz}/"))
    # architect pages
    for n, sz in ep_szlug.items():
        tagok = sorted(db[n], key=lambda p: (int(p["ev"]) if p.get("ev") else 9999, cim_cikk(p)))
        li = "".join(f'<li>{(e(p["ev"]) + " – ") if p.get("ev") else ""}<a href="/e/{gazd(p)}/">{e(cim_cikk(p))}</a>{" (" + e(cim_elso(p)) + ")" if p.get("nev") and cim_elso(p) else ""}</li>' for p in tagok)
        torzs = f"<h1>{e(n)}</h1><p class=\"k\">{len(tagok)} épülete a térképen</p><div class=\"lap\"><ul>{li}</ul></div>"
        ir(f"/explore/architect/{sz}/", oldal(f"{n} épületei", f"{n} tervezte épületek Budapesten: {len(tagok)} épület.", torzs, f"/explore/architect/{sz}/"))
    # home page
    ossz = defaultdict(int)
    for p in epuletek:
        k = p.get("kor") if isinstance(p, dict) else None
        if k and 1 <= k <= len(kor_lista):
            ossz[k - 1] += 1
    def kor_sor(i, sz, c):
        nev = f'<a href="/explore/era/{sz}/">{e(c)}</a>' if kor_db.get(sz) else e(c)
        return f'<tr><td>{nev}</td><td class="sz">{ossz.get(i, 0):,}</td><td class="sz">{kor_db.get(sz, 0):,}</td></tr>'.replace(",", "&nbsp;")
    sorok = "".join(kor_sor(i, sz, c) for i, (sz, a, b, c) in enumerate(kor_lista))
    ep_li = "".join(f'<li><a href="/explore/architect/{sz}/">{e(n)}</a> ({len(db[n])})</li>' for n, sz in ep_szlug.items())
    torzs = f"""<h1>{OLDAL_NEV}: szöveges változat</h1>
<p class="k">Budapest minden ma álló épülete a térképen; itt a részletes adattal rendelkezők kereshető, olvasható oldalai.</p>
<a class="ter" href="/">Az interaktív 3D térkép</a>
<div class="lap"><h2>Mikor épültek az épületek?</h2>
<table><tr><th>Korszak</th><th class="sz">Épület a térképen</th><th class="sz">Ismert évszámú, itt olvasható</th></tr>{sorok}</table>
<p><small>A térképen a legtöbb épület kora becsült érték. A korszak-oldalakon csak az ismert építési évvel rendelkező épületek szerepelnek.</small></p>
<h2>Építészek</h2><ul>{ep_li}</ul></div>"""
    f = ki / "explore" / "index.html"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(oldal(f"{OLDAL_NEV}: szöveges változat", "Budapest épületei kor, tervező és védettség szerint: olvasható, kereshető oldalak az interaktív 3D térkép mellé.", torzs, "/explore/"), encoding="utf-8")
    # sitemap, robots
    sm = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + \
         "".join(f"<url><loc>{ALAP_URL}{u}</loc></url>\n" for u in urlok) + "</urlset>\n"
    (ki / "sitemap.xml").write_text(sm, encoding="utf-8")
    (ki / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {ALAP_URL}/sitemap.xml\n", encoding="utf-8")
    return {"epulet": len(lista), "korszak": sum(1 for v in kor_db.values() if v), "epitesz": len(ep_szlug), "oldal": len(urlok)}
