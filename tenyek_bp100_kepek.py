"""
tenyek_bp100_kepek.py - from the Budapest100 house pages, the address of the house's image (og:image) -> data/bp100/kepek.json

Input:    data/bp100/budapest100_teljes.csv  (the 'url' column: the house's page on budapest100.hu)
Output:   data/bp100/kepek.json              {page_url: {"kep": image_url or "", "foto": the photographer's name or ""}}; can be interrupted and resumed (what is already there is not downloaded again)

Only the image's ADDRESS is stored, the image is not copied: the 3D card loads it directly from budapest100.hu, with a link
to the Budapest100 page. The image belongs to Budapest100 and its authors: check the site's terms of use before using it.

Run:       py tenyek_bp100_kepek.py teszt  (trial of a single page, with detailed output: run this first)
           py tenyek_bp100_kepek.py        (about 2500 pages, ~0.4 s/page: ~20 minutes; can be stopped with Ctrl+C, resumes on restart)
           py tenyek_bp100_kepek.py ujra   (retries the ones without an image)
Afterwards: py tenyek_bp100.py  ->  py osszeepit.py varos  ->  py csempek_keszites.py varos
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

BEMENET = Path("data/bp100/budapest100_teljes.csv")
KIMENET = Path("data/bp100/kepek.json")
KESLELTETES = 0.4
UA = "budapest-by-building (non-commercial research map; reads the image address of Budapest100 house pages)"

META = re.compile(r"""<meta\s+[^>]*?(?:property|name)\s*=\s*["'](?:og:image|twitter:image)["'][^>]*?>""", re.I)
TARTALOM = re.compile(r"""content\s*=\s*["']([^"']+)["']""", re.I)
FORDITOTT = re.compile(r"""<meta\s+[^>]*?content\s*=\s*["']([^"']+)["'][^>]*?(?:property|name)\s*=\s*["'](?:og:image|twitter:image)["']""", re.I)
IMG = re.compile(r"""<img\s+[^>]*?src\s*=\s*["']([^"']+wp-content/uploads/[^"']+)["']""", re.I)


KEP_KIZAR = ("logo", "favicon", "cropped-", "placeholder", "default", "avatar")
FELT = re.compile(r"""(?:src|data-src|data-lazy-src|data-original|href)\s*=\s*["']([^"']+wp-content/uploads/[^"']+?\.(?:jpe?g|png|webp))(?:\?[^"']*)?["']""", re.I)
SRCSET = re.compile(r"""srcset\s*=\s*["']([^"']*wp-content/uploads/[^"' ]+?\.(?:jpe?g|png|webp))""", re.I)


def kep_cim(szoveg, oldal):
    for m in META.finditer(szoveg):
        t = TARTALOM.search(m.group(0))
        if t:
            return urljoin(oldal, html.unescape(t.group(1)).strip())
    m = FORDITOTT.search(szoveg)
    if m:
        return urljoin(oldal, html.unescape(m.group(1)).strip())
    for rx in (FELT, SRCSET):
        for m in rx.finditer(szoveg):
            u = html.unescape(m.group(1)).strip()
            if not any(k in u.lower() for k in KEP_KIZAR):
                return urljoin(oldal, u)
    return ""


def fotos(szoveg):
    """On the house page the image's author is marked by a 'Fotó: Name' line (e.g. 'Fotó: Tóvári László'); we take this over for the card's caption."""
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", szoveg)
    t = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h\d|span|dd|dt|td|tr)>", "\n", t)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    m = re.search(r"Fotó\s*[:©]\s*([^\n]{2,70})", t)
    if not m:
        return ""
    nev = re.split(r"\s{3,}|\s[|•·]\s", " ".join(m.group(1).split()))[0].strip(" ,;")
    return nev[:70] if re.search(r"[A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű]{2}", nev) else ""


def tiszta(url):
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


IDOKORLAT = 12          # s / request
MAX_PEREG_HIBA = 8       # after this many errors in a row it stops and prints the reason


def letolt(url):
    """(text, error): text=None if it failed; error: a short reason (e.g. 'HTTP 403', 'időtúllépés' = timeout)."""
    hiba = ""
    for proba in range(2):
        try:
            kerés = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "hu", "Accept": "text/html"})
            with urllib.request.urlopen(kerés, timeout=IDOKORLAT) as v:
                return v.read(600_000).decode("utf-8", "replace"), ""
        except urllib.error.HTTPError as e:
            hiba = f"HTTP {e.code}"
            if e.code in (404, 410):
                return None, hiba
        except Exception as e:
            hiba = type(e).__name__ + (": " + str(e)[:80] if str(e) else "")
        time.sleep(1.5)
    return None, hiba


