"""
facts_bp100_images.py - from the Budapest100 house pages, the address of the house's image (og:image) -> data/bp100/kepek.json

Input:    data/bp100/budapest100_teljes.csv  (the 'url' column: the house's page on budapest100.hu)
Output:   data/bp100/kepek.json              {page_url: {"kep": image_url or "", "foto": the photographer's name or ""}}; can be interrupted and resumed (what is already there is not downloaded again)

Only the image's ADDRESS is stored, the image is not copied: the 3D card loads it directly from budapest100.hu, with a link
to the Budapest100 page. The image belongs to Budapest100 and its authors: check the site's terms of use before using it.

Run:       py facts_bp100_images.py teszt  (trial of a single page, with detailed output: run this first)
           py facts_bp100_images.py        (about 2500 pages, ~0.4 s/page: ~20 minutes; can be stopped with Ctrl+C, resumes on restart)
           py facts_bp100_images.py ujra   (retries the ones without an image)
Afterwards: py facts_bp100.py  ->  py assemble.py varos  ->  py build_tiles.py varos
"""
import csv
import html
import json
import re
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlparse

INPUT = Path("data/bp100/budapest100_teljes.csv")
OUTPUT = Path("data/bp100/kepek.json")
DELAY = 0.4
UA = "budapest-by-building (non-commercial research map; reads the image address of Budapest100 house pages)"

META = re.compile(r"""<meta\s+[^>]*?(?:property|name)\s*=\s*["'](?:og:image|twitter:image)["'][^>]*?>""", re.I)
CONTENT = re.compile(r"""content\s*=\s*["']([^"']+)["']""", re.I)
REVERSED = re.compile(r"""<meta\s+[^>]*?content\s*=\s*["']([^"']+)["'][^>]*?(?:property|name)\s*=\s*["'](?:og:image|twitter:image)["']""", re.I)
IMG = re.compile(r"""<img\s+[^>]*?src\s*=\s*["']([^"']+wp-content/uploads/[^"']+)["']""", re.I)


IMAGE_EXCLUDE = ("logo", "favicon", "cropped-", "placeholder", "default", "avatar")
CONDITION = re.compile(r"""(?:src|data-src|data-lazy-src|data-original|href)\s*=\s*["']([^"']+wp-content/uploads/[^"']+?\.(?:jpe?g|png|webp))(?:\?[^"']*)?["']""", re.I)
SRCSET = re.compile(r"""srcset\s*=\s*["']([^"']*wp-content/uploads/[^"' ]+?\.(?:jpe?g|png|webp))""", re.I)


def image_address(text_, page):
    for m in META.finditer(text_):
        t = CONTENT.search(m.group(0))
        if t:
            return urljoin(page, html.unescape(t.group(1)).strip())
    m = REVERSED.search(text_)
    if m:
        return urljoin(page, html.unescape(m.group(1)).strip())
    for rx in (CONDITION, SRCSET):
        for m in rx.finditer(text_):
            u = html.unescape(m.group(1)).strip()
            if not any(k in u.lower() for k in IMAGE_EXCLUDE):
                return urljoin(page, u)
    return ""


def photographer(text_):
    """On the house page the image's author is marked by a 'Fotó: Name' line (e.g. 'Fotó: Tóvári László'); we take this over for the card's caption."""
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", text_)
    t = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h\d|span|dd|dt|td|tr)>", "\n", t)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    m = re.search(r"Fotó\s*[:©]\s*([^\n]{2,70})", t)
    if not m:
        return ""
    name_ = re.split(r"\s{3,}|\s[|•·]\s", " ".join(m.group(1).split()))[0].strip(" ,;")
    return name_[:70] if re.search(r"[A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű]{2}", name_) else ""


def clean(url):
    """Only a https image of budapest100.hu (and its subdomains) is accepted."""
    try:
        if url.startswith("http://"):                      # the page's own image is also available over https
            url = "https://" + url[len("http://"):]
        u = urlparse(url)
    except ValueError:
        return ""
    if u.scheme != "https" or not u.hostname or not (u.hostname == "budapest100.hu" or u.hostname.endswith(".budapest100.hu")):
        return ""
    if not re.search(r"\.(jpe?g|png|webp)(\?|$)", u.path.lower() + ("?" + u.query if u.query else ""), re.I):
        return ""
    return url


TIMEOUT = 12          # s / request
MAX_BOUNCE_ERROR = 8       # after this many errors in a row it stops and prints the reason


def download(url):
    """(text, error): text=None if it failed; error: a short reason (e.g. 'HTTP 403', 'időtúllépés' = timeout)."""
    error_ = ""
    for try_ in range(2):
        try:
            district_s = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "hu", "Accept": "text/html"})
            with urllib.request.urlopen(district_s, timeout=TIMEOUT) as v:
                return v.read(600_000).decode("utf-8", "replace"), ""
        except urllib.error.HTTPError as e:
            error_ = f"HTTP {e.code}"
            if e.code in (404, 410):
                return None, error_
        except Exception as e:
            error_ = type(e).__name__ + (": " + str(e)[:80] if str(e) else "")
        time.sleep(1.5)
    return None, error_


