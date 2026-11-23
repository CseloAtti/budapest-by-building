"""A minimal GeoTIFF reader in pure Python (only the standard library is needed).

It can do: classic TIFF and BigTIFF, strip and tile layouts, compression: none, Deflate (8/32946), LZW (5),
horizontal predictor (2), 8/16/32-bit integer and 32-bit floating-point values, one band. It computes the pixels' position from the ModelPixelScale (33550) and
ModelTiepoint (33922) tags. It decompresses only the blocks actually requested at a time.
"""
import struct
import zlib

TYPE = {1: ("B", 1), 2: ("s", 1), 3: ("H", 2), 4: ("I", 4), 5: ("II", 8), 6: ("b", 1), 7: ("B", 1), 8: ("h", 2),
         9: ("i", 4), 10: ("ii", 8), 11: ("f", 4), 12: ("d", 8), 16: ("Q", 8), 17: ("q", 8), 18: ("Q", 8)}


def lzw_unpack(data_):
    """TIFF-LZW (MSB, with early code-width change)."""
    CLEAR, EOI = 256, 257
    out = bytearray()
    table = None
    wide = 9
    next_ = 258
    buffer = 0
    bits = 0
    previous = None
    for b in data_:
        buffer = (buffer << 8) | b
        bits += 8
        while bits >= wide:
            code_ = (buffer >> (bits - wide)) & ((1 << wide) - 1)
            bits -= wide
            buffer &= (1 << bits) - 1
            if code_ == EOI:
                return bytes(out)
            if code_ == CLEAR:
                table = [bytes([i]) for i in range(256)] + [b"", b""]
                wide, next_, previous = 9, 258, None
                continue
            if table is None:
                table = [bytes([i]) for i in range(256)] + [b"", b""]
                next_ = 258
            if previous is None:
                if code_ < len(table):
                    out += table[code_]
                    previous = table[code_]
                continue
            if code_ < len(table):
                entry = table[code_]
            elif code_ == len(table):
                entry = previous + previous[:1]
            else:
                raise ValueError("hibás LZW-adat")
            out += entry
            table.append(previous + entry[:1])
            next_ = len(table)
            previous = entry
            if next_ >= (1 << wide) - 1 and wide < 12:
                wide += 1
    return bytes(out)