def teszt():
    """Downloading and evaluating a single page, with detailed output."""
    sorok = list(csv.DictReader(open(BEMENET, encoding="utf-8-sig", newline="")))
    url = next((r["url"].strip() for r in sorok if (r.get("url") or "").startswith("https://budapest100.hu/")), "")
    print("Teszt-oldal:", url)
    t0 = time.time()
    szoveg, hiba = letolt(url)
    print(f"Letöltés: {time.time() - t0:.1f} mp, hiba: {hiba or 'nincs'}, hossz: {len(szoveg or '')} karakter")
    if szoveg:
        nyers = kep_cim(szoveg, url)
        print("Képcím:", nyers or "(nem található)", "| elfogadva:", bool(tiszta(nyers)))
        print("Fényképész:", fotos(szoveg) or "(nem található)")


def main():
    if "teszt" in sys.argv[1:]:
        return teszt()
    ujra = "ujra" in sys.argv[1:]
    sorok = list(csv.DictReader(open(BEMENET, encoding="utf-8-sig", newline="")))
    urlok = list(dict.fromkeys((r.get("url") or "").strip() for r in sorok if (r.get("url") or "").startswith("https://budapest100.hu/")))
    kesz = json.load(open(KIMENET, encoding="utf-8")) if KIMENET.exists() else {}
    stat = Counter()
    hostok = Counter()
    egymas_utan = 0
    minta_nincs, minta_elut, kepszam = [], [], Counter()
    print(f"Indul: {len(urlok)} oldal, ebből még hátra: {sum(1 for u in urlok if u not in kesz)}", flush=True)
    try:
        for i, url in enumerate(urlok, 1):
            if isinstance(kesz.get(url), str):                       # the format of the first version
                kesz[url] = {"kep": kesz[url], "foto": ""}
            if url in kesz and ((kesz[url] or {}).get("kep") or not ujra):
                stat["már megvolt"] += 1
                continue
            t0 = time.time()
            szoveg, hiba = letolt(url)
            time.sleep(KESLELTETES)
            if szoveg is None:
                stat["az oldal nem érhető el"] += 1
                stat["hiba: " + hiba] += 1
                egymas_utan += 1
                if hiba not in ("HTTP 404", "HTTP 410"):
                    print(f"  {i}/{len(urlok)} HIBA ({hiba}): {url}", flush=True)
                    if egymas_utan >= MAX_PEREG_HIBA:
                        print(f"Leállok: {egymas_utan} egymás utáni hiba ({hiba}). A site valószínűleg blokkol vagy nem érhető el; "
                              "próbáld: py tenyek_bp100_kepek.py teszt, és küldd el a kimenetet.")
                        break
                else:
                    kesz[url] = {"kep": "", "foto": ""}
                continue
            egymas_utan = 0
            nyers = kep_cim(szoveg, url)
            ok = tiszta(nyers)
            if nyers and not ok:
                hostok[urlparse(nyers).hostname or "?"] += 1
                stat["a kép nem a budapest100.hu-n van (kihagyva)"] += 1
                if len(minta_elut) < 5:
                    minta_elut.append((url, nyers))
            if not nyers and len(minta_nincs) < 5:
                minta_nincs.append((url, len(re.findall(r"wp-content/uploads", szoveg)), len(re.findall(r"<img\b", szoveg)), len(szoveg)))
            if ok:
                kepszam[ok] += 1
            kesz[url] = {"kep": ok, "foto": fotos(szoveg) if ok else ""}
            stat["kép van" if ok else "nincs kép"] += 1
            stat["fényképész neve megvan"] += 1 if kesz[url]["foto"] else 0
            if i <= 5 or i % 10 == 0:
                print(f"  {i}/{len(urlok)}  ({stat['kép van']} kép, {time.time() - t0:.1f} mp/oldal)", flush=True)
            if i % 25 == 0:
                json.dump(kesz, open(KIMENET, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    except KeyboardInterrupt:
        print("Megszakítva; az eddigi eredmény mentve, újraindításkor folytatja.")
    KIMENET.parent.mkdir(parents=True, exist_ok=True)
    json.dump(kesz, open(KIMENET, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    kepes = sum(1 for v in kesz.values() if (v.get("kep") if isinstance(v, dict) else v))
    print(f"Oldal: {len(urlok)}; képcímek: {kepes} -> {KIMENET}")
    for k, v in stat.most_common():
        print(f"  {k}: {v}")
    ism = [(k, n) for k, n in kepszam.most_common(3) if n >= 10]
    if ism:
        print("  FIGYELEM: ugyanaz a kép sok oldalon (alapértelmezett/logó lehet):", ism)
    if minta_elut:
        print("  elutasított képcímek mintái:")
        for u, k in minta_elut:
            print("    ", u, "->", k)
    if minta_nincs:
        print("  képnélküli oldalak mintái (oldal, 'wp-content/uploads' előfordulás, <img> darab, hossz):")
        for m_ in minta_nincs:
            print("    ", *m_)
    if hostok:
        print("  idegen képszerverek (ha sok, írd meg, és beállítom):", dict(hostok.most_common(5)))


if __name__ == "__main__":
    main()
