A 3D nézet (index.html, app.js, worker.js, styles.css) az amszterdami projekt megjelenítőjén alapul:
https://github.com/alexbarakov/amsterdam-by-building  (MIT licenc, lásd LICENSE-amsterdam.txt).
A shader, a csempebetöltés, a kijelölés és az évcsúszka az övé (a worker.js kis módosítással); a budapesti
adatfolyam (../csempek_keszites.py), a korszakok, a kártya és a kétnyelvűség a mi munkánk.
A vendor/ mappa a three.js-t tartalmazza (MIT).

Domborzat: NASA Shuttle Radar Topography Mission (SRTM GL1, 1 ívmásodperc), a data/ mappából (dem.py olvassa).
A csempek_keszites.py a beépített részen a közeli legalacsonyabb pontot veszi, hogy az épületek ne dudorodjanak a talajban.
A nézet nulla szintje a Duna szintje (kb. 96 m).
