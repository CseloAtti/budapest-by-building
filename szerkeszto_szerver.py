"""Helyi szerver a térképhez, szerkesztési móddal.

Elindítás (a projekt mappájában):   py szerkeszto_szerver.py
Megnyitás a böngészőben:            http://localhost:8000

Ugyanazt tudja, mint a `py -m http.server 8000`, de a térképen az épületek adatait
a popupban a "Szerkesztés" gombbal javítani lehet. A javítások a forras/kezi_javitasok.csv
fájlba kerülnek (ezek mindig győznek). A "Térkép újraépítése" gomb lefuttatja az osszeepit.py-t.

Biztonság: a szerver csak a saját gépedről érhető el (127.0.0.1), csak ezt az egy fájlt írja,
és minden beírt értéket ellenőriz.
"""
import csv
import json
import re
import subprocess
import sys
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8000
KEZI = Path("forras/kezi_javitasok.csv")
FEJLEC = ["osm_tipus", "id", "mezo", "ertek", "forras", "megjegyzes", "lat", "lon"]
SZAMOS = {"ev": (1000, 2100), "szintek": (1, 80), "magassag": (1, 500)}
SZOVEGES = {"tervezo"}
EGYSOROS = {"nev": 120}                      # az épület neve
HOSSZU_SZOVEG = {"about": 1500}              # szabad szöveges leírás (több bekezdés is lehet)
VEDETTSEG_KODOK = {"M", "MJ", "VK", "MK", "MJT"}   # műemlék, műemlék jellegű, városképi, műemléki környezet, műemléki jelentőségű terület
ENGEDELYEZETT_ORIGIN = {f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}"}


def tiszta_szoveg(x, max_hossz):
    x = " ".join(str(x).split())          # sortörések, tabok, dupla szóközök ki
    if not x or len(x) > max_hossz or re.search(r"[\x00-\x1f;]", str(x)):
        return None
    return x


def szabad_szoveg(x, max_hossz, tobb_sor):
    """Szabad szöveg: a vezérlőkarakterek (a sortörés kivételével) tiltottak; ';' megengedett (a CSV idézi)."""
    x = str(x).replace("\r\n", "\n").replace("\r", "\n")
    if tobb_sor:
        sorok = [" ".join(s.split()) for s in x.split("\n")]
        x = "\n".join(sorok).strip()
        while "\n\n\n" in x:
            x = x.replace("\n\n\n", "\n\n")
    else:
        x = " ".join(x.split())
    if not x or len(x) > max_hossz or re.search(r"[\x00-\x09\x0b-\x1f\x7f<>]", x):
        return None
    return x


def wikipedia_cim(x):
    """'https://hu.wikipedia.org/wiki/Cím' vagy 'hu:Cím' -> 'hu:Cím' (csak hu/en)."""
    x = str(x).strip()
    m = re.match(r"^https?://(hu|en)\.wikipedia\.org/wiki/([^?#\s]+)(?:[#?].*)?$", x)
    if m:
        nyelv, cim = m.group(1), urllib.parse.unquote(m.group(2)).replace("_", " ")
    else:
        m = re.match(r"^(hu|en):(.+)$", x)
        if not m:
            return None
        nyelv, cim = m.group(1), m.group(2).strip()
    cim = " ".join(cim.split())
    if not cim or len(cim) > 150 or re.search(r"[\x00-\x1f;|<>\[\]{}]", cim):
        return None
    return f"{nyelv}:{cim}"


def wikipedia_cikkek(x):
    """Több cikk '|' jellel elválasztva (legfeljebb 3); '-' = a mező eltávolítása."""
    x = str(x).strip()
    if x == "-":
        return "-"
    reszek = [wikipedia_cim(r) for r in x.split("|") if r.strip()]
    if not reszek or len(reszek) > 3 or any(r is None for r in reszek):
        return None
    return "|".join(dict.fromkeys(reszek))


