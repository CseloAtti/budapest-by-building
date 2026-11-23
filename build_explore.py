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

BASE_URL = "https://budapestbuildings.com"
PAGE_NAME = "Budapest épületei"
MIN_ARCHITECT_COUNT = 4          # for fewer buildings than this no designer page is made
YEAR_SOURCE = {"start_date": "OpenStreetMap", "budapest100": "Budapest100", "wikipedia_lista": "Wikipédia",
             "wikidata": "Wikidata", "oeny": "E-Örökség (OENY)", "lechner": "Lechner Tudásközpont", "kezi": "kézi javítás"}
PROTECTION = {"M": "műemlék", "MJ": "műemlék jellegű", "VK": "városképi jelentőségű", "MK": "műemléki környezet",
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


def slug(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "x"


def rich(p):
    return ("r" if p.get("osm_tipus") == "relation" else "w") + str(p["id"])


def address_first(p):
    return str(p.get("cim") or "").split(";")[0].strip()


def address_article(p):
    return str(p.get("nev") or "").strip() or address_first(p)


def own_wikipedia(p):
    w = p.get("wikipedia")
    if not w or p.get("wikipedia_zona"):
        return []
    return [x.strip()[3:] if x.strip().startswith("hu:") else x.strip() for x in str(w).split("|") if x.strip()]


def needed_page(p):
    if p.get("resz") or not address_article(p):
        return False
    return bool(p.get("ev") or p.get("tervezo") or p.get("budapest100_url") or p.get("epforum_url") or p.get("legenda_url")
                or p.get("oeny_azonosito") or p.get("wikidata_id") or own_wikipedia(p))


def designers(p):
    return [x.strip() for x in re.split(r"\s*(?:,|;|\bés\b)\s*", str(p.get("tervezo") or "")) if x.strip()]


def type_dict(app_js):
    """The TIPUS_HU dictionary from app.js (so that the type names appear in Hungarian just as on the map)."""
    m = re.search(r"var TIPUS_HU = \{(.*?)\};", app_js, re.S)
    return dict(re.findall(r"(\w+):\s*'([^']*)'", m.group(1))) if m else {}


def type_name(v, dict_):
    r = [dict_.get(x.strip(), x.strip()) for x in str(v or "").split(";") if x.strip() and x.strip() != "yes"]
    return ", ".join(r)


def page(address, description, serial, url, jsonld=None):
    ld = ""
    if jsonld:
        ld = '<script type="application/ld+json">' + json.dumps(jsonld, ensure_ascii=False).replace("<", "\\u003c") + "</script>"
    return f"""<!doctype html>
<html lang="hu"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(address)} | {PAGE_NAME}</title>
<meta name="description" content="{e(description)}">
<link rel="canonical" href="{BASE_URL}{url}">
<meta property="og:title" content="{e(address)}"><meta property="og:description" content="{e(description)}"><meta property="og:type" content="website"><meta property="og:url" content="{BASE_URL}{url}"><meta property="og:image" content="{BASE_URL}/megosztas_hu.png"><meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="/favicon.svg" type="image/svg+xml"><style>{CSS}</style>{ld}</head><body><main>
<nav><a href="/explore/">{PAGE_NAME}: szöveges változat</a></nav>
{serial}
<footer>Adatok: © OpenStreetMap közreműködők (ODbL), Budapest100, Építészfórum, Budapest Legendák, E-Örökség (OENY), Wikipédia. Az építési évek egy része gyűjtött adat, nem hivatalos nyilvántartás. <a href="/">Vissza az interaktív 3D térképre</a>.</footer>
</main></body></html>
"""


def building_page(p, dict_, era_list, ep_slug):
    gid = rich(p)
    address = address_article(p)
    header = address_first(p)
    rows = []
    if p.get("ev"):
        fr = YEAR_SOURCE.get(p.get("ev_forras"))
        rows.append(("Építés éve", f"{e(p['ev'])}" + (f" <small>(forrás: {e(fr)})</small>" if fr else "")))
    if p.get("tervezo"):
        links = []
        for n in designers(p):
            links.append(f'<a href="/explore/architect/{ep_slug[n]}/">{e(n)}</a>' if n in ep_slug else e(n))
        rows.append(("Tervező", ", ".join(links) if links else e(p["tervezo"])))
    if p.get("stilus"):
        rows.append(("Stílus", e(p["stilus"])))
    t = type_name(p.get("tipus"), dict_)
    if t:
        rows.append(("Típus", e(t)))
    code_ = p.get("vedettseg") or ("HV" if p.get("vedettseg_helyi") else "")
    if code_:
        v = PROTECTION.get(code_, code_) + (f" (törzsszám {p['muemlek_torzsszam']})" if p.get("muemlek_torzsszam") and code_ != "HV" else "")
        rows.append(("Védettség", e(v)))
    if header:
        rows.append(("Cím", e(header)))
    dl = "<dl>" + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows) + "</dl>" if rows else ""
    several = []
    if p.get("budapest100_url"):
        several.append(("Budapest100", p["budapest100_url"]))
    if p.get("epforum_url"):
        several.append(("Építészfórum", p["epforum_url"]))
    if p.get("legenda_url"):
        several.append(("Budapest Legendák", p["legenda_url"]))
    for a in str(p.get("oeny_azonosito") or "").split("|"):
        if re.fullmatch(r"\d{1,8}", a):
            several.append(("E-Örökség (OENY)", f"https://www.oeny.hu/oeny/eorok/public/monument/{a}"))
    for w in own_wikipedia(p):
        several.append((f"Wikipédia: {w}", "https://hu.wikipedia.org/wiki/" + quote(w.replace(" ", "_"))))
    if p.get("wikidata_id"):
        several.append(("Wikidata", f"https://www.wikidata.org/wiki/{quote(str(p['wikidata_id']))}"))
    gm = "https://www.google.com/maps/search/?api=1&query=" + quote(f"{header}, Budapest" if header else f"{p['lat']},{p['lon']}")
    several.append(("Google Térkép", gm))
    several_html = "<h2>Tudj meg többet</h2><ul>" + "".join(f'<li><a href="{e(u)}" rel="noopener">{e(n)}</a></li>' for n, u in several) + "</ul>"
    era = ""
    if p.get("ev") and era_list:
        for sz, a, b, label in era_list:
            if a <= int(p["ev"]) <= b:
                era = f'<p>Korszak: <a href="/explore/era/{sz}/">{e(label)}</a></p>'
                break
    sentence = f"{address}" + (f" ({header})" if header and header != address else "") + " Budapest egyik épülete"
    if p.get("ev"):
        sentence += f", építési éve: {p['ev']}"
    if p.get("tervezo"):
        sentence += f", tervezője: {p['tervezo']}"
    sentence += "."
    url = f"/e/{gid}/"
    ld = {"@context": "https://schema.org", "@type": "Place", "name": address,
          "geo": {"@type": "GeoCoordinates", "latitude": p["lat"], "longitude": p["lon"]}}
    if header:
        ld["address"] = {"@type": "PostalAddress", "streetAddress": header, "addressLocality": "Budapest", "addressCountry": "HU"}
    serial = f"""<h1>{e(address)}</h1>
<p class="k">{e(header) + ", " if header else ""}Budapest</p>
<a class="ter" href="/?e={gid}">Megnyitás a 3D térképen</a>
<div class="lap"><p>{e(sentence)}</p>{dl}{era}{several_html}</div>"""
    return url, page(address + (f" – {header}" if header and header != address else ""), sentence, serial, url, ld)


def make(out, buildings, eras, app_js=""):
    """ki: the release/ folder; epuletek: the FULL building list; korszakok: the 'periods' list of budapest.json.
    Returns: the number of pages made, in a dictionary."""
    out = Path(out)
    dict_ = type_dict(app_js)
    # eras: (slug, from, to, label)
    era_list = []
    for k in eras:
        a, b = int(k["from"]), int(k["to"])
        era_list.append((slug(k["label"]), a, b, k["label"]))
    list_ = [p for p in buildings if isinstance(p, dict) and needed_page(p)]
    # architect slugs (with at least MIN_EPITESZ_DB buildings)
    count_ = defaultdict(list)
    for p in list_:
        for n in set(designers(p)):
            count_[n].append(p)
    ep_slug, used = {}, set()
    for n in sorted(count_, key=lambda x: (-len(count_[x]), x)):
        if len(count_[n]) < MIN_ARCHITECT_COUNT:
            continue
        sz, i = slug(n), 2
        base = sz
        while sz in used:
            sz, i = f"{base}-{i}", i + 1
        used.add(sz)
        ep_slug[n] = sz
    urls_ = ["/", "/explore/"]

    def ir(url, content):
        f = out / url.strip("/") / "index.html"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content, encoding="utf-8")
        urls_.append(url)

    # building pages
    for p in list_:
        url, t = building_page(p, dict_, era_list, ep_slug)
        ir(url, t)
    # korszakoldalak
    era_count = {}
    for sz, a, b, label in era_list:
        members = sorted((p for p in list_ if p.get("ev") and a <= int(p["ev"]) <= b), key=lambda p: (int(p["ev"]), address_article(p)))
        era_count[sz] = len(members)
        if not members:
            continue
        li = "".join(f'<li>{e(p["ev"])} – <a href="/e/{rich(p)}/">{e(address_article(p))}</a>{" (" + e(address_first(p)) + ")" if p.get("nev") and address_first(p) else ""}</li>' for p in members)
        serial = f"<h1>{e(label)}</h1><p class=\"k\">{len(members)} épület ismert építési évvel</p><div class=\"lap\"><ul>{li}</ul></div>"
        ir(f"/explore/era/{sz}/", page(label, f"{label}: {len(members)} budapesti épület ismert építési évvel.", serial, f"/explore/era/{sz}/"))
    # architect pages
    for n, sz in ep_slug.items():
        members = sorted(count_[n], key=lambda p: (int(p["ev"]) if p.get("ev") else 9999, address_article(p)))
        li = "".join(f'<li>{(e(p["ev"]) + " – ") if p.get("ev") else ""}<a href="/e/{rich(p)}/">{e(address_article(p))}</a>{" (" + e(address_first(p)) + ")" if p.get("nev") and address_first(p) else ""}</li>' for p in members)
        serial = f"<h1>{e(n)}</h1><p class=\"k\">{len(members)} épülete a térképen</p><div class=\"lap\"><ul>{li}</ul></div>"
        ir(f"/explore/architect/{sz}/", page(f"{n} épületei", f"{n} tervezte épületek Budapesten: {len(members)} épület.", serial, f"/explore/architect/{sz}/"))
    # home page
    total = defaultdict(int)
    for p in buildings:
        k = p.get("kor") if isinstance(p, dict) else None
        if k and 1 <= k <= len(era_list):
            total[k - 1] += 1
    def era_row(i, sz, c):
        name_ = f'<a href="/explore/era/{sz}/">{e(c)}</a>' if era_count.get(sz) else e(c)
        return f'<tr><td>{name_}</td><td class="sz">{total.get(i, 0):,}</td><td class="sz">{era_count.get(sz, 0):,}</td></tr>'.replace(",", "&nbsp;")
    rows = "".join(era_row(i, sz, c) for i, (sz, a, b, c) in enumerate(era_list))
    ep_li = "".join(f'<li><a href="/explore/architect/{sz}/">{e(n)}</a> ({len(count_[n])})</li>' for n, sz in ep_slug.items())
    serial = f"""<h1>{PAGE_NAME}: szöveges változat</h1>
<p class="k">Budapest minden ma álló épülete a térképen; itt a részletes adattal rendelkezők kereshető, olvasható oldalai.</p>
<a class="ter" href="/">Az interaktív 3D térkép</a>
<div class="lap"><h2>Mikor épültek az épületek?</h2>
<table><tr><th>Korszak</th><th class="sz">Épület a térképen</th><th class="sz">Ismert évszámú, itt olvasható</th></tr>{rows}</table>
<p><small>A térképen a legtöbb épület kora becsült érték. A korszak-oldalakon csak az ismert építési évvel rendelkező épületek szerepelnek.</small></p>
<h2>Építészek</h2><ul>{ep_li}</ul></div>"""
    f = out / "explore" / "index.html"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(page(f"{PAGE_NAME}: szöveges változat", "Budapest épületei kor, tervező és védettség szerint: olvasható, kereshető oldalak az interaktív 3D térkép mellé.", serial, "/explore/"), encoding="utf-8")
    # sitemap, robots
    sm = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + \
         "".join(f"<url><loc>{BASE_URL}{u}</loc></url>\n" for u in urls_) + "</urlset>\n"
    (out / "sitemap.xml").write_text(sm, encoding="utf-8")
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {BASE_URL}/sitemap.xml\n", encoding="utf-8")
    return {"epulet": len(list_), "korszak": sum(1 for v in era_count.values() if v), "epitesz": len(ep_slug), "oldal": len(urls_)}
