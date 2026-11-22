# Átvizsgálási terv: Budapest épületei

Cél: hibák kiszűrése, a becslés ellenőrzése, a kód kitisztítása. Minden szakasz külön munkamenetben, külön commitban fusson.

## Előfeltételek (egyszer)
1. `py tesztek/futtat_mindent.py` – az alapállapot legyen zöld (vagy a figyelmeztetések ismertek).
2. A jelenlegi állapot címkézése: `git tag allapot-2026-11-pre-review`.
3. Az `ev_becsles.py varos` jelentése (`data/varos/ev_becsles_jelentes.md`) legyen friss: ez a becslés viszonyítási alapja.

## Szakaszok

| # | Terület | Fájlok (kb. méret) | Mit keresünk | Hogyan ellenőrizzük |
|---|---|---|---|---|
| 1 | Kliens: 3D nézet és UI | `terkep3d/app.js` (~208 KB), `index.html`, `styles.css` | inicializálási sorrend (TDZ), halott kód, duplikált függvények, ismétlődő szövegek, `console.log`, nyelvi (HU/EN) hiányok, memóriaszivárgás a rétegváltásnál | `teszt_kliens.py`; kézi próba: minden fül, mindkét nyelv, mobil szélesség |
| 2 | Adatlapok és építészek | `forras/adatlapok.json`, `adatlapok_keszites.py`, `terkep3d/epitesz*.json`, `forras/epulet_csoportok.csv` | hiányzó mezők, törött azonosítók, hibás Wikipédia-címek, kép-licenc hiányok | `teszt_adatlapok.py`; `py adatlapok_keszites.py` figyelmeztetései |
| 3 | Feldolgozó lánc | `osszeepit.py` (63 KB), `csempek_keszites.py`, `varos_osszeallitas.py`, `kozos.py`, `terulet_kozos.py` | hibás összefésülési sorrend, felülíródó mezők, csendes kivételek (`except: pass`), relation-többszörösség | `teszt_adatok.py`; ugyanazon bemenetből futtatott két újraépítés eredménye egyezzen |
| 4 | Forrásbetöltők (`tenyek_*.py`) | ~30 szkript | párosítási hibák (rossz épület kapja az évet/tervezőt), elavult szkriptek, kézi párosítási CSV-k ütközése | véletlen minta: 30 épület forrásának kézi ellenőrzése forrásonként |
| 5 | Évbecslés | `ev_becsles.py` (69 KB), `ev_becsles_ksh.py`, `szazad.py` | torzítás (az ismert minta 26%-a védett), a két szélső korszak (1867 előtt 0%, 2011-től 3% találat), a kalibráció, a KSH-illesztés | `teszt_becsles.py`; a jelentés kalibrációs táblája; védett / nem védett külön mérése |
| 6 | Szerkesztő szerver | `szerkeszto_szerver.py` (63 KB) | nyilvános példányon kikapcsolva; útvonal-bejárás, jogosultság, fájlírás | kód átnézés; a nyilvános build ne tartalmazza |
| 7 | Takarítás | gyökérkönyvtár | `.bak`, `hello.py`, `elemzes.py`, `diagnosztika.py`, `letolt.py`, `mentes_7korszak/`, `__pycache__`, régi `data_varos_*` mappák | `git status`, használaton kívüli szkriptek listája (nem hivatkozza más) |

## Szabályok az átnézéshez
- Egy szakasz = egy munkamenet = egy commit (vagy kevés, jól elnevezett commit).
- Minden talált hibára: reprodukáló eset, javítás, és ha lehet, egy új teszt a `tesztek/` mappában.
- A javítás után `py tesztek/futtat_mindent.py` legyen zöld; az 1., 2., 3. szakasz után újraépítés (`Újraépítés (egész város)`) és az eredmény összevetése az előzővel (épületek száma, ismert évűek aránya).
- A talált hibákat külön, független menetben ellenőrizze valaki (vagy másik modell), mielőtt javítod: egy átnézés téves riasztást is adhat.
- A becslést (5. szakasz) számok alapján ítéld meg, ne a modell véleménye alapján.

## Ismert nyitott pontok (már most látszanak)
- A korszakbecslés a legrégibb (1867 előtt: 0%) és a legújabb (2011-től: 3%) korszakot alig találja el; a Névjegy módszer-részében ez érdemes külön említést.
- Az ismert évű épületek száma 8 468–8 491 között ingadozik a források szerint (épületrészek, relationök többszörös poligonja): a Névjegyben szereplő szám („8470") egy számolás eredménye, egységesíteni kell.
- 30 relation több poligonrészként szerepel az `epuletek.json`-ban: az épületkártya és a keresés kezelése átnézendő.
- `kezi_javitasok.csv` 460 KB, 4 700+ sor: ütköző vagy elavult sorok kereshetők benne (azonos azonosító és mező, eltérő érték).
- MOME (way 725388585): a bejegyzés 1953/szocreál, ellenőrizendő; Kossuth tér 6 vs. 7; MATÁV 1954.
