// Budapest, building by building: the 3D view.
//
// The core of the viewer (shader, tile loading, selection, year slider, the idea of the time histogram) comes from
// the Amsterdam project: alexbarakov/amsterdam-by-building, MIT licence (see LICENSE-amsterdam.txt).
// The data flow, the eras, the card content, bilingual support and the estimated era are the Budapest part.
import * as THREE from './vendor/three.module.js';
import { MapControls } from './vendor/MapControls.js';
import { hidakEpit, hidRekord, korlapEpit } from './bridges.js';

THREE.ColorManagement.enabled = false;   // draw the colours as given

const SKY = '#e4e8ea';
const LAND = '#f4f3ef';
const WATER = '#b5c7c6';
const PARK = '#e1e8d6';
const MAQUETTE = '#efeee9';
const ATTR_W = 256;
const WORKERS = Math.min(4, navigator.hardwareConcurrency || 2);
const MODE = { period: 0, floors: 1 };

// the whole city (build_tiles.py varos -> data_varos/); the old inner-city version (data/) has been retired
const DATA = 'data_varos';
const [config, epuletek] = await Promise.all([
  fetch(`${DATA}/budapest.json`).then(r => r.json()),
  fetch(`${DATA}/epuletek.json`).then(r => r.json()),
]);
const periods = config.periods;
let epNevek = null, epAktiv = null, epKesz = false, epBetoltes = null, epKizart = new Set(), epDijak = { ybl: {}, prima: {}, nivo: {} };   // Architects tab
let archSzuro = null, archKiv = null, archAdat = null, archGidek = null;   // architect search: set of highlighted building gids and the selected architect

// ---------- Language (Hungarian / English) ----------
const SZOVEG = {
  hu: {
    cim: 'Budapest, épületenként', varos: 'Budapest', forras_sor: 'Domborzat: NASA SRTM · Adatok: OpenStreetMap', oldal_cim: 'Budapest épületeinek kora, interaktív 3D térkép', alcim: 'Minden ma álló épület kor és alapinformációk szerint rendezve.', about_gomb: 'Névjegy', vedett_leiras: 'Nagyjából minden {n}. épület védett az Országos Építésügyi Nyilvántartás és a kerületi szabályozások szerint.', vedett_muemlek: 'Műemlék', vedett_helyi: 'Helyi védett', vedett_ossz: 'Összesen', about_cim: 'Budapest épületei projekt', about_szoveg: 'A szöveg hamarosan.', about_alap: 'A felület alapja az Amszterdam, épületenként projekt (Alex Barakov, MIT licenc). Adatok: OpenStreetMap, E-Örökség, Wikipédia, Wikimedia Commons; domborzat: NASA SRTM.', nez_period: 'Korok', nez_layers: 'Rétegek', nez_vedett: 'Védett', nez_magassag: 'Magasság', nez_lakotelep: 'Lakótelepek', nez_arch: 'Stílusok', nez_epitesz: 'Építészek', reteg_lakotelep: 'Lakótelepek', lakotelep_leiras: '{e} lakótelep, összesen {n} épület.', ep_ker: 'Keresés az építészek között', dij_ybl: 'Ybl Miklós-díj', dij_prima: 'Prima Primissima díj', dij_nivo: 'Budapest Építészeti Nívódíja', dij_cimke: 'Díjak', ep_sorrend: 'Sorrend', ep_s_abc: 'ABC', ep_s_tobb: 'Legtöbb épület elöl', ep_s_kevesebb: 'Legkevesebb épület elöl', ep_korszak: 'Korszak', ep_minden_kor: 'Minden korszak', ep_nincs_kor: 'Nincs korszakba sorolva', ep_min1: 'Legalább', ep_min2: 'épület', ep_szam: 'építész', ep_becsult: '(becsült: a házak építési éve alapján)', arch_galeria: 'Képgaléria', arch_epulet: 'épület a térképen', arch_wiki_hiba: 'A Wikipédia-adatlap most nem érhető el.', arch_ures: 'Nincs adat.', legend_cim: 'Építés ideje', reteg_magassag: 'Magasság (szintek száma)', mod_korszak: 'Korszak', mod_szint: 'Szintek', szint_kicsi: '1 szint', szint_nagy: '40 szint',
    kiemel: 'Kiemelés', vedett: 'Védett épületek', wiki: 'Wikipédia-cikkel rendelkezők', lechner: 'Lechner-épületek',
    kereso_ph: 'Keresés: név, cím, OSM-id', utak_gomb: 'Utak', utak_cim: 'Utak és utcanevek ki/be', utak_nincs: 'nincs utak.json', kereso_nincs: 'Nincs találat', ved_ph: 'Keresés: név, cím, törzsszám', lak_ph: 'Keresés a lakótelepek között', lak_db: '{n} lakótelep', lak_ker: 'ker.', mag_cim: 'Honnan származnak a magassági adatok?', mag_1: 'A legtöbb épület (kb. 95%) magasságát az EUBUCCO nyílt épületadatbázis becslése adja; ez gépi tanulással készült, kb. ±4 m pontosságú.', mag_2: 'Ahol az OpenStreetMapban szerepel a magasság (height) vagy a szintszám (building:levels, szintenként 3 m), azt használjuk (kb. 3 300 épület).', mag_3: 'Néhány épületnél a kerületi szintszám-térkép, a műemléki adat vagy kézi javítás ad pontosabb értéket.', mag_4: 'Ahol semmilyen adat nincs, 15 m az alapértelmezett magasság (kb. 10 000 épület).', mag_5: 'A szín a szintek számát mutatja; ha nincs szintszám, a magasságot 3,2 m-rel osztjuk. A Duna szintje a nulla szint (kb. 96 m).', ved_mind: 'Minden kerület', ved_db: '{n} védett épület', ved_tobb: 'Az első {k} találat látszik; szűkítsd a keresést.',
    epulet: 'épület', ma: 'Ma', betoltes: 'A város építése',
    howto: 'Húzd a forgatáshoz. Jobb gomb vagy Shift + húzás: mozgatás. Görgő: nagyítás.',
    nevtelen: 'névtelen épület', tipus: 'Típus', resz: 'épületrész', zona_telep: 'telep', zona_haz: 'ház', zona_tervezo: 'Telep tervezője', tervezo: 'Tervező', stilus: 'Stílus',
    vedettseg: 'Védettség', torzsszam: 'törzsszám', szintszam: 'Szintszám', magassag: 'Magasság',
    tobb_cim: 'és még {n} cím', gmaps: 'Google Térkép',
    rom_cimke: 'Rom, régészeti maradvány', becsult: 'Becsült korszak (nem adat)', valoszinuseg: 'valószínűség', bizonyossag: 'bizonyosság',
    magas: 'magas', kozepes: 'közepes', alacsony: 'alacsony',
    becsles_alap: 'szomszédokból, utcából és alakból becsülve',
    szomszedtol: 'a környező épületek korszaka alapján becsült',
    kep_forras: 'Kép', kep_reszlet: 'részletfotó vagy belső tér', kep_cim: 'a fájlnév a címet tartalmazza', kep_nev: 'a fájlnév az épület nevét tartalmazza', kep_hely: 'a fotó helyadata erre az épületre mutat', kep_wd: 'a Wikidata-elem képe', kep_kat: 'az épület Commons-kategóriájából', utcakep: 'Utcakép (Google Street View)', wiki_forras: 'Forrás: Wikipédia', wiki_licenc: 'CC BY-SA 4.0', wiki_tobb: 'Teljes cikk', wiki_betolt: 'Wikipédia-kivonat betöltése…', wiki_zona: 'a(z) {zona} zóna cikke', wiki_hiba: 'A Wikipédia-kivonat most nem érhető el.', wiki_nyelv: 'magyar nyelvű cikk',
    keltezes: 'Honnan az évszám', forrasok: 'További információ', reszletek: 'Kattints a részletekért',
    lechner_blokk: 'Lechner Tudásközpont', megnevezes: 'Megnevezés', epult: 'Épült',
    kozeli_megj: 'A pont nem esik az épületbe, csak a közelébe, a párosítás bizonytalan.',
    ev_nincs: 'Nincs ismert építési év.',
    ev_becsult_leiras: 'A korszak becslés: a szomszédok, az utca és az épület alakja alapján, nem adat. A csúszkán az épület a becsült korszakán belül, a környező ismert évekből választott évnél jelenik meg.',
    ev_kozeli: 'Közeli találat alapján párosítva, ellenőrizendő.',
  },
  en: {
    cim: 'Budapest, building by building', varos: 'Budapest', forras_sor: 'Terrain: NASA SRTM · Data: OpenStreetMap', oldal_cim: 'Age of Budapest\'s buildings - interactive 3D map', alcim: 'Every building standing today, sorted by age and basic information.', about_gomb: 'About', vedett_leiras: 'About one building in {n} is protected under the National Building Register (OÉNY) and district regulations.', vedett_muemlek: 'Listed monument', vedett_helyi: 'Locally protected', vedett_ossz: 'Total', about_cim: 'Budapest building by building', about_szoveg: 'Text coming soon.', about_alap: 'The interface is based on Amsterdam, building by building (Alex Barakov, MIT licence). Data: OpenStreetMap, E-Örökség, Wikipedia, Wikimedia Commons; terrain: NASA SRTM.', nez_period: 'Eras', nez_layers: 'Layers', nez_vedett: 'Protected', nez_magassag: 'Height', nez_lakotelep: 'Estates', nez_arch: 'Styles', nez_epitesz: 'Architects', reteg_lakotelep: 'Housing estates', lakotelep_leiras: '{e} housing estates, {n} buildings in total.', ep_ker: 'Search architects', dij_ybl: 'Ybl Miklós Prize', dij_prima: 'Prima Primissima Award', dij_nivo: 'Budapest Architecture Prize', dij_cimke: 'Awards', ep_sorrend: 'Order', ep_s_abc: 'A–Z', ep_s_tobb: 'Most buildings first', ep_s_kevesebb: 'Fewest buildings first', ep_korszak: 'Era', ep_minden_kor: 'All eras', ep_nincs_kor: 'Not assigned to an era', ep_min1: 'At least', ep_min2: 'buildings', ep_szam: 'architects', ep_becsult: '(estimated from the buildings\' construction years)', arch_galeria: 'Gallery', arch_epulet: 'buildings on the map', arch_wiki_hiba: 'The Wikipedia profile is unavailable right now.', arch_ures: 'No data.', legend_cim: 'Built in', reteg_magassag: 'Height (number of storeys)', mod_korszak: 'Era', mod_szint: 'Storeys', szint_kicsi: '1 storey', szint_nagy: '40 storeys',
    kiemel: 'Highlight', vedett: 'Protected buildings', wiki: 'With a Wikipedia article', lechner: 'Lechner buildings',
    kereso_ph: 'Search: name, address, OSM id', utak_gomb: 'Streets', utak_cim: 'Show/hide streets and street names', utak_nincs: 'utak.json missing', kereso_nincs: 'No results', ved_ph: 'Search: name, address, register no.', lak_ph: 'Search among the estates', lak_db: '{n} housing estates', lak_ker: 'district', mag_cim: 'Where do the height data come from?', mag_1: 'The height of most buildings (about 95%) is an estimate from the open EUBUCCO building database, produced by machine learning with roughly ±4 m accuracy.', mag_2: 'Where OpenStreetMap has a height or a number of levels (building:levels, 3 m per level), that is used (about 3,300 buildings).', mag_3: 'For some buildings a district floor-count map, heritage records or manual corrections give a more accurate value.', mag_4: 'Where no data exists, the default height is 15 m (about 10,000 buildings).', mag_5: 'The colour shows the number of storeys; without a storey count, the height is divided by 3.2 m. The Danube level is the zero level (about 96 m).', ved_mind: 'All districts', ved_db: '{n} protected buildings', ved_tobb: 'Showing the first {k} results; narrow your search.',
    epulet: 'buildings', ma: 'Today', betoltes: 'Building the city',
    howto: 'Drag to turn. Right-drag or Shift-drag to move. Scroll to zoom.',
    nevtelen: 'unnamed building', tipus: 'Type', resz: 'building part', zona_telep: 'estate', zona_haz: 'buildings', zona_tervezo: 'Estate architect', tervezo: 'Architect', stilus: 'Style',
    vedettseg: 'Protection', torzsszam: 'register no.', szintszam: 'Storeys', magassag: 'Height',
    tobb_cim: 'and {n} more', gmaps: 'Google Maps',
    rom_cimke: 'Ruins, archaeological remains', becsult: 'Estimated era (not data)', valoszinuseg: 'probability', bizonyossag: 'confidence',
    magas: 'high', kozepes: 'medium', alacsony: 'low',
    becsles_alap: 'estimated from neighbours, street and shape',
    szomszedtol: 'estimated from the surrounding buildings',
    kep_forras: 'Photo', kep_reszlet: 'detail or interior photo', kep_cim: 'file name contains the address', kep_nev: 'file name contains the building name', kep_hely: 'the photo\'s location points to this building', kep_wd: 'image of the Wikidata item', kep_kat: 'from the building\'s Commons category', utcakep: 'Street view (Google)', wiki_forras: 'Source: Wikipedia', wiki_licenc: 'CC BY-SA 4.0', wiki_tobb: 'Full article', wiki_betolt: 'Loading Wikipedia extract…', wiki_zona: 'article of the {zona} area', wiki_hiba: 'The Wikipedia extract is unavailable right now.', wiki_nyelv: 'article in Hungarian',
    keltezes: 'Where the year comes from', forrasok: 'Read more', reszletek: 'Click for details',
    lechner_blokk: 'Lechner Knowledge Centre', megnevezes: 'Name', epult: 'Built',
    kozeli_megj: 'The point is not inside the building, only near it; the match is uncertain.',
    ev_nincs: 'No known construction year.',
    ev_becsult_leiras: 'The era is an estimate from neighbours, street and building shape, not data. On the slider the building appears at a year drawn from the known years around it, within its estimated era.',
    ev_kozeli: 'Matched by proximity; to be checked.',
  },
};
let NYELV = 'hu';
try { if (localStorage.getItem('nyelv') === 'en') NYELV = 'en'; } catch (e) { /* no storage available */ }
// language from a deep link: ?lang=en|hu overrides the stored setting; the /en/ page (html lang="en") defaults to English
{
  const nyL = new URLSearchParams(location.search).get('lang');
  if (nyL === 'en' || nyL === 'hu') NYELV = nyL;
  else if (document.documentElement.lang === 'en') NYELV = 'en';
}
const t = k => SZOVEG[NYELV][k] ?? SZOVEG.hu[k] ?? k;
const korNev = i => (NYELV === 'en' ? periods[i].label_en : periods[i].label);

const FORRAS_NEVEK = {
  hu: {
    kezi: 'kézi javítás', osm: 'OpenStreetMap', lechner: 'Lechner Tudásközpont',
    lechner_kozeli: 'Lechner Tudásközpont, közeli találat (ellenőrizendő)', muemlek: 'műemlékjegyzék',
    oeny: 'E-Örökség, hivatalos nyilvántartás (leírásból kiolvasva)', helyi_vedelem: 'fővárosi helyi védelmi lista (2001)',
    hid_adat: 'kézi híd-adat (forras/hidak_adatok.csv, ellenőrizendő)',
    wikidata: 'Wikidata', wikidata_kozeli: 'Wikidata, közeli találat (ellenőrizendő)', eubucco: 'EUBUCCO', wikipedia_szoveg: 'Wikipédia-cikk szövege (géppel kiolvasva, ellenőrizendő)',
    szintterkep: 'kerületi szintszám-térkép',
    budapestlegenda: 'Budapest Legenda', epforum: 'Építészfórum', budapest100: 'Budapest100',
    ertekleltar: 'értékleltár', osm_cimke: 'OpenStreetMap-címke',
  },
  en: {
    kezi: 'hand correction', osm: 'OpenStreetMap', lechner: 'Lechner Knowledge Centre',
    lechner_kozeli: 'Lechner Knowledge Centre, nearby match (to be checked)', muemlek: 'list of monuments',
    oeny: 'E-Örökség, official register (read from the description)', helyi_vedelem: 'Budapest local protection list (2001)',
    hid_adat: 'hand-entered bridge data (forras/hidak_adatok.csv, to be checked)',
    wikidata: 'Wikidata', wikidata_kozeli: 'Wikidata, nearby match (to be checked)', eubucco: 'EUBUCCO', wikipedia_szoveg: 'Wikipedia article text (machine-read, to be checked)',
    szintterkep: 'district storey map',
    budapestlegenda: 'Budapest Legenda', epforum: 'Építészfórum', budapest100: 'Budapest100',
    ertekleltar: 'heritage inventory', osm_cimke: 'OpenStreetMap tag',
  },
};
const forrasNev = k => FORRAS_NEVEK[NYELV][k];
const VEDETTSEG = {
  hu: { M: 'műemlék', MJ: 'műemlék jellegű', VK: 'városképi jelentőségű', MK: 'műemléki környezet', MJT: 'műemléki jelentőségű terület', HV: 'helyi védelem' },
  en: { M: 'listed monument', MJ: 'monument-like', VK: 'townscape significance', MK: 'monument surroundings', MJT: 'area of monument significance', HV: 'local protection' },
};

// ---------- Scene ----------
const canvas = document.getElementById('scene');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.outputColorSpace = THREE.LinearSRGBColorSpace;
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setClearColor(SKY);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(35, 1, 5, 60000);
const controls = new MapControls(camera, canvas);
controls.enableDamping = true;
controls.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN };
controls.rotateSpeed = 0.6;
controls.maxPolarAngle = Math.PI * 0.47;
controls.minDistance = 60;
controls.maxDistance = 30000;

// Default camera position for the whole city (after F5 and with the "home view" button): from the south, looking north, the Danube vertical, the Buda Hills on the left, Pest on the right (a value estimated from the user's reference image).
// Fine-tuning: ?nezet=x,z,azimuth,elevation,span in the URL; in the browser console __dbg.nezet() prints the current view values.
const VAROS_KEZDONEZET = { x: 250, z: 700, azimuth: -8, elevation: 33, span: 9500 };
function kezdoNezet() {
  const h = Object.assign({}, config.home, VAROS_KEZDONEZET);
  const q = new URLSearchParams(location.search).get('nezet');
  if (q) {
    const [x, z, azimuth, elevation, span] = q.split(',').map(Number);
    if ([x, z, azimuth, elevation, span].every(Number.isFinite)) Object.assign(h, { x, z, azimuth, elevation, span });
  }
  return h;
}
function nezetErtekek() {
  const t = controls.target, d = camera.position.clone().sub(t), r = d.length();
  return [Math.round(t.x), Math.round(t.z), Math.round(THREE.MathUtils.radToDeg(Math.atan2(d.x, d.z))),
          Math.round(THREE.MathUtils.radToDeg(Math.asin(d.y / r))), Math.round(r / 0.9)].join(',');
}
function goHome() {
  const h = kezdoNezet(), az = THREE.MathUtils.degToRad(h.azimuth), el = THREE.MathUtils.degToRad(h.elevation);
  const d = h.span * 0.9;
  controls.target.set(h.x, 0, h.z);
  camera.position.set(h.x + d * Math.cos(el) * Math.sin(az), d * Math.sin(el), h.z + d * Math.cos(el) * Math.cos(az));
  controls.update();
}
goHome();
// The same home view, but with a smooth fly-over (when the architect view is closed).
function kezdoRepules() {
  const h = kezdoNezet(), az0 = THREE.MathUtils.degToRad(h.azimuth), el0 = THREE.MathUtils.degToRad(h.elevation), d = h.span * 0.9;
  const t1 = new THREE.Vector3(h.x, 0, h.z);
  const c1 = new THREE.Vector3(h.x + d * Math.cos(el0) * Math.sin(az0), d * Math.sin(el0), h.z + d * Math.cos(el0) * Math.cos(az0));
  const t0 = controls.target.clone(), c0 = camera.position.clone(), kezd = performance.now(), az = ++repulAz;
  const lep = now => {
    if (az !== repulAz) return;
    const u = Math.min(1, (now - kezd) / 1200), e = u * u * (3 - 2 * u);
    controls.target.lerpVectors(t0, t1, e);
    camera.position.lerpVectors(c0, c1, e);
    if (u < 1) requestAnimationFrame(lep);
  };
  requestAnimationFrame(lep);
}