def ellenoriz(adat):
    """Visszaadja a CSV-sort vagy hibaüzenetet."""
    tipus = adat.get("osm_tipus")
    if tipus not in ("way", "relation"):
        return None, "Ismeretlen épülettípus."
    try:
        azon = int(adat.get("id"))
    except (TypeError, ValueError):
        return None, "Hibás azonosító."
    mezo = adat.get("mezo")
    if mezo in SZAMOS:
        try:
            v = float(str(adat.get("ertek")).replace(",", "."))
        except ValueError:
            return None, f"A(z) {mezo} értéke nem szám."
        lo, hi = SZAMOS[mezo]
        if not lo <= v <= hi:
            return None, f"A(z) {mezo} értéke {lo} és {hi} között lehet."
        ertek = int(v) if v == int(v) else round(v, 1)
    elif mezo in EGYSOROS or mezo in HOSSZU_SZOVEG:
        if str(adat.get("ertek", "")).strip() == "-":
            ertek = "-"
        else:
            hatar = EGYSOROS.get(mezo) or HOSSZU_SZOVEG[mezo]
            ertek = szabad_szoveg(adat.get("ertek", ""), hatar, mezo in HOSSZU_SZOVEG)
            if ertek is None:
                return None, f"A(z) {mezo} értéke üres, legfeljebb {hatar} karakter lehet, és nem tartalmazhat < > jelet."
    elif mezo == "vedettseg":
        ertek = str(adat.get("ertek", "")).strip()
        if ertek != "-" and ertek not in VEDETTSEG_KODOK:
            return None, "A védettség csak M, MJ, VK, MK vagy MJT lehet (vagy '-' az eltávolításhoz)."
    elif mezo == "muemlek_torzsszam":
        ertek = str(adat.get("ertek", "")).strip()
        if ertek != "-":
            if not re.fullmatch(r"\d{1,6}", ertek):
                return None, "A műemléki törzsszám 1–6 jegyű szám (vagy '-' az eltávolításhoz)."
            ertek = int(ertek)
    elif mezo == "wikipedia":
        ertek = wikipedia_cikkek(adat.get("ertek", ""))
        if ertek is None:
            return None, "A Wikipedia-oldal legyen hu.wikipedia.org vagy en.wikipedia.org cikk (link, vagy pl. 'hu:Vigadó'); több cikket | jellel válassz el."
    elif mezo in SZOVEGES:
        ertek = tiszta_szoveg(adat.get("ertek", ""), 100)
        if ertek is None:
            return None, f"A(z) {mezo} értéke üres, túl hosszú, vagy tiltott karaktert tartalmaz."
    else:
        return None, "Ez a mező nem szerkeszthető."
    megj = tiszta_szoveg(adat.get("megjegyzes", ""), 200)
    if megj is None:
        return None, "Add meg a forrást (rövid szöveg, pl. 'Időgép, 1944-es lakásív')."
    return [tipus, azon, mezo, ertek, "kezi", megj, "", ""], None


def sor_hozzaadasa(sor):
    KEZI.parent.mkdir(exist_ok=True)
    uj = not KEZI.exists() or KEZI.stat().st_size == 0
    if not uj:
        with open(KEZI, "rb") as f:
            f.seek(-1, 2)
            vege_ujsor = f.read(1) in (b"\n", b"\r")
    else:
        vege_ujsor = True
    with open(KEZI, "a", encoding="utf-8-sig" if uj else "utf-8", newline="") as f:
        if not vege_ujsor:
            f.write("\r\n")
        w = csv.writer(f, delimiter=";")
        if uj:
            w.writerow(FEJLEC)
        w.writerow(sor)


class Kezelo(SimpleHTTPRequestHandler):
    def _json(self, kod, adat):
        torzs = json.dumps(adat, ensure_ascii=False).encode("utf-8")
        self.send_response(kod)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(torzs)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(torzs)

    def end_headers(self):
        if self.path.split("?")[0].endswith((".geojson", ".json", ".html", ".js", ".css", ".bin", ".png")):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.path == "/api/ping":
            return self._json(200, {"szerkeszto": True})
        return super().do_GET()

    def _engedelyezett(self):
        origin = self.headers.get("Origin")
        return self.headers.get("X-Szerkeszto") == "1" and (origin is None or origin in ENGEDELYEZETT_ORIGIN)

    def do_POST(self):
        if not self._engedelyezett():
            return self._json(403, {"ok": False, "hiba": "Nem engedélyezett kérés."})
        hossz = int(self.headers.get("Content-Length") or 0)
        if hossz > 20_000:
            return self._json(413, {"ok": False, "hiba": "Túl nagy kérés."})
        try:
            adat = json.loads(self.rfile.read(hossz) or b"{}")
        except ValueError:
            return self._json(400, {"ok": False, "hiba": "Hibás kérés."})
        if self.path == "/api/javitas":
            sor, hiba = ellenoriz(adat)
            if hiba:
                return self._json(400, {"ok": False, "hiba": hiba})
            sor_hozzaadasa(sor)
            return self._json(200, {"ok": True})
        if self.path == "/api/ujraepit":
            try:
                eredmeny = subprocess.run([sys.executable, "osszeepit.py"], capture_output=True,
                                          text=True, encoding="utf-8", errors="replace", timeout=600)
            except subprocess.TimeoutExpired:
                return self._json(500, {"ok": False, "hiba": "Az újraépítés túl sokáig tartott."})
            if eredmeny.returncode != 0:
                return self._json(500, {"ok": False, "hiba": (eredmeny.stderr or "")[-400:]})
            # a 3D nézet adatai is újra elkészülnek (ha ez hibázik, a 2D térkép attól még frissül)
            harom_d = "ok"
            try:
                e3 = subprocess.run([sys.executable, "csempek_keszites.py"], capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=600)
                if e3.returncode != 0:
                    harom_d = "hiba: " + ((e3.stderr or e3.stdout or "")[-300:])
            except (subprocess.TimeoutExpired, OSError) as hiba:
                harom_d = f"hiba: {hiba}"
            print(f"  3D adatok: {harom_d}")
            return self._json(200, {"ok": True, "harom_d": harom_d})
        return self._json(404, {"ok": False, "hiba": "Ismeretlen kérés."})

    def log_message(self, fmt, *args):
        if "/api/" in (args[0] if args else ""):
            super().log_message(fmt, *args)


if __name__ == "__main__":
    print(f"A térkép: http://localhost:{PORT}   (leállítás: Ctrl+C)")
    print("Szerkesztési mód aktív: a javítások a forras/kezi_javitasok.csv fájlba kerülnek.")
    ThreadingHTTPServer(("127.0.0.1", PORT), Kezelo).serve_forever()
