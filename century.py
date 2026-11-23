"""century.py - Hungarian textual time expressions ('XIX. sz. vége', '1930-as évek második fele') -> (year_from, year_to).

Suitable only as approximate era data (it goes into *_kozelito.csv and becomes the estimator's label), NOT as an exact year.
Run for a self-check:  py century.py
Rules (the output is always a closed range of years, or None if the text is not unambiguous):
  century:  XVI. század / 16. sz.            -> (c-1)*100+1 .. c*100
            eleje | közepe | vége (beginning | middle | end)  -> thirds: 1-33 / 34-66 / 67-100
            első|második fele (first|second half)             -> 1-50 / 51-100
            első|második|harmadik|negyedik negyede (quarter)  -> 25 years;  első|második|harmadik harmada (third)
            XIX-XX. század fordulója (turn of the centuries)  -> +-10 years around the boundary of the two centuries
  decade:   1930-as évek (the 1930s) (+ eleje 0-3, közepe 4-6, vége 7-9, első fele 0-4, második fele 5-9)
            (the 1900-as évek is the decade 1900-1909, not the whole century)
  exact date: '1899. 10. 01.'            -> 1899
  range:    '1920-1930-as évek' / '1920-30-as évek' -> 1920..1939;  '1910 körül', 'kb. 1910' (around 1910) -> +-5 years;  '1912-1914' -> 1912..1914
It skips: a range spanning several centuries ('XVIII-XX. sz.'), if the text also has a four-digit year, '-' and the like,
uncertain texts without 'előtt' (before), 'után' (after), 'körül' (around), '20-as évek' (which century?).
"""
import re

ROMAI = {"i": 1, "v": 5, "x": 10}


def romai(s):
    s = s.lower()
    if not s or any(c not in ROMAI for c in s):
        return None
    ossz = 0
    for i, c in enumerate(s):
        v = ROMAI[c]
        ossz += -v if i + 1 < len(s) and ROMAI[s[i + 1]] > v else v
    return ossz if 1 <= ossz <= 21 else None


def _szam(s):
    if re.fullmatch(r"\d{1,2}", s):
        return int(s)
    return romai(s)


SZAZAD = re.compile(r"(?<![\w])([ivx]+|\d{1,2})\.?\s*(?:[-–]\s*([ivx]+|\d{1,2})\.?\s*)?(?:sz\b|sz\.|szá?zad)", re.I)


def _resz(s, kezd, veg):
    """Qualifier of a (start..end) range (inclusive, of length 100 or 10): beginning/middle/end, half, quarter, third."""
    n = veg - kezd + 1
    s = s.lower()
    if re.search(r"\bfordul", s):
        return None
    for nev, db in (("negyed", 4), ("harmad", 3)):
        m = re.search(rf"\b(első|elso|második|masodik|harmadik|negyedik|utolsó|utolso)\s+{nev}", s)
        if m:
            sorsz = {"első": 0, "elso": 0, "második": 1, "masodik": 1, "harmadik": 2, "negyedik": 3}.get(m.group(1), db - 1)
            if sorsz >= db:
                return None
            a = kezd + n * sorsz // db
            b = kezd + n * (sorsz + 1) // db - 1
            return a, b
    m = re.search(r"\b(első|elso|második|masodik)\s+fele", s)
    if m:
        f = 0 if m.group(1) in ("első", "elso") else 1
        return kezd + n * f // 2, kezd + n * (f + 1) // 2 - 1
    if re.search(r"\b(eleje|elején|elejei)\b", s):
        return (kezd, kezd + 32) if n == 100 else (kezd, kezd + 3)
    if re.search(r"\b(közepe|közepén|közepi|közepe)\b", s):
        return (kezd + 33, kezd + 65) if n == 100 else (kezd + 4, kezd + 6)
    if re.search(r"\b(vége|végén|végi)\b", s):
        return (kezd + 66, veg) if n == 100 else (kezd + 7, veg)
    return (kezd, veg)


