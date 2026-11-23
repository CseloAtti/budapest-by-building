"""EOV (HD72) -> WGS84 conversion without an external library (the inverse of the oblique cylindrical projection computed on the IUGG67 ellipsoid + a 7-parameter Helmert transformation)."""
import math

A67, F67 = 6378160.0, 1 / 298.25
E2_67 = F67 * (2 - F67)
LAT0 = math.radians(47 + 8 / 60 + 39.8174 / 3600)
LON0 = math.radians(19 + 2 / 60 + 54.8584 / 3600)
K0 = 0.99993
FE, FN = 650000.0, 200000.0
# HD72 -> WGS84 (EOTR; rotation in arcseconds, scale in ppm)
DX, DY, DZ = 52.684, -71.194, -13.975
RX, RY, RZ = (math.radians(v / 3600) for v in (0.312, 0.1063, 0.3729))
SC = -0.8157e-6
A84, F84 = 6378137.0, 1 / 298.257223563
E2_84 = F84 * (2 - F84)

_e = math.sqrt(E2_67)
_R = A67 * math.sqrt(1 - E2_67) / (1 - E2_67 * math.sin(LAT0) ** 2)
_al = math.sqrt(1 + E2_67 / (1 - E2_67) * math.cos(LAT0) ** 4)
_b0 = math.asin(math.sin(LAT0) / _al)
_K = (math.log(math.tan(math.pi / 4 + _b0 / 2)) - _al * math.log(math.tan(math.pi / 4 + LAT0 / 2))
      + _al * _e / 2 * math.log((1 + _e * math.sin(LAT0)) / (1 - _e * math.sin(LAT0))))


def eov_hd72(y, x):
    """EOV (Y east, X north, metres) -> HD72 geographic (degrees): (lat, lon)."""
    yy, xx = (y - FE) / (_R * K0), (x - FN) / (_R * K0)
    bq = 2 * (math.atan(math.exp(xx)) - math.pi / 4)
    b = math.asin(math.cos(_b0) * math.sin(bq) + math.sin(_b0) * math.cos(bq) * math.cos(yy))
    l = math.atan2(math.sin(yy) * math.cos(bq), math.cos(_b0) * math.cos(bq) * math.cos(yy) - math.sin(_b0) * math.sin(bq))
    lon = LON0 + l / _al
    phi = b
    for _ in range(10):
        S = (math.log(math.tan(math.pi / 4 + b / 2)) - _K) / _al + _e * math.log(math.tan(math.pi / 4 + math.asin(_e * math.sin(phi)) / 2))
        phi = 2 * math.atan(math.exp(S)) - math.pi / 2
    return math.degrees(phi), math.degrees(lon)


def hd72_wgs84(lat, lon):
    phi, lam = math.radians(lat), math.radians(lon)
    N = A67 / math.sqrt(1 - E2_67 * math.sin(phi) ** 2)
    X, Y, Z = N * math.cos(phi) * math.cos(lam), N * math.cos(phi) * math.sin(lam), N * (1 - E2_67) * math.sin(phi)
    X2 = DX + (1 + SC) * (X + RZ * Y - RY * Z)
    Y2 = DY + (1 + SC) * (-RZ * X + Y + RX * Z)
    Z2 = DZ + (1 + SC) * (RY * X - RX * Y + Z)
    p = math.hypot(X2, Y2)
    ph = math.atan2(Z2, p * (1 - E2_84))
    for _ in range(8):
        N = A84 / math.sqrt(1 - E2_84 * math.sin(ph) ** 2)
        ph = math.atan2(Z2 + E2_84 * N * math.sin(ph), p)
    return math.degrees(ph), math.degrees(math.atan2(Y2, X2))


def eov_wgs84(y, x):
    """EOV (Y, X) -> WGS84 (lat, lon fok)."""
    return hd72_wgs84(*eov_hd72(y, x))


if __name__ == "__main__":
    # check: Budapest, Gellért Hill (about EOV 648300, 237700) -> about 47.486, 19.046
    print(eov_wgs84(648300, 237700))
