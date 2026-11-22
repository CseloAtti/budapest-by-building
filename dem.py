"""
dem.py - NASA SRTM magassági csempék (N47E019.SRTMGL1_NC.nc stb.) beolvasása, csak Python alap könyvtárral.

Ezt a fájlt nem kell futtatni, a csempek_keszites.py használja.

A fájl NetCDF-4 (belül HDF5). A NASA fájljaiban a magassági adat 3601 x 3601 egész szám (méter), tömörítés
nélkül, egybefüggően tárolva, ezért elég megtalálni a helyét a fájlban. Ha egy fájl tömörített lenne vagy más
felépítésű, a beolvasás érthető hibaüzenettel áll le.

Csempe: a fájlnév adja a sarkát (N47E019 = 47-48° északi szélesség, 19-20° keleti hosszúság), a sorok
északról délre, az oszlopok nyugatról keletre haladnak.
"""
import array
import re
import struct
import sys
from pathlib import Path


class HibasFajl(Exception):
    pass


def _uzenetek(b, pos):
    """Egy HDF5 objektumfejléc (OHDR, 2. változat) üzenetei: [(típus, adat), ...]."""
    if b[pos:pos + 4] != b"OHDR" or b[pos + 4] != 2:
        raise HibasFajl("nem 2-es változatú HDF5 objektumfejléc")
    fl = b[pos + 5]
    p = pos + 6
    if fl & 0x20:
        p += 16
    if fl & 0x10:
        p += 4
    n = 1 << (fl & 3)
    meret = int.from_bytes(b[p:p + n], "little")
    p += n
    ki = []
    blokkok = [(p, p + meret)]
    while blokkok:
        s, e = blokkok.pop(0)
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
            ki.append((t, b[q:q + sz]))
            if t == 0x10 and sz >= 16:
                off, ln = struct.unpack("<QQ", b[q:q + 16])
                blokkok.append((off + 4, off + ln - 4))
            q += sz
    return ki


class Csempe:
    N = 3601

    def __init__(self, ut):
        ut = Path(ut)
        m = re.match(r"([NS])(\d+)([EW])(\d+)", ut.name.upper())
        if not m:
            raise HibasFajl(f"a fájlnévből nem olvasható ki a csempe sarka: {ut.name}")
        lat = int(m.group(2)) * (1 if m.group(1) == "N" else -1)
        lon = int(m.group(4)) * (1 if m.group(3) == "E" else -1)
        self.lat_felso = lat + 1      # a csempe északi széle
        self.lon_nyugati = lon        # a csempe nyugati széle
        b = ut.read_bytes()
        if b[:8] != b"\x89HDF\r\n\x1a\n":
            raise HibasFajl(f"{ut.name}: nem HDF5/NetCDF-4 fájl")
        helye = None
        i = b.find(b"OHDR")
        while i != -1:
            try:
                uz = _uzenetek(b, i)
                tomb = {t: d for t, d in uz}
                ds, dt, ly = tomb.get(1), tomb.get(3), tomb.get(8)
                if ds and dt and ly and ds[0] == 2 and ds[1] == 2:
                    dims = struct.unpack("<QQ", ds[4:20])
                    if dims == (self.N, self.N) and dt[0] & 0x0F == 0 and struct.unpack("<I", dt[4:8])[0] == 2:
                        if ly[0] != 3 or ly[1] != 1:
                            raise HibasFajl(f"{ut.name}: a magassági adat nem egybefüggő (tömörített vagy darabolt)")
                        helye = struct.unpack("<QQ", ly[2:18])
                        break
            except (HibasFajl, struct.error, IndexError):
                if helye is None and False:
                    raise
            i = b.find(b"OHDR", i + 4)
        if not helye:
            raise HibasFajl(f"{ut.name}: nem találom benne a {self.N}x{self.N}-es magassági adatot")
        cim, hossz = helye
        if hossz != self.N * self.N * 2:
            raise HibasFajl(f"{ut.name}: váratlan adatméret")
        self.adat = array.array("h")
        self.adat.frombytes(b[cim:cim + hossz])
        if sys.byteorder != "little":
            self.adat.byteswap()

    def kozel(self, lon, lat):
        return self.lon_nyugati <= lon <= self.lon_nyugati + 1 and self.lat_felso - 1 <= lat <= self.lat_felso

    def minta(self, sor, oszlop):
        return self.adat[sor * self.N + oszlop]


class Domborzat:
    """A mappában lévő összes SRTM-csempe egyben."""

    FOK = 3600  # minta / fok

    def __init__(self, mappa):
        self.csempek = []
        for ut in sorted(Path(mappa).glob("*SRTMGL1*.nc")):
            self.csempek.append(Csempe(ut))
        if not self.csempek:
            raise HibasFajl(f"nincs SRTM-csempe (*.SRTMGL1_NC.nc) a(z) {mappa} mappában")

    def _csempe(self, lon, lat):
        for c in self.csempek:
            if c.kozel(lon, lat):
                return c
        return None

    def racs(self, lon_ny, lon_k, lat_d, lat_e):
        """Az adott téglalap magasságai az SRTM saját rácsán (méter, lebegőpontos).
        Visszaad: (sorok, oszlopok, lat_felso, lon_nyugati, [[...], ...]) - a sorok északról délre."""
        sor0 = int(round((lat_e - lat_d) * self.FOK))
        j0 = int(round(lat_e * self.FOK))
        i0 = int(round(lon_ny * self.FOK))
        sorok = sor0 + 1
        oszlopok = int(round((lon_k - lon_ny) * self.FOK)) + 1
        ki = []
        for r in range(sorok):
            lat = (j0 - r) / self.FOK
            sor = []
            for c in range(oszlopok):
                lon = (i0 + c) / self.FOK
                cs = self._csempe(lon, lat)
                if cs is None:
                    raise HibasFajl(f"a terület ({lon:.4f}, {lat:.4f}) pontja nincs a letöltött csempék között")
                s = round((cs.lat_felso - lat) * self.FOK)
                o = round((lon - cs.lon_nyugati) * self.FOK)
                v = cs.minta(min(s, Csempe.N - 1), min(o, Csempe.N - 1))
                sor.append(float(v) if v != -32768 else float("nan"))
            ki.append(sor)
        return sorok, oszlopok, j0 / self.FOK, i0 / self.FOK, ki
