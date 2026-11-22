"""A szerkesztő szerver biztonsági ellenőrzése. Futtatás: py tesztek/teszt_szerver.py
Egy üres ideiglenes mappában, szabad porton indítja el a szerkeszto_szerver.py kezelőjét (a valódi fájlokhoz nem nyúl), és megnézi:
  - idegen 'Host' fejléccel (DNS rebinding) a szerver semmit nem ad ki (403);
  - hiányzó fájlra rendes 404 jön (korábban a szerver válasz nélkül bontotta a kapcsolatot);
  - negatív Content-Length nem akasztja meg a szálat (400);
  - idegen Origin-ről nem lehet írni (403);
  - hibás alakú kérésre (pl. '[]') is jön válasz (400);
  - párhuzamos mentések nem írják felül egymást."""
import csv
import http.client
import json
import os
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from kozos_teszt import GYOKER, ellenoriz, vege

sys.path.insert(0, str(GYOKER))


def kerdez(port, modszer, ut, fejlec=None, torzs=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        c.putrequest(modszer, ut, skip_host=True, skip_accept_encoding=True)
        for k, v in (fejlec or {}).items():
            c.putheader(k, v)
        c.endheaders(torzs)
        return c.getresponse().status
    except Exception as kiv:
        return f"nincs válasz ({kiv.__class__.__name__})"
    finally:
        c.close()


def main():
    print("[szerver] szerkeszto_szerver.py")
    import szerkeszto_szerver as sz
    regi = os.getcwd()
    with tempfile.TemporaryDirectory() as mappa:
        os.chdir(mappa)
        open("proba.txt", "w").write("titok")
        srv = ThreadingHTTPServer(("127.0.0.1", 0), sz.Kezelo)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            helyi = {"Host": f"localhost:{port}"}
            r = kerdez(port, "GET", "/proba.txt", {"Host": f"tamado.example:{port}"})
            ellenoriz(r == 403, f"idegen Host fejléccel a szerver kiadta a fájlt (DNS rebinding): {r}")
            r = kerdez(port, "GET", "/proba.txt", helyi)
            ellenoriz(r == 200, f"helyi kérésre a fájl nem jött: {r}")
            r = kerdez(port, "GET", "/nincs_ilyen.json", helyi)
            ellenoriz(r == 404, f"hiányzó fájlra nem 404 jött: {r}")
            r = kerdez(port, "POST", "/api/javitas", {**helyi, "X-Szerkeszto": "1", "Content-Length": "-1"})
            ellenoriz(r == 400, f"negatív Content-Length: {r}")
            r = kerdez(port, "POST", "/api/javitas", {"Host": f"tamado.example:{port}", "Origin": f"http://tamado.example:{port}",
                                                      "X-Szerkeszto": "1", "Content-Length": "2"}, b"{}")
            ellenoriz(r == 403, f"idegen helyről érkező írási kérés nem lett elutasítva: {r}")
            r = kerdez(port, "POST", "/api/javitas", {**helyi, "X-Szerkeszto": "1", "Content-Length": "2"}, b"[]")
            ellenoriz(r == 400, f"'[]' törzsre nem jött válasz (400 kellene): {r}")
            # párhuzamos mentések: egyik sem veszhet el (korábban 200 kérésből 6 sor maradt)
            os.makedirs("forras", exist_ok=True)
            with open("forras/epitesz_irodak.csv", "w", encoding="utf-8-sig", newline="") as f:
                f.write("kulcs;nev;tipus;forras;megjegyzes\r\n")
            N = 60
            sikeres = []

            def ment(i):
                torzs = json.dumps({"kulcs": f"k{i}", "nev": f"Iroda {i}", "tipus": "iroda"}).encode()
                if kerdez(port, "POST", "/api/epitesz_tipus", {**helyi, "X-Szerkeszto": "1", "Content-Length": str(len(torzs))}, torzs) == 200:
                    sikeres.append(i)
            szalak = [threading.Thread(target=ment, args=(i,)) for i in range(N)]
            for t in szalak:
                t.start()
            for t in szalak:
                t.join()
            with open("forras/epitesz_irodak.csv", encoding="utf-8-sig") as f:
                db = sum(1 for _ in csv.DictReader(f, delimiter=";"))
            # a gép egyszerre csak néhány kapcsolatot fogad: a visszautasított kérés hibát kap (nem csendes), de minden 'OK' mentésnek meg kell maradnia
            ellenoriz(len(sikeres) >= N // 2 and db == len(sikeres), f"{len(sikeres)} sikeresnek jelzett párhuzamos mentésből {db} maradt meg a fájlban")
        finally:
            srv.shutdown()
            os.chdir(regi)
    return vege("szerver")


if __name__ == "__main__":
    raise SystemExit(main())
