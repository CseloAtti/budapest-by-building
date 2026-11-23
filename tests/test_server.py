"""Security check of the editor server. Run: py tests/test_server.py
In an empty temporary folder, on a free port, it starts the handler of editor_server.py (it does not touch the real files), and checks:
  - with a foreign 'Host' header (DNS rebinding) the server gives out nothing (403);
  - for a missing file a proper 404 comes (earlier the server dropped the connection without a response);
  - a negative Content-Length does not hang the thread (400);
  - writing from a foreign Origin is not possible (403);
  - a malformed request (e.g. '[]') also gets a response (400);
  - parallel saves do not overwrite each other."""
import csv
import http.client
import json
import os
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from test_common import GYOKER, ellenoriz, vege

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
    print("[szerver] editor_server.py")
    import editor_server as sz
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
            # parallel saves: none of them may be lost (earlier out of 200 requests 6 rows remained)
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
            # the machine accepts only a few connections at a time: a refused request gets an error (not silent), but every 'OK' save must be kept
            ellenoriz(len(sikeres) >= N // 2 and db == len(sikeres), f"{len(sikeres)} sikeresnek jelzett párhuzamos mentésből {db} maradt meg a fájlban")
        finally:
            srv.shutdown()
            os.chdir(regi)
    return vege("szerver")


if __name__ == "__main__":
    raise SystemExit(main())