def test():
    """Downloading and evaluating a single page, with detailed output."""
    rows = list(csv.DictReader(open(INPUT, encoding="utf-8-sig", newline="")))
    url = next((r["url"].strip() for r in rows if (r.get("url") or "").startswith("https://budapest100.hu/")), "")
    print("Teszt-oldal:", url)
    t0 = time.time()
    text_, error_ = download(url)
    print(f"Letöltés: {time.time() - t0:.1f} mp, hiba: {error_ or 'nincs'}, hossz: {len(text_ or '')} karakter")
    if text_:
        raw = image_address(text_, url)
        print("Képcím:", raw or "(nem található)", "| elfogadva:", bool(clean(raw)))
        print("Fényképész:", photographer(text_) or "(nem található)")


def main():
    if "teszt" in sys.argv[1:]:
        return test()
    again = "ujra" in sys.argv[1:]
    rows = list(csv.DictReader(open(INPUT, encoding="utf-8-sig", newline="")))
    urls_ = list(dict.fromkeys((r.get("url") or "").strip() for r in rows if (r.get("url") or "").startswith("https://budapest100.hu/")))
    done = json.load(open(OUTPUT, encoding="utf-8")) if OUTPUT.exists() else {}
    stat = Counter()
    hosts = Counter()
    each_other_after = 0
    sample_none, sample_road_type, image_count = [], [], Counter()
    print(f"Indul: {len(urls_)} oldal, ebből még hátra: {sum(1 for u in urls_ if u not in done)}", flush=True)
    try:
        for i, url in enumerate(urls_, 1):
            if isinstance(done.get(url), str):                       # the format of the first version
                done[url] = {"kep": done[url], "foto": ""}
            if url in done and ((done[url] or {}).get("kep") or not again):
                stat["már megvolt"] += 1
                continue
            t0 = time.time()
            text_, error_ = download(url)
            time.sleep(DELAY)
            if text_ is None:
                stat["az oldal nem érhető el"] += 1
                stat["hiba: " + error_] += 1
                each_other_after += 1
                if error_ not in ("HTTP 404", "HTTP 410"):
                    print(f"  {i}/{len(urls_)} HIBA ({error_}): {url}", flush=True)
                    if each_other_after >= MAX_BOUNCE_ERROR:
                        print(f"Leállok: {each_other_after} egymás utáni hiba ({error_}). A site valószínűleg blokkol vagy nem érhető el; "
                              "próbáld: py facts_bp100_images.py teszt, és küldd el a kimenetet.")
                        break
                else:
                    done[url] = {"kep": "", "foto": ""}
                continue
            each_other_after = 0
            raw = image_address(text_, url)
            ok = clean(raw)
            if raw and not ok:
                hosts[urlparse(raw).hostname or "?"] += 1
                stat["a kép nem a budapest100.hu-n van (kihagyva)"] += 1
                if len(sample_road_type) < 5:
                    sample_road_type.append((url, raw))
            if not raw and len(sample_none) < 5:
                sample_none.append((url, len(re.findall(r"wp-content/uploads", text_)), len(re.findall(r"<img\b", text_)), len(text_)))
            if ok:
                image_count[ok] += 1
            done[url] = {"kep": ok, "foto": photographer(text_) if ok else ""}
            stat["kép van" if ok else "nincs kép"] += 1
            stat["fényképész neve megvan"] += 1 if done[url]["foto"] else 0
            if i <= 5 or i % 10 == 0:
                print(f"  {i}/{len(urls_)}  ({stat['kép van']} kép, {time.time() - t0:.1f} mp/oldal)", flush=True)
            if i % 25 == 0:
                json.dump(done, open(OUTPUT, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    except KeyboardInterrupt:
        print("Megszakítva; az eddigi eredmény mentve, újraindításkor folytatja.")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    json.dump(done, open(OUTPUT, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    capable = sum(1 for v in done.values() if (v.get("kep") if isinstance(v, dict) else v))
    print(f"Oldal: {len(urls_)}; képcímek: {capable} -> {OUTPUT}")
    for k, v in stat.most_common():
        print(f"  {k}: {v}")
    repeat = [(k, n) for k, n in image_count.most_common(3) if n >= 10]
    if repeat:
        print("  FIGYELEM: ugyanaz a kép sok oldalon (alapértelmezett/logó lehet):", repeat)
    if sample_road_type:
        print("  elutasított képcímek mintái:")
        for u, k in sample_road_type:
            print("    ", u, "->", k)
    if sample_none:
        print("  képnélküli oldalak mintái (oldal, 'wp-content/uploads' előfordulás, <img> darab, hossz):")
        for m_ in sample_none:
            print("    ", *m_)
    if hosts:
        print("  idegen képszerverek (ha sok, írd meg, és beállítom):", dict(hosts.most_common(5)))


if __name__ == "__main__":
    main()
