"""Minimális GeoTIFF-olvasó tiszta Pythonban (csak az alap könyvtár kell).

Tud: klasszikus TIFF és BigTIFF, sávos (strip) és csempés (tile) elrendezés, tömörítés: nincs, Deflate (8/32946), LZW (5),
vízszintes predictor (2), 8/16/32 bites egész és 32 bites lebegőpontos érték, egy sáv. A pixelek helyét a ModelPixelScale (33550) és a
ModelTiepoint (33922) címkékből számolja. Egyszerre csak a ténylegesen kért blokkokat bontja ki.
"""
import struct
import zlib

TIPUS = {1: ("B", 1), 2: ("s", 1), 3: ("H", 2), 4: ("I", 4), 5: ("II", 8), 6: ("b", 1), 7: ("B", 1), 8: ("h", 2),
         9: ("i", 4), 10: ("ii", 8), 11: ("f", 4), 12: ("d", 8), 16: ("Q", 8), 17: ("q", 8), 18: ("Q", 8)}


def lzw_kibont(adat):
    """TIFF-LZW (MSB, korai kódszélesség-váltással)."""
    CLEAR, EOI = 256, 257
    ki = bytearray()
    tabla = None
    szeles = 9
    kovetkezo = 258
    puffer = 0
    bitek = 0
    elozo = None
    for b in adat:
        puffer = (puffer << 8) | b
        bitek += 8
        while bitek >= szeles:
            kod = (puffer >> (bitek - szeles)) & ((1 << szeles) - 1)
            bitek -= szeles
            puffer &= (1 << bitek) - 1
            if kod == EOI:
                return bytes(ki)
            if kod == CLEAR:
                tabla = [bytes([i]) for i in range(256)] + [b"", b""]
                szeles, kovetkezo, elozo = 9, 258, None
                continue
            if tabla is None:
                tabla = [bytes([i]) for i in range(256)] + [b"", b""]
                kovetkezo = 258
            if elozo is None:
                if kod < len(tabla):
                    ki += tabla[kod]
                    elozo = tabla[kod]
                continue
            if kod < len(tabla):
                bejegyzes = tabla[kod]
            elif kod == len(tabla):
                bejegyzes = elozo + elozo[:1]
            else:
                raise ValueError("hibás LZW-adat")
            ki += bejegyzes
            tabla.append(elozo + bejegyzes[:1])
            kovetkezo = len(tabla)
            elozo = bejegyzes
            if kovetkezo >= (1 << szeles) - 1 and szeles < 12:
                szeles += 1
    return bytes(ki)


