# Építési korszak becslés: mérési jelentés

Címkézett (ismert évű) épület: **521**; szürke, becsült: **1321**; épületrészt nem becslünk.

A mérés úgy megy, hogy minden ismert épületet egyenként elrejtünk, és megnézzük, eltalálná-e a modell.

## Fő eredmények

| | db | találat | az első kettő között | legfeljebb 1 korszakot téved | log-veszteség (kisebb a jobb) |
|---|---|---|---|---|---|
| a legtöbbször előforduló korszak tippelése | 521 | 57% | 80% | 88% | 1.27 |
| a végső modell (egyenként elrejtve) | 521 | 67% | 85% | 88% | 0.95 |
| a végső modell (keresztillesztett súlyokkal) | 521 | 67% | 85% | 88% | 0.95 |
| a végső modell (300 m-es blokk kizárva) | 521 | 59% | 85% | 88% | 1.04 |

## Mit ad az egyes bizonyíték? (a végső modellből kihagyva)

| | db | találat | az első kettő között | legfeljebb 1 korszakot téved | log-veszteség (kisebb a jobb) |
|---|---|---|---|---|---|
| szomszédok nélkül | 521 | 59% | 80% | 85% | 1.18 |
| utca nélkül | 521 | 65% | 85% | 87% | 1.00 |
| alak nélkül | 521 | 64% | 84% | 87% | 1.07 |
| zóna nélkül | 521 | 66% | 85% | 88% | 0.96 |
| alapeloszlás nélkül | 521 | 67% | 85% | 88% | 0.95 |

Végső súlyok: {'0': 0.0, 'N': 0.5, 'S': 0.3, 'F': 0.6, 'Z': 1.0}


## Védett és nem védett épületek külön

Az ismert évű épületek jelentős része védett, a szürkék többsége viszont nem az, ezért a *nem védett* sor a reálisabb.

| | db | találat | az első kettő között | legfeljebb 1 korszakot téved | log-veszteség (kisebb a jobb) |
|---|---|---|---|---|---|
| védett épületek | 299 | 71% | 95% | 97% | 0.71 |
| NEM védett épületek | 222 | 61% | 73% | 74% | 1.27 |

## Korszakonként: hányat talál el?

| korszak | ismert db | találat |
|---|---|---|
| 1848 előtt | 117 | 48% |
| 1848–1918 | 299 | 88% |
| 1919–1944 | 45 | 53% |
| 1945–1956 | 7 | 0% |
| 1957–1989 | 17 | 18% |
| 1990–2010 | 25 | 8% |
| 2011-től | 11 | 0% |

A 1945 utáni korszakoknál kevés az ismert példa, ezért ott a becslés megbízhatatlanabb.

## Kalibráció: amit a modell X%-osra mond, az valójában mennyi?

| a modell biztonsága | db | tényleges találat |
|---|---|---|
| 20–30% | 14 | 21% |
| 30–40% | 39 | 38% |
| 40–50% | 84 | 49% |
| 50–60% | 98 | 56% |
| 60–70% | 86 | 70% |
| 70–80% | 97 | 77% |
| 80–90% | 51 | 90% |
| 90–100% | 52 | 100% |

Bizonyossági sávok: **magas** ≥ 0.66 (mért találat ≥ 85%), **közepes** ≥ 0.39 (≥ 70%), különben **alacsony**.

A bizonyossági sávok tényleges találata csak a NEM védett épületeken:

- magas: 93 nem védett ismert épületből 84% találat
- közepes: 96 nem védett ismert épületből 49% találat
- alacsony: 33 nem védett ismert épületből 33% találat

## Zavaró mátrix (sor: igazi, oszlop: becsült)

| | 1848 előtt | 1848–1918 | 1919–1944 | 1945–1956 | 1957–1989 | 1990–2010 | 2011-től |
|---|---|---|---|---|---|---|---|
| 1848 előtt | 56 | 57 | 3 | 0 | 0 | 1 | 0 |
| 1848–1918 | 25 | 262 | 7 | 1 | 1 | 2 | 1 |
| 1919–1944 | 2 | 18 | 24 | 0 | 0 | 1 | 0 |
| 1945–1956 | 2 | 4 | 0 | 0 | 1 | 0 | 0 |
| 1957–1989 | 2 | 7 | 2 | 1 | 3 | 0 | 2 |
| 1990–2010 | 3 | 18 | 2 | 0 | 0 | 2 | 0 |
| 2011-től | 2 | 8 | 0 | 0 | 1 | 0 | 0 |

## A szürke épületek becslése

| korszak | magas | közepes | alacsony |
|---|---|---|---|
| 1848 előtt | 13 | 103 | 40 |
| 1848–1918 | 569 | 412 | 66 |
| 1919–1944 | 12 | 33 | 26 |
| 1945–1956 | 1 | 5 | 8 |
| 1957–1989 | 2 | 2 | 7 |
| 1990–2010 | 0 | 14 | 6 |
| 2011-től | 0 | 1 | 1 |

Zóna-támpont 75 szürke épületnél érvényes (utca-egyezés alapján).

## Amit nem tud a modell

- A tanítóadat torz: sok az 1848–1918-as és a védett épület, kevés az 1945 utáni.
- A zónák csak az utcát nézik, a háborús pótlásokat és későbbi beépítéseket nem.
- A kortárs és modernista épületek listái (később) fogják javítani a 1945 utáni korszakokat.
- A becslés soha nem kerül az `ev` mezőbe, és a térképen külön, halványabb rétegként látszik.
