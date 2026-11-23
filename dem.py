"""
dem.py - reading NASA SRTM elevation tiles (N47E019.SRTMGL1_NC.nc etc.), with only the Python standard library.

This file does not need to be run, build_tiles.py uses it.

The file is NetCDF-4 (HDF5 inside). In NASA's files the elevation data is 3601 x 3601 integers (metres), stored uncompressed
and contiguously, so it is enough to find its place in the file. If a file were compressed or structured
differently, the reader stops with a clear error message.

Tile: the file name gives its corner (N47E019 = 47-48 degrees north latitude, 19-20 degrees east longitude), the rows
run from north to south, the columns from west to east.
"""
import array
import re
import struct
import sys
from pathlib import Path


class FaultyFile(Exception):
    pass


def _messages(b, pos):
    """The messages of an HDF5 object header (OHDR, version 2): [(type, data), ...]."""
    if b[pos:pos + 4] != b"OHDR" or b[pos + 4] != 2:
        raise FaultyFile("nem 2-es változatú HDF5 objektumfejléc")
    fl = b[pos + 5]
    p = pos + 6
    if fl & 0x20:
        p += 16
    if fl & 0x10:
        p += 4
    n = 1 << (fl & 3)
    size = int.from_bytes(b[p:p + n], "little")
    p += n
    out = []
    blocks = [(p, p + size)]
    while blocks:
        s, e = blocks.pop(0)
        q = s
        while q + 4 <= e:
            t = b[q]
            sz = struct.unpack("<H", b[q + 1:q + 3])[0]
            q += 4
            if fl & 4:
                q += 2
            if t == 0 and sz == 0:
                break
            if q + sz > e + 4:
                break
            out.append((t, b[q:q + sz]))
            if t == 0x10 and sz >= 16:
                off, ln = struct.unpack("<QQ", b[q:q + 16])
                blocks.append((off + 4, off + ln - 4))
            q += sz
    return out


class Tile:
    N = 3601

    def __init__(self, path_):
        path_ = Path(path_)
        m = re.match(r"([NS])(\d+)([EW])(\d+)", path_.name.upper())
        if not m:
            raise FaultyFile(f"a fájlnévből nem olvasható ki a csempe sarka: {path_.name}")
        lat = int(m.group(2)) * (1 if m.group(1) == "N" else -1)
        lon = int(m.group(4)) * (1 if m.group(3) == "E" else -1)
        self.lat_felso = lat + 1      # the tile's northern edge
        self.lon_nyugati = lon        # the tile's western edge
        b = path_.read_bytes()
        if b[:8] != b"\x89HDF\r\n\x1a\n":
            raise FaultyFile(f"{path_.name}: nem HDF5/NetCDF-4 fájl")
        place = None
        i = b.find(b"OHDR")
        while i != -1:
            try:
                uz = _messages(b, i)
                array_ = {t: d for t, d in uz}
                ds, dt, ly = array_.get(1), array_.get(3), array_.get(8)
                if ds and dt and ly and ds[0] == 2 and ds[1] == 2:
                    dims = struct.unpack("<QQ", ds[4:20])
                    if dims == (self.N, self.N) and dt[0] & 0x0F == 0 and struct.unpack("<I", dt[4:8])[0] == 2:
                        if ly[0] != 3 or ly[1] != 1:
                            raise FaultyFile(f"{path_.name}: a magassági adat nem egybefüggő (tömörített vagy darabolt)")
                        place = struct.unpack("<QQ", ly[2:18])
                        break
            except (FaultyFile, struct.error, IndexError):
                if place is None and False:
                    raise
            i = b.find(b"OHDR", i + 4)
        if not place:
            raise FaultyFile(f"{path_.name}: nem találom benne a {self.N}x{self.N}-es magassági adatot")
        address, length = place
        if length != self.N * self.N * 2:
            raise FaultyFile(f"{path_.name}: váratlan adatméret")
        self.data_ = array.array("h")
        self.data_.frombytes(b[address:address + length])
        if sys.byteorder != "little":
            self.data_.byteswap()

    def near(self, lon, lat):
        return self.lon_nyugati <= lon <= self.lon_nyugati + 1 and self.lat_felso - 1 <= lat <= self.lat_felso

    def sample(self, row, column):
        return self.data_[row * self.N + column]


class Terrain:
    """All the SRTM tiles in the folder as one."""

    DEGREE = 3600  # minta / fok

    def __init__(self, folder):
        self.tiles = []
        for path_ in sorted(Path(folder).glob("*SRTMGL1*.nc")):
            self.tiles.append(Tile(path_))
        if not self.tiles:
            raise FaultyFile(f"nincs SRTM-csempe (*.SRTMGL1_NC.nc) a(z) {folder} mappában")

    def _tile(self, lon, lat):
        for c in self.tiles:
            if c.near(lon, lat):
                return c
        return None

    def grid(self, lon_ny, lon_k, lat_d, lat_e):
        """The heights of the given rectangle on SRTM's own grid (metres, floating point).
        Returns: (rows, columns, lat_top, lon_west, [[...], ...]) - the rows from north to south."""
        row0 = int(round((lat_e - lat_d) * self.DEGREE))
        j0 = int(round(lat_e * self.DEGREE))
        i0 = int(round(lon_ny * self.DEGREE))
        rows = row0 + 1
        columns = int(round((lon_k - lon_ny) * self.DEGREE)) + 1
        out = []
        for r in range(rows):
            lat = (j0 - r) / self.DEGREE
            row = []
            for c in range(columns):
                lon = (i0 + c) / self.DEGREE
                cs = self._tile(lon, lat)
                if cs is None:
                    raise FaultyFile(f"a terület ({lon:.4f}, {lat:.4f}) pontja nincs a letöltött csempék között")
                s = round((cs.lat_felso - lat) * self.DEGREE)
                o = round((lon - cs.lon_nyugati) * self.DEGREE)
                v = cs.sample(min(s, Tile.N - 1), min(o, Tile.N - 1))
                row.append(float(v) if v != -32768 else float("nan"))
            out.append(row)
        return rows, columns, j0 / self.DEGREE, i0 / self.DEGREE, out