class GeoTiff:
    def __init__(self, data_):
        self.d = data_
        if data_[:2] == b"II":
            self.e = "<"
        elif data_[:2] == b"MM":
            self.e = ">"
        else:
            raise ValueError("nem TIFF fájl")
        self_code = struct.unpack(self.e + "H", data_[2:4])[0]
        self.big = self_code == 43
        if self_code == 43:
            ifd = struct.unpack(self.e + "Q", data_[8:16])[0]
        elif self_code == 42:
            ifd = struct.unpack(self.e + "I", data_[4:8])[0]
        else:
            raise ValueError("nem TIFF fájl")
        self.c = self._ifd(ifd)
        t = self.c
        self.w, self.h = t[256][0], t[257][0]
        self.bit = t.get(258, [8])[0]
        self.compressed = t.get(259, [1])[0]
        self.pred = t.get(317, [1])[0]
        self.forma = t.get(339, [1])[0]
        if t.get(277, [1])[0] != 1:
            raise ValueError("csak egysávos TIFF támogatott")
        if self.compressed not in (1, 5, 8, 32946):
            raise ValueError("nem támogatott tömörítés: %s" % self.compressed)
        if 322 in t:
            self.csempes = True
            self.bw, self.bh = t[322][0], t[323][0]
            self.offs, self.length = t[324], t[325]
        else:
            self.csempes = False
            self.bw, self.bh = self.w, t.get(278, [self.h])[0]
            self.offs, self.length = t[273], t[279]
        scale, tie = t.get(33550), t.get(33922)
        if not scale or not tie:
            raise ValueError("nincs georeferencia (ModelPixelScale/Tiepoint)")
        self.sx, self.sy = scale[0], scale[1]
        self.x0 = tie[3] - tie[0] * self.sx          # the coordinate of the top-left corner
        self.y0 = tie[4] + tie[1] * self.sy
        self.nodata = None
        if 42113 in t:
            try:
                self.nodata = float(t[42113][0].strip("\x00 ") if isinstance(t[42113][0], str) else t[42113][0])
            except (ValueError, TypeError):
                pass
        if self.forma == 3:
            self.code_ = {32: "f", 64: "d"}[self.bit]
        else:
            self.code_ = {(8, 1): "B", (16, 1): "H", (32, 1): "I", (8, 2): "b", (16, 2): "h", (32, 2): "i"}[(self.bit, self.forma)]
        self.size = self.bit // 8

    def _ifd(self, path_):
        e, d = self.e, self.d
        out = {}
        if self.big:
            n = struct.unpack(e + "Q", d[path_:path_ + 8])[0]
            first, entry, inline, indicator = path_ + 8, 20, 8, "Q"
        else:
            n = struct.unpack(e + "H", d[path_:path_ + 2])[0]
            first, entry, inline, indicator = path_ + 2, 12, 4, "I"
        for k in range(n):
            o = first + entry * k
            if self.big:
                tag, kind, count_, value = struct.unpack(e + "HHQ8s", d[o:o + entry])
            else:
                tag, kind, count_, value = struct.unpack(e + "HHI4s", d[o:o + entry])
            if kind not in TYPE:
                continue
            fmt, mer = TYPE[kind]
            all_ = mer * count_
            if all_ <= inline:
                raw = value[:all_]
            else:
                p = struct.unpack(e + indicator, value[:struct.calcsize(indicator)])[0]
                raw = d[p:p + all_]
            if kind == 2:
                out[tag] = [raw.decode("latin-1")]
            elif kind in (5, 10):
                out[tag] = [x / y if y else 0.0 for x, y in struct.iter_unpack(e + fmt, raw)]
            else:
                out[tag] = list(struct.unpack(e + fmt * count_, raw))
        return out

    def block(self, index):
        """Decompressing one block (strip or tile): (block_width, block_height, list of values concatenated row by row)."""
        raw = self.d[self.offs[index]: self.offs[index] + self.length[index]]
        if self.compressed in (8, 32946):
            raw = zlib.decompress(raw)
        elif self.compressed == 5:
            raw = lzw_unpack(raw)
        bw = self.bw
        if self.csempes:
            bh = self.bh
        else:
            bh = min(self.bh, self.h - index * self.bh)
        count_ = bw * bh
        raw = raw[:count_ * self.size]
        if len(raw) < count_ * self.size:
            raw = raw + b"\x00" * (count_ * self.size - len(raw))
        value = list(struct.unpack(self.e + self.code_ * count_, raw))
        if self.pred == 2 and self.forma != 3:
            mask = (1 << self.bit) - 1
            for row in range(bh):
                o = row * bw
                for k in range(1, bw):
                    value[o + k] = (value[o + k] + value[o + k - 1]) & mask
            if self.forma == 2:       # signed: converting back
                half = 1 << (self.bit - 1)
                value = [v - (1 << self.bit) if v >= half else v for v in value]
        return bw, bh, value

    def coordinate_per_pixel(self, x, y):
        return (x - self.x0) / self.sx, (self.y0 - y) / self.sy

    def values_(self, points):
        """points: [(x, y)] in the file's projection. Returns: a list, the point's value or None (outside / nodata)."""
        out = [None] * len(points)
        group_ = {}
        for n, (x, y) in enumerate(points):
            c, r = self.coordinate_per_pixel(x, y)
            c, r = int(c // 1), int(r // 1)
            if not (0 <= c < self.w and 0 <= r < self.h):
                continue
            if self.csempes:
                per_row = (self.w + self.bw - 1) // self.bw
                bi = (r // self.bh) * per_row + (c // self.bw)
                group_.setdefault(bi, []).append((n, c % self.bw, r % self.bh))
            else:
                group_.setdefault(r // self.bh, []).append((n, c, r % self.bh))
        for bi, list_ in group_.items():
            bw, bh, value = self.block(bi)
            for n, c, r in list_:
                v = value[r * bw + c]
                if self.nodata is not None and v == self.nodata:
                    continue
                out[n] = v
        return out