// Ground: terrain mesh (SRTM) with the water and park image (build_tiles.py). Flat ground if missing.
const LAND_C = new THREE.Color(LAND), WATER_C = new THREE.Color(WATER), PARK_C = new THREE.Color(PARK);
const terrainUniforms = {
  uLand: { value: LAND_C }, uWater: { value: WATER_C }, uPark: { value: PARK_C },
  uCover: { value: null }, uHasCover: { value: 0 }, uBox: { value: new THREE.Vector4(0, 0, 1, 1) },
  uFogColor: uniformsFog().uFogColor, uFog: uniformsFog().uFog,
};
const flat = new THREE.Group();
scene.add(flat);
function uniformsFog() {
  if (!uniformsFog.o) uniformsFog.o = { uFogColor: { value: new THREE.Color(SKY) }, uFog: { value: new THREE.Vector2(9000, 26000) } };
  return uniformsFog.o;
}
const TERRAIN_VERT = /* glsl */`
  out vec3 vWorld;
  out vec3 vN;
  out vec2 vUv;
  uniform vec4 uBox;
  void main() {
    vWorld = position;
    vN = normal;
    vUv = (position.xz - uBox.xy) / uBox.zw;
    gl_Position = projectionMatrix * viewMatrix * vec4(position, 1.0);
  }
`;
const TERRAIN_FRAG = /* glsl */`
  precision highp float;
  uniform vec3 uLand, uWater, uPark, uFogColor;
  uniform vec2 uFog;
  uniform sampler2D uCover;
  uniform float uHasCover;
  in vec3 vWorld;
  in vec3 vN;
  in vec2 vUv;
  out vec4 outColor;
  void main() {
    vec3 c = uLand;
    if (uHasCover > 0.5) {
      vec2 k = texture(uCover, vUv).rg;
      c = mix(c, uPark, k.r);
      c = mix(c, uWater, k.g);
    }
    vec3 n = normalize(vN);
    float sun = max(dot(n, normalize(vec3(-0.55, 0.55, 0.62))), 0.0);
    float light = 0.62 + 0.52 * sun;
    c *= light;
    float d = length(vWorld - cameraPosition);
    c = mix(c, uFogColor, smoothstep(uFog.x, uFog.y, d));
    outColor = vec4(c, 1.0);
  }
`;
// Loading a binary data file (tiles.bin, terrain.bin). In the public release these are gzip-compressed
// (Cloudflare does not compress .bin files by itself); this is detected from the first two bytes (1f 8b) and unpacked here.
async function binarisBetolt(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error('nincs ' + url);
  const buf = await resp.arrayBuffer();
  const b = new Uint8Array(buf, 0, Math.min(2, buf.byteLength));
  if (b.length === 2 && b[0] === 0x1f && b[1] === 0x8b)
    return new Response(new Blob([buf]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer();
  return buf;
}
let terepMesh = null;
let terepMag = null;
async function buildTerrain() {
  const buf = await binarisBetolt(`${DATA}/terrain.bin`);
  const hd = new DataView(buf);
  const nx = hd.getUint32(0, true), nz = hd.getUint32(4, true);
  const x0 = hd.getFloat32(8, true), z0 = hd.getFloat32(12, true), step = hd.getFloat32(16, true);
  const h = new Int16Array(buf.slice(24));
  terepMag = (x, z) => {        // bilinear height from the terrain mesh (to lay the street lines onto it)
    const fx = (x - x0) / step, fz = (z - z0) / step;
    if (fx < 0 || fz < 0 || fx > nx - 1 || fz > nz - 1) return 0;
    const i = Math.min(Math.floor(fx), nx - 2), j = Math.min(Math.floor(fz), nz - 2), u = fx - i, v = fz - j;
    const m00 = h[j * nx + i], m10 = h[j * nx + i + 1], m01 = h[(j + 1) * nx + i], m11 = h[(j + 1) * nx + i + 1];
    return ((m00 * (1 - u) + m10 * u) * (1 - v) + (m01 * (1 - u) + m11 * u) * v) / 10;
  };
  const SKIRT = -120;
  const W = nx + 2, H = nz + 2;      // an outer ring: the edge forms a downward "skirt"
  const pos = new Float32Array(W * H * 3);
  for (let j = 0; j < H; j++) for (let i = 0; i < W; i++) {
    const ci = Math.min(Math.max(i - 1, 0), nx - 1), cj = Math.min(Math.max(j - 1, 0), nz - 1);
    const edge = i === 0 || j === 0 || i === W - 1 || j === H - 1;
    const k = (j * W + i) * 3;
    pos[k] = x0 + ci * step; pos[k + 1] = edge ? SKIRT : h[cj * nx + ci] / 10; pos[k + 2] = z0 + cj * step;
  }
  const idx = new Uint32Array((W - 1) * (H - 1) * 6);
  let q = 0;
  for (let j = 0; j < H - 1; j++) for (let i = 0; i < W - 1; i++) {
    const a = j * W + i, b = a + 1, c = a + W, d = c + 1;
    idx.set([a, c, b, b, c, d], q); q += 6;
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setIndex(new THREE.BufferAttribute(idx, 1));
  g.computeVertexNormals();
  const x1 = x0 + (nx - 1) * step, z1 = z0 + (nz - 1) * step;
  terrainUniforms.uBox.value.set(x0, z0, x1 - x0, z1 - z0);
  const mat = new THREE.ShaderMaterial({ glslVersion: THREE.GLSL3, uniforms: terrainUniforms,
    vertexShader: TERRAIN_VERT, fragmentShader: TERRAIN_FRAG, side: THREE.DoubleSide });
  const mesh = new THREE.Mesh(g, mat);
  flat.add(mesh);
  terepMesh = mesh;
  kerekMagassag();
  if (config.terep && config.terep.kep) {
    const coverLoaded = tex => {
      tex.flipY = false;
      tex.colorSpace = THREE.NoColorSpace;
      tex.minFilter = THREE.LinearMipmapLinearFilter;
      tex.generateMipmaps = true;
      tex.anisotropy = 4;
      terrainUniforms.uCover.value = tex;
      terrainUniforms.uHasCover.value = 1;
    };
    // the smaller lossless WebP first; the PNG is the fallback if the WebP does not exist
    new THREE.TextureLoader().load(`${DATA}/landcover.webp`, coverLoaded, undefined,
      () => new THREE.TextureLoader().load(`${DATA}/landcover.png`, coverLoaded));
  }
}
buildTerrain().catch(() => {
  const g = new THREE.PlaneGeometry(80000, 80000);
  g.rotateX(-Math.PI / 2);
  flat.add(new THREE.Mesh(g, new THREE.MeshBasicMaterial({ color: LAND })));
});

// ---------- Shared uniforms ----------
const col = c => new THREE.Color(c);
const uniforms = {
  uYear: { value: config.yearMax },
  uYearFrom: { value: config.yearMin - 1 },
  uMode: { value: MODE.period },
  uPalette: { value: periods.map(p => col(p.color)) },
  uMask: { value: periods.map(() => 1) },
  uNow: { value: 0 },
  uPlaying: { value: 0 },
  uRise: { value: 0.01 },
  uMaquette: { value: col(MAQUETTE) },
  uHover: { value: -1 },
  uSelected: { value: -1 },
  uHoverGrp: { value: 0 },
  uSelGrp: { value: 0 },
  uGrp: { value: null },
  uPick: { value: null },
  uPickOn: { value: 0 },
  uFogColor: uniformsFog().uFogColor,
  uFog: uniformsFog().uFog,
};

// Highlighting (protected / Wikipedia / Lechner): one bit per building; highlighted ones keep their colour, the rest fade.
const PICK_ROWS = Math.ceil(config.stats.buildings / ATTR_W);
const pickData = new Uint8Array(ATTR_W * PICK_ROWS * 4);
const pickTex = new THREE.DataTexture(pickData, ATTR_W, PICK_ROWS, THREE.RGBAFormat, THREE.UnsignedByteType);
pickTex.needsUpdate = true;
uniforms.uPick.value = pickTex;

// Building group: gid -> group number (16 bits, 0 = no group); all members of a group light up together
const grpData = new Uint8Array(ATTR_W * PICK_ROWS * 4);
const grpTex = new THREE.DataTexture(grpData, ATTR_W, PICK_ROWS, THREE.RGBAFormat, THREE.UnsignedByteType);
const grpIdx = new Uint16Array(ATTR_W * PICK_ROWS);
{
  const nevek = new Map();
  for (let gid = 0; gid < Math.min(epuletek.length, config.stats.buildings); gid++) {
    const k = epuletek[gid] && epuletek[gid].csoport;
    if (!k) continue;
    if (!nevek.has(k)) nevek.set(k, nevek.size + 1);
    const n = nevek.get(k) & 0xffff;
    grpIdx[gid] = n; grpData[gid * 4] = n & 255; grpData[gid * 4 + 1] = n >> 8;
  }
}
grpTex.needsUpdate = true;
uniforms.uGrp.value = grpTex;

const VERT = /* glsl */`
  in float bld;
  uniform sampler2D uAttr;
  uniform float uHoverGrp, uSelGrp;
  uniform sampler2D uGrp;
  uniform float uYear, uYearFrom, uMode, uHover, uSelected, uNow, uBorn, uPlaying, uRise;
  uniform vec3 uPalette[${periods.length}];
  uniform float uMask[${periods.length}];
  uniform vec3 uMaquette;
  uniform sampler2D uPick;
  uniform float uPickOn;
  out vec3 vColor;
  out vec3 vWorld;
  out float vGid;
  out float vRel;

  vec3 floorsRamp(float f) {
    float t = clamp(log(f) / log(40.0), 0.0, 1.0);
    vec3 a = vec3(0.86, 0.89, 0.90), b = vec3(0.49, 0.66, 0.75), c = vec3(0.17, 0.36, 0.55), d = vec3(0.05, 0.10, 0.25);
    return t < 0.33 ? mix(a, b, t / 0.33) : t < 0.66 ? mix(b, c, (t - 0.33) / 0.33) : mix(c, d, (t - 0.66) / 0.34);
  }

  void main() {
    int i = int(bld + 0.5);
    ivec2 tc = ivec2(2 * (i % ${ATTR_W}), i / ${ATTR_W});
    vec4 a = texelFetch(uAttr, tc, 0);
    float year = a.x;
    int pf = int(a.y + 0.5);
    int period = pf % 16;
    vGid = a.w;
    float vis = uMask[period];
    float g = clamp((uYear - year + 1.0) / uRise, 0.0, 1.0);
    g = g * g * (3.0 - 2.0 * g);
    if (g <= 0.003 || vis <= 0.003) { gl_Position = vec4(2.0, 2.0, 2.0, 1.0); return; }

    // Entry animation: only for the played film and when tiles load. The building "drops in" from its own side.
    vec3 p = position;
    vRel = position.y * 0.1;
    vec4 lay = texelFetch(uAttr, tc + ivec2(1, 0), 0);
    p.y += lay.x + lay.y * 65536.0 - 1000.0;   // base height (dm)
    float seed = fract(sin(a.w * 12.9898) * 43758.5453);
    float arrive = clamp((uNow - uBorn) / 0.9 - seed * 0.35, 0.0, 1.0);
    float fly = 1.0 - arrive;
    if (uPlaying > 0.5) fly = max(fly, 1.0 - g);
    if (fly > 0.0) {
      float e = fly * fly * fly;
      float ang = seed * 6.2831853;
      p += vec3(cos(ang), 0.0, sin(ang)) * (1800.0 + 1600.0 * fract(seed * 7.13)) * e;
      p.y += (2600.0 + 2400.0 * fract(seed * 3.71)) * e;
    }
    vec3 c = uMode < 0.5 ? uPalette[period] : floorsRamp(mod(a.z, 128.0));
    if (year <= uYearFrom) c = mix(c, uMaquette, 0.8);
    int gg = int(vGid + 0.5);
    vec4 gt = texelFetch(uGrp, ivec2(gg % ${ATTR_W}, gg / ${ATTR_W}), 0);
    float grp = floor(gt.x * 255.0 + 0.5) + floor(gt.y * 255.0 + 0.5) * 256.0;
    if (vGid == uHover || vGid == uSelected || (grp > 0.5 && (grp == uHoverGrp || grp == uSelGrp))) c = mix(c, vec3(0.0), 0.35);
    if (uPickOn > 0.5) {
      int gi = int(vGid + 0.5);
      if (texelFetch(uPick, ivec2(gi % ${ATTR_W}, gi / ${ATTR_W}), 0).x < 0.5) c = vec3(1.0);   // highlight filter: whatever does not match is white
    }
    vColor = c;
    vec4 w = modelMatrix * vec4(p, 1.0);
    vWorld = w.xyz;
    gl_Position = projectionMatrix * viewMatrix * w;
  }
`;

const FRAG = /* glsl */`
  precision highp float;
  uniform vec3 uFogColor;
  uniform vec2 uFog;
  in vec3 vColor;
  in vec3 vWorld;
  in float vGid;
  in float vRel;
  out vec4 outColor;
  void main() {
    #ifdef PICK
      float id = vGid + 1.0;
      outColor = vec4(mod(id, 256.0), mod(floor(id / 256.0), 256.0), floor(id / 65536.0), 255.0) / 255.0;
    #else
      vec3 n = normalize(cross(dFdx(vWorld), dFdy(vWorld)));
      // Low afternoon sun from the south-west, soft sky light from above.
      float sun = max(dot(n, normalize(vec3(-0.55, 0.55, 0.62))), 0.0);
      float light = n.y > 0.9 ? 1.04 : 0.66 + 0.34 * sun;
      float foot = mix(0.82, 1.0, clamp(vRel / 12.0, 0.0, 1.0));
      vec3 c = vColor * light * foot;
      float d = length(vWorld - cameraPosition);
      c = mix(c, uFogColor, smoothstep(uFog.x, uFog.y, d));
      outColor = vec4(c, 1.0);
    #endif
  }
`;

function makeMaterial(tex, pick, born) {
  return new THREE.ShaderMaterial({
    glslVersion: THREE.GLSL3,
    uniforms: { ...uniforms, uAttr: { value: tex }, uBorn: born },
    vertexShader: VERT,
    fragmentShader: FRAG,
    defines: pick ? { PICK: 1 } : {},
    side: THREE.DoubleSide,
  });
}

// ---------- Tiles ----------
const meshes = [];

// Bridges follow the legend's era checkboxes and the time slider like buildings do (by era; those without a year are always visible).
const hidRek = o => epuletek[o.userData.rek != null ? o.userData.rek : EPULET_DB + o.userData.hid];
// Bridges appear only once the whole city (all tiles) has loaded; they then "drop in" (hidBorn), and during playback they rise at their construction year, like buildings.
const hidBorn = { value: 1e9 };
function hidFrissit() {
  const Y = uniforms.uYear.value, kesz = loaded === config.tiles.length;
  const lat = o => { const p = hidRek(o); return !!(p && maskTarget[p.kor]) && (!p || !p.ev || p.ev <= Y + 1); };
  for (const m of hidMeshek) m.visible = lat(m) && (m.userData.hid == null || kesz);
  // the lines (cables, arch) are not animated: they stay hidden until the bridge body has arrived / has risen
  const megerkezett = kesz && uniforms.uNow.value - hidBorn.value > 1.4;
  for (const l of hidVonalak) { const p = hidRek(l); l.visible = lat(l) && megerkezett && (!uniforms.uPlaying.value || !p || !p.ev || Y >= p.ev + uniforms.uRise.value); }
}

// ---------- Danube bridges (schematic model; build_bridges.py -> hidak.json) ----------
const EPULET_DB = epuletek.length;       // the bridges' card records follow the buildings: gid = EPULET_DB + bridge index
const hidMeshek = [], hidVonalak = [];
fetch(`${DATA}/hidak.json`).then(r => (r.ok ? r.json() : null)).then(adat => {
  if (!adat || !adat.hidak || !adat.hidak.length) return;
  const korIdx = ev => { const i = ev ? periods.findIndex(p => p.to !== 0 && ev >= p.from && ev <= p.to) : -1; return i < 0 ? 1 : i; };
  adat.hidak.forEach(h => epuletek.push(hidRekord(h, korIdx)));
  const ut = hidakEpit(THREE, adat, { ...uniformsFog(), uMaquette: uniforms.uMaquette, uYear: uniforms.uYear, uNow: uniforms.uNow, uPlaying: uniforms.uPlaying, uRise: uniforms.uRise, uBorn: hidBorn }, EPULET_DB, h => { const c = col(periods[korIdx(h.ev)].color); return [c.r, c.g, c.b]; });
  scene.add(ut.csoport);
  hidMeshek.push(...ut.meshek);
  hidVonalak.push(...ut.vonalak);
  frissitKiemelest();   // an already active highlight filter also applies to bridges
}).catch(() => {});
// The Ferris wheel (OSM way 386319234) is misleading as a 65 m tall box: it is left out of the tiles and a thin, vertical disc is drawn instead (same card/highlight).
const KEREK_GID = epuletek.findIndex(p => p && !p.hid && p.id === 386319234 && (p.osm_tipus || 'way') === 'way');
var kerekMesh = null, kerekX = 0, kerekZ = 0;
// the disc is placed at ground height (three sample points along the disc's axis, the lowest one)
function kerekMagassag() {
  if (!kerekMesh || !terepMesh) return;
  terepMesh.updateMatrixWorld(true);
  const rc = new THREE.Raycaster(); let y = Infinity;
  for (const o of [-20, 0, 20]) {
    rc.set(new THREE.Vector3(kerekX + o * -0.731, 3000, kerekZ + o * -0.682), new THREE.Vector3(0, -1, 0));
    const h = rc.intersectObject(terepMesh, false)[0];
    if (h) y = Math.min(y, h.point.y);
  }
  if (isFinite(y)) kerekMesh.position.y = y;
}
// the disc appears (and "drops in" the same way) when the Ferris wheel's tile has loaded
function kerekEpit(born) {
  if (kerekMesh || KEREK_GID < 0) return;
  const kp = epuletek[KEREK_GID];
  kerekX = (kp.lon - 19.0515) * Math.cos(47.5015 * Math.PI / 180) * 111320; kerekZ = -(kp.lat - 47.5015) * 110574;   // LON0/LAT0/COSLAT are declared later
  const kc = col(periods[Math.max(0, periods.findIndex(q => q.to !== 0 && kp.ev >= q.from && kp.ev <= q.to))].color);
  // the disc's plane lies along the footprint's long axis (roughly NW-SE); 65 m peak: R = 31.5 m, lowest point at 2 m
  const km = korlapEpit(THREE, { ...uniformsFog(), uMaquette: uniforms.uMaquette, uYear: uniforms.uYear, uNow: uniforms.uNow, uPlaying: uniforms.uPlaying, uRise: uniforms.uRise },
    KEREK_GID, [kc.r, kc.g, kc.b], kerekX, kerekZ, -0.731, -0.682, 31.5, 33.5, 1.2, kp.ev, born);
  scene.add(km);
  hidMeshek.push(km);
  kerekMesh = km;
  kerekMagassag();
  frissitKiemelest();
}
let loaded = 0;
const queue = [...config.tiles];
const pool = Array.from({ length: WORKERS }, () => new Worker('worker.js', { type: 'module' }));

function addTile(m) {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(m.pos, 3));
  g.setAttribute('bld', new THREE.BufferAttribute(m.bld, 1));
  g.setIndex(new THREE.BufferAttribute(m.idx, 1));
  // The base height (terrain) is added by the vertex shader; the mesh geometry sits at ground level. For picking (a 1-pixel view stub)
  // three.js would therefore cull high-lying buildings (e.g. Jánoshegy) unless viewed from directly above: the bounding sphere is enlarged (700 m).
  g.computeBoundingSphere();
  g.boundingSphere.radius += 7000;
  const rows = Math.ceil(m.nB / ATTR_W);
  const data = new Float32Array(ATTR_W * 2 * rows * 4);
  data.set(m.attr);
  const tex = new THREE.DataTexture(data, ATTR_W * 2, rows, THREE.RGBAFormat, THREE.FloatType);
  tex.needsUpdate = true;
  const born = { value: performance.now() / 1000 };
  if (KEREK_GID >= 0 && !kerekMesh) for (let b = 0; b < m.nB; b++) if (m.attr[b * 8 + 3] === KEREK_GID) { kerekEpit(born); break; }
  const mesh = new THREE.Mesh(g, makeMaterial(tex, false, born));
  mesh.userData = { draw: mesh.material, pick: makeMaterial(tex, true, born) };
  mesh.scale.setScalar(0.1);
  mesh.position.set(m.origin[0], 0, m.origin[1]);
  scene.add(mesh);
  meshes.push(mesh);
}

const packs = Object.fromEntries(config.packs.map(name => [name, binarisBetolt(`${DATA}/${name}`)]));
for (const w of pool) {
  const next = async () => {
    const tt = queue.shift();
    if (!tt) return;
    const buf = (await packs[tt.pack]).slice(tt.offset, tt.offset + tt.length);
    w.postMessage({ buf, id: tt.file, skip: KEREK_GID >= 0 ? [KEREK_GID] : null }, [buf]);
  };
  w.onmessage = ({ data }) => {
    addTile(data);
    loaded++;
    document.getElementById('progress').textContent = Math.round(100 * loaded / config.tiles.length);
    if (loaded === config.tiles.length) { document.getElementById('loading').hidden = true; hidBorn.value = performance.now() / 1000; }
    next();
  };
  next();
}

// ---------- Picking (which building is under the pointer) ----------
const pickTarget = new THREE.WebGLRenderTarget(1, 1);
const pickPixel = new Uint8Array(4);
function pick(x, y) {
  const w = renderer.domElement.clientWidth, h = renderer.domElement.clientHeight;
  camera.setViewOffset(w, h, x, y, 1, 1);
  for (const m of meshes) m.material = m.userData.pick;
  for (const m of hidMeshek) m.material = m.userData.pick;
  for (const l of hidVonalak) l.visible = false;
  flat.visible = false;
  renderer.setRenderTarget(pickTarget);
  renderer.setClearColor(0x000000, 0);
  renderer.clear();
  renderer.render(scene, camera);
  renderer.readRenderTargetPixels(pickTarget, 0, 0, 1, 1, pickPixel);
  renderer.setRenderTarget(null);
  renderer.setClearColor(SKY, 1);
  flat.visible = true;
  for (const m of meshes) m.material = m.userData.draw;
  for (const m of hidMeshek) m.material = m.userData.draw;
  hidFrissit();
  camera.clearViewOffset();
  return pickPixel[0] + pickPixel[1] * 256 + pickPixel[2] * 65536 - 1;
}

// ---------- Card ----------
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function inkOn(hex) {
  const c = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map(v => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2] > 0.3 ? '#000' : '#fff';
}

var TIPUS_HU = { apartments: 'lakóház (társasház)', house: 'lakóház', residential: 'lakóépület', detached: 'családi ház', industrial: 'ipari épület', semidetached_house: 'ikerház', garage: 'garázs', garages: 'garázssor', retail: 'üzlet', office: 'irodaház', school: 'iskola', service: 'szolgáltató épület', shed: 'fészer', commercial: 'kereskedelmi épület', kindergarten: 'óvoda', church: 'templom', hospital: 'kórház', construction: 'építés alatt', warehouse: 'raktár', terrace: 'sorház', university: 'egyetemi épület', hotel: 'szálloda', greenhouse: 'üvegház', public: 'közösségi épület', government: 'állami épület', bungalow: 'bungaló', ruins: 'romos épület', carport: 'autóbeálló', dormitory: 'kollégium', transportation: 'közlekedési épület', train_station: 'vasútállomás', allotment_house: 'zártkerti ház', civic: 'középület', kiosk: 'kioszk', hut: 'kunyhó', outbuilding: 'melléképület', sports_centre: 'sportcentrum', childcare: 'bölcsőde', chapel: 'kápolna', container: 'konténer', tower: 'torony', sports_hall: 'sportcsarnok', bridge: 'híd', bunker: 'bunker', guardhouse: 'őrház', gatehouse: 'kapuház', storage_tank: 'tároló tartály', parking: 'parkolóház', toilets: 'illemhely', manufacture: 'üzem', synagogue: 'zsinagóga', basilica: 'bazilika', fire_station: 'tűzoltóállomás', stadium: 'stadion', grandstand: 'lelátó', religious: 'vallási épület', transformer_tower: 'transzformátorház', prison: 'börtön', ship: 'hajó', museum: 'múzeum', hangar: 'hangár', college: 'főiskola', barn: 'pajta', silo: 'siló', water_tower: 'víztorony', tent: 'sátor', stable: 'istálló', monastery: 'kolostor', abandoned: 'elhagyott épület', dome: 'kupola', porters_cubicle: 'portásfülke', zoo: 'állatkerti épület', static_caravan: 'lakókocsi', boathouse: 'csónakház', pavilion: 'pavilon', government_office: 'hivatal', farm_auxiliary: 'gazdasági épület', theatre: 'színház', cabin: 'faház', electricity: 'villamos létesítmény', porch: 'veranda', shrine: 'szentély', castle: 'kastély', clinic: 'rendelő', demolished: 'lebontott épület', cinema: 'mozi', data_center: 'adatközpont', supermarket: 'szupermarket', palace: 'palota', balcony: 'erkély', staircase: 'lépcsőház', farm: 'tanya', sport: 'sportépület', restaurant: 'étterem', public_building: 'középület', presbytery: 'plébánia', bell_tower: 'harangtorony', mosque: 'mecset', swimming_pool: 'uszoda', fort: 'erőd', riding_hall: 'lovarda', place_of_worship: 'imaház', shelter: 'menedék', bank: 'bank', transformer: 'transzformátor', police: 'rendőrség', cloister: 'kolostor', social_facility: 'szociális intézmény', houseboat: 'lakóhajó', power: 'energetikai épület', bakehouse: 'sütöde', watermill: 'vízimalom', temple: 'templom', mall: 'bevásárlóközpont', corridor: 'összekötő folyosó', patio: 'belső udvar' };
function tipusNev(v) {
  if (!v) return v;
  const r = String(v).split(';').map(x => x.trim()).filter(x => x && x !== 'yes').map(x => NYELV === 'en' ? x : (TIPUS_HU[x] || x));
  return r.length ? r.join(', ') : '-';       // 'yes' (generic building): no specific type, "-" is shown
}
function gmapsUrl(p) {
  const q = p.cim ? `${p.cim}, Budapest` : `${p.lat},${p.lon}`;
  return 'https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent(q);
}

function wikipediaLinkek(p) {
  return String(p.wikipedia || '').split('|').slice(0, 3).map(cikk => {
    const m = /^(hu|en):(.+)$/.exec(cikk.trim());
    if (!m) return '';
    const url = `https://${m[1]}.wikipedia.org/wiki/${encodeURIComponent(m[2].replace(/ /g, '_'))}`;
    const zonaJel = p.wikipedia_zona ? `, ${esc(t('wiki_zona').replace('{zona}', p.wikipedia_zona))}` : '';
    return `<a href="${url}" target="_blank" rel="noopener">${esc(m[2])}</a> <small>(Wikipedia, ${m[1]}${zonaJel})</small>`;
  }).filter(Boolean);
}

function vedettsegSzoveg(p) {
  const r = [];
  const kod = p.vedettseg || (p.vedettseg_helyi ? 'HV' : '');   // local protection is a type of its own: only for local protection is this the main protection status
  if (kod) r.push((VEDETTSEG[NYELV][kod] || kod) + (p.muemlek_torzsszam && kod !== 'HV' ? ` (${t('torzsszam')} ${p.muemlek_torzsszam})` : ''));
  if (p.vedettseg_helyi && kod !== 'HV') r.push(VEDETTSEG[NYELV].HV || p.vedettseg_helyi);
  return r.join(', ');
}

// Data of the drawn zone from the reasoning of ev_becsles: "...; drawn zone: Name (1971-1975); ..."
// If the building lies in a drawn zone, the card shows the zone's name and the period tied to it (the colour stays that of the estimated era).
function zonaAdat(p) {
  const m = /rajzolt zóna: (.*?) \((\d{3,4})[–-](\d{3,4})\)(?=;|$)/.exec(String(p.ev_becsles_indoklas || ''));
  if (!m) return null;
  const tol = +m[2], ig = +m[3];
  return { nev: m[1], ido: tol === ig ? String(tol) : `${tol}–${ig}` };
}

function kozelitoIdo(p) { return +p.ev_kozelito_tol === +p.ev_kozelito_ig ? String(p.ev_kozelito_tol) : `${p.ev_kozelito_tol}–${p.ev_kozelito_ig}`; }

// ---------- Data sheets of key buildings (adatlapok.json <- py build_datasheets.py): text, image gallery, sources in the map card ----------
let adatlapok = null;
const adatlapBe = fetch('adatlapok.json').then(r => (r.ok ? r.json() : null)).then(j => { adatlapok = j; }).catch(() => {});
const adatlapAdat = p => (adatlapok && p && adatlapok.adatlapok[(p.osm_tipus || 'way') + '/' + p.id]) || null;
const biztonsagosUrl = u => /^https?:\/\/[^\s"'<>]+$/i.test(u || '');
// Image gallery in the card (as in the Amsterdam project): large image, ‹ › arrows, the label in the image corner, the source below, then label buttons row by row (e.g. year).
// Sources: the automatic photo (Commons, Budapest100, ...) + the data sheet's images (adatlapok.json) + the "Image links" given in the editor. The label is the year in the caption, otherwise the index.
function galeriaDiak(p) {
  const d = [], ad = adatlapAdat(p);
  const kesz = k => {
    const reszek = [];
    if (k.felirat) reszek.push(esc(k.felirat));
    if (k.szerzo) reszek.push((NYELV === 'en' ? 'Photo: ' : 'Fotó: ') + esc(k.szerzo));
    if (k.fp) reszek.push(`${t('kep_forras')}: <a href="${esc(k.lap)}" target="_blank" rel="noopener noreferrer">Fortepan #${esc(k.fp)}</a>`);
    else if (biztonsagosUrl(k.lap)) { let h = k.lap; try { h = new URL(k.lap).hostname.replace(/^www\./, ''); } catch (e) { /* stays */ } reszek.push(`${t('kep_forras')}: <a href="${esc(k.lap)}" target="_blank" rel="noopener noreferrer">${esc(h)}</a>`); }
    if (k.licenc) reszek.push(k.licencUrl ? `<a href="${esc(k.licencUrl)}" target="_blank" rel="noopener noreferrer">${esc(k.licenc)}</a>` : esc(k.licenc));
    const ev = /(?:^|\D)(1[5-9]\d\d|20[0-3]\d)(?!\d)/.exec(k.felirat || k.szerzo || '');
    return { src: k.src, html: reszek.join(' · '), chip: ev ? ev[1] : '', ev: ev ? +ev[1] : null };
  };
  if (ad) (ad.kepek || []).forEach(k => d.push(kesz({ src: k.f, szerzo: k.szerzo, lap: k.forras, licenc: k.licenc })));
  String((p && p.kepek_linkek) || '').split('\n').forEach(sor => {
    const i = sor.lastIndexOf('|'), url = sor.slice(i + 1).trim(), felirat = i >= 0 ? sor.slice(0, i).trim() : '';
    if (!/^https:\/\/[^\s"'<>]+$/i.test(url)) return;
    const fp = /^https:\/\/(?:[a-z0-9-]+\.)?fortepan\.(?:hu|download)\/[^\s"'<>]*?fortepan_(\d+)/i.exec(url);      // Fortepan: the photo page and licence derived from the id
    d.push(kesz(fp ? { src: url, felirat, fp: fp[1], lap: `https://fortepan.hu/hu/photos/?id=${fp[1]}`, licenc: 'CC BY-SA 3.0', licencUrl: 'https://creativecommons.org/licenses/by-sa/3.0/' } : { src: url, felirat, lap: url }));
  });
  d.sort((x, y) => (x.ev === null ? 1e9 : x.ev) - (y.ev === null ? 1e9 : y.ev));      // chronological order (those without a year at the end, in the order given)
  d.forEach((k, i) => { if (!k.chip) k.chip = String(i + 1); });
  return d;
}
// The automatic photo (the result of kepLeker) becomes the gallery's first slide
function galeriaAutoDia(k) {
  const link = (u, sz) => u ? `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(sz)}</a>` : esc(sz);
  const f = `${t('kep_forras')}: `;
  if (k.forras === 'oeny') {
    const az = k.azonositok[0], lap = `https://www.oeny.hu/oeny/eorok/public/monument/${az}`;
    return { src: `https://www.oeny.hu/oeny/eorok/public/api/v1/ovnyr/muemlek/${az}/kep`, html: f + link(lap, 'E-Örökség') + ' (oeny.hu; a fotó jogai a megjelölt jogtulajdonosé)' };
  }
  if (k.forras === 'url') { let h = 'link'; try { h = new URL(k.lap).hostname.replace(/^www\./, ''); } catch (e) { /* stays */ } return { src: k.src, html: f + esc(h) }; }
  if (k.forras === 'legenda') return { src: k.src, html: f + link(k.lap, 'Budapest Legenda') + ' (budapestlegenda.hu)' };
  if (k.forras === 'bp100') return { src: k.src, html: f + (k.foto ? '© ' + esc(k.foto) + ' · ' : '') + link(k.lap, 'Budapest100') + ' (budapest100.hu)' };
  return { src: k.src, html: f + esc(k.szerzo || 'Wikimedia Commons') + ' · ' + link(k.licencUrl, k.licenc || 'Wikimedia Commons') + ' · ' + link(k.lap, 'Wikimedia Commons')
    + (k.mod ? ` <em>(${t({ cim: 'kep_cim', hely: 'kep_hely', wd: 'kep_wd', kat: 'kep_kat' }[k.mod] || 'kep_nev')}${k.reszlet ? '; ' + t('kep_reszlet') : ''})</em>` : '') };
}
function galeriaBetolt(gid) {
  const p = epuletek[gid], hely = kartya.querySelector('section.kep.galeria'), diak = galeriaDiak(p);
  if (!hely || !diak.length) return;
  hely.innerHTML = '<div class="gal-kep"><img alt="" referrerpolicy="no-referrer"><button type="button" data-d="-1" aria-label="‹">‹</button><button type="button" data-d="1" aria-label="›">›</button><span class="gal-cimke"></span></div><small class="gal-felirat"></small><div class="gal-chipek"></div>';
  const kep = hely.querySelector('img'), fel = hely.querySelector('.gal-felirat'), cim = hely.querySelector('.gal-cimke'), chipek = hely.querySelector('.gal-chipek');
  let akt = 0, lapozott = false;
  const ujabbDia = () => { let j = -1; diak.forEach((k, i) => { if (k.ev !== null) j = i; }); return j >= 0 ? j : 0; };
  const rajzol = () => {
    hely.querySelectorAll('.gal-kep button').forEach(b => { b.hidden = diak.length < 2; });
    chipek.hidden = diak.length < 2;
    chipek.innerHTML = diak.map((k, i) => `<button type="button" data-i="${i}">${esc(k.chip)}</button>`).join('');
  };
  const mut = i => {
    akt = (i + diak.length) % diak.length;
    const k = diak[akt];
    kep.alt = p.nev || p.cim || '';
    kep.src = k.src;
    fel.innerHTML = k.html || '';
    fel.hidden = !k.html;
    cim.textContent = diak.length > 1 ? k.chip : '';
    chipek.querySelectorAll('button').forEach((b, j) => b.classList.toggle('aktiv', j === akt));
    const aktChip = chipek.querySelector('.aktiv'); if (aktChip && chipek.scrollWidth > chipek.clientWidth) aktChip.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  };
  kep.addEventListener('error', () => {      // skips an image that cannot be loaded; if none can be loaded, the automatic photo is used
    diak.splice(akt, 1);
    if (diak.length) { rajzol(); mut(Math.min(akt, diak.length - 1)); return; }
    hely.hidden = true; hely.classList.remove('galeria'); hely.innerHTML = '';
    kepBetolt(gid);
  });
  hely.querySelector('.gal-kep').addEventListener('click', ev => { const b = ev.target.closest('button[data-d]'); if (b) { lapozott = true; mut(akt + +b.dataset.d); } });
  chipek.addEventListener('click', ev => { const b = ev.target.closest('button[data-i]'); if (b) { lapozott = true; mut(+b.dataset.i); } });
  let x0 = null;      // drag (touch screen / mouse): left = next, right = previous
  kep.addEventListener('pointerdown', ev => { x0 = ev.clientX; });
  kep.addEventListener('pointerup', ev => { if (x0 !== null && diak.length > 1 && Math.abs(ev.clientX - x0) > 40) { lapozott = true; mut(akt + (ev.clientX < x0 ? 1 : -1)); } x0 = null; });
  rajzol();
  mut(ujabbDia());      // the newest (latest-year) image is shown first, not the earliest
  hely.hidden = false;
  // the automatic photo goes in front of the "original", unless the user has paged in the meantime
  if (!nincsKep(p) && kepLehet(p)) {
    if (!kepGyorsitotar.has(gid)) kepGyorsitotar.set(gid, kepLeker(p).catch(() => null));
    kepGyorsitotar.get(gid).then(k => {
      if (!k || rogzitettGid !== gid || !kartya.contains(hely) || !hely.classList.contains('galeria')) return;
      const dia = galeriaAutoDia(k);
      const jelenlegi = diak[akt];
      dia.chip = NYELV === 'en' ? 'Today' : 'Ma';      // the automatic (current) photo stands at the end of the timeline, and it is shown first
      diak.push(dia);
      rajzol();
      mut(lapozott ? diak.indexOf(jelenlegi) : diak.length - 1);
    });
  }
}
function kartyaHtml(p, rogzitett) {
  const per = periods[p.kor];
  const rom = !!p.rom;
  const ismert = !!p.ev && !rom;
  const zona = (ismert || rom) ? null : zonaAdat(p);
  const nev = p.nev || p.lechner_nev || p.nev_kozepulet || (!rom && p.zona_nev) || (zona && zona.nev) || (rom && p.wikipedia_zona);
  const cim = p.cim ? esc(p.cim) + (p.cim_tobb ? ` <small>(${t('tobb_cim').replace('{n}', p.cim_tobb)})</small>` : '') : '';
  let html = rogzitett ? '<button type="button" class="kartya-bezar" aria-label="×">×</button>' : '';
  html += `<header class="kartya-fej" style="background:${per.color};color:${inkOn(per.color)}">`;
  html += `<h3>${esc(nev || p.cim || t('nevtelen'))}</h3>`;
  html += `<p class="cim"><span>${cim}</span><span class="pont"> • </span><a href="${esc(gmapsUrl(p))}" target="_blank" rel="noopener">${t('gmaps')}</a></p>`;
  html += `<div class="mikor">`;
  if (rom) html += `<span class="ev kicsi">${esc(p.rom)}</span><span class="korszak">${t('rom_cimke')}</span>`;
  else if (ismert) html += `<span class="ev">${esc(p.ev)}</span><span class="korszak">${esc(korNev(p.kor))}</span>`;
  else if (p.hid) html += `<span class="ev kicsi">?</span><span class="korszak">${NYELV === 'en' ? 'year unknown' : 'nincs évszám'}</span>`;
  else if (p.ev_kozelito_tol) html += `<span class="ev kicsi">${esc(kozelitoIdo(p))}</span><span class="korszak">${NYELV === 'en' ? 'per source' : 'forrás szerint'}</span>`;
  else html += `<span class="ev kicsi">${esc(zona ? zona.ido : korNev(p.kor))}</span><span class="korszak">${t('becsult')}</span>`;
  html += `</div></header>`;
  if (p.ev_kozelito_tol && !ismert && !rom && !p.hid) {
    html += `<section class="becsles">${NYELV === 'en' ? 'Period according to the source (approximate)' : 'A forrás szerinti időszak (közelítő)'}: <strong>${esc(kozelitoIdo(p))}</strong>`
      + (p.ev_kozelito_szoveg || p.ev_kozelito_forras ? `<br><small>${p.ev_kozelito_szoveg ? '„' + esc(p.ev_kozelito_szoveg) + '”' : ''}${p.ev_kozelito_forras ? ' – ' + esc(p.ev_kozelito_forras) : ''}</small>` : '') + `</section>`;
  }

  if (!rogzitett) return html + `<p class="tipp">${t('reszletek')}</p>`;

  const adatlap = adatlapAdat(p);
  if (galeriaDiak(p).length) html += `<section class="kep galeria" hidden></section>`;
  else if (kepLehet(p)) html += `<section class="kep" hidden></section>`;
  const sorok = [[t('tipus'), esc(tipusNev(p.tipus) || '?') + (p.resz ? ` <small>(${t('resz')})</small>` : '')]];
  if (p.hid) {
    if (p.hid_hossz) sorok.push([NYELV === 'en' ? 'Length' : 'Hossz', `${p.hid_hossz} m` + (p.hid_viz ? ` <small>(${NYELV === 'en' ? 'over water' : 'ebből a víz fölött'}: ${p.hid_viz} m)</small>` : '')]);
    if (p.hid_ujjaepitve) sorok.push([NYELV === 'en' ? 'Rebuilt' : 'Újjáépítés', esc(p.hid_ujjaepitve)]);
  }
  if (p.zona_tervezo && !(p.tervezo && archFold(p.tervezo).includes(archFold(p.zona_tervezo)))) sorok.push([t('zona_tervezo'), esc(p.zona_tervezo) + (p.zona_tervezo_nev ? ` <small>(${esc(p.zona_tervezo_nev)})</small>` : '')]);
  if (p.tervezo) sorok.push([t('tervezo'), esc(p.tervezo) + (p.tervezo_forras ? ` <small>(${esc(forrasNev(p.tervezo_forras) || p.tervezo_forras)})</small>` : '')]);
  if (p.stilus) sorok.push([t('stilus'), esc(p.stilus)]);
  const ved = vedettsegSzoveg(p);
  if (ved) sorok.push([t('vedettseg'), esc(ved)]);
  const tobb = [];     // "Learn more": external pages about the building (E-Örökség, Budapest100, Építészfórum, Budapest Legenda)
  String(p.oeny_azonosito || '').split('|').filter(a => /^\d{1,8}$/.test(a)).forEach(a =>
    tobb.push(`<a href="https://www.oeny.hu/oeny/eorok/public/monument/${a}" target="_blank" rel="noopener">E-Örökség (OENY)${p.muemlek_torzsszam ? ', törzsszám ' + esc(p.muemlek_torzsszam) : ''}</a>`));
  if (/^https:\/\/budapest100\.hu\//.test(p.budapest100_url || ''))
    tobb.push(`<a href="${esc(p.budapest100_url)}" target="_blank" rel="noopener">Budapest100</a>`);
  const epfCikkek = String(p.epforum_url || '').split('|').filter(u => /^https:\/\/epiteszforum\.hu\//.test(u));   // the point's articles (not the map's landing page)
  epfCikkek.forEach((u, n) => tobb.push(`<a href="${esc(u)}" target="_blank" rel="noopener">Építészfórum${epfCikkek.length > 1 ? ' (' + (n + 1) + ')' : ''}</a>`));
  if (legendaLap(p)) tobb.push(`<a href="${esc(legendaLap(p))}" target="_blank" rel="noopener">Budapest Legenda</a>`);
  html += `<section><dl>${sorok.map(([a, b]) => `<dt>${a}</dt><dd>${b}</dd>`).join('')}</dl></section>`;
  if (tobb.length) html += `<section class="tobbet"><h4>${NYELV === 'en' ? 'Learn more' : 'Tudj meg többet'}</h4><div>${tobb.join('<br>')}</div></section>`;
  if (p.hid && p.hid_megj) html += `<section><small>${esc(p.hid_megj)}</small></section>`;
  if (adatlap && adatlap.szoveg) html += `<section class="adatszoveg"><div style="white-space:pre-line">${esc(adatlap.szoveg)}</div></section>`;
  if (p.about) html += `<section><div style="white-space:pre-line">${esc(p.about)}</div></section>`;
  if (/^https?:\/\/[^\s"'<>]+$/i.test(p.link_url || '')) {
    let host = p.link_url;
    try { host = new URL(p.link_url).hostname.replace(/^www\./, ''); } catch (e) { /* the full address stays */ }
    html += `<section><a href="${esc(p.link_url)}" target="_blank" rel="noopener noreferrer">${esc(host)}</a></section>`;
  }
  if (p.csoport_reszek) html += `<section><h4>${NYELV === 'en' ? 'Parts of the building' : 'Az épület részei'}</h4><div style="white-space:pre-line"><small>${esc(p.csoport_reszek)}</small></div></section>`;
  if (wikiCikkek(p).length) html += `<section class="wikikivonat"><small>${t('wiki_betolt')}</small></section>`;

  const forrasok = [...wikipediaLinkek(p)];
  if (adatlap) (adatlap.forrasok || []).forEach(f => { if (biztonsagosUrl(f.url)) forrasok.push(`<a href="${esc(f.url)}" target="_blank" rel="noopener noreferrer">${esc(f.nev || f.url)}</a>`); });
  String(p.linkek || '').split('\n').forEach(sor => {
    const i = sor.lastIndexOf('|'), url = sor.slice(i + 1).trim(), felirat = i >= 0 ? sor.slice(0, i).trim() : '';
    if (!/^https?:\/\/[^\s"'<>]+$/i.test(url)) return;
    let host = url;
    try { host = new URL(url).hostname.replace(/^www\./, ''); } catch (e) { /* the full address stays */ }
    forrasok.push(`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(felirat || host)}</a>`);
  });
  if (/^Q\d+$/.test(p.wikidata_id || '')) forrasok.push(`<a href="https://www.wikidata.org/wiki/${p.wikidata_id}" target="_blank" rel="noopener">Wikidata: ${p.wikidata_id}</a>`);
  // the link of the OpenStreetMap id is hidden on the card
  if (p.lat !== undefined) forrasok.push(`<a href="https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${p.sv_lat !== undefined ? p.sv_lat : p.lat},${p.sv_lon !== undefined ? p.sv_lon : p.lon}" target="_blank" rel="noopener">${t('utcakep')}</a>`);
  html += `<section><h4>${t('forrasok')}</h4><div>${forrasok.join('<br>')}</div></section>`;

  if (false && p.lechner_nev) {   // the Lechner block is hidden (the data stays in the background)
    let l = `<h4>${t('lechner_blokk')}</h4>${t('megnevezes')}: ${esc(p.lechner_nev)}<br>`;
    if (p.lechner_epult) l += `${t('epult')}: ${esc(p.lechner_epult)}<br>`;
    if (p.lechner_tervezo) l += `${t('tervezo')}: ${esc(p.lechner_tervezo)}<br>`;
    if (p.lechner_illesztes === 'kozeli') l += `<small>${t('kozeli_megj')}</small>`;
    html += `<section>${l}</section>`;
  }
  return html;
}


// ---------- Wikipedia extract (on the card, loaded when pinned; CC BY-SA 4.0, with attribution) ----------
const wikiGyorsitotar = new Map();
function wikiCikkek(p) {
  return String(p.wikipedia || '').split('|').map(c => /^(hu|en):(.+)$/.exec(c.trim())).filter(Boolean)
    .map(m => ({ nyelv: m[1], cim: m[2].trim() }));
}
function wikiKivonatLeker(c) {
  const kulcs = c.nyelv + ':' + c.cim;
  if (!wikiGyorsitotar.has(kulcs)) {
    const url = `https://${c.nyelv}.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(c.cim.replace(/ /g, '_'))}`;
    wikiGyorsitotar.set(kulcs, fetch(url, { headers: { Accept: 'application/json' } })
      .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); }));
  }
  return wikiGyorsitotar.get(kulcs);
}
function wikiBetolt(gid) {
  const p = epuletek[gid], hely = kartya.querySelector('.wikikivonat');
  if (!p || !hely) return;
  // in the English interface the English article is preferred, if there is one
  const lista = wikiCikkek(p).sort((a, b) => (b.nyelv === NYELV) - (a.nyelv === NYELV));
  const c = lista[0];
  wikiKivonatLeker(c).then(j => {
    if (rogzitettGid !== gid || !kartya.contains(hely)) return;
    const szoveg = String(j.extract || '').trim();
    if (!szoveg) { hely.remove(); return; }
    const url = (j.content_urls && j.content_urls.desktop && j.content_urls.desktop.page)
      || `https://${c.nyelv}.wikipedia.org/wiki/${encodeURIComponent(c.cim.replace(/ /g, '_'))}`;
    hely.innerHTML = `<div>${esc(szoveg)}</div><small>${t('wiki_forras')}: <a href="${esc(url)}" target="_blank" rel="noopener">${esc(j.title || c.cim)}</a>`
      + (c.nyelv !== NYELV ? ` (${t('wiki_nyelv')})` : '')
      + ` · <a href="https://creativecommons.org/licenses/by-sa/4.0/" target="_blank" rel="noopener">${t('wiki_licenc')}</a></small>`;
    kartyaHelye(parseFloat(kartya.style.left) - 18, parseFloat(kartya.style.top) - 18);
  }).catch(() => {
    if (rogzitettGid === gid && kartya.contains(hely)) hely.innerHTML = `<small>${t('wiki_hiba')}</small>`;
  });
}

// ---------- Image on the card: Wikimedia Commons (Wikidata P18 or the Wikipedia article's image), with a free licence and author ----------
const kepGyorsitotar = new Map();
const legendaLap = p => /^https:\/\/budapestlegenda\.hu\//.test(p.legenda_url || '') ? p.legenda_url : '';
const legendaKep = p => (legendaLap(p) && /^https:\/\/([a-z0-9-]+\.)*budapestlegenda\.hu\//i.test(p.legenda_kep || '')) ? p.legenda_kep : '';
const kepUrl = p => (/^https:\/\/[^\s"'<>]+$/i.test(p.kep_url || '') && !p.kep_url_hibas) ? p.kep_url : '';
const nincsKep = p => String(p.commons_kep || '').trim().toLowerCase() === 'nincs';   // manually disabled photo: commons_kep = nincs
const kepLehet = p => !nincsKep(p) && !!(p.kep || kepUrl(p) || keziCommonsFajl(p) || p.hid || bp100Kep(p) || legendaKep(p) || oenyAzonositok(p).length || /^Q\d+$/.test(p.wikidata_id || '') || wikiCikkek(p).length);
const commonsFajl = j => {
  const m = /\/wikipedia\/commons\/(?:thumb\/)?[0-9a-f]\/[0-9a-f]{2}\/([^/]+)/.exec((j && j.originalimage && j.originalimage.source) || '');
  return m ? decodeURIComponent(m[1]) : null;
};
const bp100Kep = p => (p.budapest100_kep && /^https:\/\/([a-z0-9-]+\.)*budapest100\.hu\//i.test(p.budapest100_kep)
  && /^https:\/\/budapest100\.hu\//.test(p.budapest100_url || '')) ? p.budapest100_kep : '';
// E-Örökség (oeny.hu): the photo of a monument's data sheet is directly reachable from the browser; only if no image is available from another source, and
// only requested when the card is opened (no harvesting). oeny_azonosito is the number of the monument/<id> page.
const oenyAzonositok = p => String(p.oeny_azonosito || '').split('|').filter(a => /^\d{1,8}$/.test(a)).slice(0, 3);
async function kepLeker(p) {
  if (nincsKep(p)) return null;
  // order: 1. manually given Commons photo, 2. E-Örökség (OENY) photo, 3. Budapest100, 4. Budapest Legenda, 5. Commons; if the OENY image cannot be loaded, the next one is used
  if (kepUrl(p) && !keziCommonsFajl(p)) return { forras: 'url', src: kepUrl(p), lap: /^https?:\/\/[^\s"'<>]+$/i.test(p.link_url || '') ? p.link_url : kepUrl(p) };   // manually given photo URL (e.g. public artwork)
  if (!keziCommonsFajl(p) && oenyAzonositok(p).length && !p.oeny_kep_hibas) return { forras: 'oeny', azonositok: oenyAzonositok(p) };
  return kepLekerElso(p);
}
// Manually given Commons photo (forras/kezi_javitasok.csv, mezo = commons_kep; value: the Commons file's link or file name). Takes precedence over every other source.
const keziCommonsFajl = p => {
  let v = String(p.commons_kep || '').trim();
  if (!v) return null;
  const m = /^https?:\/\/(?:[a-z]+\.)?(?:commons\.)?wikimedia\.org\/wiki\/(?:File|Fájl|F%C3%A1jl):([^?#]+)/i.exec(v);
  if (m) { try { v = decodeURIComponent(m[1]); } catch (e) { v = m[1]; } }
  else v = v.replace(/^(?:File|Fájl):/i, '');
  v = v.replace(/ /g, '_');
  return /^[^\/<>]+\.(?:jpe?g|png|gif|tiff?|webp|svg)$/i.test(v) ? v : null;
};
async function kepLekerElso(p) {
  const keziFajl = keziCommonsFajl(p);
  if (!keziFajl && bp100Kep(p)) return { src: bp100Kep(p), lap: p.budapest100_url, forras: 'bp100', foto: p.budapest100_foto || '' };   // the Budapest100 page's image takes precedence over Commons
  if (!keziFajl && legendaKep(p)) return { src: legendaKep(p), lap: legendaLap(p), forras: 'legenda' };   // then the Budapest Legenda page's image, which also takes precedence over Commons
  let fajl = keziFajl || (p.hid && p.kep_fajl ? String(p.kep_fajl).replace(/^(?:File|Fájl):/i, '').replace(/ /g, '_') : null);
  if (!fajl && /^Q\d+$/.test(p.wikidata_id || '')) {
    try {
      const r = await fetch(`https://www.wikidata.org/w/api.php?action=wbgetclaims&entity=${p.wikidata_id}&property=P18&format=json&origin=*`);
      const j = await r.json();
      const c = (j.claims && j.claims.P18) || [];
      const jo = c.find(x => x.rank === 'preferred') || c[0];
      if (jo && jo.mainsnak && jo.mainsnak.datavalue) fajl = String(jo.mainsnak.datavalue.value).replace(/ /g, '_');
    } catch (e) { /* continue with the article's image */ }
  }
  if (!fajl && p.kep) {   // the photo matched to the address or name by commons_images.py
    const [f, a, l, u, m, r] = p.kep;
    return { src: `https://commons.wikimedia.org/wiki/Special:FilePath/${encodeURIComponent(f)}?width=800`,
             lap: `https://commons.wikimedia.org/wiki/File:${encodeURIComponent(f)}`, szerzo: a, licenc: l, licencUrl: u, mod: m, reszlet: r };
  }
  if (!fajl && wikiCikkek(p).length) {
    try { fajl = commonsFajl(await wikiKivonatLeker(wikiCikkek(p)[0])); } catch (e) { /* no image */ }
  }
  if (!fajl && p.hid && p.nev) {   // bridge: search Commons for its name (with several name variants, increasingly permissive)
    const szavak = (p.kep_keres && p.kep_keres.length ? p.kep_keres : [p.nev]).slice(0, 6);
    const kerdesek = [];
    for (const sz of szavak) kerdesek.push(sz + ' Budapest', sz);
    for (const q of kerdesek) {
      try {
        const sj = await (await fetch('https://commons.wikimedia.org/w/api.php?action=query&format=json&origin=*&generator=search&gsrnamespace=6&gsrlimit=20'
          + '&gsrsearch=' + encodeURIComponent(q) + '&prop=imageinfo&iiprop=url|mime|size')).json();
        const lista = Object.values((sj.query && sj.query.pages) || {}).sort((x, y) => (x.index || 0) - (y.index || 0))
          .filter(r => r.imageinfo && r.imageinfo[0] && /jpeg|png/.test(r.imageinfo[0].mime) && r.imageinfo[0].width >= 640);
        const jo = lista.find(r => r.imageinfo[0].width >= r.imageinfo[0].height) || lista[0];
        if (jo) { fajl = jo.title.replace(/^File:/, '').replace(/ /g, '_'); break; }
      } catch (e) { /* continue with the next search */ }
    }
  }
  if (!fajl) return null;
  const url = 'https://commons.wikimedia.org/w/api.php?action=query&format=json&origin=*&prop=imageinfo&iiprop=url|extmetadata&iiurlwidth=800'
    + '&titles=' + encodeURIComponent('File:' + fajl);
  const j = await (await fetch(url)).json();
  const lap = Object.values((j.query && j.query.pages) || {})[0];
  const ii = lap && lap.imageinfo && lap.imageinfo[0];
  if (!ii || !ii.thumburl) return null;
  const em = ii.extmetadata || {};
  const szoveg = h => h ? new DOMParser().parseFromString(String(h), 'text/html').body.textContent.trim() : '';
  return { src: ii.thumburl, lap: ii.descriptionurl, szerzo: szoveg(em.Artist && em.Artist.value).slice(0, 90),
           licenc: szoveg(em.LicenseShortName && em.LicenseShortName.value), licencUrl: em.LicenseUrl && em.LicenseUrl.value };
}
function kepBetolt(gid) {
  const p = epuletek[gid], hely = kartya.querySelector('.kep');
  if (!p || !hely) return;
  if (!kepGyorsitotar.has(gid)) kepGyorsitotar.set(gid, kepLeker(p).catch(() => null));
  kepGyorsitotar.get(gid).then(k => {
    if (!k || rogzitettGid !== gid || !kartya.contains(hely)) return;
    const link = (u, sz) => u ? `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(sz)}</a>` : esc(sz);
    if (k.forras === 'oeny') {
      const oenyKep = (i) => {
        const az = k.azonositok[i];
        const lap = `https://www.oeny.hu/oeny/eorok/public/monument/${az}`;
        hely.innerHTML = `<a href="${esc(lap)}" target="_blank" rel="noopener"><img alt="${esc(p.nev || p.cim || '')}" loading="lazy" referrerpolicy="no-referrer" `
          + `src="https://www.oeny.hu/oeny/eorok/public/api/v1/ovnyr/muemlek/${az}/kep"></a>`
          + `<small>${t('kep_forras')}: <a href="${esc(lap)}" target="_blank" rel="noopener">E-Örökség</a> (oeny.hu; a fotó jogai a megjelölt jogtulajdonosé)</small>`;
        const kep = hely.querySelector('img');
        kep.addEventListener('load', () => kartyaHelye(parseFloat(kartya.style.left) - 18, parseFloat(kartya.style.top) - 18));
        kep.addEventListener('error', () => {
          if (i + 1 < k.azonositok.length) { oenyKep(i + 1); return; }
          kepGyorsitotar.set(gid, kepLeker(Object.assign({}, p, { oeny_kep_hibas: true })).catch(() => null));   // none of the OENY images loaded: the other sources follow
          hely.hidden = true;
          kepBetolt(gid);
        });
      };
      oenyKep(0);
      hely.hidden = false;
      return;
    }
    if (k.forras === 'url') {
      let host = '';
      try { host = new URL(k.lap).hostname.replace(/^www\./, ''); } catch (e) { host = ''; }
      hely.innerHTML = `<a href="${esc(k.lap)}" target="_blank" rel="noopener noreferrer"><img alt="${esc(p.nev || p.cim || '')}" src="${esc(k.src)}" referrerpolicy="no-referrer"></a>`
        + `<small>${t('kep_forras')}: ${esc(host || 'link')}</small>`;
      const kep = hely.querySelector('img');
      kep.addEventListener('load', () => kartyaHelye(parseFloat(kartya.style.left) - 18, parseFloat(kartya.style.top) - 18));
      kep.addEventListener('error', () => {      // if the given photo cannot be loaded, the other sources follow
        kepGyorsitotar.set(gid, kepLeker(Object.assign({}, p, { kep_url_hibas: true })).catch(() => null));
        hely.hidden = true;
        kepBetolt(gid);
      });
      hely.hidden = false;
      return;
    }
    if (k.forras === 'legenda') {
      hely.innerHTML = `<a href="${esc(k.lap)}" target="_blank" rel="noopener"><img alt="${esc(p.nev || p.cim || '')}" src="${esc(k.src)}" referrerpolicy="no-referrer"></a>`
        + `<small>${t('kep_forras')}: <a href="${esc(k.lap)}" target="_blank" rel="noopener">Budapest Legenda</a> (budapestlegenda.hu)</small>`;
      const kep = hely.querySelector('img');
      kep.addEventListener('load', () => kartyaHelye(parseFloat(kartya.style.left) - 18, parseFloat(kartya.style.top) - 18));
      kep.addEventListener('error', () => {      // if the Legenda image cannot be loaded, the Commons image follows
        kepGyorsitotar.set(gid, kepLeker(Object.assign({}, p, { legenda_kep: '' })).catch(() => null));
        hely.hidden = true;
        kepBetolt(gid);
      });
      hely.hidden = false;
      return;
    }
    if (k.forras === 'bp100') {
      hely.innerHTML = `<a href="${esc(k.lap)}" target="_blank" rel="noopener"><img alt="${esc(p.nev || p.cim || '')}" src="${esc(k.src)}" referrerpolicy="no-referrer"></a>`
        + `<small>${t('kep_forras')}: ${k.foto ? '© ' + esc(k.foto) + ' · ' : ''}<a href="${esc(k.lap)}" target="_blank" rel="noopener">Budapest100</a> (budapest100.hu)</small>`;
      const kep = hely.querySelector('img');
      kep.addEventListener('load', () => kartyaHelye(parseFloat(kartya.style.left) - 18, parseFloat(kartya.style.top) - 18));
      kep.addEventListener('error', () => {      // if the Budapest100 image cannot be loaded, the Commons image follows
        kepGyorsitotar.set(gid, kepLeker(Object.assign({}, p, { budapest100_kep: '' })).catch(() => null));
        hely.hidden = true;
        kepBetolt(gid);
      });
      hely.hidden = false;
      return;
    }
    hely.innerHTML = `<a href="${esc(k.lap)}" target="_blank" rel="noopener"><img alt="${esc(p.nev || p.cim || '')}" src="${esc(k.src)}"></a>`
      + `<small>${t('kep_forras')}: ${esc(k.szerzo || 'Wikimedia Commons')} · ${link(k.licencUrl, k.licenc || 'Wikimedia Commons')} · `
      + `<a href="${esc(k.lap)}" target="_blank" rel="noopener">Wikimedia Commons</a>`
      + (k.mod ? ` <em>(${t({cim: 'kep_cim', hely: 'kep_hely', wd: 'kep_wd', kat: 'kep_kat'}[k.mod] || 'kep_nev')}${k.reszlet ? '; ' + t('kep_reszlet') : ''})</em>` : '') + `</small>`;
    hely.hidden = false;
    hely.querySelector('img').addEventListener('load', () => kartyaHelye(parseFloat(kartya.style.left) - 18, parseFloat(kartya.style.top) - 18));
  });
}

const kartya = document.getElementById('kartya');
// The pinned card stays on screen even if it grows later (image, Wikipedia extract, Edit button load) or the window is resized;
// if it is taller than the window, it scrolls thanks to CSS max-height + overflow.
function kartyaBent() {
  if (!kartya.hidden && kartya.classList.contains('rogzitett') && kartya.style.left)
    kartyaHelye(parseFloat(kartya.style.left) - 18, parseFloat(kartya.style.top) - 18);
}
if (window.ResizeObserver) new ResizeObserver(kartyaBent).observe(kartya);
addEventListener('resize', kartyaBent);
let rogzitettGid = -1, hoverGid = -1, pointer = null, dragging = false, downAt = null;
const nincsEger = window.matchMedia('(hover: none)');

function kartyaHelye(x, y) {
  const r = kartya.getBoundingClientRect();
  kartya.style.left = Math.max(12, Math.min(x + 18, innerWidth - r.width - 12)) + 'px';
  kartya.style.top = Math.max(12, Math.min(y + 18, innerHeight - r.height - 12)) + 'px';
}
// The pinned card sits in the right third of the screen so that it does not cover the selected building.
function kartyaJobbSzel() {
  const ty = document.querySelector('.tally');
  return ty ? Math.round(ty.getBoundingClientRect().left) : innerWidth - 24;
}
function kartyaJobbra() {
  if (innerWidth <= 700) return;
  const w = kartya.offsetWidth || 400, top = 150;
  kartya.style.left = Math.max(12, kartyaJobbSzel() - w) + 'px';   // its right edge coincides with the left edge of the year area (top right)
  kartya.style.top = top + 'px';
  kartya.style.maxHeight = Math.max(240, innerHeight - top - 110) + 'px';
}
// If the clicked building would fall under the card, the view is shifted sideways so that the building ends up in the middle of the free area.
let eltolAz = 0;
function nezetEltol(kx) {
  if (innerWidth <= 700) return;
  const w = kartya.offsetWidth || 400, balra = kartyaJobbSzel() - w;
  if (kx < balra - 60) return;
  const cel = (360 + balra) / 2, dpx = kx - cel;
  const dist = camera.position.distanceTo(controls.target);
  const szel = 2 * dist * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * (innerWidth / innerHeight);
  const jobb = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 0).setY(0).normalize().multiplyScalar(dpx / innerWidth * szel);
  const c0 = camera.position.clone(), t0 = controls.target.clone(), kezd = performance.now(), az = ++eltolAz;
  const lep = now => {
    if (az !== eltolAz) return;
    const u = Math.min(1, (now - kezd) / 500), e = u * u * (3 - 2 * u);
    camera.position.copy(c0).addScaledVector(jobb, e);
    controls.target.copy(t0).addScaledVector(jobb, e);
    if (u < 1) requestAnimationFrame(lep);
  };
  requestAnimationFrame(lep);
}
function bezar() {
  hazKiemel(null);
  rogzitettGid = -1;
  uniforms.uSelected.value = -1;
  uniforms.uSelGrp.value = 0;
  kartya.hidden = true;
  kartya.classList.remove('rogzitett');
}
let hazKiem = false;
function hazKiemel(gid) {      // on the Styles tab everything except the selected key building is white; gid === null: end
  if (gid === null) { if (hazKiem) { hazKiem = false; archSzuro = null; frissitKiemelest(); } return; }
  const p = epuletek[gid], ad = adatlapAdat(p), g = new Set(archGidIndex().get((p.osm_tipus === 'relation' ? 'r' : 'w') + p.id) || [gid]);
  if (ad && ad.kiemel) epuletek.forEach((q, i) => {      // a whole zone / estate is highlighted together (adatlapok.json: kiemel.zona = zone id, kiemel.wikipedia = part of the Wikipedia label)
    if (q && !q.hid && !(ad.kiemel.kiveve || []).includes((q.osm_tipus || 'way') + '/' + q.id) && ((ad.kiemel.zona && q.zona_azon === ad.kiemel.zona) || (ad.kiemel.wikipedia && String(q.wikipedia || '').includes(ad.kiemel.wikipedia)))) g.add(i);
  });
  archSzuro = new Set(g); archZonaAzon = new Set(); hazKiem = true;
  frissitKiemelest();
}
function rogzit(gid, x, y) {
  kartya.style.height = ''; kartya.style.maxHeight = '';
  rogzitettGid = gid;
  hoverGid = -1;
  uniforms.uSelected.value = gid;
  uniforms.uSelGrp.value = grpIdx[gid] || 0;
  kartya.classList.add('rogzitett');
  kartya.innerHTML = kartyaHtml(epuletek[gid], true);
  kartya.hidden = false;
  kartya.querySelector('.kartya-bezar').addEventListener('click', bezar);
  kartyaHelye(x, y);
  kartyaJobbra();
  wikiBetolt(gid);
  if (galeriaDiak(epuletek[gid]).length) galeriaBetolt(gid); else kepBetolt(gid);
  szerkGomb(gid);
  if (!archKiv && adatlapAdat(epuletek[gid]) && !document.getElementById('nez-arch').hidden) hazKiemel(gid);
  else if (hazKiem) hazKiemel(null);
}
function mutat(gid, x, y) {
  if (rogzitettGid >= 0 || nincsEger.matches) return;
  if (gid < 0 || !epuletek[gid]) { kartya.hidden = true; hoverGid = -1; return; }
  if (gid !== hoverGid || kartya.hidden) {
    hoverGid = gid;
    kartya.classList.remove('rogzitett');
    kartya.innerHTML = kartyaHtml(epuletek[gid], false);
    kartya.hidden = false;
  }
  kartyaHelye(x, y);
}
addEventListener('keydown', e => { if (e.key === 'Escape') bezar(); });
canvas.addEventListener('pointermove', e => { pointer = [e.clientX, e.clientY]; });
canvas.addEventListener('pointerdown', e => {
  dragging = true; downAt = [e.clientX, e.clientY];
  if (rogzitettGid < 0) kartya.hidden = true;
});
canvas.addEventListener('pointerup', e => {
  dragging = false;
  if (!downAt || Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 5) return;
  if (alkotasMod) { alkotasPont(e.clientX, e.clientY); return; }
  const gid = pick(e.clientX, e.clientY);
  if (gid < 0 || !epuletek[gid] || gid === rogzitettGid) { bezar(); return; }
  rogzit(gid, e.clientX, e.clientY);
  nezetEltol(e.clientX);
});
canvas.addEventListener('pointerleave', () => {
  pointer = null;
  if (rogzitettGid < 0) kartya.hidden = true;
  uniforms.uHover.value = -1;
  uniforms.uHoverGrp.value = 0;
});

// ---------- Left panel: mode, legend, highlighting ----------
const maskTarget = periods.map(() => 1);
function renderLegend() {
  document.getElementById('legend').innerHTML = periods.map((p, i) =>
    `<label><input type="checkbox" data-i="${i}" ${maskTarget[i] ? 'checked' : ''}><i style="--c:${p.color}"></i><span>${esc(korNev(i))}</span></label>`).join('');
  document.querySelectorAll('#legend input').forEach(c => c.addEventListener('change', () => {
    maskTarget[+c.dataset.i] = c.checked ? 1 : 0;
    uniforms.uMask.value = maskTarget;
    drawHist();
  }));
}
function setMode(m) {
  uniforms.uMode.value = m;
  const mag = document.getElementById('magassag-reteg');
  if (mag) mag.checked = m === MODE.floors;
  document.getElementById('legend').hidden = m !== MODE.period;
  const lc = document.querySelector('#nez-period strong'); if (lc) lc.hidden = m !== MODE.period;
  document.getElementById('szintlegend').hidden = m !== MODE.floors;
  frissitKiemelest();   // bridges have no storey count: they are grey in storeys mode
}
document.getElementById('magassag-reteg').addEventListener('change', e => setMode(e.target.checked ? MODE.floors : MODE.period));
// Era / Layers view at the top of the panel
var aktNezet = null;
function setNezet(n) {
  if (aktNezet !== n) {      // when switching tabs, the previous tab's filter (architect, style, estate) must not stay on the map
    aktNezet = n;
    archSzuro = null; archZonaAzon = new Set(); hazKiem = false; epAktiv = null; epUnio = false; clearTimeout(epUnioIdo);
    epPopupTok++; archPopupTok++;
    const pp0 = document.getElementById('arch-popup'); if (pp0) pp0.hidden = true;
    archLepteto(null);
  }
  document.querySelectorAll('.nez button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.nez === n)));
  document.getElementById('nez-period').hidden = n !== 'period';
  ['vedett', 'magassag', 'lakotelep'].forEach(r => { document.getElementById('nez-' + r).hidden = n !== r; });
  // the three layers are separate tabs: the selected tab switches on its own layer and switches the others off
  document.getElementById('vedett').checked = n === 'vedett';
  document.getElementById('lakotelep').checked = n === 'lakotelep';
  if (n !== 'lakotelep') lakKiv = null;
  if (n === 'lakotelep') { lakotelepInfoRender(); lakFrissit(); }
  if (n === 'vedett') vedSzuroFrissit();
  setMode(n === 'magassag' ? MODE.floors : MODE.period);      // also calls frissitKiemelest
  document.getElementById('nez-arch').hidden = n !== 'arch';
  document.getElementById('nez-epitesz').hidden = n !== 'epitesz';
  archNezet(n === 'arch');
  epiteszNezet(n === 'epitesz');
}
document.querySelectorAll('.nez button').forEach(b => b.addEventListener('click', () => setNezet(b.dataset.nez)));

// ---------- Architect search: eras -> architects -> data sheet (Wikipedia) + their buildings in colour, the rest white ----------
const archWikiGyorsitotar = new Map();
async function archBetolt() {
  if (!archAdat) {
    try { archAdat = await (await fetch('epitesz.json')).json(); } catch { archAdat = []; }
    await adatlapBe;
    archKiemeltEpit();
  }
  return archAdat;
}
// The Styles panel's "Key architects" list comes from the styles table (adatlapok.json "tabla", source: forras/budapest_stilusok_final.xlsx).
// Whoever epitesz.json already knows (Wikipedia articles, buildings) uses that record; for the others a simple record is created (searched by the Designer field).
function archKiemeltEpit() {
  const tabla = adatlapok && adatlapok.tabla;
  if (!tabla) return;
  const f = x => String(x || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
  const idx = new Map();
  archAdat.forEach(k => (k.epitesz || []).forEach(e => [e.nev, ...(e.m || [])].forEach(n => { if (!idx.has(f(n))) idx.set(f(n), e); })));
  archAdat.forEach(k => {
    const sor = tabla[k.nev_hu];
    if (!sor) return;
    k.kiemelt = sor.tervezok.map(nev => {
      const van = idx.get(f(nev));
      if (van) return van;
      const kot = nev.replace(/-\S+/, '');      // e.g. "Neuschloss-Knüsli Kornél" appears in the data as "Neuschloss Kornél"
      return { nev, l: '', w: [], m: kot !== nev ? [nev, kot] : [nev], e: [] };
    });
  });
}
function archGidIndex() {
  if (archGidek) return archGidek;
  archGidek = new Map();
  epuletek.forEach((p, gid) => {
    if (!p || p.hid) return;
    const k = (p.osm_tipus === 'relation' ? 'r' : 'w') + p.id;
    if (!archGidek.has(k)) archGidek.set(k, []);
    archGidek.get(k).push(gid);
  });
  return archGidek;
}
function archWiki(nev0) {
  const pontos = String(nev0).startsWith('='), nev = pontos ? String(nev0).slice(1) : nev0;      // "=Title": exact article title (not an architect): no architect filtering or search
  if (!archWikiGyorsitotar.has(nev0)) {
    archWikiGyorsitotar.set(nev0, (async () => {
      const sum = async cim => {
        const r = await fetch(`https://hu.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(cim.replace(/ /g, '_'))}`, { headers: { Accept: 'application/json' } });
        if (!r.ok) throw new Error(r.status);
        return r.json();
      };
      const jo = j => j && j.type === 'standard' && (pontos || /építész/i.test((j.description || '') + ' ' + String(j.extract || '').slice(0, 500)));
      try { const j = await sum(nev); if (jo(j)) return j; } catch { /* search */ }
      if (pontos) throw new Error('nincs ilyen cikk');
      const s = await (await fetch(`https://hu.wikipedia.org/w/api.php?action=query&list=search&srsearch=${encodeURIComponent('"' + nev + '" építész')}&srlimit=1&format=json&origin=*`)).json();
      const h = s.query && s.query.search && s.query.search[0];
      if (!h) throw new Error('nincs találat');
      return sum(h.title);
    })());
  }
  return archWikiGyorsitotar.get(nev0);
}
// the architect tab's own era classification (from epitesz.json), independent of the map's eras
const archKorNev = k => (NYELV === 'en' ? (k.en || k.hu) : (k.hu || k.korszak));
async function archRender() {
  const lista = document.getElementById('arch-lista');
  if (!lista || lista.dataset.kesz) return;
  const adat = await archBetolt();
  await adatlapBe;
  lista.dataset.kesz = '1';
  const hazak = k => ((adatlapok && adatlapok.stilusok && adatlapok.stilusok[k.nev_hu]) || []);
  lista.innerHTML = adat.length ? adat.map((k, i) =>
    `<div class="arch-kor"><button type="button" class="arch-kor-gomb" data-i="${i}" aria-expanded="false"><i style="--c:${k.szin || '#999'}"></i><span>${esc(archKorNev(k))}</span></button>`
    + `<ul hidden>${hazak(k).length ? `<li class="arch-haz-fej">${NYELV === 'en' ? 'Defining buildings' : 'Meghatározó épületek'}</li>` + hazak(k).map(h => `<li><button type="button" class="arch-haz" data-azon="${esc(h.azon)}">${esc(h.nev)}</button></li>`).join('') + '' : ''}<li class="arch-haz-fej">${NYELV === 'en' ? 'Defining architects' : 'Meghatározó építészek'}</li>${(k.kiemelt || k.epitesz).map((e, j) => `<li><button type="button" data-i="${i}" data-j="${j}">${esc(e.nev)}<small>${archSzam(e)}</small></button></li>`).join('')}</ul></div>`).join('')
    : `<p>${esc(t('arch_ures'))}</p>`;
}
function archNyelvFrissit() {
  const lista = document.getElementById('arch-lista');
  if (!lista || !lista.dataset.kesz) return;
  lista.querySelectorAll('.arch-kor-gomb').forEach(b => { b.querySelector('span').textContent = archKorNev(archAdat[+b.dataset.i]); });
}
function archNezet(be) {
  if (be) { archRender().then(() => { if (!document.getElementById('nez-arch').hidden) archKivalaszt(archKiv); }); return; }
  archLepteto(null);
  hazKiem = false;
  const pp = document.getElementById('arch-popup'); if (pp) pp.hidden = true;
  if (archSzuro) { archSzuro = null; frissitKiemelest(); }
}
function archKivalaszt(kiv) {
  archKiv = kiv;
  hazKiem = false;
  document.querySelectorAll('#arch-lista li button').forEach(b => b.classList.toggle('aktiv', !!kiv && +b.dataset.i === kiv.i && +b.dataset.j === kiv.j));
  const lap = document.getElementById('arch-adatlap');
  if (!kiv || !archAdat) { archSzuro = null; archLepteto(null); if (lap) lap.hidden = true; const pp = document.getElementById('arch-popup'); if (pp) pp.hidden = true; frissitKiemelest(); return; }
  const e = (archAdat[kiv.i].kiemelt || archAdat[kiv.i].epitesz)[kiv.j], { halmaz, zk } = archHalmaz(e);
  archZonaAzon = new Set(zk.map(z => z.azon));
  archSzuro = halmaz;
  frissitKiemelest();
  archLepteto(halmaz);
  lap.hidden = true; lap.innerHTML = '';   // the name and the building count are shown in the popup, not at the bottom of the list
  archPopupMutat(e, kiv);
}
// ---------- Designer assigned to a zone (e.g. housing estate): every house of the estate belongs to the architect, but counts as one project in the counter ----------
const archFold = x => String(x || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
const archNevek = e => ((e.m && e.m.length) ? e.m : (/^(id|ifj)\./i.test(e.nev) ? [] : [e.nev])).map(archFold).filter(Boolean);
let zonaTervIdx = null;
const EP_PROJEKTEK = [
  { azon: 'projekt:kaposztasmegyer', nev: 'Káposztásmegyeri lakótelep', re: /^Káposztásmegyer/i },
  { azon: 'projekt:len-pinceszer', nev: 'Len utcai és Pinceszer utcai lakóépületek', cim: /(^|;\s*)(Len|Pinceszer) (utca|u\.)/i },   // by zona_nev (re) or address (cim)
];
function zonaTerv() {
  if (zonaTervIdx) return zonaTervIdx;
  const m = new Map();
  epuletek.forEach((p, gid) => {
    if (!p || p.hid || !p.zona_tervezo || !p.zona_azon) return;
    let z = m.get(p.zona_azon);
    if (!z) m.set(p.zona_azon, z = { azon: p.zona_azon, nev: p.zona_tervezo_nev || p.zona_azon, tv: archFold(p.zona_tervezo), gids: [] });
    z.gids.push(gid);
  });
  // Estates whose houses carry only the estate name (zona_nev) and have no designer zone: in the architect list they count as one project
  EP_PROJEKTEK.forEach(pr => {
    const gids = [];
    epuletek.forEach((p, gid) => {
      if (!p || p.hid || p.zona_azon || !((pr.re && pr.re.test(p.zona_nev || '')) || (pr.cim && pr.cim.test(String(p.cim || ''))))) return;
      p.zona_azon = pr.azon; gids.push(gid);
    });
    if (gids.length) m.set(pr.azon, { azon: pr.azon, nev: pr.nev, tv: '', gids });
  });
  return zonaTervIdx = m;
}
function archZonak(e) {
  const nv = archNevek(e);
  return nv.length ? [...zonaTerv().values()].filter(z => nv.some(n => z.tv.includes(n))) : [];
}
// The set of an architect's highlighted buildings: the `e` list + those matching the Designer field (manual, paired, building parts) + the houses of the zones.
const archFoldGyorsitotar = new Map();
const archFoldC = x => { let v = archFoldGyorsitotar.get(x); if (v === undefined) { v = archFold(x); archFoldGyorsitotar.set(x, v); } return v; };
function archHalmaz(e) {
  const idx = archGidIndex(), halmaz = new Set(), nevek = archNevek(e);
  for (const k of e.e) { const g = idx.get(k); if (g) g.forEach(x => halmaz.add(x)); }
  if (nevek.length) epuletek.forEach((p, gid) => {
    if (!p || p.hid || !p.tervezo || halmaz.has(gid)) return;
    const tv = archFoldC(p.tervezo);
    if (nevek.some(n => tv.includes(n))) halmaz.add(gid);
  });
  const zk = archZonak(e);
  zk.forEach(z => z.gids.forEach(g => halmaz.add(g)));
  return { halmaz, zk };
}
// The stepper's items: individual houses (parts of the same house count as one) + each estate as one item. The number beside the name and the dropdown use the same list.
function archTetelek(halmaz, zonaAzon) {
  const lista = [], lattuk = new Set();
  halmaz.forEach(gid => {
    const p = epuletek[gid];
    if (!p || p.hid && !p.lat) return;
    if (p.zona_azon && zonaAzon.has(p.zona_azon)) return;
    const k = (p.osm_tipus || 'way') + p.id;
    if (lattuk.has(k) || p.lat == null || p.lon == null) return;
    lattuk.add(k);
    const cim = p.cim ? String(p.cim).split(';')[0] : '';
    const nev = p.nev || p.lechner_nev || p.nev_kozepulet || cim || p.zona_nev || t('nevtelen');
    const cimke = nev + (p.nev && cim ? ' – ' + cim : '') + (p.ev ? ' (' + p.ev + ')' : '');
    const dx = (p.lon - LON0) * COSLAT * 111320, dz = (p.lat - LAT0) * 110574;
    if (lista.some(y => y.cimke === cimke && Math.hypot(y.dx - dx, y.dz - dz) < 150)) return;
    lista.push({ gid, ev: +p.ev || 0, cimke, dx, dz });
  });
  for (const z of zonaTerv().values()) {
    if (!zonaAzon.has(z.azon)) continue;
    const gs = z.gids.filter(g => halmaz.has(g));      // only the highlighted houses (those belonging to the architect)
    if (!gs.length) continue;
    const ps = gs.map(g => epuletek[g]), la = ps.reduce((a, p) => a + p.lat, 0) / ps.length, lo = ps.reduce((a, p) => a + p.lon, 0) / ps.length;
    let jo = gs[0], tav = Infinity;
    gs.forEach((g, i) => { const d = (ps[i].lat - la) ** 2 + (ps[i].lon - lo) ** 2; if (d < tav) { tav = d; jo = g; } });
    const kp = epuletek[jo], ev = kp.ev ? ' (' + kp.ev + ')' : '';
    lista.push({ gid: jo, ev: +kp.ev || 0, cimke: z.nev + ' – ' + t('zona_telep') + ' · ' + gs.length + ' ' + t('zona_haz') + ev });
  }
  lista.sort((a, b) => (a.ev || 9999) - (b.ev || 9999) || a.cimke.localeCompare(b.cimke, 'hu'));
  return lista;
}
function archSzam(e) {
  const { halmaz, zk } = archHalmaz(e);
  return archTetelek(halmaz, new Set(zk.map(z => z.azon))).length;
}
// ---------- Bottom stepper: the selected architect's buildings one by one (dropdown + previous/next); the camera zooms in, the data sheet opens ----------
var archEpLista = [], archEpIdx = -1, archZonaAzon = new Set();
function archLepHely() {
  let el = document.getElementById('arch-lep');
  if (!el) {
    el = document.createElement('div');
    el.id = 'arch-lep'; el.className = 'arch-lep'; el.hidden = true;
    el.innerHTML = '<button type="button" class="el" aria-label="Előző épület">‹</button><select aria-label="Az építész épületei"></select><span class="sz"></span><button type="button" class="kov" aria-label="Következő épület">›</button>';
    document.body.appendChild(el);
    const sel = el.querySelector('select');
    sel.addEventListener('change', () => archLepj(+sel.value));
    el.querySelector('.el').addEventListener('click', () => archLepj(archEpIdx <= 0 ? archEpLista.length - 1 : archEpIdx - 1));
    el.querySelector('.kov').addEventListener('click', () => archLepj(archEpIdx + 1 >= archEpLista.length ? 0 : archEpIdx + 1));
  }
  return el;
}
function archLepteto(halmaz) {
  const el = archLepHely(), sel = el.querySelector('select');
  archEpLista = []; archEpIdx = -1;
  if (halmaz && halmaz.size) archEpLista = archTetelek(halmaz, archZonaAzon);
  el.hidden = !archEpLista.length;
  archLepIgazit();
  sel.innerHTML = '<option value="-1">Épület kiválasztása…</option>' + archEpLista.map((x, i) => `<option value="${i}">${esc(x.cimke)}</option>`).join('');
  sel.value = '-1';
  archLepFrissit();
}
// the stepper sits below the two panels (architect list + data sheet), across their full width
function archLepIgazit() {
  const el = document.getElementById('arch-lep'), pn = document.getElementById('panel');
  if (!el || !pn) return;
  if (innerWidth <= 700) { el.style.cssText = ''; return; }
  const r = pn.getBoundingClientRect(), pp = document.getElementById('arch-popup');
  const jobb = pp && !pp.hidden ? pp.getBoundingClientRect().right : r.right;
  Object.assign(el.style, { left: Math.round(r.left) + 'px', top: Math.round(r.bottom + 12) + 'px', bottom: 'auto', width: Math.round(jobb - r.left) + 'px', transform: 'none', maxWidth: 'none', boxSizing: 'border-box' });
  Object.assign(el.querySelector('select').style, { flex: '1 1 0', width: '0', minWidth: '0' });
}
addEventListener('resize', archLepIgazit);
function archLepFrissit() {
  archLepIgazit();
  const el = document.getElementById('arch-lep'); if (!el) return;
  el.querySelector('select').value = String(archEpIdx);
  el.querySelector('.sz').textContent = archEpLista.length ? (archEpIdx >= 0 ? archEpIdx + 1 : '–') + ' / ' + archEpLista.length : '';
}
function mobilMenuZar() {
  epPopupTok++; archPopupTok++;
  const pp = document.getElementById('arch-popup'); if (pp) pp.hidden = true;
  const fp = document.getElementById('panel'); if (fp) fp.classList.remove('mobil-nyitva');
  const rg = document.getElementById('reteg-gomb'); if (rg) rg.setAttribute('aria-pressed', 'false');
}
function archLepj(i) {
  if (i < 0 || i >= archEpLista.length) { archEpIdx = -1; archLepFrissit(); return; }
  archEpIdx = i; archLepFrissit();
  if (innerWidth <= 700) mobilMenuZar();      // mobile: the architect/style card and the main panel close, the filter stays; the map is visible below the building card
  const x = archEpLista[i];
  const pp = document.getElementById('arch-popup');
  // the card opens to the right of the house at the screen centre; its top and bottom follow the architect's data sheet (left panel)
  repulj(x.gid, innerWidth / 2 + 130, () => {
    const pn = document.getElementById('panel');
    if (!pn || innerWidth <= 700) return;
    const r = pn.getBoundingClientRect();
    Object.assign(kartya.style, { top: Math.round(r.top) + 'px', height: Math.round(r.height) + 'px', maxHeight: Math.round(r.height) + 'px' });
  });
}
// The full text + lead image of a Wikipedia article (MediaWiki API, in one query); without the trailing notes/references sections
const archCikkGyorsitotar = new Map();
function archFejezet(szoveg, fej) {      // one section of the article (with its subsections); without the section title
  const sorok = String(szoveg || '').split('\n'), fold = s => s.trim().toLowerCase();
  const fejSor = s => { const m = /^(=+)\s*(.+?)\s*=+$/.exec(s.trim()); return m ? { szint: m[1].length, cim: m[2] } : null; };
  const i = sorok.findIndex(s => { const h = fejSor(s); return h && fold(h.cim) === fold(fej); });
  if (i < 0) return szoveg;
  const szint = fejSor(sorok[i]).szint, ki = [];
  for (let j = i + 1; j < sorok.length; j++) { const h = fejSor(sorok[j]); if (h && h.szint <= szint) break; ki.push(sorok[j]); }
  return ki.join('\n');
}
function archCikk(nev) {      // "Title" or "Title#Section": only that section is shown
  if (!archCikkGyorsitotar.has(nev)) {
    const [cimNev, fejezet] = String(nev).split('#');
    archCikkGyorsitotar.set(nev, archWiki(cimNev).then(async j => {
      const u = `https://hu.wikipedia.org/w/api.php?action=query&prop=extracts%7Cpageimages&explaintext=1&exsectionformat=wiki&piprop=thumbnail&pithumbsize=480&redirects=1&format=json&origin=*&titles=${encodeURIComponent(j.title)}`;
      let szoveg = '', kep = (j.thumbnail && j.thumbnail.source) || '';
      try {
        const r = await (await fetch(u)).json(), lap = Object.values(r.query.pages)[0];
        szoveg = String(lap.extract || '');
        if (lap.thumbnail && lap.thumbnail.source) kep = lap.thumbnail.source;
      } catch { /* the extract stays */ }
      if (!szoveg.trim()) szoveg = String(j.extract || '');
      if (fejezet) szoveg = archFejezet(szoveg, fejezet);
      let url = (j.content_urls && j.content_urls.desktop && j.content_urls.desktop.page) || `https://hu.wikipedia.org/wiki/${encodeURIComponent(String(j.title).replace(/ /g, '_'))}`;
      if (fejezet) url += '#' + encodeURIComponent(fejezet.replace(/ /g, '_'));
      return { cim: fejezet ? `${j.title} – ${fejezet}` : j.title, leiras: j.description || '', szoveg, kep, url };
    }));
  }
  return archCikkGyorsitotar.get(nev);
}
const ARCH_ELDOB = /^(Jegyzetek|Források|Forrás|Hivatkozások|Külső hivatkozások|Irodalom|Lásd még|Megjegyzések|Képtár|Díjak és elismerések? ?\(.*\))$/i;
function archSzovegHtml(szoveg) {
  let ki = '', eldob = false;
  for (const sor of szoveg.split(/\n+/)) {
    const m = /^(=+)\s*(.+?)\s*=+$/.exec(sor.trim());
    if (m) { eldob = ARCH_ELDOB.test(m[2]); if (!eldob) ki += `<h4>${esc(m[2])}</h4>`; continue; }
    if (!eldob && sor.trim()) ki += `<p>${esc(sor.trim())}</p>`;
  }
  return ki;
}
function archPopupHely() {
  let el = document.getElementById('arch-popup');
  if (!el) {
    el = document.createElement('div');
    el.id = 'arch-popup'; el.className = 'arch-popup'; el.hidden = true;
    el.innerHTML = '<button type="button" class="arch-popup-bezar" aria-label="Bezár">×</button><div class="arch-popup-test"></div>';
    document.body.appendChild(el);
    el.querySelector('button').addEventListener('click', () => {
      if (!document.getElementById('nez-epitesz').hidden) { if (epAktiv) epiteszValaszt(epAktiv); el.hidden = true; kezdoRepules(); return; }   // Architects tab: closing also clears the selection
      archKivalaszt(null); kezdoRepules();
    });   // closing the data sheet also clears the filter, and the camera returns to the home view
    addEventListener('resize', () => archPopupIgazit(el));
  }
  return el;
}
// the window's height, width and top edge follow the left panel; it sits right next to it
function archPopupIgazit(el) {
  const panel = document.getElementById('panel');
  if (!panel || innerWidth <= 700) { el.style.cssText = ''; return; }
  const r = panel.getBoundingClientRect();
  Object.assign(el.style, { left: Math.round(r.right + 12) + 'px', top: Math.round(r.top) + 'px', height: Math.round(r.height) + 'px', width: Math.round(r.width) + 'px', bottom: 'auto' });
  if (typeof archLepIgazit === 'function') archLepIgazit();
}
function archPopupMutat(e, kiv) {
  const el = archPopupHely(), test = el.querySelector('.arch-popup-test');
  el.hidden = false; el.scrollTop = 0; archPopupIgazit(el);
  test.innerHTML = `<p class="arch-tolt">…</p>`;
  Promise.allSettled((e.nw ? [] : (e.w && e.w.length ? e.w : e.nev.split(' – '))).map(archCikk)).then(rs => {
    if (archKiv !== kiv || (e.tok && e.tok !== archPopupTok)) return;
    const jo = rs.filter(r => r.status === 'fulfilled').map(r => r.value);
    if (e.stilus) {      // style description: title, header (period), image, text (the Wikipedia article if there is one; otherwise the short description)
      const forras = c => `<small>${t('wiki_forras')}: <a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.cim)}</a> · <a href="https://creativecommons.org/licenses/by-sa/4.0/" target="_blank" rel="noopener">${t('wiki_licenc')}</a></small>`;
      const tisztit = s => String(s || '').replace(/Ez a szócikk[^.]*(?:Monarchia|földrajzi területeket)[^.]*\.\s*/g, '');      // the introductory note of the Wikipedia article is not relevant
      test.innerHTML = `<article class="arch-cikk arch-stilus"><h3>${esc(e.nev)}</h3>` + (e.ossz ? `<p class="arch-ossz" style="--sz:${esc(e.szin || '#999')}">${esc(e.ossz)}</p>` : '')
        + (jo.length ? jo.map(c => (c.kep ? `<img src="${esc(c.kep)}" alt="${esc(c.cim)}" referrerpolicy="no-referrer">` : '') + archSzovegHtml(tisztit(c.szoveg)) + forras(c)).join('')
          : `<p>${esc(e.l || '')}</p>`) + (e.f && e.f.length ? `<small>${NYELV === 'en' ? 'Sources' : 'Források'}: ` + e.f.map(x => `<a href="${esc(x.u)}" target="_blank" rel="noopener">${esc(x.n)}</a>`).join(' · ') + `</small>` : '') + `</article>`;
      return;
    }
    const jell = e.l ? `<div class="arch-jellemzes"><h3>${esc(e.nev)}</h3><p>${esc(e.l)}</p>` + (e.f && e.f.length ? `<small>${NYELV === 'en' ? 'Sources' : 'Források'}: ` + e.f.map(x => `<a href="${esc(x.u)}" target="_blank" rel="noopener">${esc(x.n)}</a>`).join(' · ') + '</small>' : '') + '</div>' : '';
    test.innerHTML = jell + (jo.length ? jo.map(c => `<article class="arch-cikk"><h3>${esc(c.cim)}</h3>`
      + (c.leiras ? `<p class="arch-leiras">${esc(String(c.leiras).replace(/^\s*\(\s*\d{3,4}\s*[–-]\s*(?:\d{3,4})?\s*\)\s*/, ''))}</p>` : '')
      + (c.kep ? `<img src="${esc(c.kep)}" alt="${esc(c.cim)}" referrerpolicy="no-referrer">` : '')
      + archSzovegHtml(c.szoveg)
      + `<small>${t('wiki_forras')}: <a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.cim)}</a> · <a href="https://creativecommons.org/licenses/by-sa/4.0/" target="_blank" rel="noopener">${t('wiki_licenc')}</a></small></article>`).join('')
      : (e.nw ? '' : `<p><small>${esc(t('arch_wiki_hiba'))}</small></p>`));
  });
}
// clicking the style's header shows the style's description in the popup (and its Wikipedia article, if any)
function archStilusMutat(k) {
  const en = NYELV === 'en';
  const elsoMondat = s => { const m = /^.*?[.!?](?=\s|$)/s.exec(String(s || '').trim()); return m ? m[0] : String(s || ''); };
  archPopupMutat({ stilus: true, szin: k.szin, ossz: en ? elsoMondat(k.d_en || k.d) : (k.ossz || elsoMondat(k.d)), nev: en ? (k.nev_en || k.nev_hu) : (k.nev_hu || k.hu), l: (en ? (k.d_en || k.d) : k.d) || '', w: k.w || [], f: k.f || [], nw: !(k.w && k.w.length) }, archKiv);
}
document.getElementById('arch-lista').addEventListener('click', ev => {
  const b = ev.target.closest('button');
  if (!b) return;
  if (b.classList.contains('arch-haz')) {       // key house: fly there, the card opens with the data sheet
    const [ot, oi] = b.dataset.azon.split('/');
    const gid = epuletek.findIndex(q => q && !q.hid && (q.osm_tipus || 'way') === ot && String(q.id) === oi);
    if (gid < 0) return;
    if (archKiv) archKivalaszt(null);
    const pp = document.getElementById('arch-popup'); if (pp) pp.hidden = true;
    repulj(gid);
    return;
  }
  if (b.classList.contains('arch-kor-gomb')) {
    const ul = b.nextElementSibling, nyit = ul.hidden;
    ul.hidden = !nyit;
    b.setAttribute('aria-expanded', String(nyit));
    if (archKiv) archKivalaszt(null);
    if (nyit) archStilusMutat(archAdat[+b.dataset.i]); else { const pp = document.getElementById('arch-popup'); if (pp) pp.hidden = true; }
    return;
  }
  const kiv = { i: +b.dataset.i, j: +b.dataset.j };
  archKivalaszt(archKiv && archKiv.i === kiv.i && archKiv.j === kiv.j ? null : kiv);
});

// Protected buildings: the number of OSM elements (not outlines). 'Monument' = every national-level protection (M, MJ, VK, MK, MJT); 'locally protected' = only under local protection (HV).
function vedettStat() {
  const lattuk = new Set();
  let ossz = 0, oeny = 0, helyi = 0;
  for (const p of epuletek) {
    if (!p || p.hid) continue;
    const k = (p.osm_tipus || 'way') + ':' + p.id;
    if (lattuk.has(k)) continue;
    lattuk.add(k);
    ossz++;
    if (p.vedettseg === 'HV') helyi++;
    else if (p.vedettseg) oeny++;
  }
  return { ossz, oeny, helyi };
}
let vedettAdat = null;
function vedettInfoRender() {
  const el = document.getElementById('vedett-info');
  if (!el) return;
  vedettAdat = vedettAdat || vedettStat();
  const { ossz, oeny, helyi } = vedettAdat, n = oeny + helyi, f = x => x.toLocaleString(NYELV === 'en' ? 'en' : 'hu-HU');
  el.innerHTML = `<p>${esc(t('vedett_leiras').replace('{n}', f(Math.max(10, Math.round(ossz / Math.max(n, 1) / 10) * 10))))}</p>`
    + `<dl><dt>${esc(t('vedett_muemlek'))}</dt><dd>${f(oeny)}</dd><dt>${esc(t('vedett_helyi'))}</dt><dd>${f(helyi)}</dd><dt>${esc(t('vedett_ossz'))}</dt><dd>${f(n)}</dd></dl>`;
}

function frissitKiemelest() {
  document.getElementById('vedett-info').hidden = !document.getElementById('vedett').checked;
  const lt = document.getElementById('lakotelep').checked;
  document.getElementById('lakotelep-info').hidden = !lt;
  const v = document.getElementById('vedett').checked, w = false, l = false, a = archSzuro;   // the Wikipedia and Lechner highlighting has been removed from the interface
  pickData.fill(0);
  epuletek.forEach((p, gid) => {
    if (p.hid) return;
    const be = (v && vedBe(p)) || (w && p.wikipedia && !p.wikipedia_zona) || (l && p.lechner_nev) || (lt && lakBe(p)) || (a && a.has(gid));
    if (be) pickData[gid * 4] = 255;
  });
  pickTex.needsUpdate = true;
  uniforms.uPickOn.value = (v || w || l || a || lt) ? 1 : 0;
  // bridges use a separate material: if a highlight filter is active and the bridge does not match it, they turn grey as well
  const szurt = v || w || l || a || lt, maq = uniforms.uMaquette.value, szintMod = uniforms.uMode.value !== MODE.period;
  for (const m of hidMeshek) {
    const p = hidRek(m);
    const be = p && ((v && vedBe(p)) || (w && p.wikipedia) || (l && p.lechner_nev) || (a && m.userData.rek != null && a.has(m.userData.rek)));
    const g = szintMod || (szurt && !be) ? 1 : 0;
    m.userData.draw.uniforms.uGrey.value = szintMod ? 1 : (szurt && !be ? 2 : 0);   // 1: storeys mode (grey), 2: filter (white)
  }
  for (const ln of hidVonalak) {
    const p = epuletek[EPULET_DB + ln.userData.hid];
    const be = p && ((v && vedBe(p)) || (w && p.wikipedia) || (l && p.lechner_nev));
    const c0 = ln.userData.szin || (ln.userData.szin = ln.material.color.clone());
    ln.material.color.copy(c0);
    if (szintMod) ln.material.color.lerp(maq, 0.78);
    else if (szurt && !be) ln.material.color.setRGB(1, 1, 1);
  }
}
// ---------- Protected buildings search (Protected tab) ----------
// filter: words of name/address/register number + Monument / Locally protected + district; on the map only the results stay coloured
var vedSzuro = null, vedGyorsitotar = new Map();
function vedAdat(p) {
  let a = vedGyorsitotar.get(p);
  if (!a) {
    const kod = p.vedettseg || '';
    a = { s: normal([p.nev, p.nev_kozepulet, p.cim, p.cim_tobb, p.muemlek_torzsszam].filter(Boolean).join(' | ')), m: !!kod && kod !== 'HV', h: kod === 'HV' || !!p.vedettseg_helyi };
    vedGyorsitotar.set(p, a);
  }
  return a;
}
function vedEgyezik(p) {
  if (!vedSzuro) return true;
  const a = vedAdat(p);
  if (!((vedSzuro.m && a.m) || (vedSzuro.h && a.h))) return false;
  if (vedSzuro.ker && keruletSzam(p) !== vedSzuro.ker) return false;
  return vedSzuro.talal.every(f => f(a.s));
}
function vedBe(p) { return !!(p.vedettseg || p.vedettseg_helyi) && vedEgyezik(p); }
function magInfoRender() {
  const el = document.getElementById('mag-info');
  if (!el) return;
  el.innerHTML = `<b>${esc(t('mag_cim'))}</b><ul>` + [1, 2, 3, 4, 5].map(i => `<li>${esc(t('mag_' + i))}</li>`).join('') + '</ul>';
}
function vedNyelv() {
  const q = document.getElementById('ved-ker'), sel = document.getElementById('ved-kerulet');
  if (!q || !sel) return;
  q.placeholder = t('ved_ph');
  const lq = document.getElementById('lak-ker'); if (lq) lq.placeholder = t('lak_ph');
  document.getElementById('ved-m-sz').textContent = t('vedett_muemlek');
  document.getElementById('ved-h-sz').textContent = t('vedett_helyi');
  const akt = sel.value;
  sel.innerHTML = `<option value="">${esc(t('ved_mind'))}</option>` + ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X', 'XI', 'XII', 'XIII', 'XIV', 'XV', 'XVI', 'XVII', 'XVIII', 'XIX', 'XX', 'XXI', 'XXII', 'XXIII'].map((r, i) => `<option value="${i + 1}">${r}. ${NYELV === 'en' ? 'district' : 'ker.'}</option>`).join('');
  sel.value = akt;
}
function vedSzuroFrissit() {
  const q = document.getElementById('ved-ker'); if (!q) return;
  const m = document.getElementById('ved-m').checked, h = document.getElementById('ved-h').checked, ker = +document.getElementById('ved-kerulet').value || 0;
  let szavak = normal(q.value).split(/[\s,;]+/).map(w => w.replace(/^[.,;:()]+|[.,;:()]+$/g, '')).filter(Boolean);
  const tisztabb = szavak.filter(w => !/^[1-2]\d{3}$/.test(w) && w !== 'budapest');
  if (tisztabb.length) szavak = tisztabb;
  vedSzuro = (m && h && !ker && !szavak.length) ? null : { m, h, ker, talal: szavak.map(keresoSzoPar) };
  const lattuk = new Set(), ki = [];
  epuletek.forEach((p, gid) => {
    if (!p || p.hid || !(p.vedettseg || p.vedettseg_helyi) || !vedEgyezik(p)) return;
    const k = (p.osm_tipus || 'way') + ':' + p.id;
    if (lattuk.has(k)) return;      // the several outlines of one element count as one result
    lattuk.add(k); ki.push(gid);
  });
  const kulcs = g => { const p = epuletek[g]; return String(p.cim ? p.cim.split(';')[0] : (p.nev || '')); };
  ki.sort((a, b) => (keruletSzam(epuletek[a]) - keruletSzam(epuletek[b])) || kulcs(a).localeCompare(kulcs(b), 'hu', { numeric: true }));
  const MAX = 300, f = x => x.toLocaleString(NYELV === 'en' ? 'en' : 'hu-HU');
  document.getElementById('ved-db').textContent = t('ved_db').replace('{n}', f(ki.length));
  document.getElementById('ved-lista').innerHTML = ki.length
    ? ki.slice(0, MAX).map(gid => {
      const p = epuletek[gid], cim = p.cim ? p.cim.split(';')[0] : '', cimke = p.nev || p.nev_kozepulet || cim || t('nevtelen');
      return `<button type="button" data-gid="${gid}"><b>${esc(cimke)}</b>${p.nev && cim ? ' <small>' + esc(cim) + '</small>' : ''}${kerSzoveg(p)}<small>${esc(vedettsegSzoveg(p))}</small></button>`;
    }).join('') + (ki.length > MAX ? `<span class="tobb">${esc(t('ved_tobb').replace('{k}', MAX))}</span>` : '')
    : `<span class="nincs">${esc(t('kereso_nincs'))}</span>`;
  document.getElementById('ved-lista').scrollTop = 0;
  frissitKiemelest();
}
(function vedKeresoInit() {
  vedNyelv();
  document.getElementById('ved-ker').addEventListener('input', vedSzuroFrissit);
  ['ved-m', 'ved-h', 'ved-kerulet'].forEach(i => document.getElementById(i).addEventListener('change', vedSzuroFrissit));
  document.getElementById('ved-lista').addEventListener('click', ev => { const b = ev.target.closest('button[data-gid]'); if (b) repulj(+b.dataset.gid); });
})();
document.getElementById('vedett').addEventListener('change', frissitKiemelest);
var lakIpar = null, lakKiv = null, lakAdatCache = null;     // lakIpar: names of the industrial/commercial zones (zonak.json); these are not housing estates
function lakBe(p) { return !!p.zona_nev && !(lakIpar && lakIpar.has(p.zona_nev)) && (!lakKiv || p.zona_nev === lakKiv); }
// zones from the building data: name -> { db, lat, lon (median), r (about 90% radius, m), cikk (Wikipedia title) }
function lakAdat() {
  if (lakAdatCache) return lakAdatCache;
  const m = new Map();
  for (const p of epuletek) {
    if (!p || p.hid || !p.zona_nev || (lakIpar && lakIpar.has(p.zona_nev))) continue;
    let z = m.get(p.zona_nev);
    if (!z) m.set(p.zona_nev, z = { nev: p.zona_nev, db: 0, la: [], lo: [], cikk: '' });
    z.db++; z.la.push(p.lat); z.lo.push(p.lon);
    if (!z.cikk && p.wikipedia && p.wikipedia_zona === p.zona_nev) z.cikk = String(p.wikipedia);
    if (p.wikipedia) { (z.wc || (z.wc = {}))[p.wikipedia] = (z.wc[p.wikipedia] || 0) + 1; }
  }
  const med = a => { const b = a.slice().sort((x, y) => x - y); return b[b.length >> 1]; };
  const ki = [...m.values()];
  for (const z of ki) {
    z.lat = med(z.la); z.lon = med(z.lo);
    if (!z.cikk && z.wc) { const top = Object.entries(z.wc).sort((x, y) => y[1] - x[1])[0]; if (top && top[1] >= 2 && top[1] >= z.db * 0.5) z.cikk = String(top[0]); }   // the zone's article: the article that appears on most of its buildings
    delete z.wc;
    const d = z.la.map((la, i) => Math.hypot((z.lo[i] - z.lon) * COSLAT * 111320, (la - z.lat) * 110574)).sort((x, y) => x - y);
    z.r = d[Math.floor(d.length * 0.9)] || 100;
    delete z.la; delete z.lo;
    const j = (window.__zonak && window.__zonak[z.nev]) || {};
    z.t = j.t || ''; z.kr = j.k || ''; z.a = j.a || null; z.b = j.b || null;
  }
  const kn = z => (z.kr && ROMAI_KER.indexOf(z.kr) > 0) ? ROMAI_KER.indexOf(z.kr) : 99;      // zones without a district go to the end of the list
  ki.sort((x, y) => kn(x) - kn(y) || x.nev.localeCompare(y.nev, 'hu'));
  return (lakAdatCache = ki);
}
function lakotelepInfoRender() {
  const el = document.getElementById('lakotelep-info');
  if (!el) return;
  const zonak = lakAdat(), f = x => x.toLocaleString(NYELV === 'en' ? 'en' : 'hu-HU');
  el.innerHTML = `<p>${esc(t('lakotelep_leiras').replace('{e}', f(zonak.length)).replace('{n}', f(zonak.reduce((s, z) => s + z.db, 0))))}</p>`;
}
function lakFrissit() {
  const q = document.getElementById('lak-ker'); if (!q) return;
  const szavak = normal(q.value).split(/\s+/).filter(Boolean);
  const ki = lakAdat().filter(z => { const s = normal(z.nev + ' ' + z.kr); return szavak.every(w => s.includes(w)); });
  const f = x => x.toLocaleString(NYELV === 'en' ? 'en' : 'hu-HU');
  document.getElementById('lak-db').textContent = t('lak_db').replace('{n}', f(ki.length));
  document.getElementById('lak-lista').innerHTML = ki.map(z => {
    const ev = z.a ? (z.b && z.b !== z.a ? `${z.a}–${z.b}` : String(z.a)) : '';
    const info = [z.kr ? `${z.kr}. ${t('lak_ker')}` : '', ev, `${f(z.db)} ${NYELV === 'en' ? 'buildings' : 'épület'}`].filter(Boolean).join(' · ');
    return `<button type="button" data-nev="${esc(z.nev)}" class="${z.nev === lakKiv ? 'aktiv' : ''}"><b>${esc(z.nev)}</b><small>${esc(info)}</small></button>`;
  }).join('');
}
function repuljHelyre(lat, lon, tav) {
  keresoLista.hidden = true;
  const cx = (lon - LON0) * COSLAT * 111320, cz = -(lat - LAT0) * 110574;
  const cel = new THREE.Vector3(cx, terepMag ? terepMag(cx, cz) : 0, cz);   // the target sits on the terrain, so it also works in the hills
  const irany = camera.position.clone().sub(controls.target);
  irany.setLength(tav);
  if (irany.y < tav * 0.35) irany.y = tav * 0.5;
  const t0 = controls.target.clone(), c0 = camera.position.clone(), c1 = cel.clone().add(irany);
  const kezd = performance.now(), az = ++repulAz;
  const lep = now => {
    if (az !== repulAz) return;
    const u = Math.min(1, (now - kezd) / 900), e = u * u * (3 - 2 * u);
    controls.target.lerpVectors(t0, cel, e);
    camera.position.lerpVectors(c0, c1, e);
    if (u < 1) requestAnimationFrame(lep);
  };
  requestAnimationFrame(lep);
}
function lakValaszt(nev) {
  lakKiv = lakKiv === nev ? null : nev;
  const pp = document.getElementById('arch-popup'); if (pp) pp.hidden = true;
  const z = lakKiv && lakAdat().find(x => x.nev === lakKiv);
  if (z) {
    repuljHelyre(z.lat, z.lon, Math.max(350, Math.min(1500, z.r * 2.4)));
    const m = /^hu:(.+)$/.exec(z.cikk);        // own Wikipedia data sheet: popup, as for the architects
    if (m) { const tok = ++epPopupTok; archPopupTok = tok; archPopupMutat({ nev: z.nev, l: '', w: ['=' + m[1]], nw: false, tok }, archKiv); }
  }
  lakFrissit();
  frissitKiemelest();
}
fetch('zonak.json').then(r => r.ok ? r.json() : null).then(j => {
  if (!j) return;
  window.__zonak = j;
  lakIpar = new Set(Object.entries(j).filter(([, z]) => z.t === 'ipar_kereskedelem').map(([n]) => n));
  lakAdatCache = null;
  if (document.getElementById('lakotelep').checked) { lakotelepInfoRender(); lakFrissit(); }
  frissitKiemelest();
}).catch(() => {});
(function lakKeresoInit() {
  document.getElementById('lak-ker').addEventListener('input', lakFrissit);
  document.getElementById('lak-lista').addEventListener('click', ev => { const b = ev.target.closest('button[data-nev]'); if (b) lakValaszt(b.dataset.nev); });
})();
document.getElementById('lakotelep').addEventListener('change', () => { lakotelepInfoRender(); frissitKiemelest(); });

const ABOUT_HTML = {
  hu: `<p>Budapest összes ma álló épülete, az építés ideje szerint színezve, térben ábrázolva. A térképen a város jelenlegi felépítése elemezhető különböző szemszögekből: történelmi korszakok, építészeti stílusok, építészek, védett épületek, lakótelepek és magasság.</p>
<p>Készítette: <a href="https://www.linkedin.com/in/attila-cselovszki-18993a48/" target="_blank" rel="noopener">Cselovszki Attila</a></p>
<p>Az inspirációs forrást <a href="https://www.linkedin.com/in/alexanderbarakov" target="_blank" rel="noopener">Alex Barakov</a> Amszterdam térképe szolgáltatta. Külön köszönettel tartozom azért, hogy a projektjét nyilvánosan elérhetővé teszi, így ez a Budapest térkép az ő kódján alapszik. Az ő amszterdami térképe pedig Sasha Bogachev <a href="https://paris.bogachev.fr/" target="_blank" rel="noopener">Paris, building by building</a> projektjének architektúráját követi.</p>
<h3>Nyílt forráskód</h3>
<p>A kód és a feldolgozás a <a href="https://github.com/CseloAtti/budapest-by-building" target="_blank" rel="noopener">GitHubon</a> érhető el.</p>
<h3>Adatok</h3>
<ul>
<li>Épületek, körvonalak, címek: OpenStreetMap (ODbL).</li>
<li>Magasságok: OpenStreetMap, EUBUCCO, kerületi szabályozási tervek, műemléki adatok, kézi javítások. Ha nincs adat, 15 m az alapérték.</li>
<li>Domborzat: NASA SRTM.</li>
<li>Építési évek, műemlékek, tervezők: E-Örökség, Budapest100, Budapest Legendák, Építészfórum, Lechner Tudásközpont, Wikipédia és kézi kutatás, kerületi Településképi Arculati Kézikönyvek és Értékkataszterek, Központi Statisztikai Hivatal adatai; a kézi adatbevitelhez archív fotók.</li>
<li>Képek: Wikidata, Wikipédia, Wikimedia Commons; E-Örökség, Budapest100, Budapest Legendák, Építészfórum. Minden kép az eredeti tárhelyről töltődik be, és feltünteti szerzőjét és licencét.</li>
<li>Leírások: Wikipédia, AI generált tartalom.</li>
<li>Adatletöltés ideje: 2026. november.</li>
</ul>
<h3>Módszer - Becslés az épületek többségére</h3>
<p>A cél az, hogy minél pontosabban meg lehessen állapítani Budapest jelenlegi épületállományának korát. Mivel egységes és nyilvánosan elérhető adatbázis nem áll rendelkezésre, ezért több egymással fedésben lévő töredék információ felhasználásával kell megbecsülni a házak többségének építési idejét.</p>
<p>A közel 260 000 épületből mindössze {ISMERT_HU} épülethez ({ARANY_HU}) köthető pontos dátum a fent megnevezett adatforrásokból. A fennmaradók korszakba sorolásához az algoritmus a következőket veszi figyelembe:</p>
<ul>
<li>Az épület geometriája, telepítése, szintek száma, formája, szomszédok közelsége, az utcán elfoglalt pozíciója.</li>
<li>Az ismert korú épületektől mért távolság.</li>
<li>A városban elfoglalt pozíció, a belvárostól és a történelmi alközpontoktól mért távolság.</li>
<li>A KSH (Központi Statisztikai Hivatal) legutóbbi népszámláláskor felvett kerületi bontású adatsora.</li>
<li>A városfejlődésben ismert korú telepek, negyedek és ipari övezetek közelsége.</li>
</ul>
<p>Látható, hogy a legjobb szándék mellett is a teljes épületállomány pontos korára csak bizonytalan becslés adható, ezért kellően nagy történelmi időszakokba soroltam a házakat. Ezáltal a végeredmény az összképet tekintve informatív, de nem szabad elfelejteni, hogy az egyedi objektumok szintjén pontatlan.</p>
<p>Volt egy nem várt haszna annak a törekvésnek, hogy minél több épületről tudjam meg a pontos építési dátumát. A kerületi értékkataszterekben, TAK-okban, Wikipédia-adatbázisokban, örökségvédelmi listában ez a szám legtöbbször az alapadatok között szerepel, így egy körben ismertté vált a tervező személye is.</p>
<p>Így lehetett könnyűszerrel egy olyan nézetét is adni az adatsornak, ami az építészeti stílusokra és a tervező építészekre koncentrál. Természetesen itt is érvényes, hogy az adathalmaz közel sem teljes, az interneten szabadon elérhető, véletlenszerűen fellelt források terjedelmére és pontosságára hagyatkozik.</p>
<h3>Szöveges oldal</h3>
<p>Elérhető egyszerű szöveges oldalakként is, olvasáshoz és keresőmotorok számára: <a href="https://budapestbuildings.com/explore/">budapestbuildings.com/explore</a></p>
<h3>Beszéljünk</h3>
<p>Ha a projekt felkeltette az érdeklődésedet, és kérdésed, ötleted van, keress meg ezen az elérhetőségen: <a href="mailto:cselovszki.attila@gmail.com">cselovszki.attila@gmail.com</a></p>`,
  en: `<p>All buildings standing in Budapest today, coloured by the year they were built and shown in space. The map lets you analyse the city's current fabric from different angles: historical periods, architectural styles, architects, protected buildings, housing estates and height.</p>
<p>Made by <a href="https://www.linkedin.com/in/attila-cselovszki-18993a48/" target="_blank" rel="noopener">Attila Cselovszki</a></p>
<p>The inspiration came from <a href="https://www.linkedin.com/in/alexanderbarakov" target="_blank" rel="noopener">Alex Barakov</a>'s map of Amsterdam. Special thanks for making his project publicly available: this Budapest map is built on his code. His Amsterdam map in turn follows the architecture of Sasha Bogachev's <a href="https://paris.bogachev.fr/" target="_blank" rel="noopener">Paris, building by building</a>.</p>
<h3>Open source</h3>
<p>The code and the pipeline are on <a href="https://github.com/CseloAtti/budapest-by-building" target="_blank" rel="noopener">GitHub</a>.</p>
<h3>Data</h3>
<ul>
<li>Buildings, outlines, addresses: OpenStreetMap (ODbL).</li>
<li>Heights: OpenStreetMap, EUBUCCO, district zoning plans, monument data, manual corrections. 15 m by default where nothing is known.</li>
<li>Terrain: NASA SRTM.</li>
<li>Years, monuments, architects: E-Örökség, Budapest100, Budapest Legendák, Építészfórum, Lechner Knowledge Centre, Wikipedia and manual research, district townscape manuals and heritage registers, Hungarian Central Statistical Office (KSH) data; archive photographs for manual data entry.</li>
<li>Photos: Wikidata, Wikipedia, Wikimedia Commons; E-Örökség, Budapest100, Budapest Legendák, Építészfórum. Each photo loads from its original host and credits its author and licence.</li>
<li>Texts: Wikipedia, AI-generated content.</li>
<li>Data downloaded: November 2026.</li>
</ul>
<h3>Method - Estimate for most buildings</h3>
<p>The aim is to establish the age of Budapest's building stock as accurately as possible. No single public database exists, so the construction date of most buildings has to be estimated from several overlapping fragments of information.</p>
<p>Of the nearly 260,000 buildings, only {ISMERT_EN} ({ARANY_EN}) have an exact date from the sources above. To place the rest in a period, the algorithm considers:</p>
<ul>
<li>The building's geometry, siting, number of floors, shape, closeness of neighbours and position on the street.</li>
<li>Distance from buildings of known age.</li>
<li>Position in the city: distance from the centre and from historical sub-centres.</li>
<li>District-level data from the latest census of the KSH.</li>
<li>Closeness of estates, quarters and industrial zones of known age in the city's development.</li>
</ul>
<p>Even with the best intentions, only an uncertain estimate can be given for the exact age of the whole stock, so buildings are placed in sufficiently broad historical periods. The result is informative as an overall picture, but inaccurate for individual buildings.</p>
<p>The effort to find exact dates had an unexpected benefit: in district heritage registers, townscape manuals, Wikipedia databases and heritage lists the architect is usually among the basic data, so for a share of buildings the designer became known too.</p>
<p>This made it easy to add a view focused on architectural styles and architects. Here too the dataset is far from complete and relies on the scope and accuracy of sources found freely on the internet.</p>
<h3>Text version</h3>
<p>Also available as plain text pages, for reading and for search engines: <a href="https://budapestbuildings.com/explore/">budapestbuildings.com/explore</a></p>
<h3>Let's talk</h3>
<p>If the project caught your interest and you have a question or idea, get in touch: <a href="mailto:cselovszki.attila@gmail.com">cselovszki.attila@gmail.com</a></p>`
};
// The About window's numbers from the tile builder's measurements (budapest.json stats): buildings with a known year (the parts of one building count once)
function nevjegySzamok(h) {
  const st = config.stats || {}, n = st.ismert_ev_epulet, ossz = st.epulet_egyedi || st.buildings;
  const hu = x => String(x).replace(/\B(?=(\d{3})+(?!\d))/g, '\u00a0'), en = x => String(x).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  const ar = n && ossz ? 100 * n / ossz : null;
  return h.replace('{ISMERT_HU}', n ? hu(n) : 'kb. 7700').replace('{ARANY_HU}', ar ? ar.toFixed(1).replace('.', ',') + '%' : 'kb. 3%')
          .replace('{ISMERT_EN}', n ? en(n) : 'about 7,700').replace('{ARANY_EN}', ar ? ar.toFixed(1) + '%' : 'about 3%');
}
function alkalmazSzoveg() {
  document.documentElement.lang = NYELV;
  { const ab = document.getElementById('about-tartalom'); if (ab) ab.innerHTML = nevjegySzamok(ABOUT_HTML[NYELV] || ABOUT_HTML.hu); }
  document.querySelectorAll('[data-t]').forEach(el => { el.textContent = t(el.dataset.t); });
  document.querySelectorAll('.nez button').forEach(b => { const x = b.querySelector('.tx'); if (x) { b.title = x.textContent; b.setAttribute('aria-label', x.textContent); } });
  document.querySelectorAll('#nyelv button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.nyelv === NYELV)));
  document.title = t('oldal_cim');
  keresoSzoveg();
  vedettInfoRender();
  vedNyelv();
  magInfoRender();
  if (document.getElementById('lakotelep').checked) lakotelepInfoRender();
  epNyelvFrissit();
  renderLegend();
  archNyelvFrissit();
  drawHist();
  kartyaUjra();
}
// About window: closed by the button, ×, a click on the background or Esc
const aboutAblak = document.getElementById('about');
const aboutNyit = ki => { aboutAblak.hidden = !ki; if (ki) document.getElementById('about-bezar').focus(); };
document.getElementById('about-gomb').addEventListener('click', () => aboutNyit(true));
document.getElementById('about-bezar').addEventListener('click', () => aboutNyit(false));
aboutAblak.addEventListener('click', e => { if (e.target === aboutAblak) aboutNyit(false); });
window.addEventListener('keydown', e => { if (e.key === 'Escape' && !aboutAblak.hidden) aboutNyit(false); });
document.querySelectorAll('#nyelv button').forEach(b => b.addEventListener('click', () => {
  NYELV = b.dataset.nyelv === 'en' ? 'en' : 'hu';
  try { localStorage.setItem('nyelv', NYELV); } catch (e) { /* no storage available */ }
  alkalmazSzoveg();
}));

// ---------- Search: OSM id (way/123, relation/123, osm.org link or just the number), name, address ----------
const keresoBe = document.getElementById('kereso'), keresoLista = document.getElementById('kereso-lista');
const LAT0 = 47.5015, LON0 = 19.0515, COSLAT = Math.cos(LAT0 * Math.PI / 180);   // the same as in build_tiles.py
const normal = s => String(s ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
const KERESO_MAX = 500;      // the result list shows at most this many rows (scrollable)
let keresoIndex = null;
function keresoEpit() {
  keresoIndex = [];
  const lattuk = new Set();       // an OSM element made of several outlines (relation) should appear only once among the results
  for (let gid = 0; gid < epuletek.length; gid++) {
    const p = epuletek[gid];
    if (!p || (!p.nev && !p.cim && !p.nev_kozepulet && !p.lechner_nev && !p.zona_nev)) continue;
    if (!p.hid) {
      const k = (p.osm_tipus || 'way') + ':' + p.id;
      if (lattuk.has(k)) continue;
      lattuk.add(k);
    }
    keresoIndex.push([gid, normal([p.nev, p.nev_kozepulet, p.lechner_nev, p.cim, p.zona_nev].filter(Boolean).join(' | '))]);
  }
}
function keresoSzoveg() { if (keresoBe) keresoBe.placeholder = t('kereso_ph'); if (document.getElementById('utak-gomb')) document.getElementById('utak-gomb').title = t('utak_cim'); }
// Street types and their abbreviations are accepted in place of each other (utca = u. = út = útja; krt. = körút; tér; rkp. = rakpart; köz; sétány);
// these are searched as whole words, the other search words as fragments
const KERESO_CSOPORTOK = [['utca', 'u', 'ut', 'utja', 'uton'], ['korut', 'krt'], ['ter', 'tere'], ['rakpart', 'rkp'], ['koz', 'koze'], ['setany', 'stny']];
const keresoSzoPar = w => {
  const cs = KERESO_CSOPORTOK.find(c => c.includes(w));
  if (!cs) return s => s.includes(w);
  const re = new RegExp('(^|[^a-z0-9])(?:' + cs.join('|') + ')(?![a-z0-9])');
  return s => re.test(s);
};
function keres(q) {
  q = q.trim();
  if (!q) return [];
  // OSM id: "way/123", "relation 123", "w123", "r123", an osm.org link, or just the number
  const m = q.match(/^(?:https?:\/\/(?:www\.)?openstreetmap\.org\/)?(?:(way|relation|w|r)[\s\/:#-]*)?(\d{3,})\/?$/i);
  if (m) {
    const tip = m[1] ? (m[1][0].toLowerCase() === 'r' ? 'relation' : 'way') : null, id = +m[2];
    const ki = [];
    for (let gid = 0; gid < epuletek.length && ki.length < 12; gid++) {
      const p = epuletek[gid];
      if (p && p.id === id && (!tip || (p.osm_tipus || 'way') === tip) && !ki.some(g => epuletek[g].osm_tipus === p.osm_tipus)) ki.push(gid);   // the several outlines of one element count as one result
    }
    return ki;
  }
  if (q.length < 3) return [];
  if (!keresoIndex) keresoEpit();
  // punctuation of pasted addresses (the full stop after a house number, "u.", postcode, "Budapest") must not hinder the search
  let szavak = normal(q).split(/[\s,;]+/).map(w => w.replace(/^[.,;:()]+|[.,;:()]+$/g, '')).filter(Boolean);
  const tisztabb = szavak.filter(w => !/^[1-2]\d{3}$/.test(w) && w !== 'budapest');
  if (tisztabb.length) szavak = tisztabb;
  const ki = [];
  const talal = szavak.map(keresoSzoPar);
  for (const [gid, s] of keresoIndex) {
    if (talal.every(f => f(s))) { ki.push(gid); if (ki.length >= KERESO_MAX) break; }
  }
  const cimKulcs = g => { const p = epuletek[g]; return String(p.cim ? p.cim.split(';')[0] : (p.nev || p.lechner_nev || '')); };
  return ki.sort((a, b) => cimKulcs(a).localeCompare(cimKulcs(b), 'hu', { numeric: true }));      // e.g. the house numbers of a street in order
}
// District next to the results: from the coordinate, using kerulethatarok.json (loaded late; until then no district is written)
let kerHatar = null;
fetch('kerulethatarok.json').then(r => r.ok ? r.json() : null).then(j => {
  if (!j) return;
  kerHatar = [];
  for (const [kn, gyuruk] of Object.entries(j)) for (const g of gyuruk) {
    let x0 = 1e9, x1 = -1e9, y0 = 1e9, y1 = -1e9;
    for (const [x, y] of g) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
    kerHatar.push([+kn, g, x0, x1, y0, y1]);
  }
  if (keresoBe && !keresoLista.hidden && keresoBe.value.trim()) keresoFrissit();
  if (document.getElementById('vedett').checked) vedSzuroFrissit();      // district filter/ordering after the boundaries have loaded
}).catch(() => {});
const ROMAI_KER = ['', 'I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X', 'XI', 'XII', 'XIII', 'XIV', 'XV', 'XVI', 'XVII', 'XVIII', 'XIX', 'XX', 'XXI', 'XXII', 'XXIII'];
const kerCache = new Map();
function keruletSzam(p) {
  if (p.kerulet) return +p.kerulet || 0;
  if (!kerHatar || p.lat == null) return 0;
  const k = p.lat + ',' + p.lon;
  if (kerCache.has(k)) return kerCache.get(k);
  const x = p.lon, y = p.lat;
  let kn = 0;
  for (const [n, g, x0, x1, y0, y1] of kerHatar) {
    if (x < x0 || x > x1 || y < y0 || y > y1) continue;
    let be = false;
    for (let i = 0, j = g.length - 1; i < g.length; j = i++) {
      const [xi, yi] = g[i], [xj, yj] = g[j];
      if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) be = !be;
    }
    if (be) { kn = n; break; }
  }
  kerCache.set(k, kn);
  return kn;
}
function kerSzoveg(p) { const n = keruletSzam(p); return n ? ' <small class="ker">(' + ROMAI_KER[n] + ')</small>' : ''; }
function keresoSor(gid) {
  const p = epuletek[gid];
  const cim = p.cim ? p.cim.split(';')[0] : '';
  const cimke = p.nev || p.lechner_nev || p.nev_kozepulet || cim || p.zona_nev || t('nevtelen');
  return `<button type="button" data-gid="${gid}"><b>${esc(cimke)}</b>${p.nev && cim ? ' <small>' + esc(cim) + '</small>' : ''}${kerSzoveg(p)}</button>`;
}
function keresoFrissit() {
  const ki = keres(keresoBe.value);
  if (!keresoBe.value.trim() || (keresoBe.value.trim().length < 3 && !ki.length)) { keresoLista.hidden = true; keresoLista.innerHTML = ''; return; }
  const fej = ki.length > 12 ? `<span class="nincs">${ki.length >= KERESO_MAX ? (NYELV === 'en' ? 'First ' + KERESO_MAX + ' results – refine your search' : 'Az első ' + KERESO_MAX + ' találat – pontosítsd a keresést') : ki.length + (NYELV === 'en' ? ' results' : ' találat')}</span>` : '';
  keresoLista.innerHTML = ki.length ? fej + ki.map(keresoSor).join('') : `<span class="nincs">${t('kereso_nincs')}</span>`;
  keresoLista.scrollTop = 0;
  keresoLista.hidden = false;
}

// ---------- Streets and street names (toggleable layer; utak.json <- py build_roads.py) ----------
// Lines: laid onto the terrain, one LineSegments per class; the names are DOM labels that turn along the street,
// and avoid each other (main roads take priority). More street names appear the closer you zoom.
const utakGomb = document.getElementById('utak-gomb');
const UT_STILUS = [{ szin: 0x4f5b63, alfa: 0.95 }, { szin: 0x5f6b73, alfa: 0.8 }, { szin: 0x7a858c, alfa: 0.6 }, { szin: 0x9aa4aa, alfa: 0.5 }];
const UT_LATHATO_TAV = [Infinity, Infinity, 5500, 1500];     // the camera distance within which the class's line is visible
const UT_CIMKE_TAV = [3200, 3200, 1600, 450];               // the same for the names (closer than about a 2x2 km view)
const UT_MEGALL_MS = 220;                                    // after this much stillness the names reappear after moving
let utakBetoltve = false, utakBetolt = null, utakBe = false, utakCsoport = null, utakVonalak = [];
let utCim = null;       // arrays of {x, z, dx, dz, nev, osz, hossz}
let utRacs = new Map();
const UT_CELLA = 400;
const utakKont = document.createElement('div');
utakKont.id = 'utcanevek';
canvas.after(utakKont);
const utakSpanok = [];
function utakEpit(adat) {
  utakCsoport = new THREE.Group();
  flat.add(utakCsoport);
  const poz = [[], [], [], []];
  const cim = { x: [], z: [], dx: [], dz: [], nev: [], osz: [], hossz: [] };
  for (const [nev, osz, f] of adat.utak) {
    const n = f.length / 2;
    let hossz = 0;
    const cum = [0];
    for (let i = 1; i < n; i++) { hossz += Math.hypot(f[2 * i] - f[2 * i - 2], f[2 * i + 1] - f[2 * i - 1]); cum.push(hossz); }
    if (hossz < 1) continue;
    const P = poz[osz];
    for (let i = 0; i < n - 1; i++) {      // split into 25 m segments so that the line follows the terrain
      const x0 = f[2 * i], z0 = f[2 * i + 1], x1 = f[2 * i + 2], z1 = f[2 * i + 3];
      const db = Math.max(1, Math.ceil(Math.hypot(x1 - x0, z1 - z0) / 25));
      for (let k = 0; k < db; k++) {
        const ax = x0 + (x1 - x0) * k / db, az = z0 + (z1 - z0) * k / db, bx = x0 + (x1 - x0) * (k + 1) / db, bz = z0 + (z1 - z0) * (k + 1) / db;
        P.push(ax, (terepMag ? terepMag(ax, az) : 0) + 2.5, az, bx, (terepMag ? terepMag(bx, bz) : 0) + 2.5, bz);
      }
    }
    // label anchors: in the middle, every 350 m on a long road
    if (hossz >= 18) {
      const s0 = hossz / 2, db = Math.floor((hossz - 1) / 700);
      for (let q = -db; q <= db; q++) {
        const s = s0 + q * 350;
        let i = 1;
        while (i < n - 1 && cum[i] < s) i++;
        const l = cum[i] - cum[i - 1] || 1, u = Math.min(1, Math.max(0, (s - cum[i - 1]) / l));
        const dx = f[2 * i] - f[2 * i - 2], dz = f[2 * i + 1] - f[2 * i - 1], dl = Math.hypot(dx, dz) || 1;
        cim.x.push(f[2 * i - 2] + dx * u); cim.z.push(f[2 * i - 1] + dz * u); cim.dx.push(dx / dl); cim.dz.push(dz / dl);
        cim.nev.push(nev); cim.osz.push(osz); cim.hossz.push(hossz);
      }
    }
  }
  utakVonalak = poz.map((P, o) => {
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(P), 3));
    const m = new THREE.LineBasicMaterial({ color: UT_STILUS[o].szin, transparent: true, opacity: UT_STILUS[o].alfa, fog: false });
    const ls = new THREE.LineSegments(g, m);
    ls.frustumCulled = false;
    ls.renderOrder = 2;
    utakCsoport.add(ls);
    return ls;
  });
  utCim = cim;
  utRacs = new Map();
  for (let i = 0; i < cim.x.length; i++) {
    const k = Math.floor(cim.x[i] / UT_CELLA) + ',' + Math.floor(cim.z[i] / UT_CELLA);
    (utRacs.get(k) || utRacs.set(k, []).get(k)).push(i);
  }
}
const utV = new THREE.Vector3(), utW = new THREE.Vector3();
let utUtolso = '', utMozgas = 0, utRajzolt = false;
const utKulcs = () => camera.position.x.toFixed(1) + '|' + camera.position.y.toFixed(1) + '|' + camera.position.z.toFixed(1) + '|' + controls.target.x.toFixed(1) + '|' + controls.target.z.toFixed(1) + '|' + innerWidth + 'x' + innerHeight;
function utakCimkek() {
  if (!utakBe || !utCim) return;
  const tav = camera.position.distanceTo(controls.target);
  const szelesseg = innerWidth, magassag = innerHeight;
  const maxO = UT_CIMKE_TAV.reduce((m, d, o) => (tav < d ? o : m), -1);
  const jel = [];
  if (maxO >= 0) {
    const R = Math.min(tav * 1.6, 4200), tx = controls.target.x, tz = controls.target.z;
    for (let cx = Math.floor((tx - R) / UT_CELLA); cx <= Math.floor((tx + R) / UT_CELLA); cx++) for (let cz = Math.floor((tz - R) / UT_CELLA); cz <= Math.floor((tz + R) / UT_CELLA); cz++) {
      const lista = utRacs.get(cx + ',' + cz);
      if (!lista) continue;
      for (const i of lista) {
        const o = utCim.osz[i];
        if (tav >= UT_CIMKE_TAV[o]) continue;
        utV.set(utCim.x[i], (terepMag ? terepMag(utCim.x[i], utCim.z[i]) : 0) + 3, utCim.z[i]).project(camera);
        if (utV.z > 1 || Math.abs(utV.x) > 1.05 || Math.abs(utV.y) > 1.05) continue;
        const sx = (utV.x + 1) / 2 * szelesseg, sy = (1 - utV.y) / 2 * magassag;
        utW.set(utCim.x[i] + utCim.dx[i] * 10, (terepMag ? terepMag(utCim.x[i] + utCim.dx[i] * 10, utCim.z[i] + utCim.dz[i] * 10) : 0) + 3, utCim.z[i] + utCim.dz[i] * 10).project(camera);
        const ex = (utW.x + 1) / 2 * szelesseg, ey = (1 - utW.y) / 2 * magassag;
        const ppm = Math.hypot(ex - sx, ey - sy) / 10;
        let szog = Math.atan2(ey - sy, ex - sx) * 180 / Math.PI;
        if (szog > 90) szog -= 180; else if (szog < -90) szog += 180;
        jel.push({ i, sx, sy, szog, ppm, o });
      }
    }
  }
  jel.sort((a, b) => a.o - b.o || utCim.hossz[b.i] - utCim.hossz[a.i]);
  const doboz = [], nevek = new Map(), ki = [];
  for (const c of jel) {
    if (ki.length >= 140) break;
    const nev = utCim.nev[c.i];
    const w = nev.length * (c.o === 0 ? 7 : 6.3) + 10, h = 15;
    if (c.ppm * utCim.hossz[c.i] < w * 0.8) continue;           // the street segment is shorter on screen than its name
    const r = c.szog * Math.PI / 180, cw = Math.abs(w * Math.cos(r)) + Math.abs(h * Math.sin(r)), ch = Math.abs(w * Math.sin(r)) + Math.abs(h * Math.cos(r));
    const x0 = c.sx - cw / 2, x1 = c.sx + cw / 2, y0 = c.sy - ch / 2, y1 = c.sy + ch / 2;
    if (x1 < 0 || x0 > szelesseg || y1 < 0 || y0 > magassag) continue;
    if (doboz.some(b => x0 < b[2] && x1 > b[0] && y0 < b[3] && y1 > b[1])) continue;
    const korabbi = nevek.get(nev);
    if (korabbi && korabbi.some(q => Math.hypot(q[0] - c.sx, q[1] - c.sy) < 260)) continue;
    doboz.push([x0, y0, x1, y1]);
    (nevek.get(nev) || nevek.set(nev, []).get(nev)).push([c.sx, c.sy]);
    ki.push({ nev, sx: c.sx, sy: c.sy, szog: c.szog, o: c.o });
  }
  while (utakSpanok.length < ki.length) {
    const s = document.createElement('span');
    utakKont.appendChild(s);
    utakSpanok.push(s);
  }
  for (let q = 0; q < utakSpanok.length; q++) {
    const s = utakSpanok[q], c = ki[q];
    if (!c) { if (!s.hidden) s.hidden = true; continue; }
    if (s.textContent !== c.nev) s.textContent = c.nev;
    s.className = 'ut-' + c.o;
    s.style.transform = `translate(${c.sx.toFixed(1)}px, ${c.sy.toFixed(1)}px) translate(-50%, -50%) rotate(${c.szog.toFixed(1)}deg)`;
    s.hidden = false;
  }
}
function utakFrissit() {
  if (!utakCsoport) return;
  utakCsoport.visible = utakBe;
  utakKont.hidden = !utakBe;
  if (utakBe) {
    const tav = camera.position.distanceTo(controls.target);
    utakVonalak.forEach((l, o) => { l.visible = tav < UT_LATHATO_TAV[o]; });
  }
}
function utakKor() {
  if (!utakBe) return;
  utakFrissit();
  // the labels are hidden while moving (the jittery tracking is distracting); they are recomputed once after stillness
  const kulcs = utKulcs(), most = performance.now();
  if (kulcs !== utUtolso) {
    utUtolso = kulcs; utMozgas = most;
    if (utRajzolt) { utakKont.classList.add('mozog'); utRajzolt = false; }
  } else if (!utRajzolt && most - utMozgas > UT_MEGALL_MS) {
    utakCimkek();
    utakKont.classList.remove('mozog');
    utRajzolt = true;
  }
  requestAnimationFrame(utakKor);
}
async function utakKapcsol() {
  if (!utakBe && !utakBetoltve) {
    if (!utakBetolt) utakBetolt = fetch(`${DATA}/utak.json`).then(r => { if (!r.ok) throw new Error('nincs'); return r.json(); }).then(a => { utakEpit(a); utakBetoltve = true; });
    try { await utakBetolt; }
    catch (h) {
      utakBetolt = null;
      const regi = utakGomb.textContent;
      utakGomb.textContent = t('utak_nincs');
      setTimeout(() => { utakGomb.textContent = regi; }, 3500);
      return;
    }
  }
  utakBe = !utakBe;
  utakGomb.setAttribute('aria-pressed', String(utakBe));
  utakFrissit();
  if (utakBe) { utUtolso = ''; utRajzolt = false; utakKont.classList.add('mozog'); utakKor(); }
  else utakKont.hidden = true;
}
if (utakGomb) utakGomb.addEventListener('click', utakKapcsol);
let repulAz = 0;
function repulj(gid, kx, utan) {
  const p = epuletek[gid];
  keresoLista.hidden = true;
  const x = (p.lon - LON0) * COSLAT * 111320, z = -(p.lat - LAT0) * 110574;
  const cel = new THREE.Vector3(x, terepMag ? terepMag(x, z) : 0, z);   // on the terrain, not at sea level
  const irany = camera.position.clone().sub(controls.target);
  const tav = Math.max(250, Math.min(irany.length(), 450));
  irany.setLength(tav);
  if (irany.y < tav * 0.35) irany.y = tav * 0.5;      // do not look flat from the side, but from higher up
  const t0 = controls.target.clone(), c0 = camera.position.clone(), c1 = cel.clone().add(irany);
  const kezd = performance.now(), az = ++repulAz;
  const lep = now => {
    if (az !== repulAz) return;
    const u = Math.min(1, (now - kezd) / 900), e = u * u * (3 - 2 * u);
    controls.target.lerpVectors(t0, cel, e);
    camera.position.lerpVectors(c0, c1, e);
    if (u < 1) requestAnimationFrame(lep);
    else { rogzit(gid, kx || innerWidth * 0.55, innerHeight * 0.3); if (utan) utan(); }
  };
  requestAnimationFrame(lep);
}
if (keresoBe) {
  keresoBe.addEventListener('input', keresoFrissit);
  keresoBe.addEventListener('keydown', e => {
    if (e.key === 'Enter') { const b = keresoLista.querySelector('button'); if (b) repulj(+b.dataset.gid); }
    if (e.key === 'Escape') { keresoBe.value = ''; keresoLista.hidden = true; keresoBe.blur(); e.stopPropagation(); }
  });
  keresoLista.addEventListener('click', e => { const b = e.target.closest('button[data-gid]'); if (b) repulj(+b.dataset.gid); });
  canvas.addEventListener('pointerdown', () => { repulAz++; });   // manual movement interrupts the flight
  // mobile: the collapsed search is just a magnifier; it opens on tap, and collapses again if left empty (on desktop the CSS does not use it)
  const retegGomb = document.getElementById('reteg-gomb'), fopanel = document.getElementById('panel');
  const panelAllit = nyit => { fopanel.classList.toggle('mobil-nyitva', nyit); if (retegGomb) retegGomb.setAttribute('aria-pressed', String(nyit)); };
  if (retegGomb && fopanel) {
    retegGomb.addEventListener('click', () => panelAllit(!fopanel.classList.contains('mobil-nyitva')));      // mobile: the main panel opens/closes with the Layers button
    // mobile: tapping the map (not dragging) also closes the open main panel
    let le = null;
    canvas.addEventListener('pointerdown', e => { le = e.isPrimary ? { x: e.clientX, y: e.clientY, t: performance.now() } : null; });
    canvas.addEventListener('pointerup', e => {
      const l = le; le = null;
      if (!l || innerWidth > 700 || !fopanel.classList.contains('mobil-nyitva')) return;
      if (Math.hypot(e.clientX - l.x, e.clientY - l.y) < 8 && performance.now() - l.t < 400) panelAllit(false);
    });
  }
  const keresoDoboz = keresoBe.closest('.kereso');
  if (keresoDoboz) {
    keresoDoboz.querySelector('.kereso-sav').addEventListener('click', () => { keresoDoboz.classList.add('nyitva'); keresoBe.focus(); });
    keresoBe.addEventListener('blur', () => setTimeout(() => { if (!keresoBe.value.trim()) keresoDoboz.classList.remove('nyitva'); }, 200));
  }
}

// ---------- Time slider (histogram) ----------
const hist = document.getElementById('hist');
const hctx = hist.getContext('2d');
const T0 = Math.floor(config.yearMin / 50) * 50, T1 = config.yearMax + 1;
const years = Object.entries(config.histogram).map(([y, v]) => [+y, v]);
const yMax = Math.max(...years.map(([, v]) => v.reduce((a, b) => a + b, 0)));
const xOf = y => (y - T0) / (T1 - T0) * hist.clientWidth;
const yearOf = x => Math.round(T0 + x / hist.clientWidth * (T1 - T0));
const fmt = n => n.toLocaleString(NYELV === 'en' ? 'en' : 'hu-HU');

function visibleCount() {
  const Y = uniforms.uYear.value;
  let n = 0;
  for (const [y, v] of years) if (y <= Y) v.forEach((c, i) => { if (maskTarget[i]) n += c; });
  return n;
}

function drawHist() {
  const w = hist.clientWidth, h = hist.clientHeight, dpr = devicePixelRatio;
  if (!w || !h) return;
  hist.width = w * dpr; hist.height = h * dpr;
  hctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  hctx.clearRect(0, 0, w, h);
  const plotH = h - 20, bw = Math.max(1, w / (T1 - T0));
  const Y = uniforms.uYear.value, Yf = uniforms.uYearFrom.value;
  for (const [y, v] of years) {
    let top = plotH;
    v.forEach((c, i) => {
      if (!c) return;
      const bh = Math.sqrt(c / yMax) * (plotH - 6);
      hctx.fillStyle = periods[i].color;
      hctx.globalAlpha = maskTarget[i] && y <= Y ? (y <= Yf ? 0.3 : 1) : 0.18;
      hctx.fillRect(xOf(y), top - bh, bw, bh);
      top -= bh;
    });
  }
  hctx.globalAlpha = 1;
  hctx.fillStyle = '#5d6266';
  hctx.font = '600 11px "Source Sans Pro", "Source Sans 3", Arial, sans-serif';
  const step = w < 500 ? 100 : 50;
  for (let y = Math.ceil(T0 / step) * step; y <= T1; y += step) hctx.fillText(y, Math.min(w - 28, Math.max(0, xOf(y) - 13)), h - 4);
  hctx.fillStyle = '#000';
  hctx.fillRect(xOf(Y) - 1, 0, 2, plotH);
  if (Yf >= T0) { hctx.fillStyle = '#5d6266'; hctx.fillRect(xOf(Yf) - 0.5, 0, 1, plotH); }
  document.getElementById('year').textContent = Math.round(Math.min(Y, config.yearMax));   // the latest year (e.g. 2026) is shown, not 'Today'
  document.getElementById('count').textContent = fmt(visibleCount());
}

let handle = null;
hist.addEventListener('pointerdown', e => {
  hist.setPointerCapture(e.pointerId);
  const x = e.offsetX;
  handle = 'uYear';   // a click or drag always sets the end year: everything built before it is coloured, the rest stays white
  moveHandle(x);
  stopPlay();
});
hist.addEventListener('pointermove', e => handle && moveHandle(e.offsetX));
hist.addEventListener('pointerup', () => { handle = null; });
function moveHandle(x) {
  const y = Math.max(T0, Math.min(config.yearMax, yearOf(x)));
  if (handle === 'uYear') uniforms.uYear.value = Math.max(y, uniforms.uYearFrom.value + 1);
  else uniforms.uYearFrom.value = Math.min(y, uniforms.uYear.value - 1);
  drawHist();
}

// Playback: fast over the sparse centuries, slow over the densely built ones.
let playing = false, playT0 = 0, playStart = 0;
const playBtn = document.getElementById('play');
const playIcon = document.getElementById('play-icon');
const DURATION = (+new URLSearchParams(location.search).get('film') || 30) * 1000;   // ?film=6: short film
function playYear(tt) {
  const k = 0.35;
  return tt < k ? T0 + (1850 - T0) * (tt / k) : 1850 + (config.yearMax - 1850) * ((tt - k) / (1 - k));
}
function startPlay() {
  playing = true; playStart = performance.now();
  if (uniforms.uYear.value >= config.yearMax) uniforms.uYear.value = T0;
  playT0 = 0;
  while (playT0 < 1 && playYear(playT0) < uniforms.uYear.value) playT0 += 0.001;
  playIcon.setAttribute('d', 'M4 2.5h3v11H4zM9 2.5h3v11H9z');
  uniforms.uPlaying.value = 1;
}
function stopPlay() {
  playing = false;
  uniforms.uPlaying.value = 0;
  uniforms.uRise.value = 0.01;
  uniforms.uYear.value = Math.round(uniforms.uYear.value);
  playIcon.setAttribute('d', 'M4 2.5v11l9-5.5z');
}
playBtn.onclick = () => (playing ? stopPlay() : startPlay());

// ---------- Loop ----------
function resize() {
  const w = innerWidth, h = innerHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  drawHist();
}
addEventListener('resize', resize);

setMode(MODE.period);
alkalmazSzoveg();
resize();

let frame = 0, elozoIdo = 0, lassuDb = 0, pixelKicsi = false;
renderer.setAnimationLoop(now => {
  frame++;
  // the damping (inertia) is per frame, so on a slow machine (low fps) the camera would glide for a long time: it is tied to time, and with persistently slow rendering the pixel ratio is set to 1
  const dt = elozoIdo ? Math.min(0.25, (now - elozoIdo) / 1000) : 1 / 60; elozoIdo = now;
  controls.dampingFactor = Math.min(0.4, 1 - Math.pow(0.95, Math.max(1, dt * 60)));
  lassuDb = dt > 0.04 ? lassuDb + 1 : Math.max(0, lassuDb - 1);
  if (lassuDb > 40 && !pixelKicsi && renderer.getPixelRatio() > 1) { pixelKicsi = true; renderer.setPixelRatio(1); resize(); }
  uniforms.uNow.value = now / 1000;
  controls.update();
  const dist = camera.position.distanceTo(controls.target);
  uniforms.uFog.value.set(dist * 1.6, dist * 4);
  if (playing) {
    const tt = Math.min(1, playT0 + (now - playStart) / DURATION);
    uniforms.uYear.value = playYear(tt);
    uniforms.uRise.value = Math.max(2, playYear(Math.min(1, tt + 800 / DURATION)) - playYear(tt));
    if (tt >= 1) stopPlay();
    drawHist();
  }
  hidFrissit();
  if (pointer && !dragging && frame % 3 === 0) {
    const gid = pick(pointer[0], pointer[1]);
    uniforms.uHover.value = gid;
    uniforms.uHoverGrp.value = (gid >= 0 && grpIdx[gid]) || 0;
    mutat(gid, pointer[0], pointer[1]);
  }
  renderer.render(scene, camera);
});

// ---------- Edit mode (only alongside py editor_server.py, http://localhost:8000/terkep3d/index.html) ----------
// Corrections go into forras/kezi_javitasok.csv (the same as on the 2D map); the "Rebuild" button rebuilds the whole city.
let szerkeszto = false, szerkFuggo = 0;
const SZERK_MEZOK = [
  { mezo: 'nev', cimke: 'Az épület neve (üresen hagyva eltávolítja)', tipus: 'text', torlheto: true },
  { mezo: 'ev', cimke: 'Építési év', tipus: 'number' },
  { mezo: 'tervezo', cimke: 'Tervező (üresen hagyva eltávolítja)', tipus: 'text', torlheto: true },
  { mezo: 'stilus', cimke: 'Stílus (több esetén vesszővel elválasztva, pl. neobarokk, art déco; üresen hagyva eltávolítja)', tipus: 'text', torlheto: true },
  { mezo: 'korszak', cimke: 'Korszak (ha az évet nem tudom; a becslést és a színt is befolyásolja)', tipus: 'select', torlheto: true, korszakValaszto: true },
  { mezo: 'szintek', cimke: 'Szintszám', tipus: 'number' },
  { mezo: 'magassag', cimke: 'Magasság (m)', tipus: 'number' },
  { mezo: 'vedettseg', cimke: 'Védettség', tipus: 'select', torlheto: true,
    opciok: [['', '– nincs megadva / eltávolítás –'], ['M', 'M – műemlék'], ['HV', 'HV – helyi védelem'], ['MJ', 'MJ – műemlék jellegű'], ['VK', 'VK – városképi jelentőségű'], ['MK', 'MK – műemléki környezet'], ['MJT', 'MJT – műemléki jelentőségű terület']] },
  { mezo: 'muemlek_torzsszam', cimke: 'Műemléki törzsszám (üresen hagyva eltávolítja)', tipus: 'number', torlheto: true },
  { mezo: 'about', cimke: 'Leírás / megjegyzés (legfeljebb 1500 karakter; üresen hagyva eltávolítja)', tipus: 'textarea', torlheto: true },
  { mezo: 'wikipedia', cimke: 'Wikipédia-cikk (link vagy hu:Cím; több: | jellel; üresen hagyva eltávolítja)', tipus: 'text', torlheto: true },
  { mezo: 'commons_kep', cimke: 'Commons-fotó (a Commons fájl-oldalának linkje; az éppen látszó Commons-kép linkje előre kitöltve; üresen hagyva eltávolítja a kézi választást; „nincs” = az épületnél egyáltalán nem jelenik meg fotó)', tipus: 'text', torlheto: true },
  { mezo: 'linkek', cimke: 'Linkek (soronként egy; elé írható felirat: „Projektoldal | https://…”; pl. építész projektoldala, Budapest Legenda; üresen hagyva eltávolítja)', tipus: 'textarea', torlheto: true },
  { mezo: 'kepek_linkek', cimke: 'Képek (a galériába: évszám, forrás/szerző és a közvetlen képlink; Fortepan-linknél a Kiolvasás gomb megpróbálja kitölteni; a sorok törlésével eltávolíthatók)', tipus: 'kepsorok', torlheto: true },
  { mezo: 'budapest100_url', cimke: 'Budapest100-oldal (a budapest100.hu címe; üresen hagyva eltávolítja)', tipus: 'text', torlheto: true },
];
const szerkStilus = document.createElement('style');
szerkStilus.textContent = `.szerk-urlap label{display:block;margin:6px 0;font-size:12px}.szerk-urlap input,.szerk-urlap select,.szerk-urlap textarea{display:block;width:95%;box-sizing:border-box;margin-top:2px}
.szerk-uzenet{font-size:12px;margin-top:6px}.szerk-hiba{color:#b00020}.szerk-ok{color:#1b6e2d}.szerk-gomb{cursor:pointer}`;
document.head.appendChild(szerkStilus);

async function szerkKuldes(url, adat) {
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Szerkeszto': '1' }, body: JSON.stringify(adat) });
  let v = {};
  try { v = await r.json(); } catch (e) { /* not JSON */ }
  if (!r.ok || !v.ok) throw new Error(v.hiba || 'A mentés nem sikerült.');
  return v;
}

function kartyaUjra() {
  if (rogzitettGid < 0) return;
  kartya.innerHTML = kartyaHtml(epuletek[rogzitettGid], true);
  kartya.querySelector('.kartya-bezar').addEventListener('click', bezar);
  wikiBetolt(rogzitettGid);
  kepBetolt(rogzitettGid);
  szerkGomb(rogzitettGid);
}

function szerkGomb(gid) {
  if (!szerkeszto || rogzitettGid !== gid || (epuletek[gid] && epuletek[gid].hid)) return;
  const sec = document.createElement('section');
  const gomb = document.createElement('button');
  gomb.type = 'button'; gomb.className = 'szerk-gomb'; gomb.textContent = 'Szerkesztés';
  gomb.addEventListener('click', () => szerkUrlap(gid));
  sec.appendChild(gomb);
  const p = epuletek[gid];
  if (p && String(p.oeny_azonosito || '').trim()) {
    const oenyGomb = document.createElement('button');
    oenyGomb.type = 'button'; oenyGomb.className = 'szerk-gomb'; oenyGomb.style.marginLeft = '6px';
    oenyGomb.textContent = 'OENY-adatok levétele';
    const uz = document.createElement('div'); uz.className = 'szerk-uzenet';
    oenyGomb.addEventListener('click', () => oenyLevetel(gid, oenyGomb, uz));
    sec.append(oenyGomb, uz);
  }
  if (parAktiv && p) {
    const pg = document.createElement('button');
    pg.type = 'button'; pg.className = 'szerk-gomb'; pg.style.cssText = 'display:block;margin-top:6px;background:#2a7;color:#fff';
    pg.textContent = `Párosítás: ${parAktiv.a} ← ez az épület`;
    const uz = document.createElement('div'); uz.className = 'szerk-uzenet';
    pg.addEventListener('click', () => parositas(gid, pg, uz));
    sec.append(pg, uz);
  }
  if (ertAktiv && p) {
    const eg = document.createElement('button');
    eg.type = 'button'; eg.className = 'szerk-gomb'; eg.style.cssText = 'display:block;margin-top:6px;background:#2a7;color:#fff';
    eg.textContent = `Értékleltár: „${ertAktiv.cim}” ← ez az épület`;
    const uz = document.createElement('div'); uz.className = 'szerk-uzenet';
    eg.addEventListener('click', () => ertDontes(ertAktiv, `${p.osm_tipus || 'way'} ${p.id}`, 'ellenőrizve (térképen kijelölve)', eg, uz));
    sec.append(eg, uz);
  }
  kartya.appendChild(sec);
}

// Removing E-Örökség (OENY) data from the building: the server writes it to forras/oeny_kizart.csv, and it disappears for good after the rebuild.
async function oenyLevetel(gid, gomb, uzenet) {
  const p = epuletek[gid];
  const lista = String(p.oeny_azonosito || '').split('|').filter(Boolean).join(', ');
  const kuld = async (extra, szoveg) => {
    if (!confirm(szoveg)) return;
    gomb.disabled = true;
    try {
      await szerkKuldes('/api/oeny_levetel', { osm_tipus: p.osm_tipus || 'way', id: p.id, ...extra });
      if (!extra.egy) { delete p.oeny_azonosito; delete p.muemlek_torzsszam; if (p.vedettseg && p.vedettseg !== 'HV') delete p.vedettseg; }
      else { szerkAllapot('Az adatlap levétele elmentve – az újraépítés után tűnik el.', 'ok'); }
      szerkFuggo++;
      szerkAllapot(`${szerkFuggo} mentett javítás vár újraépítésre.`, 'ok');
      kartyaUjra();
    } catch (hiba) {
      uzenet.className = 'szerk-uzenet szerk-hiba'; uzenet.textContent = hiba.message;
      gomb.disabled = false;
    }
  };
  // if several data sheets (register numbers) are tied to the building, they can be removed one by one
  let adatlapok = [];
  try {
    const v = await (await fetch(`/api/oeny_lista?tipus=${encodeURIComponent(p.osm_tipus || 'way')}&id=${encodeURIComponent(p.id)}`, { cache: 'no-store' })).json();
    adatlapok = (v && v.adatlapok) || [];
  } catch (e) { /* old server: the full removal stays */ }
  if (adatlapok.length < 2) {
    return kuld({ torzsszam: p.muemlek_torzsszam || '' }, `Levegyed az E-Örökség (OENY) adatokat erről az épületről?\n\nAdatlap: ${lista}${p.muemlek_torzsszam ? ', törzsszám: ' + p.muemlek_torzsszam : ''}\n\nAz adatlap-hivatkozás, a törzsszám, a műemléki védettség és az OENY-ből jövő adatok (év, tervező) tűnnek el az újraépítés után. Más forrás adatai megmaradnak.`);
  }
  uzenet.className = 'szerk-uzenet'; uzenet.textContent = '';
  const doboz = document.createElement('div'); doboz.style.cssText = 'margin-top:6px';
  doboz.append('Melyiket vegyem le?');
  for (const a of adatlapok) {
    const b = document.createElement('button'); b.type = 'button'; b.className = 'szerk-gomb'; b.style.cssText = 'display:block;margin-top:3px;text-align:left';
    const leir = [a.adatlap.length ? 'adatlap ' + a.adatlap.join(', ') : '', a.ev.length ? 'év ' + a.ev.join('/') : '', a.tervezo.length ? a.tervezo.join(', ') : ''].filter(Boolean).join(' · ');
    b.textContent = `Törzsszám ${a.torzsszam}${leir ? ' – ' + leir : ''}`;
    b.addEventListener('click', () => kuld({ torzsszam: a.torzsszam, egy: true }, `Csak a ${a.torzsszam} törzsszámú OENY-adatlapot veszed le erről az épületről? A többi adatlap megmarad.`));
    doboz.appendChild(b);
  }
  const mind = document.createElement('button'); mind.type = 'button'; mind.className = 'szerk-gomb'; mind.style.cssText = 'display:block;margin-top:6px';
  mind.textContent = 'Mindet levenni';
  mind.addEventListener('click', () => kuld({ torzsszam: p.muemlek_torzsszam || '' }, `Az összes (${adatlapok.length}) OENY-adatlapot levegyed erről az épületről?`));
  doboz.appendChild(mind);
  uzenet.appendChild(doboz);
}

// Line-by-line editor of image links: Year | Source / author | Link (+ Read-out for a Fortepan link). Stored as "Year – Source | link" per line (the gallery takes its label and caption from this).
function kepSorokSzerkeszto(lab, ertek) {
  const rejtett = document.createElement('input'); rejtett.type = 'hidden';
  const lista = document.createElement('div'); lista.className = 'kepsorok';
  const tiszta = x => x.replace(/[|<>"\n\r]/g, ' ').trim();
  const kiir = () => {
    rejtett.value = [...lista.children].map(sor => {
      const [ev, fo, ln] = [...sor.querySelectorAll('input')].map(i => i.value.trim());
      if (!ln) return '';
      const fel = [tiszta(ev), tiszta(fo)].filter(Boolean).join(' – ');
      return (fel ? fel + ' | ' : '') + ln;
    }).filter(Boolean).join('\n');
  };
  const sorHozzaad = (ev, fo, ln) => {
    const sor = document.createElement('div'); sor.className = 'kepsor';
    sor.innerHTML = '<input class="ks-ev" placeholder="Év" maxlength="4" inputmode="numeric"><input class="ks-fo" placeholder="Forrás / szerző (pl. Fortepan / Donor neve)" maxlength="70"><input class="ks-ln" placeholder="https://… közvetlen képlink"><button type="button" class="ks-ki" title="Év és adományozó kiolvasása a Fortepan oldalról" hidden>Kiolvasás</button><button type="button" class="ks-torol" title="Sor törlése">×</button>';
    const [e, f, l] = sor.querySelectorAll('input');
    e.value = ev || ''; f.value = fo || ''; l.value = ln || '';
    const ki = sor.querySelector('.ks-ki');
    const lathato = () => { ki.hidden = !/fortepan_\d+/i.test(l.value); };
    lathato();
    sor.addEventListener('input', () => { lathato(); kiir(); });
    ki.addEventListener('click', async () => {
      ki.disabled = true; const cimke = ki.textContent; ki.textContent = '…';
      try {
        const r = await (await fetch('/api/kep_adat?url=' + encodeURIComponent(l.value.trim()))).json();
        if (r.ok) { if (r.ev && !e.value) e.value = r.ev; if (!f.value) f.value = r.szerzo || r.adomanyozo || ''; kiir(); ki.textContent = '✓'; }
        else { ki.textContent = cimke; alert(r.hiba || 'Nem sikerült kiolvasni.'); }
      } catch (x) { ki.textContent = cimke; alert('Nem sikerült kiolvasni (fut a szerkesztő-szerver?).'); }
      ki.disabled = false;
    });
    sor.querySelector('.ks-torol').addEventListener('click', () => { sor.remove(); kiir(); });
    lista.appendChild(sor);
  };
  String(ertek || '').split('\n').map(x => x.trim()).filter(Boolean).forEach(s => {
    const i = s.lastIndexOf('|'), fel = i >= 0 ? s.slice(0, i).trim() : '', ln = s.slice(i + 1).trim();
    const m = /^(1[5-9]\d\d|20[0-3]\d)(?:\s*[–-]\s*(.*))?$/.exec(fel);
    sorHozzaad(m ? m[1] : '', m ? (m[2] || '') : fel, ln);
  });
  const uj = document.createElement('button'); uj.type = 'button'; uj.textContent = '+ Kép hozzáadása'; uj.className = 'szerk-gomb';
  uj.addEventListener('click', () => sorHozzaad('', '', ''));
  lab.append(lista, uj, rejtett);
  rejtett.value = ''; kiir();
  return rejtett;
}

function szerkUrlap(gid) {
  const p = epuletek[gid];
  const urlap = document.createElement('div');
  urlap.className = 'szerk-urlap';
  const cim = document.createElement('strong');
  cim.textContent = 'Szerkesztés: ' + (p.nev || p.lechner_nev || p.nev_kozepulet || p.cim || ((p.osm_tipus || 'way') + ' ' + p.id));
  urlap.appendChild(cim);
  const mezok = {};
  SZERK_MEZOK.forEach(m => {
    const lab = document.createElement('label');
    lab.textContent = m.cimke;
    let inp;
    if (m.tipus === 'kepsorok') {
      inp = kepSorokSzerkeszto(lab, p[m.mezo]);
    } else if (m.tipus === 'select') {
      inp = document.createElement('select');
      const opciok = m.korszakValaszto ? [['', '– nincs megadva / eltávolítás –']].concat(periods.map((q, i) => q.to === 0 ? null : [String(i), korNev(i)]).filter(Boolean)) : m.opciok;
      opciok.forEach(([ertek, felirat]) => { const o = document.createElement('option'); o.value = ertek; o.textContent = felirat; inp.appendChild(o); });
    } else if (m.tipus === 'textarea') {
      inp = document.createElement('textarea'); inp.rows = 5; inp.maxLength = 1500;
    } else {
      inp = document.createElement('input'); inp.type = m.tipus;
      if (m.tipus === 'number') inp.step = 'any';
    }
    const v = m.korszakValaszto ? (p.ev_kozelito_forras === 'kezi' ? String(Math.max(-1, periods.findIndex(q => q.to !== 0 && +p.ev_kozelito_tol >= q.from && +p.ev_kozelito_tol <= q.to))).replace('-1', '') : '') : p[m.mezo];
    const eredeti = (v === undefined || v === null || v === '') ? '' : String(m.mezo === 'magassag' ? Math.round(v) : v);
    if (m.tipus !== 'kepsorok') { inp.value = eredeti; lab.appendChild(inp); } else { inp.value = eredeti; }
    urlap.appendChild(lab);
    mezok[m.mezo] = { inp, eredeti, m };
  });
  const ck = mezok.commons_kep;   // if a Commons photo is currently shown on the card, its link is pre-filled and can be overwritten with a better one
  if (ck && !ck.inp.value && kepGyorsitotar.has(gid)) {
    kepGyorsitotar.get(gid).then(k => {
      if (k && /^https:\/\/commons\.wikimedia\.org\//.test(k.lap || '') && !ck.inp.value) { ck.inp.value = k.lap; ck.eredeti = k.lap; }
    }).catch(() => {});
  }
  const forrasLab = document.createElement('label');
  forrasLab.textContent = 'Forrás (kötelező)';
  const forras = document.createElement('input');
  forras.type = 'text'; forras.placeholder = 'pl. Időgép, 1944-es lakásív, hrsz. 24576';
  forrasLab.appendChild(forras);
  urlap.appendChild(forrasLab);
  const mentes = document.createElement('button'); mentes.type = 'button'; mentes.textContent = 'Mentés';
  const megse = document.createElement('button'); megse.type = 'button'; megse.textContent = 'Mégse'; megse.style.marginLeft = '6px';
  const uzenet = document.createElement('div'); uzenet.className = 'szerk-uzenet';
  urlap.append(mentes, megse, uzenet);
  megse.addEventListener('click', kartyaUjra);
  mentes.addEventListener('click', async () => {
    const valtozott = Object.values(mezok).filter(o => o.inp.value.trim() !== o.eredeti);
    uzenet.className = 'szerk-uzenet';
    if (!valtozott.length) { uzenet.textContent = 'Nem változtattál semmit.'; return; }
    if (!forras.value.trim()) { uzenet.className = 'szerk-uzenet szerk-hiba'; uzenet.textContent = 'Add meg a forrást.'; return; }
    mentes.disabled = true;
    try {
      for (const o of valtozott) {
        const ertek = o.inp.value.trim();
        if (ertek === '' && !o.m.torlheto) throw new Error(`A(z) ${o.m.cimke} nem lehet üres (törlés nem támogatott).`);
        if (o.m.korszakValaszto) {
          await szerkKuldes('/api/korszak', { osm_tipus: p.osm_tipus || 'way', id: p.id, korszak: ertek, megjegyzes: forras.value.trim() });
          if (ertek === '') { if (p.ev_kozelito_forras === 'kezi') { delete p.ev_kozelito_tol; delete p.ev_kozelito_ig; delete p.ev_kozelito_forras; delete p.ev_kozelito_szoveg; } }
          else if (!p.ev) { p.ev_kozelito_tol = periods[+ertek].from; p.ev_kozelito_ig = Math.min(periods[+ertek].to, 2026); p.ev_kozelito_forras = 'kezi'; p.ev_kozelito_szoveg = 'kézi korszak: ' + korNev(+ertek); }
          szerkFuggo++;
          continue;
        }
        await szerkKuldes('/api/javitas', { osm_tipus: p.osm_tipus || 'way', id: p.id, mezo: o.m.mezo, ertek: ertek === '' ? '-' : ertek, megjegyzes: forras.value.trim() });
        if (ertek === '') delete p[o.m.mezo];
        else p[o.m.mezo] = o.m.tipus === 'number' ? +ertek : (o.m.mezo === 'budapest100_url' ? ertek.replace(/^(?:https?:\/\/)?(?:www\.)?/i, 'https://') : ertek);
        if (o.m.mezo === 'wikipedia') delete p.wikipedia_zona;
        if (o.m.mezo === 'commons_kep') kepGyorsitotar.delete(gid);   // the new photo has to be requested again
        szerkFuggo++;
      }
      szerkAllapot(`${szerkFuggo} mentett javítás vár újraépítésre.`, 'ok');
      kartyaUjra();
    } catch (hiba) {
      uzenet.className = 'szerk-uzenet szerk-hiba'; uzenet.textContent = hiba.message;
    } finally { mentes.disabled = false; }
  });
  kartya.replaceChildren(urlap);
  kartyaHelye(parseFloat(kartya.style.left) - 18, parseFloat(kartya.style.top) - 18);   // the form is taller: keep the card on screen
}

function szerkAllapot(szoveg, osztaly) {
  const el = document.getElementById('szerk-allapot');
  if (el) { el.textContent = szoveg; el.className = 'szerk-uzenet' + (osztaly ? ' szerk-' + osztaly : ''); }
}

// ---------- New work (not a building: public installation, statue, etc.): a point on the map -> small manual item (forras/kezi_epuletek.geojson) ----------
// When an architect is highlighted, the item is highlighted together with their buildings by the "Designer" field (the name must match the name in the architect list).
let alkotasMod = false, alkotasJelolo = null, alkotasHely = null;
function alkotasPont(cx, cy) {
  if (!terepMesh) { szerkAllapot('A domborzat még nem töltődött be, próbáld újra.', 'hiba'); return; }
  const r = canvas.getBoundingClientRect();
  const rc = new THREE.Raycaster();
  rc.setFromCamera(new THREE.Vector2((cx - r.left) / r.width * 2 - 1, -((cy - r.top) / r.height) * 2 + 1), camera);
  const h = rc.intersectObject(terepMesh, false)[0];
  if (!h) { szerkAllapot('Itt nem találtam a terepet, kattints máshova.', 'hiba'); return; }
  const lon = LON0 + h.point.x / (COSLAT * 111320), lat = LAT0 - h.point.z / 110574;
  alkotasHely = { lat: +lat.toFixed(6), lon: +lon.toFixed(6) };
  if (!alkotasJelolo) {
    alkotasJelolo = new THREE.Mesh(new THREE.SphereGeometry(5, 16, 12), new THREE.MeshBasicMaterial({ color: 0xe0245e }));
    scene.add(alkotasJelolo);
  }
  alkotasJelolo.position.set(h.point.x, h.point.y + 5, h.point.z);
  const la = document.getElementById('alk-lat'), lo = document.getElementById('alk-lon');
  if (la && lo) { la.value = alkotasHely.lat; lo.value = alkotasHely.lon; }
  const u = document.getElementById('alk-urlap');
  if (u) u.hidden = false;
  szerkAllapot('Pont kijelölve. Töltsd ki az adatokat, és mentsd el; kattintással áthelyezheted a pontot.', 'ok');
}
function alkotasPanel(doboz) {
  const d = document.createElement('div');
  d.innerHTML = '<hr><strong>Új alkotás (nem épület)</strong><br><small>Köztéri installáció, szobor stb.: kattints a térképen a helyére, majd töltsd ki az adatokat. Az Újraépítés után kis jelölőként látszik, és az alkotó kiemelésénél együtt kiemelődik az épületeivel.</small><br>'
    + '<button type="button" id="alk-kezd">Új alkotás kijelölése a térképen</button>'
    + '<form id="alk-urlap" class="szerk-urlap" hidden>'
    + '<label>Az alkotás neve<input id="alk-nev" maxlength="120" required></label>'
    + '<label>Alkotó (az építész-listabeli névvel egyezően, pl. Szabó Levente)<input id="alk-tervezo" maxlength="100" required></label>'
    + '<label>Év<input id="alk-ev" type="number" min="1000" max="2100" required></label>'
    + '<label>Leírás (legfeljebb 1500 karakter)<textarea id="alk-about" rows="4" maxlength="1500"></textarea></label>'
    + '<label>Fotó (közvetlen https:// képlink)<input id="alk-kep" type="url" maxlength="400"></label>'
    + '<label>Link (a fotóra kattintva ide visz; pl. az alkotás vagy az alkotó oldala)<input id="alk-link" type="url" maxlength="400"></label>'
    + '<label>Szélesség (lat)<input id="alk-lat" type="number" step="any"></label><label>Hosszúság (lon)<input id="alk-lon" type="number" step="any"></label>'
    + '<button type="submit">Mentés</button> <button type="button" id="alk-megse">Mégse</button></form>';
  doboz.appendChild(d);
  const ki = () => { alkotasMod = false; canvas.style.cursor = ''; document.getElementById('alk-kezd').textContent = 'Új alkotás kijelölése a térképen'; };
  const zar = () => {
    ki(); alkotasHely = null;
    document.getElementById('alk-urlap').hidden = true; document.getElementById('alk-urlap').reset();
    if (alkotasJelolo) { scene.remove(alkotasJelolo); alkotasJelolo = null; }
  };
  d.querySelector('#alk-kezd').addEventListener('click', e => {
    alkotasMod = !alkotasMod;
    e.currentTarget.textContent = alkotasMod ? 'Kijelölés kikapcsolása' : 'Új alkotás kijelölése a térképen';
    canvas.style.cursor = alkotasMod ? 'crosshair' : '';
    if (alkotasMod) szerkAllapot('Kattints a térképen az alkotás helyére.');
  });
  d.querySelector('#alk-megse').addEventListener('click', zar);
  for (const id of ['alk-lat', 'alk-lon']) d.querySelector('#' + id).addEventListener('change', () => {
    const la = parseFloat(document.getElementById('alk-lat').value), lo = parseFloat(document.getElementById('alk-lon').value);
    if (!isFinite(la) || !isFinite(lo)) return;
    alkotasHely = { lat: la, lon: lo };
    if (alkotasJelolo) alkotasJelolo.position.set((lo - LON0) * COSLAT * 111320, alkotasJelolo.position.y, -(la - LAT0) * 110574);
  });
  d.querySelector('#alk-urlap').addEventListener('submit', async ev => {
    ev.preventDefault();
    if (!alkotasHely) { szerkAllapot('Előbb jelöld ki a pontot a térképen.', 'hiba'); return; }
    const v = id => document.getElementById(id).value.trim();
    const gomb = ev.submitter || d.querySelector('button[type=submit]');
    gomb.disabled = true;
    try {
      const r = await szerkKuldes('/api/uj_alkotas', { nev: v('alk-nev'), tervezo: v('alk-tervezo'), ev: v('alk-ev'), about: v('alk-about'),
        kep_url: v('alk-kep'), link_url: v('alk-link'), lat: alkotasHely.lat, lon: alkotasHely.lon });
      szerkFuggo++;
      zar();
      szerkAllapot(`Felvéve (${r.kulcs}). Az „Újraépítés” után látszik; az építész kiemelésekor a Tervező név alapján együtt kiemelődik az épületeivel.`, 'ok');
    } catch (hiba) {
      szerkAllapot(hiba.message, 'hiba');
    } finally { gomb.disabled = false; }
  });
}

function szerkPanel() {
  const hely = document.querySelector('.tally');
  if (!hely) return;
  const keret = document.createElement('div');
  keret.className = 'szerk-keret';
  const fej = document.createElement('button');
  fej.type = 'button'; fej.className = 'szerk-fej'; fej.textContent = 'Szerkesztés ▾';
  const doboz = document.createElement('div');
  doboz.className = 'szerk-doboz'; doboz.hidden = true;
  fej.addEventListener('click', () => {
    doboz.hidden = !doboz.hidden;
    fej.textContent = doboz.hidden ? 'Szerkesztés ▾' : 'Szerkesztés ▴';
  });
  keret.append(fej, doboz);
  hely.appendChild(keret);
  doboz.innerHTML = '<strong>Szerkesztési mód</strong><br><small>Kattints egy épületre, majd „Szerkesztés". A javítások az újraépítés után látszanak.<br><b>Figyelem:</b> a kézi korszak vagy évszám színhatásához (a becslés újraszámolásához) a teljes frissítés kell: futtasd a <code>zones_refresh.bat</code> fájlt, majd Ctrl+Shift+R. Az alábbi gomb ezt nem futtatja.</small><br>'
    + '<button type="button" id="szerk-ujraepit">Újraépítés (egész város)</button><div id="szerk-allapot" class="szerk-uzenet"></div>';
  alkotasPanel(doboz);
  doboz.querySelector('#szerk-ujraepit').addEventListener('click', async e => {
    const gomb = e.currentTarget;
    gomb.disabled = true;
    szerkAllapot('Újraépítés folyamatban… (az egész városra több percig is tarthat, az ablakot hagyd nyitva)');
    try {
      const v = await szerkKuldes('/api/ujraepit', { varos: true });
      if (v.harom_d !== 'ok') throw new Error('Az adatok megépültek, de a 3D csempék elkészítése hibázott: ' + v.harom_d);
      szerkFuggo = 0;
      szerkAllapot('Kész. Töltsd újra az oldalt (Ctrl+Shift+R). Ha kézi korszakot vagy évszámot adtál meg, a színéhez futtasd a zones_refresh.bat-ot: ez a gomb a becslést (year_estimate.py) nem számolja újra.', 'ok');
    } catch (hiba) {
      szerkAllapot(hiba.message, 'hiba');
    } finally { gomb.disabled = false; }
  });
}

// Heritage-inventory check: reviewing the rows of forras/ertekleltar_kezi_parositas.csv (recommended candidates, manual decision, manually given OSM element)
let ertSorok = null, ertAktiv = null, ertSzuro = 'nyitott', ertPoz = 0;
function ertJeloltek(r) {
  const out = [], re = /(way|relation) (\d+) \((\d+) m(, saroképület)?\)/g;
  let m;
  while ((m = re.exec(r.jeloltek || ''))) out.push({ tip: m[1], id: m[2], tav: m[3], sarok: !!m[4] });
  return out;
}
const ertNyitott = r => !String(r.osm_azonosito || '').trim() && !String(r.megjegyzes || '').trim();
function ertLista() {
  const kerSzuro = document.getElementById('ert-ker').value;
  return ertSorok.filter(r => {
    if (kerSzuro && r.kerulet !== kerSzuro) return false;
    if (ertSzuro === 'nyitott') return ertNyitott(r);
    if (ertSzuro === 'dontott') return !ertNyitott(r);
    if (ertSzuro === 'valoszinu') return ertNyitott(r) && /^valószínű/.test(r.allapot);
    if (ertSzuro === 'jeloltes') return ertNyitott(r) && /^bizonytalan/.test(r.allapot);
    if (ertSzuro === 'nincs') return ertNyitott(r) && /^(nincs|ismeretlen)/.test(r.allapot);
    return true;
  });
}
async function ertDontes(r, osm, megj, gomb, uzenet) {
  if (gomb) gomb.disabled = true;
  try {
    await szerkKuldes('/api/ertekleltar_dontes', { index: ertSorok.indexOf(r), kerulet: r.kerulet, cim: r.cim, hrsz: r.hrsz, osm_azonosito: osm, megjegyzes: megj });
    r.osm_azonosito = osm; r.megjegyzes = megj;
    szerkFuggo++;
    szerkAllapot(`Döntés mentve (forras/ertekleltar_kezi_parositas.csv). A tények a „py facts_corner.py” + zones_refresh.bat futtatása után látszanak.`, 'ok');
    ertAktiv = null;
    const lista = ertLista();
    if (ertPoz >= lista.length) ertPoz = Math.max(0, lista.length - 1);
    ertRender();
    if (rogzitettGid >= 0) kartyaUjra();
  } catch (hiba) {
    if (uzenet) { uzenet.className = 'szerk-uzenet szerk-hiba'; uzenet.textContent = hiba.message; } else szerkAllapot(hiba.message, 'hiba');
    if (gomb) gomb.disabled = false;
  }
}
function ertRender() {
  const doboz = document.getElementById('ert-doboz');
  if (!doboz || !ertSorok) return;
  const lista = ertLista(), idx = archGidIndex();
  document.getElementById('ert-db').textContent = `${lista.length ? ertPoz + 1 : 0} / ${lista.length} (nyitott az egészben: ${ertSorok.filter(ertNyitott).length})`;
  const hely = document.getElementById('ert-sor');
  hely.innerHTML = '';
  const r = lista[ertPoz];
  if (!r) { hely.textContent = 'Nincs sor ezzel a szűrővel.'; ertAktiv = null; return; }
  ertAktiv = r;
  const fej = document.createElement('div');
  fej.innerHTML = `<b>${esc(r.cim)}</b> <small>(${esc(r.kerulet)}. ker.${r.hrsz ? ', hrsz ' + esc(r.hrsz) : ''})</small><br>`
    + `<small>${r.epites_ideje ? 'Építés: ' + esc(r.epites_ideje) + '. ' : ''}${r.tervezo ? 'Tervező: ' + esc(r.tervezo) + '. ' : ''}Állapot: ${esc(r.allapot)}</small>`
    + (ertNyitott(r) ? '' : `<br><small>Döntés: <b>${esc(r.osm_azonosito || '–')}</b> ${esc(r.megjegyzes)}</small>`);
  hely.appendChild(fej);
  const mez = document.createElement('div'); mez.style.cssText = 'margin-top:4px;display:flex;flex-wrap:wrap;gap:4px';
  const jel = ertJeloltek(r);
  const javasolt = String(r.javasolt_osm || '').trim();
  jel.forEach((c, n) => {
    const g = idx.get((c.tip === 'relation' ? 'r' : 'w') + c.id);
    const b = document.createElement('button'); b.type = 'button'; b.className = 'szerk-gomb';
    const p = g && epuletek[g[0]];
    b.textContent = `${javasolt === c.tip + ' ' + c.id ? '★ ' : ''}${n + 1}. ${p ? String(p.cim || p.nev || c.id).slice(0, 26) : c.id} · ${c.tav} m${c.sarok ? ' · sarok' : ''}`;
    b.title = `${c.tip} ${c.id}: ugrás az épületre`;
    b.addEventListener('click', () => { if (g) repulj(g[0]); ertJeloltKivalasztva = c; ertAktivJelolt(); });
    mez.appendChild(b);
  });
  if (!jel.length) { const k = document.createElement('small'); k.textContent = 'Nincs automatikus jelölt: kattints a térképen az épületre, vagy add meg az azonosítóját.'; mez.appendChild(k); }
  hely.appendChild(mez);
  const muv = document.createElement('div'); muv.style.marginTop = '6px';
  muv.innerHTML = '<div id="ert-kijelolt" style="margin-bottom:4px"></div>';
  const elfogad = document.createElement('button'); elfogad.type = 'button'; elfogad.className = 'szerk-gomb'; elfogad.id = 'ert-elfogad'; elfogad.textContent = 'Elfogadom a kijelölt jelöltet'; elfogad.disabled = true;
  elfogad.style.cssText = 'background:#2a7;color:#fff';
  elfogad.addEventListener('click', () => { if (ertJeloltKivalasztva) ertDontes(r, `${ertJeloltKivalasztva.tip} ${ertJeloltKivalasztva.id}`, 'ellenőrizve (jelölt elfogadva)', elfogad); });
  const kihagy = document.createElement('button'); kihagy.type = 'button'; kihagy.className = 'szerk-gomb'; kihagy.textContent = 'Nem párosítható'; kihagy.style.marginLeft = '4px';
  kihagy.addEventListener('click', () => ertDontes(r, '', 'nem párosítható', kihagy));
  muv.append(elfogad, kihagy);
  if (!ertNyitott(r)) {
    const vissza = document.createElement('button'); vissza.type = 'button'; vissza.className = 'szerk-gomb'; vissza.textContent = 'Döntés visszavonása'; vissza.style.marginLeft = '4px';
    vissza.addEventListener('click', () => ertDontes(r, '', '', vissza));
    muv.appendChild(vissza);
  }
  const kez = document.createElement('div'); kez.style.marginTop = '4px';
  kez.innerHTML = '<input id="ert-kez" placeholder="vagy OSM-elem(ek): way 123 | way 456" style="width:60%"> ';
  const kezGomb = document.createElement('button'); kezGomb.type = 'button'; kezGomb.className = 'szerk-gomb'; kezGomb.textContent = 'Megad';
  kezGomb.addEventListener('click', () => {
    const m = /(?:(way|relation)[\/ :]*)?(\d{3,})/i.exec(document.getElementById('ert-kez').value);
    if (!m) { szerkAllapot('Adj meg egy OSM-azonosítót (pl. way 271003349 vagy az OSM-oldal linkje).', 'hiba'); return; }
    const c = { tip: (m[1] || 'way').toLowerCase(), id: m[2], tav: '?', sarok: false };
    const g = idx.get((c.tip === 'relation' ? 'r' : 'w') + c.id);
    if (!g) { szerkAllapot(`Nincs ilyen épület a térképen: ${c.tip} ${c.id}`, 'hiba'); return; }
    ertJeloltKivalasztva = c; repulj(g[0]); ertAktivJelolt();
  });
  kez.appendChild(kezGomb);
  muv.appendChild(kez);
  hely.appendChild(muv);
  ertJeloltKivalasztva = null;
  const els = javasolt && jel.find(c => c.tip + ' ' + c.id === javasolt);
  if (els && ertNyitott(r)) { ertJeloltKivalasztva = els; ertAktivJelolt(); }
}
let ertJeloltKivalasztva = null;
function ertAktivJelolt() {
  const c = ertJeloltKivalasztva, k = document.getElementById('ert-kijelolt'), b = document.getElementById('ert-elfogad');
  if (!k || !b) return;
  k.innerHTML = c ? `Kijelölt: <b>${esc(c.tip)} ${esc(c.id)}</b>${c.tav !== '?' ? ' (' + esc(c.tav) + ' m)' : ''}` : '';
  b.disabled = !c;
}
function ertLep(d) {
  const n = ertLista().length;
  if (!n) return;
  ertPoz = (ertPoz + d + n) % n;
  ertRender();
  const r = ertLista()[ertPoz], j = ertJeloltek(r), idx = archGidIndex();
  const javasolt = String(r.javasolt_osm || '').trim();
  const c = j.find(x => x.tip + ' ' + x.id === javasolt) || j[0];
  if (c) { const g = idx.get((c.tip === 'relation' ? 'r' : 'w') + c.id); if (g) repulj(g[0]); }
}
// Review of suspicious OENY pairings (editor): stepping, flying there, decision (keep / reassign / remove)
let oenyGy = null, oenyPoz = 0;
function oenyKulcsGid(k) {
  const m = /^(way|relation) (\d+)$/.exec(k); if (!m) return -1;
  const g = archGidIndex().get((m[1] === 'relation' ? 'r' : 'w') + m[2]);
  return g ? g[0] : -1;
}
function oenyRender() {
  const hely = document.getElementById('oeny-sor'); if (!hely) return;
  hely.innerHTML = '';
  const db = oenyGy.length, nyitott = oenyGy.filter(x => !x.allapot).length;
  document.getElementById('oeny-db').textContent = `${db ? oenyPoz + 1 : 0} / ${db} (átnézetlen: ${nyitott})`;
  const r = oenyGy[oenyPoz]; if (!r) { hely.textContent = 'Nincs tétel.'; return; }
  const allapotSzoveg = { ok: 'ellenőrizve, marad', atrakva: 'átrakva', levetel: 'levéve' }[r.allapot] || 'átnézetlen';
  const fej = document.createElement('div');
  fej.innerHTML = `<b>${esc(r.nev)}</b> <small>(törzsszám ${esc(r.t)})</small><br><small>${esc(r.cim)} · <a href="${esc(r.oeny)}" target="_blank" rel="noopener">OENY-adatlap</a> · <b>${esc(allapotSzoveg)}</b></small>`;
  hely.append(fej);
  const sor = (cim, kulcsok, extra) => {
    const d = document.createElement('div'); d.style.marginTop = '4px';
    d.append(cim + ': ');
    kulcsok.forEach(k => {
      const g = oenyKulcsGid(k), b = document.createElement('button'); b.type = 'button';
      b.textContent = (g >= 0 ? 'Mutasd ' : 'nincs a térképen ') + k; b.disabled = g < 0;
      b.addEventListener('click', () => repulj(g)); d.append(b, ' ');
    });
    if (extra) d.append(extra);
    hely.append(d);
  };
  sor('Jelenlegi', r.akt);
  if (r.javaslat) sor('Javaslat (címalapú)', [r.javaslat]);
  const dont = async (uj, uzenet) => {
    try {
      if (uj === 'levetel') {
        const m = /^(way|relation) (\d+)$/.exec(r.akt[0]);
        await szerkKuldes('/api/oeny_levetel', { osm_tipus: m[1], id: +m[2], torzsszam: r.t, egy: true });
      }
      await szerkKuldes('/api/oeny_atrak', { t: r.t, cim: r.cim, uj });
      if (uj === 'ok') r.allapot = 'ok'; else if (uj === 'levetel') r.allapot = 'levetel';
      else { r.akt = [uj]; r.allapot = 'atrakva'; r.javaslat = ''; }
      if (uj !== 'ok') { szerkFuggo++; szerkAllapot(`${uzenet} – ${szerkFuggo} mentett javítás vár újraépítésre (előtte: py facts_oeny_manual.py).`, 'ok'); }
      if (oenyPoz < oenyGy.length - 1) oenyPoz++;
      oenyRender();
    } catch (e) { szerkAllapot(e.message, 'hiba'); }
  };
  const gombok = document.createElement('div'); gombok.style.marginTop = '6px';
  const gomb = (szoveg, fn, tiltva) => { const b = document.createElement('button'); b.type = 'button'; b.textContent = szoveg; b.disabled = !!tiltva; b.addEventListener('click', fn); gombok.append(b, ' '); };
  gomb('Marad', () => dont('ok'));
  if (r.javaslat) gomb('Átrakom a javaslatra', () => dont(r.javaslat, 'Átrakva'));
  const kij = rogzitettGid >= 0 ? epuletek[rogzitettGid] : null;
  gomb('Átrakom a térképen kijelölt épületre', () => dont((kij.osm_tipus || 'way') + ' ' + kij.id, 'Átrakva'), !kij);
  gomb('OENY levétele', () => dont('levetel', 'Levéve'));
  hely.append(gombok);
}
function oenyLep(d) {
  if (!oenyGy || !oenyGy.length) return;
  oenyPoz = (oenyPoz + d + oenyGy.length) % oenyGy.length;
  oenyRender();
  const r = oenyGy[oenyPoz], g = oenyKulcsGid(r.akt[0]);
  if (g >= 0) repulj(g);
}
function oenyPanel(doboz) {
  const nyit = document.createElement('button'); nyit.type = 'button'; nyit.textContent = 'Gyanús OENY-párosítások'; nyit.style.marginTop = '6px';
  const tart = document.createElement('div'); tart.hidden = true;
  tart.innerHTML = '<small>Lépkedj a tételeken (‹ ›): odarepít a jelenlegi épülethez. Ha a térképen egy másik épületre kattintasz, az „Átrakom a térképen kijelölt épületre” gomb azt használja.</small>'
    + '<div class="lista-sor" style="margin-top:4px"><button type="button" id="oeny-elozo">‹</button> <span id="oeny-db"></span> <button type="button" id="oeny-kovetkezo">›</button></div><div id="oeny-sor" style="margin-top:6px"></div>';
  doboz.append(nyit, tart);
  tart.querySelector('#oeny-elozo').addEventListener('click', () => oenyLep(-1));
  tart.querySelector('#oeny-kovetkezo').addEventListener('click', () => oenyLep(1));
  nyit.addEventListener('click', async () => {
    tart.hidden = !tart.hidden;
    if (tart.hidden) return;
    try { oenyGy = (await (await fetch('/api/oeny_gyanus', { cache: 'no-store' })).json()).tetelek || []; }
    catch (e) { document.getElementById('oeny-sor').textContent = 'A lista nem tölthető be (indítsd újra a editor_server.py-t).'; return; }
    const elso = oenyGy.findIndex(x => !x.allapot); oenyPoz = elso >= 0 ? elso : 0;
    oenyRender();
  });
}

// ---------- "Architect" trial panel: all names occurring in the Designer field in alphabetical order; clicking a name keeps only the houses where the name appears highlighted ----------
const EP_EGYBEN = /(?<=^|[;,]\s*)(?:Brenstein\s+és\s+Káldor|Dénes\s+és\s+Weisz|Kondor\s+és\s+Feledi|Melczer\s+és\s+Wensky|Wawra\s+és\s+Pfeifer)(?=\s*(?:[;,]|$))|Preisz\s+és\s+Kirchenbaum|Zsuffa\s+és\s+Kalmár\s+Építész\s+Műterem|Lukács\s+és\s+Vikár\s+Építészstúdió/gi;   // exception: a name joined with "és" ("and") counts as one name (further exceptions can be added with |)
const EP_KIHAGY = /^([-–—]+|tervezo nem ismert)$/;   // items that are not names: left out of the list
function epNevekEpit() {
  const m = new Map();
  epuletek.forEach((p, gid) => {
    if (!p || p.hid || !p.tervezo) return;
    const latott = new Set();
    String(p.tervezo).replace(/\([^)]*\)/g, '').replace(EP_EGYBEN, m => m.replace(/\s+/g, '\ue000')).split(/\s*[;,]\s*|\s+és\s+/).forEach(r => {
      const nev = r.replace(/\ue000/g, ' ').replace(/\s+/g, ' ').trim();
      if (!nev) return;
      const k = archFold(nev);
      if (EP_KIHAGY.test(k) || latott.has(k)) return;
      latott.add(k);
      let e = m.get(k);
      if (!e) m.set(k, e = { k, alak: new Map(), gids: [] });
      e.alak.set(nev, (e.alak.get(nev) || 0) + 1);
      e.gids.push(gid);
    });
  });
  epNevek = [...m.values()].map(e => ({ k: e.k, nev: [...e.alak.entries()].sort((a, b) => b[1] - a[1])[0][0], gids: e.gids }))
    .sort((a, b) => a.nev.localeCompare(b.nev, 'hu'));
  // the houses of an estate (zone), if the architect has at least two in it, count together as one project (as in the architect layer)
  const zt = zonaTerv();
  epNevek.forEach(e => {
    const db = new Map();
    e.gids.forEach(g => { const z = epuletek[g].zona_azon; if (z && zt.has(z)) db.set(z, (db.get(z) || 0) + 1); });
    e.zonak = new Set([...db].filter(([, n]) => n >= 2).map(([z]) => z));
    e.szam = archTetelek(new Set(e.gids), e.zonak).length;    // the same counting as in the stepper: several elements of one building (parts, same name and address within 150 m) count as one, and an estate counts as one
  });
}
const EP_NEM_SZEMELY = new Set(['iroda', 'intezmeny', 'tobb_szemely', 'nem_nev']);
let epKeziKor = null;     // epitesz_korok_kezi.json: name key -> { kor: [era indices 0-6] } or { elet: [birth, death|null] } (manual override)
let epElete = null;       // epitesz_elete.json: name key -> [birth year, death year | null] (Wikidata)
async function epKorokRendel() {
  // The Architects tab's era filter uses the map's 7 eras: an architect appears in the era in which they have a house (fitting their own lifetime).
  // A house does not count if its construction year is before the architect's 18th birthday or more than 3 years after their death
  // (renovation, rebuilding, later attribution). With an unknown biography, a rare era (<10% of the houses) does not count.
  if (!epElete) { try { epElete = await (await fetch('epitesz_elete.json')).json(); } catch (h) { epElete = {}; } }
  if (!epKeziKor) { try { epKeziKor = await (await fetch('epitesz_korok_kezi.json', { cache: 'no-store' })).json(); } catch (h) { epKeziKor = {}; } }
  const korIdx = ev => periods.findIndex(q => q.to !== 0 && ev >= q.from && ev <= q.to);
  epNevek.forEach(e => {
    const evek = [];
    e.gids.forEach(g => {
      const p = epuletek[g], ev = +p.ev || +p.ev_kozelito_tol || 0;
      if (ev >= 1 && ev <= 2100) evek.push(ev);
    });
    const kezi = epKeziKor[e.k] || {};
    let el = kezi.elet || epElete[e.k], jo = evek;
    e.elet = null;
    if (el) {
      const [sz, ha] = el, bent = evek.filter(ev => ev >= sz + 18 && (ha == null || ev <= ha + 3));
      // if most of the houses would fall outside, the match is probably another person with the same name: the biography is not used
      if (!evek.length || bent.length >= evek.length * 0.4) { jo = bent; e.elet = el; }
    }
    if (!e.elet && jo.length >= 10) {
      const db = new Map(); jo.forEach(ev => { const i = korIdx(ev); if (i >= 0) db.set(i, (db.get(i) || 0) + 1); });
      jo = jo.filter(ev => (db.get(korIdx(ev)) || 0) >= jo.length * 0.1);
    }
    e.korDb = new Map();
    jo.forEach(ev => { const i = korIdx(ev); if (i >= 0) e.korDb.set(i, (e.korDb.get(i) || 0) + 1); });
    e.kors = new Set([...e.korDb.keys()].sort((a, b) => a - b)); e.korBecsult = false;
    if (Array.isArray(kezi.kor)) {       // manual era classification: the given eras, regardless of the houses' years
      e.kors = new Set(kezi.kor.filter(i => periods[i] && periods[i].to !== 0).sort((a, b) => a - b));
      e.korDb = new Map([...e.kors].map(i => [i, evek.filter(ev => korIdx(ev) === i).length]));
    }
  });
  const sel = document.getElementById('ep-kor'), regi = sel.value;
  sel.innerHTML = `<option value="">${esc(t('ep_minden_kor'))}</option>` + periods.map((q, i) => q.to === 0 ? '' : `<option value="${i}">${esc(korNev(i))}</option>`).join('') + `<option value="nincs">${esc(t('ep_nincs_kor'))}</option>`;
  sel.value = regi;
}
let epUnio = false, epUnioIdo = 0;      // var: setNezet('period') calls epiteszNezet at startup, before the declaration
function epSzuroKiemel(sorok, aktiv) {
  clearTimeout(epUnioIdo);
  epUnioIdo = setTimeout(() => {
    if (epAktiv || document.getElementById('nez-epitesz').hidden) return;      // for a selected architect their own houses count
    if (!aktiv) {
      if (epUnio) { epUnio = false; archSzuro = null; archZonaAzon = new Set(); frissitKiemelest(); archLepteto(null); }
      return;
    }
    const s = new Set(), z = new Set();
    sorok.forEach(e => { e.gids.forEach(g => s.add(g)); (e.zonak || []).forEach(x => z.add(x)); });
    epUnio = true; archSzuro = s; archZonaAzon = z;
    frissitKiemelest();
    archLepteto(s.size <= 4000 ? s : null);      // the stepper only for a moderate number of buildings (compiling the list is expensive)
  }, 150);
}
function epiteszRender() {
  if (!epKesz) return;
  const lista = document.getElementById('ep-lista'), ker = archFold(document.getElementById('ep-ker').value.trim());
  const kor = document.getElementById('ep-kor').value;
  const dijak = [...document.querySelectorAll('.ep-dijak input:checked')].map(c => c.dataset.dij);
  const sorrend = document.getElementById('ep-sorrend').value, min = Math.max(1, parseInt(document.getElementById('ep-min').value, 10) || 1);
  const nevek = epNevek.filter(e => !epKizart.has(e.k)), sorok = nevek.filter(e => (!ker || e.k.includes(ker)) && e.szam >= min && dijak.every(d => epDijak[d] && epDijak[d][e.k]) && (kor === '' || (kor === 'nincs' ? !e.kors.size : e.kors.has(+kor))));
  if (sorrend === 'db') sorok.sort((a, b) => b.szam - a.szam || a.nev.localeCompare(b.nev, 'hu'));      // most buildings first; alphabetical on a tie
  else if (sorrend === 'db_nov') sorok.sort((a, b) => a.szam - b.szam || a.nev.localeCompare(b.nev, 'hu'));
  document.getElementById('ep-db').textContent = sorok.length + ' / ' + nevek.length + ' ' + t('ep_szam');
  lista.innerHTML = sorok.map(e => `<div class="ep-sor${epAktiv === e.k ? ' aktiv' : ''}" data-k="${esc(e.k)}"${e.elet ? ` title="${e.elet[0]}–${e.elet[1] || ''}"` : ''}>${esc(e.nev)} <small>(${e.szam})</small>${[['ybl', 'Y', 'dij_ybl'], ['prima', 'P', 'dij_prima'], ['nivo', 'N', 'dij_nivo']].filter(([d]) => epDijak[d] && epDijak[d][e.k]).map(([d, j, c]) => ` <i class="dij" title="${esc(t(c))}: ${epDijak[d][e.k].join(', ')}">${j}</i>`).join('')}${[...e.kors].map(i => ` <i title="${esc(korNev(i))}${e.korDb.get(i) ? ' (' + e.korDb.get(i) + ')' : ''}" style="color:${periods[i].color || '#999'};font-style:normal">●</i>`).join('')}</div>`).join('');
  // the architect list's filters (search, era, awards, at least N buildings) are also visible in 3D: the houses of all architects in the filtered list are highlighted
  epSzuroKiemel(sorok, !!(ker || kor !== '' || dijak.length || min > 1));
}
// ---------- Architects tab: the selected architect's personal Wikipedia data sheet opens in the same popup as on the Styles tab ----------
let archPopupTok = 0, epPopupTok = 0;
const epWikiGyorsitotar = new Map();
async function epWikiCimek(e) {
  if (epWikiGyorsitotar.has(e.k)) return epWikiGyorsitotar.get(e.k);
  const ered = (async () => {
    await archBetolt();
    // 1) the article titles of the manually curated architect layer (epitesz.json)
    for (const k of archAdat) for (const x of k.epitesz || []) if (archNevek(x).includes(e.k) && x.w && x.w.length) return x.w;
    // 2) an article with the exact title (or "Name (építész)") whose description mentions an architect; if the article mentions years of life, the birth year must match the known one (against namesakes)
    const el = epElete && epElete[e.k];
    for (const cim of [e.nev, e.nev + ' (építész)']) {
      try {
        const r = await fetch(`https://hu.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(cim.replace(/ /g, '_'))}`, { headers: { Accept: 'application/json' } });
        if (!r.ok) continue;
        const j = await r.json(), szoveg = (j.description || '') + ' ' + String(j.extract || '').slice(0, 500);
        if (j.type !== 'standard' || !/építész/i.test(szoveg)) continue;
        const ev = szoveg.match(/\(\s*(\d{4})\s*[–-]/);       // rejected only if the article mentions a different birth year (most descriptions have no year)
        if (el && ev && +ev[1] !== el[0]) continue;
        return [j.title];
      } catch { /* next variant */ }
    }
    return [];
  })();
  epWikiGyorsitotar.set(e.k, ered);
  return ered;
}
async function epHelyi(e) {
  await archBetolt();
  for (const k of archAdat) for (const x of k.epitesz || []) if (x.nw && x.l && archNevek(x).includes(e.k)) return x;
  return null;
}
async function epWikiPopup(e) {
  const tok = ++epPopupTok, pp = document.getElementById('arch-popup');
  if (pp) pp.hidden = true;
  const helyi = await epHelyi(e);        // hand-written data sheet (nw): no Wikipedia article is searched for, since it could find a namesake
  if (helyi) { if (tok !== epPopupTok || epAktiv !== e.k) return; archPopupTok = tok; archPopupMutat({ nev: e.nev, l: helyi.l, f: helyi.f || [], w: [], nw: true, tok }, archKiv); return; }
  const cimek = await epWikiCimek(e);
  if (tok !== epPopupTok || epAktiv !== e.k || !cimek.length) return;     // in the meantime another architect was chosen, or there is no personal data sheet
  archPopupTok = tok;
  archPopupMutat({ nev: e.nev, l: '', w: cimek, nw: false, tok }, archKiv);
}
function epiteszValaszt(k) {
  if (epAktiv === k) k = null;                      // clicking again clears the filter
  epAktiv = k;
  const e = k && epNevek.find(x => x.k === k);
  archZonaAzon = e ? e.zonak : new Set();
  archSzuro = e ? new Set(e.gids) : null;
  if (e) epWikiPopup(e); else { epPopupTok++; const pp = document.getElementById('arch-popup'); if (pp) pp.hidden = true; }
  frissitKiemelest();
  archLepteto(archSzuro);
  epiteszRender();
}
// The "Architects" tab: built on first opening (the name list from the loaded building data, the excluded names from epitesz_kizart.json)
async function epiteszNezet(be) {
  if (!be) { epUnio = false; clearTimeout(epUnioIdo); epPopupTok++; if (epAktiv) { epAktiv = null; if (epKesz) epiteszRender(); } return; }
  if (!epBetoltes) epBetoltes = (async () => {
    epNevekEpit();
    try { epKizart = new Set(await (await fetch('epitesz_kizart.json', { cache: 'no-store' })).json()); }
    catch (h) {
      try {      // the editor's server also serves it (if the static file does not exist yet)
        const v = await (await fetch('/api/epitesz_tipusok', { cache: 'no-store' })).json();
        epKizart = new Set((v.sorok || []).filter(r => EP_NEM_SZEMELY.has(r.tipus)).map(r => r.kulcs));
      } catch (h2) { epKizart = new Set(); }
    }
    try { epDijak = await (await fetch('epitesz_dijak.json')).json(); } catch (h) { /* works without the award filters too */ }
    await epKorokRendel();
    epKesz = true;
  })();
  await epBetoltes;
  if (document.getElementById('nez-epitesz').hidden) return;      // in the meantime the user switched to another tab
  epiteszRender();
}
function epNyelvFrissit() {
  const ker = document.getElementById('ep-ker'); if (ker) ker.placeholder = t('ep_ker');
  if (epKesz) { epKorokRendel().then(epiteszRender); }
}
document.getElementById('ep-ker').addEventListener('input', epiteszRender);
document.getElementById('ep-sorrend').addEventListener('change', epiteszRender);
document.getElementById('ep-kor').addEventListener('change', epiteszRender);
document.getElementById('ep-min').addEventListener('input', epiteszRender);
document.querySelectorAll('.ep-dijak input').forEach(c => c.addEventListener('change', epiteszRender));
document.getElementById('ep-lista').addEventListener('click', ev => {
  const sor = ev.target.closest('.ep-sor');
  if (sor) epiteszValaszt(sor.dataset.k);
});

async function ertPanel(doboz) {
  const nyit = document.createElement('button'); nyit.type = 'button'; nyit.textContent = 'Értékleltár-ellenőrzés'; nyit.style.marginTop = '6px';
  const tart = document.createElement('div'); tart.id = 'ert-doboz'; tart.hidden = true;
  tart.innerHTML = '<small>Lépkedj a sorokon (‹ ›). A ★ jelölt a program tippje; kattints egy jelöltre (odarepít), majd „Elfogadom”. Vagy kattints a térképen egy épületre, és a kártyáján a zöld gombbal párosítsd; vagy adj meg OSM-azonosítót.</small>'
    + '<div class="lista-sor" style="margin-top:4px"><button type="button" id="ert-elozo">‹</button> <select id="ert-szuro"><option value="nyitott">Nyitott</option><option value="valoszinu">Valószínű (tipp)</option><option value="jeloltes">Bizonytalan, jelöltekkel</option><option value="nincs">Nincs jelölt</option><option value="dontott">Már eldöntött</option><option value="mind">Mind</option></select> <select id="ert-ker"><option value="">Minden kerület</option></select> <button type="button" id="ert-kovetkezo">›</button> <span id="ert-db"></span></div>'
    + '<div id="ert-sor" style="margin-top:6px"></div>';
  doboz.append(nyit, tart);
  document.getElementById('ert-szuro').addEventListener('change', e => { ertSzuro = e.target.value; ertPoz = 0; ertLep(0); });
  document.getElementById('ert-ker').addEventListener('change', () => { ertPoz = 0; ertLep(0); });
  document.getElementById('ert-elozo').addEventListener('click', () => ertLep(-1));
  document.getElementById('ert-kovetkezo').addEventListener('click', () => ertLep(1));
  nyit.addEventListener('click', async () => {
    tart.hidden = !tart.hidden;
    if (tart.hidden) { ertAktiv = null; if (rogzitettGid >= 0) kartyaUjra(); return; }
    try {
      const v = await (await fetch('/api/ertekleltar_lista', { cache: 'no-store' })).json();
      ertSorok = v.sorok || [];
    } catch (e) { document.getElementById('ert-sor').textContent = 'A lista nem tölthető be (indítsd újra a editor_server.py-t).'; return; }
    const kerek = [...new Set(ertSorok.map(r => r.kerulet))].sort((a, b) => a - b);
    document.getElementById('ert-ker').innerHTML = '<option value="">Minden kerület</option>' + kerek.map(k => `<option value="${esc(k)}">${esc(k)}. ker.</option>`).join('');
    ertPoz = 0; ertLep(0);
  });
}

// Architect pairing (manual): pairing the uncertain / unmatched items left over from the Wikipedia works lists to OSM buildings
let parAdat = null, parAktiv = null, parKesz = new Set(), parElvetett = new Set(), parLimit = 80;
try { parKesz = new Set(JSON.parse(localStorage.getItem('parKesz') || '[]')); } catch (e) { /* no storage */ }
function parKulcs(it) { const n = x => String(x || '').replace(/\s+/g, ' ').trim(); return n(it.a).slice(0, 120) + '|' + n(it.t).slice(0, 400); }   // normalised the same way as on the server
async function parositas(gid, gomb, uzenet) {
  const p = epuletek[gid], it = parAktiv;
  const regi = String(p.tervezo || '').trim();
  const fold = x => String(x || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  // An item name of the form "A és B" / "A, B és C" splits into separate architects; only names still missing from the house's designer are added (no duplication).
  // Item names with parentheses or hyphens (company name, remark) are not split.
  const nevek = /[(–]/.test(it.a) ? [it.a] : String(it.a).split(/\s*,\s*|\s+és\s+/).map(x => x.trim()).filter(Boolean);
  const hianyzik = nevek.filter(n => !fold(regi).includes(fold(n)));
  const ertek = !regi ? it.a : !hianyzik.length ? regi : regi + (regi.includes(',') ? ', ' : '; ') + hianyzik.join(', ');
  if (regi && ertek !== regi && !confirm(`Már van tervező: „${regi}".\nÚj érték: „${ertek}". Rendben?`)) return;
  gomb.disabled = true;
  try {
    await szerkKuldes('/api/epitesz_parositas', { osm_tipus: p.osm_tipus || 'way', id: p.id, ertek, tetel: it.t, epitesz: it.a, tetel_teljes: it.t });
    p.tervezo = ertek;
    parKesz.add(parKulcs(it));
    try { localStorage.setItem('parKesz', JSON.stringify([...parKesz])); } catch (e) { /* no storage */ }
    szerkFuggo++;
    szerkAllapot(`${szerkFuggo} mentett javítás vár újraépítésre.`, 'ok');
    parAktiv = null; parRender();
    kartyaUjra();
  } catch (hiba) {
    uzenet.className = 'szerk-uzenet szerk-hiba'; uzenet.textContent = hiba.message;
    gomb.disabled = false;
  }
}
function parRender() {
  const doboz = document.getElementById('par-doboz');
  if (!doboz || !parAdat) return;
  const sz = document.getElementById('par-szuro').value, st = document.getElementById('par-allapot').value;
  const lista = document.getElementById('par-lista'), idx = archGidIndex();
  const mind = parAdat.filter(it => !parKesz.has(parKulcs(it)) && !parElvetett.has(parKulcs(it)));
  document.getElementById('par-db').textContent = `${mind.length} nyitott tétel összesen`;
  const legjobb = it => (it.c[0] && +it.c[0][3]) || 0;
  const allapotSzuro = it => !st || (st === 'jel' ? it.c.length : st === 'nincs' ? !it.c.length : st === 'eros' ? legjobb(it) >= 80 && !it.na : st === 'kozepes' ? legjobb(it) >= 60 && legjobb(it) < 80 && !it.na : st === 'na' ? it.na : st === 'uj' ? /^új.*díjazott/.test(it.s || '') : st === 'uj57' ? /^új.*1957/.test(it.s || '') : st === 'uj19' ? /^új.*1919/.test(it.s || '') : true);
  // the dropdown: per architect the number of still open items (an architect with 0 open items does not appear)
  const szSel = document.getElementById('par-szuro'), szam = new Map();
  for (const it of mind) if (allapotSzuro(it)) szam.set(it.a, (szam.get(it.a) || 0) + 1);
  const nevek = [...szam.keys()].sort((a, b) => a.localeCompare(b, 'hu'));
  if (sz && !szam.has(sz)) nevek.push(sz);
  szSel.innerHTML = `<option value="">Minden építész (${[...szam.values()].reduce((a, b) => a + b, 0)})</option>` + nevek.map(n => `<option value="${esc(n)}"${n === sz ? ' selected' : ''}>${esc(n)} (${szam.get(n) || 0})</option>`).join('');
  const szurt = mind.filter(it => (!sz || it.a === sz) && allapotSzuro(it));
  const sor = szurt.slice(0, parLimit);
  lista.innerHTML = '';
  for (const it of sor) {
    const li = document.createElement('div'); li.style.cssText = 'border-top:1px solid #ddd;padding:4px 0;font-size:12px';
    if (parAktiv === it) li.style.background = '#fff3c4';
    const fej = document.createElement('div');
    fej.innerHTML = `<b>${esc(it.a)}</b>: ${esc(it.t.slice(0, 160))}`;
    li.appendChild(fej);
    const mez = document.createElement('div'); mez.style.marginTop = '3px';
    const ki = document.createElement('button'); ki.type = 'button'; ki.className = 'szerk-gomb'; ki.textContent = parAktiv === it ? 'Kiválasztva ✓' : 'Ezt párosítom';
    ki.addEventListener('click', () => { parAktiv = parAktiv === it ? null : it; parRender(); if (rogzitettGid >= 0) kartyaUjra(); });
    mez.appendChild(ki);
    const elv = document.createElement('button'); elv.type = 'button'; elv.className = 'szerk-gomb'; elv.textContent = 'Elvetés'; elv.style.marginLeft = '4px';
    elv.title = 'Kiveszi a tételt a listából (pl. lebontott épület vagy csak terv): minden böngészőből eltűnik; visszahozni a forras/epitesz_elvetett.csv szerkesztésével lehet.';
    elv.addEventListener('click', async () => {
      elv.disabled = true;
      try {
        await szerkKuldes('/api/epitesz_elvetes', { epitesz: it.a, tetel: it.t });
        parElvetett.add(parKulcs(it));
        if (parAktiv === it) { parAktiv = null; if (rogzitettGid >= 0) kartyaUjra(); }
        parRender();
      } catch (hiba) { szerkAllapot(hiba.message, 'hiba'); elv.disabled = false; }
    });
    mez.appendChild(elv);
    if (it.na) {
      const na = document.createElement('div'); na.style.cssText = 'color:#a33;margin-top:2px';
      na.textContent = '⚠ A szöveg szerint valószínűleg lebontották, vagy csak terv maradt – ilyenkor az Elvetés a jó választás.';
      li.appendChild(na);
    }
    const uzen = document.createElement('div'); uzen.className = 'szerk-uzenet';
    let elso = true;
    for (const c of it.c.slice(0, 4)) {
      const g = idx.get((c[0] === 'relation' ? 'r' : 'w') + c[1]);
      if (!g) continue;
      const sorj = document.createElement('div'); sorj.style.marginTop = '3px';
      const b = document.createElement('button'); b.type = 'button'; b.className = 'szerk-gomb';
      const pont = +c[3] || 0;
      b.textContent = `${pont >= 80 ? '★ ' : ''}${String(c[2] || c[1]).slice(0, 30)} (${pont >= 80 ? 'erős' : pont >= 60 ? 'közepes' : 'gyenge'})`;
      b.title = (c[4] ? c[4] + ' – ' : '') + 'kattintás: ugrás a jelölt épületre';
      b.addEventListener('click', () => { parAktiv = it; parRender(); repulj(g[0]); });
      const ok = document.createElement('button'); ok.type = 'button'; ok.className = 'szerk-gomb'; ok.textContent = '✓ Ez az';
      ok.title = 'Közvetlen párosítás ezzel az épülettel (a térképen nem kell rákattintani)';
      ok.style.cssText = 'margin-left:4px;background:#2a7;color:#fff';
      ok.addEventListener('click', async () => { parAktiv = it; await parositas(g[0], ok, uzen); });
      sorj.append(b, ok);
      if (c[4] && elso) { const ind = document.createElement('div'); ind.style.cssText = 'color:#555;font-size:11px'; ind.textContent = c[4]; sorj.appendChild(ind); }
      elso = false;
      mez.appendChild(sorj);
    }
    li.appendChild(mez);
    li.appendChild(uzen);
    lista.appendChild(li);
  }
  if (!sor.length) lista.textContent = 'Nincs több tétel ezzel a szűrővel.';
  if (szurt.length > sor.length) {
    const tov = document.createElement('button'); tov.type = 'button'; tov.className = 'szerk-gomb'; tov.style.margin = '6px 0';
    tov.textContent = `Továbbiak (${sor.length} / ${szurt.length} látszik)`;
    tov.addEventListener('click', () => { parLimit += 80; parRender(); });
    lista.appendChild(tov);
  }
}
async function parPanel(doboz) {
  const nyit = document.createElement('button'); nyit.type = 'button'; nyit.textContent = 'Építész-párosítás (Wikipédia-lista)';
  nyit.style.marginTop = '6px';
  const tart = document.createElement('div'); tart.id = 'par-doboz'; tart.hidden = true;
  tart.innerHTML = '<small>Válassz egy tételt („Ezt párosítom" vagy egy jelölt-gomb), majd kattints a térképen a megfelelő épületre, és az épület kártyáján nyomd meg a zöld „Párosítás" gombot.</small>'
    + '<div><select id="par-szuro"><option value="">Minden építész</option></select> <select id="par-allapot"><option value="">Mind</option><option value="uj">Új: díjazott kortárs építészek</option><option value="uj57">Új: 1957–89 építészek</option><option value="uj19">Új: 1919–56 építészek</option><option value="eros">Erős javaslat</option><option value="kozepes">Közepes javaslat</option><option value="jel">Van jelölt</option><option value="nincs">Nincs jelölt</option><option value="na">Valószínűleg lebontott / terv</option></select> <span id="par-db"></span></div>'
    + '<div id="par-lista" style="max-height:320px;overflow:auto"></div>';
  doboz.append(nyit, tart);
  nyit.addEventListener('click', async () => {
    tart.hidden = !tart.hidden;
    if (!tart.hidden && !parAdat) {
      try {
        parAdat = await (await fetch('epitesz_parositas.json', { cache: 'no-store' })).json();
      } catch (e) { tart.textContent = 'Az epitesz_parositas.json nem tölthető be.'; return; }
      try {
        const ev = await (await fetch('/api/epitesz_elvetett', { cache: 'no-store' })).json();
        parElvetett = new Set((ev.tetelek || []).map(x => parKulcs({ a: x.a, t: x.t })));
      } catch (e) { /* no rejected list: every item is visible */ }
      document.getElementById('par-szuro').addEventListener('change', () => { parLimit = 80; parRender(); });
      document.getElementById('par-allapot').addEventListener('change', () => { parLimit = 80; parRender(); });
    }
    if (parAdat) parRender();
  });
}

// the debug object (window.__dbg, e.g. __dbg.nezet()) is available only in editor mode (with the local server), not on the public site
fetch('/api/ping', { cache: 'no-store' }).then(r => r.json()).then(d => {
  szerkeszto = !!d.szerkeszto;
  if (szerkeszto) { szerkPanel(); window.__dbg = { nezet: nezetErtekek, uniforms, camera, controls, pick, rogzit, bezar, epuletek, config }; }
}).catch(() => {});
// deep link from the text pages: ?e=w123 or ?e=r123 (OSM id) -> the map flies there and the building's card opens
{
  const eAz = new URLSearchParams(location.search).get('e');
  if (eAz) { const talalat = keres(eAz); if (talalat.length) setTimeout(() => repulj(talalat[0]), 800); }
}
let melyLinkNincs = false;
// deep links: ?tab=period|arch|epitesz|vedett|lakotelep|magassag  ?architect=<name>  ?estate=<estate name>  ?lang=en|hu
{
  const q = new URLSearchParams(location.search);
  const tab = q.get('tab'), ar = q.get('architect'), tel = q.get('estate');
  const egyszeru = x => String(x || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
  const fulek = ['period', 'arch', 'epitesz', 'vedett', 'lakotelep', 'magassag'];
  if (ar) {
    setNezet('epitesz');
    epBetoltes.then(() => {
      const kulcs = egyszeru(ar), e = epNevek.find(x => egyszeru(x.nev) === kulcs || x.k === kulcs) || epNevek.find(x => egyszeru(x.nev).includes(kulcs));
      if (e) epiteszValaszt(e.k);
    });
  } else if (tel) {
    setNezet('lakotelep');
    setTimeout(() => { const z = lakAdat().find(x => egyszeru(x.nev) === egyszeru(tel)); if (z) lakValaszt(z.nev); }, 1200);
  } else if (fulek.includes(tab)) setNezet(tab);
  else melyLinkNincs = true;
}
if (melyLinkNincs) setNezet('period');      // at startup, at the end of the file: by then every let/const declaration exists