class GeoTiff:
    def __init__(self, adat):
        self.d = adat
        if adat[:2] == b"II":
            self.e = "<"
        elif adat[:2] == b"MM":
            self.e = ">"
        else:
            raise ValueError("nem TIFF fájl")
        onkod = struct.unpack(self.e + "H", adat[2:4])[0]
        self.big = onkod == 43
        if onkod == 43:
            ifd = struct.unpack(self.e + "Q", adat[8:16])[0]
        elif onkod == 42:
            ifd = struct.unpack(self.e + "I", adat[4:8])[0]
        else:
            raise ValueError("nem TIFF fájl")
        self.c = self._ifd(ifd)
        t = self.c
        self.w, self.h = t[256][0], t[257][0]
        self.bit = t.get(258, [8])[0]
        self.tomor = t.get(259, [1])[0]
        self.pred = t.get(317, [1])[0]
        self.forma = t.get(339, [1])[0]
        if t.get(277, [1])[0] != 1:
            raise ValueError("csak egysávos TIFF támogatott")
        if self.tomor not in (1, 5, 8, 32946):
            raise ValueError("nem támogatott tömörítés: %s" % self.tomor)
        if 322 in t:
            self.csempes = True
            self.bw, self.bh = t[322][0], t[323][0]
            self.offs, self.hossz = t[324], t[325]
        else:
            self.csempes = False
            self.bw, self.bh = self.w, t.get(278, [self.h])[0]
            self.offs, self.hossz = t[273], t[279]
        skala, tie = t.get(33550), t.get(33922)
        if not skala or not tie:
            raise ValueError("nincs georeferencia (ModelPixelScale/Tiepoint)")
        self.sx, self.sy = skala[0], skala[1]
        self.x0 = tie[3] - tie[0] * self.sx          # a bal felső sarok koordinátája
        self.y0 = tie[4] + tie[1] * self.sy
        self.nodata = None
        if 42113 in t:
            try:
                self.nodata = float(t[42113][0].strip("\x00 ") if isinstance(t[42113][0], str) else t[42113][0])
            except (ValueError, TypeError):
                pass
        if self.forma == 3:
            self.kod = {32: "f", 64: "d"}[self.bit]
        else:
            self.kod = {(8, 1): "B", (16, 1): "H", (32, 1): "I", (8, 2): "b", (16, 2): "h", (32, 2): "i"}[(self.bit, self.forma)]
        self.meret = self.bit // 8

    def _ifd(self, ut):
        e, d = self.e, self.d
        ki = {}
        if self.big:
            n = struct.unpack(e + "Q", d[ut:ut + 8])[0]
            elso, bejegyzes, inline, mutato = ut + 8, 20, 8, "Q"
        else:
            n = struct.unpack(e + "H", d[ut:ut + 2])[0]
            elso, bejegyzes, inline, mutato = ut + 2, 12, 4, "I"
        for k in range(n):
            o = elso + bejegyzes * k
            if self.big:
                tag, tip, db, ertek = struct.unpack(e + "HHQ8s", d[o:o + bejegyzes])
            else:
                tag, tip, db, ertek = struct.unpack(e + "HHI4s", d[o:o + bejegyzes])
            if tip not in TIPUS:
                continue
            fmt, mer = TIPUS[tip]
            osszes = mer * db
            if osszes <= inline:
                nyers = ertek[:osszes]
            else:
                p = struct.unpack(e + mutato, ertek[:struct.calcsize(mutato)])[0]
                nyers = d[p:p + osszes]
            if tip == 2:
                ki[tag] = [nyers.decode("latin-1")]
            elif tip in (5, 10):
                ki[tag] = [x / y if y else 0.0 for x, y in struct.iter_unpack(e + fmt, nyers)]
            else:
                ki[tag] = list(struct.unpack(e + fmt * db, nyers))
        return ki

    def blokk(self, index):
        """Egy blokk (sáv vagy csempe) kibontása: (blokk_szélesség, blokk_magasság, értékek listája soronként összefűzve)."""
        nyers = self.d[self.offs[index]: self.offs[index] + self.hossz[index]]
        if self.tomor in (8, 32946):
            nyers = zlib.decompress(nyers)
        elif self.tomor == 5:
            nyers = lzw_kibont(nyers)
        bw = self.bw
        if self.csempes:
            bh = self.bh
        else:
            bh = min(self.bh, self.h - index * self.bh)
        db = bw * bh
        nyers = nyers[:db * self.meret]
        if len(nyers) < db * self.meret:
            nyers = nyers + b"\x00" * (db * self.meret - len(nyers))
        ertek = list(struct.unpack(self.e + self.kod * db, nyers))
        if self.pred == 2 and self.forma != 3:
            maszk = (1 << self.bit) - 1
            for sor in range(bh):
                o = sor * bw
                for k in range(1, bw):
                    ertek[o + k] = (ertek[o + k] + ertek[o + k - 1]) & maszk
            if self.forma == 2:       # előjeles: visszaalakítás
                fel = 1 << (self.bit - 1)
                ertek = [v - (1 << self.bit) if v >= fel else v for v in ertek]
        return bw, bh, ertek

    def koordinata_pixelre(self, x, y):
        return (x - self.x0) / self.sx, (self.y0 - y) / self.sy

    def ertekek(self, pontok):
        """pontok: [(x, y)] a fájl vetületében. Visszaad: lista, a pont értéke vagy None (kívül van / nodata)."""
        ki = [None] * len(pontok)
        csoport = {}
        for n, (x, y) in enumerate(pontok):
            c, r = self.koordinata_pixelre(x, y)
            c, r = int(c // 1), int(r // 1)
            if not (0 <= c < self.w and 0 <= r < self.h):
                continue
            if self.csempes:
                per_sor = (self.w + self.bw - 1) // self.bw
                bi = (r // self.bh) * per_sor + (c // self.bw)
                csoport.setdefault(bi, []).append((n, c % self.bw, r % self.bh))
            else:
                csoport.setdefault(r // self.bh, []).append((n, c, r % self.bh))
        for bi, lista in csoport.items():
            bw, bh, ertek = self.blokk(bi)
            for n, c, r in lista:
                v = ertek[r * bw + c]
                if self.nodata is not None and v == self.nodata:
                    continue
                ki[n] = v
        return ki
