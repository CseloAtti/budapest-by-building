The 3D view (index.html, app.js, worker.js, styles.css) is based on the viewer of the Amsterdam project:
https://github.com/alexbarakov/amsterdam-by-building  (MIT licence, see LICENSE-amsterdam.txt).
The shader, the tile loading, the selection and the year slider are his (worker.js with a small modification); the Budapest
data pipeline (../build_tiles.py), the eras, the card and the bilingual interface are our own work.
The vendor/ folder contains three.js (MIT).

Terrain: NASA Shuttle Radar Topography Mission (SRTM GL1, 1 arc-second), from the data/ folder (read by dem.py).
On the built-up part build_tiles.py takes the nearby lowest point, so that the buildings do not bulge in the ground.
The view's zero level is the level of the Danube (about 96 m).