def szoveg_evtartomany(szoveg):
    t = (szoveg or "").strip()
    if not t or t in ("-", "–"):
        return None
    tl = t.lower()
    # exact date: 1899. 10. 01.
    m = re.fullmatch(r"(1[0-9]{3}|20[0-2][0-9])\.\s*\d{1,2}\.\s*\d{1,2}\.?", tl)
    if m:
        return int(m.group(1)), int(m.group(1))
    # decade range: '1920-1930-as évek', '1920-30-as évek' -> 1920..1939
    m = re.fullmatch(r"(?:kb\.?\s*|cca\.?\s*)?(1[0-9])(\d)0\s*[-–]\s*(?:(1[0-9])(\d)0|(\d)0)\s*-?\s*[ae]s\s+évek", tl)
    if m:
        a = int(m.group(1) + m.group(2) + "0")
        b = int(m.group(3) + m.group(4) + "0") if m.group(3) else int(m.group(1) + m.group(5) + "0")
        if a <= b <= a + 50:
            return a, b + 9
    # '1910 körül', 'kb. 1910', '1910 k.' -> +-5 years;  '1912-1914' -> the range between the two years
    m = re.fullmatch(r"(?:kb\.?|cca\.?|~)?\s*(1[0-9]{3}|20[0-2][0-9])\s*(?:körül|k\.|táján)?", tl)
    if m and re.search(r"körül|k\.|táján|kb|cca|~", tl):
        y = int(m.group(1))
        return y - 5, y + 5
    m = re.fullmatch(r"(1[0-9]{3}|20[0-2][0-9])\s*[-–]\s*(1[0-9]{3}|20[0-2][0-9])", tl)
    if m and 0 <= int(m.group(2)) - int(m.group(1)) <= 30:
        return int(m.group(1)), int(m.group(2))
    if re.search(r"\b(előtt|után|elott|utan|óta|tól|től|vitatott|feltehet|valószín|kr\.\s*u|kr\.\s*e)", tl):
        return None
    if re.search(r"[:/]|\b(vagy|és|majd|illetve)\b", tl) or len(SZAZAD.findall(t)) > 1 or len(re.findall(r"\b\d{3}0-[ae]s", tl)) > 1:
        return None                           # several points in time in one text: not unambiguous
    van_ev = re.search(r"\b1[0-9]{3}\b|\b20[0-2][0-9]\b", tl)
    # decade: 1930-as évek ...
    m = re.search(r"\b(1[0-9]{2})0-[ae]s\s+évek", tl)
    if m and not re.search(r"\b1[0-9]{3}\b(?!-as)", re.sub(r"\b1[0-9]{2}0-[ae]s", "", tl)):
        d = int(m.group(1)) * 10
        r = _resz(tl[m.end():], d, d + 9)
        return r
    if van_ev:
        return None
    # century
    m = SZAZAD.search(t)
    if m:
        a = _szam(m.group(1))
        b = _szam(m.group(2)) if m.group(2) else a
        if a is None or b is None or b < a:
            return None
        utana = tl[m.end():]
        if a != b:
            if re.search(r"\bfordul", utana) and b == a + 1:
                return a * 100 - 9, a * 100 + 10
            return None                       # several centuries: not unambiguous
        c = a
        elotte = tl[:m.start()]
        return _resz(elotte + " " + utana, (c - 1) * 100 + 1, c * 100)
    return None


if __name__ == "__main__":
    pelda = [
        ("XVI. század", (1501, 1600)), ("XIX. sz. vége", (1867, 1900)), ("XX. sz első harmada", (1901, 1933)),
        ("a XX. század eleje", (1901, 1933)), ("XIX. Század közepe", (1834, 1866)), ("XIX. század eleje", (1801, 1833)),
        ("XIX. század első fele", (1801, 1850)), ("19. század vége", (1867, 1900)), ("18-19. század", None),
        ("XVIII-XX. sz.", None), ("XIX-XX. század fordulója", (1891, 1910)), ("13. század", (1201, 1300)),
        ("1930-as évek második fele", (1935, 1939)), ("1900-as évek eleje", (1900, 1903)), ("1890-es évek közepe", (1894, 1896)),
        ("1940-es évek eleje", (1940, 1943)), ("1899. 10. 01.", (1899, 1899)), ("1872 előtt", None), ("-", None),
        ("2. század", (101, 200)), ("Kr.u. 145 körül", None), ("20-as évek körül", None), ("1960-as évek eleje", (1960, 1963)),
        ("1920-1930-as évek", (1920, 1939)), ("1920–30-as évek", (1920, 1939)), ("1910 körül", (1905, 1915)), ("kb. 1925", (1920, 1930)),
        ("1912-1914", (1912, 1914)), ("1930-as évek", (1930, 1939)),
    ]
    for sz, vart in pelda:
        r = szoveg_evtartomany(sz)
        print(("OK  " if r == vart else "??  ") + f"{sz!r:40} -> {r}   (várt {vart})")
