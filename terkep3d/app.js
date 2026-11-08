// Budapest, épületenként: a 3D nézet.
//
// A megjelenítő magja (shader, csempebetöltés, kijelölés, évcsúszka, az időhisztogram ötlete) az
// amszterdami projektből való: alexbarakov/amsterdam-by-building, MIT licenc (lásd LICENSE-amsterdam.txt).
// Az adatfolyam, a korszakok, a kártya tartalma, a kétnyelvűség és a becsült korszak a budapesti rész.
import * as THREE from './vendor/three.module.js';
import { MapControls } from './vendor/MapControls.js';

THREE.ColorManagement.enabled = false;   // a színeket úgy rajzoljuk, ahogy megadtuk

const SKY = '#e4e8ea';
const LAND = '#f4f3ef';
const WATER = '#b5c7c6';
const PARK = '#e1e8d6';
const MAQUETTE = '#efeee9';
const ATTR_W = 256;
const WORKERS = Math.min(4, navigator.hardwareConcurrency || 2);
const MODE = { period: 0, floors: 1 };

const [config, epuletek] = await Promise.all([
  fetch('data/budapest.json').then(r => r.json()),
  fetch('data/epuletek.json').then(r => r.json()),
]);
const periods = config.periods;

// ---------- Nyelv (magyar / angol) ----------
const SZOVEG = {
  hu: {
    cim: 'Budapest, épületenként', mod_korszak: 'Korszak', mod_szint: 'Szintek', szint_kicsi: '1 szint', szint_nagy: '40 szint',
    kiemel: 'Kiemelés', vedett: 'Védett épületek', wiki: 'Wikipédia-cikkel rendelkezők', lechner: 'Lechner-épületek',
    terkep_link: 'Szerkesztő térkép (2D) →', epulet: 'épület', ma: 'Ma', betoltes: 'A város építése',
    howto: 'Húzd a forgatáshoz. Jobb gomb vagy Shift + húzás: mozgatás. Görgő: nagyítás.',
    nevtelen: 'névtelen épület', tipus: 'Típus', resz: 'épületrész', tervezo: 'Tervező', stilus: 'Stílus',
    vedettseg: 'Védettség', torzsszam: 'törzsszám', szintszam: 'Szintszám', magassag: 'Magasság',
    tobb_cim: 'és még {n} cím', gmaps: 'Google Térkép',
    becsult: 'Becsült korszak (nem adat)', valoszinuseg: 'valószínűség', bizonyossag: 'bizonyosság',
    magas: 'magas', kozepes: 'közepes', alacsony: 'alacsony',
    becsles_alap: 'szomszédokból, utcából és alakból becsülve',
    szomszedtol: 'a környező épületek korszaka alapján becsült',
    kep_forras: 'Kép', kep_reszlet: 'részletfotó vagy belső tér', kep_cim: 'a fájlnév a címet tartalmazza', kep_nev: 'a fájlnév az épület nevét tartalmazza', utcakep: 'Utcakép (Google Street View)', wiki_forras: 'Forrás: Wikipédia', wiki_licenc: 'CC BY-SA 4.0', wiki_tobb: 'Teljes cikk', wiki_betolt: 'Wikipédia-kivonat betöltése…', wiki_hiba: 'A Wikipédia-kivonat most nem érhető el.', wiki_nyelv: 'magyar nyelvű cikk',
    keltezes: 'Honnan az évszám', forrasok: 'További információ', reszletek: 'Kattints a részletekért',
    lechner_blokk: 'Lechner Tudásközpont', megnevezes: 'Megnevezés', epult: 'Épült',
    kozeli_megj: 'A pont nem esik az épületbe, csak a közelébe, a párosítás bizonytalan.',
    ev_nincs: 'Nincs ismert építési év.',
    ev_becsult_leiras: 'A korszak becslés: a szomszédok, az utca és az épület alakja alapján, nem adat. A csúszkán az épület a becsült korszakán belül, a környező ismert évekből választott évnél jelenik meg.',
    ev_kozeli: 'Közeli találat alapján párosítva, ellenőrizendő.',
  },
  en: {
    cim: 'Budapest, building by building', mod_korszak: 'Era', mod_szint: 'Storeys', szint_kicsi: '1 storey', szint_nagy: '40 storeys',
    kiemel: 'Highlight', vedett: 'Protected buildings', wiki: 'With a Wikipedia article', lechner: 'Lechner buildings',
    terkep_link: 'Editing map (2D) →', epulet: 'buildings', ma: 'Today', betoltes: 'Building the city',
    howto: 'Drag to turn. Right-drag or Shift-drag to move. Scroll to zoom.',
    nevtelen: 'unnamed building', tipus: 'Type', resz: 'building part', tervezo: 'Architect', stilus: 'Style',
    vedettseg: 'Protection', torzsszam: 'register no.', szintszam: 'Storeys', magassag: 'Height',
    tobb_cim: 'and {n} more', gmaps: 'Google Maps',
    becsult: 'Estimated era (not data)', valoszinuseg: 'probability', bizonyossag: 'confidence',
    magas: 'high', kozepes: 'medium', alacsony: 'low',
    becsles_alap: 'estimated from neighbours, street and shape',
    szomszedtol: 'estimated from the surrounding buildings',
    kep_forras: 'Photo', kep_reszlet: 'detail or interior photo', kep_cim: 'file name contains the address', kep_nev: 'file name contains the building name', utcakep: 'Street view (Google)', wiki_forras: 'Source: Wikipedia', wiki_licenc: 'CC BY-SA 4.0', wiki_tobb: 'Full article', wiki_betolt: 'Loading Wikipedia extract…', wiki_hiba: 'The Wikipedia extract is unavailable right now.', wiki_nyelv: 'article in Hungarian',
    keltezes: 'Where the year comes from', forrasok: 'Read more', reszletek: 'Click for details',
    lechner_blokk: 'Lechner Knowledge Centre', megnevezes: 'Name', epult: 'Built',
    kozeli_megj: 'The point is not inside the building, only near it; the match is uncertain.',
    ev_nincs: 'No known construction year.',
    ev_becsult_leiras: 'The era is an estimate from neighbours, street and building shape, not data. On the slider the building appears at a year drawn from the known years around it, within its estimated era.',
    ev_kozeli: 'Matched by proximity; to be checked.',
  },
};
let NYELV = 'hu';
try { if (localStorage.getItem('nyelv') === 'en') NYELV = 'en'; } catch (e) { /* nincs tárhely */ }
const t = k => SZOVEG[NYELV][k] ?? SZOVEG.hu[k] ?? k;
const korNev = i => (NYELV === 'en' ? periods[i].label_en : periods[i].label);

const FORRAS_NEVEK = {
  hu: {
    kezi: 'kézi javítás', osm: 'OpenStreetMap', lechner: 'Lechner Tudásközpont',
    lechner_kozeli: 'Lechner Tudásközpont, közeli találat (ellenőrizendő)', muemlek: 'műemlékjegyzék',
    oeny: 'E-Örökség, hivatalos nyilvántartás (leírásból kiolvasva)', helyi_vedelem: 'fővárosi helyi védelmi lista (2001)',
    wikidata: 'Wikidata', wikidata_kozeli: 'Wikidata, közeli találat (ellenőrizendő)', eubucco: 'EUBUCCO',
    szintterkep: 'kerületi szintszám-térkép',
  },
  en: {
    kezi: 'hand correction', osm: 'OpenStreetMap', lechner: 'Lechner Knowledge Centre',
    lechner_kozeli: 'Lechner Knowledge Centre, nearby match (to be checked)', muemlek: 'list of monuments',
    oeny: 'E-Örökség, official register (read from the description)', helyi_vedelem: 'Budapest local protection list (2001)',
    wikidata: 'Wikidata', wikidata_kozeli: 'Wikidata, nearby match (to be checked)', eubucco: 'EUBUCCO',
    szintterkep: 'district storey map',
  },
};
const forrasNev = k => FORRAS_NEVEK[NYELV][k];
const VEDETTSEG = {
  hu: { M: 'műemlék', MJ: 'műemlék jellegű', VK: 'városképi jelentőségű', MK: 'műemléki környezet', MJT: 'műemléki jelentőségű terület' },
  en: { M: 'listed monument', MJ: 'monument-like', VK: 'townscape significance', MK: 'monument surroundings', MJT: 'area of monument significance' },
};

// ---------- Jelenet ----------
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

function goHome() {
  const h = config.home, az = THREE.MathUtils.degToRad(h.azimuth), el = THREE.MathUtils.degToRad(h.elevation);
  const d = h.span * 0.9;
  controls.target.set(h.x, 0, h.z);
  camera.position.set(h.x + d * Math.cos(el) * Math.sin(az), d * Math.sin(el), h.z + d * Math.cos(el) * Math.cos(az));
  controls.update();
}
goHome();

// Talaj: domborzati háló (SRTM) a víz- és parkképpel (csempek_keszites.py). Ha nincs, sík talaj.
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
async function buildTerrain() {
  const resp = await fetch('data/terrain.bin');
  if (!resp.ok) throw new Error('nincs terrain.bin');
  const buf = await resp.arrayBuffer();
  const hd = new DataView(buf);
  const nx = hd.getUint32(0, true), nz = hd.getUint32(4, true);
  const x0 = hd.getFloat32(8, true), z0 = hd.getFloat32(12, true), step = hd.getFloat32(16, true);
  const h = new Int16Array(buf.slice(24));
  const SKIRT = -120;
  const W = nx + 2, H = nz + 2;      // egy külső gyűrű: a szél lefelé "szoknya"
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
  if (config.terep && config.terep.kep) {
    new THREE.TextureLoader().load('data/landcover.png', tex => {
      tex.flipY = false;
      tex.colorSpace = THREE.NoColorSpace;
      tex.minFilter = THREE.LinearMipmapLinearFilter;
      tex.generateMipmaps = true;
      tex.anisotropy = 4;
      terrainUniforms.uCover.value = tex;
      terrainUniforms.uHasCover.value = 1;
    });
  }
}
buildTerrain().catch(() => {
  const g = new THREE.PlaneGeometry(80000, 80000);
  g.rotateX(-Math.PI / 2);
  flat.add(new THREE.Mesh(g, new THREE.MeshBasicMaterial({ color: LAND })));
});

// ---------- Közös uniformok ----------
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
  uPick: { value: null },
  uPickOn: { value: 0 },
  uFogColor: uniformsFog().uFogColor,
  uFog: uniformsFog().uFog,
};

// Kiemelés (védett / Wikipédia / Lechner): épületenként egy bit; a kiemeltek megtartják a színüket, a többi elhalványul.
const PICK_ROWS = Math.ceil(config.stats.buildings / ATTR_W);
const pickData = new Uint8Array(ATTR_W * PICK_ROWS * 4);
const pickTex = new THREE.DataTexture(pickData, ATTR_W, PICK_ROWS, THREE.RGBAFormat, THREE.UnsignedByteType);
pickTex.needsUpdate = true;
uniforms.uPick.value = pickTex;

const VERT = /* glsl */`
  in float bld;
  uniform sampler2D uAttr;
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

    // Belépő animáció: csak a lejátszott filmnél és a csempék betöltésekor. Az épület a saját oldaláról "esik be".
    vec3 p = position;
    vRel = position.y * 0.1;
    vec4 lay = texelFetch(uAttr, tc + ivec2(1, 0), 0);
    p.y += lay.x + lay.y * 65536.0 - 1000.0;   // talpmagasság (dm)
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
    if (vGid == uHover || vGid == uSelected) c = mix(c, vec3(0.0), 0.35);
    if (uPickOn > 0.5) {
      int gi = int(vGid + 0.5);
      if (texelFetch(uPick, ivec2(gi % ${ATTR_W}, gi / ${ATTR_W}), 0).x < 0.5) c = mix(c, uMaquette, 0.78);
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
      // Alacsony délutáni nap délnyugatról, lágy égbolt-fény felülről.
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

// ---------- Csempék ----------
const meshes = [];
let loaded = 0;
const queue = [...config.tiles];
const pool = Array.from({ length: WORKERS }, () => new Worker('worker.js', { type: 'module' }));

function addTile(m) {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(m.pos, 3));
  g.setAttribute('bld', new THREE.BufferAttribute(m.bld, 1));
  g.setIndex(new THREE.BufferAttribute(m.idx, 1));
  const rows = Math.ceil(m.nB / ATTR_W);
  const data = new Float32Array(ATTR_W * 2 * rows * 4);
  data.set(m.attr);
  const tex = new THREE.DataTexture(data, ATTR_W * 2, rows, THREE.RGBAFormat, THREE.FloatType);
  tex.needsUpdate = true;
  const born = { value: performance.now() / 1000 };
  const mesh = new THREE.Mesh(g, makeMaterial(tex, false, born));
  mesh.userData = { draw: mesh.material, pick: makeMaterial(tex, true, born) };
  mesh.scale.setScalar(0.1);
  mesh.position.set(m.origin[0], 0, m.origin[1]);
  scene.add(mesh);
  meshes.push(mesh);
}

const packs = Object.fromEntries(config.packs.map(name => [name, fetch(`data/${name}`).then(r => r.arrayBuffer())]));
for (const w of pool) {
  const next = async () => {
    const tt = queue.shift();
    if (!tt) return;
    const buf = (await packs[tt.pack]).slice(tt.offset, tt.offset + tt.length);
    w.postMessage({ buf, id: tt.file }, [buf]);
  };
  w.onmessage = ({ data }) => {
    addTile(data);
    loaded++;
    document.getElementById('progress').textContent = Math.round(100 * loaded / config.tiles.length);
    if (loaded === config.tiles.length) document.getElementById('loading').hidden = true;
    next();
  };
  next();
}

// ---------- Kijelölés (melyik épület van az egér alatt) ----------
const pickTarget = new THREE.WebGLRenderTarget(1, 1);
const pickPixel = new Uint8Array(4);
function pick(x, y) {
  const w = renderer.domElement.clientWidth, h = renderer.domElement.clientHeight;
  camera.setViewOffset(w, h, x, y, 1, 1);
  for (const m of meshes) m.material = m.userData.pick;
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
  camera.clearViewOffset();
  return pickPixel[0] + pickPixel[1] * 256 + pickPixel[2] * 65536 - 1;
}

// ---------- Kártya ----------
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function inkOn(hex) {
  const c = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map(v => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2] > 0.3 ? '#000' : '#fff';
}

function gmapsUrl(p) {
  const q = p.cim ? `${p.cim}, Budapest` : `${p.lat},${p.lon}`;
  return 'https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent(q);
}

function indoklasSzoveg(s) {
  s = String(s || '');
  if (NYELV !== 'en') return s;
  const m = /^(\d+) ismert korú szomszéd 60 m-en belül/.exec(s);
  let out = m ? `${m[1]} neighbours with a known year within 60 m` : '';
  const z = /zóna: (\S+)/.exec(s);
  if (z) out += (out ? '; ' : '') + `zone: ${z[1]}`;
  return out;
}

function magassagSor(p) {
  const m = Math.round(p.magassag) + ' m', hu = NYELV === 'hu';
  switch (p.magassag_forras) {
    case 'height': return `${m} <small>(OpenStreetMap${hu ? ', megadott érték' : ', given value'})</small>`;
    case 'eubucco_becsles': {
      const sav = (p.eubucco_magassag_min != null && p.eubucco_magassag_max != null)
        ? (hu ? ', becslési sáv ' : ', range ') + `${Math.round(p.eubucco_magassag_min)}–${Math.round(p.eubucco_magassag_max)} m` : '';
      return `${m} <small>(EUBUCCO, ${hu ? 'gépi tanulással becsült' : 'machine-learning estimate'}${sav})</small>`;
    }
    case 'eubucco_forras': return `${m} <small>(EUBUCCO${hu ? ', forrásadatból' : ', from source data'})</small>`;
    case 'szintszam': return `${m} <small>(${hu ? 'szintszámból számolt, 3 m/szint' : 'from storeys, 3 m each'})</small>`;
    case 'szintterkep': return `${m} <small>(${hu ? 'szintszám-térképből számolt, 3 m/szint' : 'from the storey map, 3 m each'})</small>`;
    default: return `${m} <small>(${hu ? 'alapértelmezett, nincs adat' : 'default, no data'})</small>`;
  }
}

function szintSor(p) {
  let s = `${esc(p.szintek)} <small>(${esc(forrasNev(p.szintek_forras) || p.szintek_forras || '')})</small>`;
  if (p.szint_eltero && p.szintek_osm) s += ` <small>OSM: ${esc(p.szintek_osm)}</small>`;
  return s;
}

function wikipediaLinkek(p) {
  return String(p.wikipedia || '').split('|').slice(0, 3).map(cikk => {
    const m = /^(hu|en):(.+)$/.exec(cikk.trim());
    if (!m) return '';
    const url = `https://${m[1]}.wikipedia.org/wiki/${encodeURIComponent(m[2].replace(/ /g, '_'))}`;
    return `<a href="${url}" target="_blank" rel="noopener">${esc(m[2])}</a> <small>(Wikipedia, ${m[1]})</small>`;
  }).filter(Boolean);
}

function vedettsegSzoveg(p) {
  const r = [];
  if (p.vedettseg) r.push((VEDETTSEG[NYELV][p.vedettseg] || p.vedettseg) + (p.muemlek_torzsszam ? ` (${t('torzsszam')} ${p.muemlek_torzsszam})` : ''));
  if (p.vedettseg_helyi) r.push(p.vedettseg_helyi);
  return r.join(', ');
}

function keltezesSzoveg(p) {
  if (p.ev) {
    let s = esc(p.ev_forras === 'osm' || !forrasNev(p.ev_forras) ? 'OpenStreetMap' : forrasNev(p.ev_forras)) + '.';
    if (p.ev_forras === 'lechner_kozeli' || p.ev_forras === 'wikidata_kozeli') s += ' ' + t('ev_kozeli');
    return s;
  }
  return t('ev_nincs') + ' ' + t('ev_becsult_leiras');
}

function kartyaHtml(p, rogzitett) {
  const per = periods[p.kor];
  const ismert = !!p.ev;
  const nev = p.nev || p.lechner_nev;
  const cim = p.cim ? esc(p.cim) + (p.cim_tobb ? ` <small>(${t('tobb_cim').replace('{n}', p.cim_tobb)})</small>` : '') : '';
  let html = rogzitett ? '<button type="button" class="kartya-bezar" aria-label="×">×</button>' : '';
  html += `<header class="kartya-fej" style="background:${per.color};color:${inkOn(per.color)}">`;
  html += `<h3>${esc(nev || p.cim || t('nevtelen'))}</h3>`;
  html += `<p class="cim"><span>${cim}</span><a href="${esc(gmapsUrl(p))}" target="_blank" rel="noopener">${t('gmaps')} ↗</a></p>`;
  html += `<div class="mikor">`;
  if (ismert) html += `<span class="ev">${esc(p.ev)}</span><span class="korszak">${esc(korNev(p.kor))}</span>`;
  else html += `<span class="ev kicsi">${esc(korNev(p.kor))}</span><span class="korszak">${t('becsult')}</span>`;
  html += `</div></header>`;

  if (!ismert) {
    if (p.ev_becsles_korszak !== undefined) {
      html += `<section class="becsles">${t('becsult')}: <strong>${esc(korNev(p.ev_becsles_korszak))}</strong>, `
        + `${Math.round(p.ev_becsles_valoszinuseg * 100)}% ${t('valoszinuseg')}, ${t('bizonyossag')}: ${t(p.ev_becsles_bizonyossag) || '?'}`
        + `<br><small>${esc(indoklasSzoveg(p.ev_becsles_indoklas))}; ${t('becsles_alap')}</small></section>`;
    } else {
      html += `<section class="becsles">${t('becsult')}: <strong>${esc(korNev(p.kor))}</strong><br><small>${t('szomszedtol')}</small></section>`;
    }
  }
  if (!rogzitett) return html + `<p class="tipp">${t('reszletek')}</p>`;

  if (kepLehet(p)) html += `<section class="kep" hidden></section>`;
  const sorok = [[t('tipus'), esc(p.tipus || '?') + (p.resz ? ` <small>(${t('resz')})</small>` : '')]];
  if (p.tervezo) sorok.push([t('tervezo'), esc(p.tervezo) + (p.tervezo_forras ? ` <small>(${esc(forrasNev(p.tervezo_forras) || p.tervezo_forras)})</small>` : '')]);
  if (p.stilus) sorok.push([t('stilus'), esc(p.stilus)]);
  const ved = vedettsegSzoveg(p);
  if (ved) sorok.push([t('vedettseg'), esc(ved)]);
  if (p.szintek) sorok.push([t('szintszam'), szintSor(p)]);
  sorok.push([t('magassag'), magassagSor(p)]);
  html += `<section><dl>${sorok.map(([a, b]) => `<dt>${a}</dt><dd>${b}</dd>`).join('')}</dl></section>`;
  if (p.about) html += `<section><div style="white-space:pre-line">${esc(p.about)}</div></section>`;
  if (wikiCikkek(p).length) html += `<section class="wikikivonat"><small>${t('wiki_betolt')}</small></section>`;
  html += `<section><h4>${t('keltezes')}</h4><div>${keltezesSzoveg(p)}</div></section>`;

  const forrasok = [...wikipediaLinkek(p)];
  if (/^Q\d+$/.test(p.wikidata_id || '')) forrasok.push(`<a href="https://www.wikidata.org/wiki/${p.wikidata_id}" target="_blank" rel="noopener">Wikidata: ${p.wikidata_id}</a>`);
  forrasok.push(`<a href="https://www.openstreetmap.org/${encodeURIComponent(p.osm_tipus || 'way')}/${encodeURIComponent(p.id)}" target="_blank" rel="noopener">OpenStreetMap: ${esc((p.osm_tipus || 'way') + ' ' + p.id)}</a>`);
  forrasok.push(`<a href="${esc(gmapsUrl(p))}" target="_blank" rel="noopener">Google Maps</a>`);
  if (p.lat !== undefined) forrasok.push(`<a href="https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${p.lat},${p.lon}" target="_blank" rel="noopener">${t('utcakep')}</a>`);
  html += `<section><h4>${t('forrasok')}</h4><div>${forrasok.join('<br>')}</div></section>`;

  if (p.lechner_nev) {
    let l = `<h4>${t('lechner_blokk')}</h4>${t('megnevezes')}: ${esc(p.lechner_nev)}<br>`;
    if (p.lechner_epult) l += `${t('epult')}: ${esc(p.lechner_epult)}<br>`;
    if (p.lechner_tervezo) l += `${t('tervezo')}: ${esc(p.lechner_tervezo)}<br>`;
    if (p.lechner_illesztes === 'kozeli') l += `<small>${t('kozeli_megj')}</small>`;
    html += `<section>${l}</section>`;
  }
  return html;
}


// ---------- Wikipédia-kivonat (a kártyán, rögzítéskor tölt be; CC BY-SA 4.0, forrásmegjelöléssel) ----------
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
  // az angol felületen az angol cikket részesítjük előnyben, ha van
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

// ---------- Kép a kártyán: Wikimedia Commons (Wikidata P18 vagy a Wikipédia-cikk képe), szabad licenccel és szerzővel ----------
const kepGyorsitotar = new Map();
const kepLehet = p => !!(p.kep || /^Q\d+$/.test(p.wikidata_id || '') || wikiCikkek(p).length);
const commonsFajl = j => {
  const m = /\/wikipedia\/commons\/(?:thumb\/)?[0-9a-f]\/[0-9a-f]{2}\/([^/]+)/.exec((j && j.originalimage && j.originalimage.source) || '');
  return m ? decodeURIComponent(m[1]) : null;
};
async function kepLeker(p) {
  let fajl = null;
  if (/^Q\d+$/.test(p.wikidata_id || '')) {
    try {
      const r = await fetch(`https://www.wikidata.org/w/api.php?action=wbgetclaims&entity=${p.wikidata_id}&property=P18&format=json&origin=*`);
      const j = await r.json();
      const c = (j.claims && j.claims.P18) || [];
      const jo = c.find(x => x.rank === 'preferred') || c[0];
      if (jo && jo.mainsnak && jo.mainsnak.datavalue) fajl = String(jo.mainsnak.datavalue.value).replace(/ /g, '_');
    } catch (e) { /* tovább a cikk képére */ }
  }
  if (!fajl && p.kep) {   // a commons_kepek.py által a címhez vagy a névhez párosított fotó
    const [f, a, l, u, m, r] = p.kep;
    return { src: `https://commons.wikimedia.org/wiki/Special:FilePath/${encodeURIComponent(f)}?width=800`,
             lap: `https://commons.wikimedia.org/wiki/File:${encodeURIComponent(f)}`, szerzo: a, licenc: l, licencUrl: u, mod: m, reszlet: r };
  }
  if (!fajl && wikiCikkek(p).length) {
    try { fajl = commonsFajl(await wikiKivonatLeker(wikiCikkek(p)[0])); } catch (e) { /* nincs kép */ }
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
    hely.innerHTML = `<a href="${esc(k.lap)}" target="_blank" rel="noopener"><img alt="${esc(p.nev || p.cim || '')}" src="${esc(k.src)}"></a>`
      + `<small>${t('kep_forras')}: ${esc(k.szerzo || 'Wikimedia Commons')} · ${link(k.licencUrl, k.licenc || 'Wikimedia Commons')} · `
      + `<a href="${esc(k.lap)}" target="_blank" rel="noopener">Wikimedia Commons</a>`
      + (k.mod ? ` <em>(${t(k.mod === 'cim' ? 'kep_cim' : 'kep_nev')}${k.reszlet ? '; ' + t('kep_reszlet') : ''})</em>` : '') + `</small>`;
    hely.hidden = false;
    hely.querySelector('img').addEventListener('load', () => kartyaHelye(parseFloat(kartya.style.left) - 18, parseFloat(kartya.style.top) - 18));
  });
}

const kartya = document.getElementById('kartya');
let rogzitettGid = -1, hoverGid = -1, pointer = null, dragging = false, downAt = null;
const nincsEger = window.matchMedia('(hover: none)');

function kartyaHelye(x, y) {
  const r = kartya.getBoundingClientRect();
  kartya.style.left = Math.max(12, Math.min(x + 18, innerWidth - r.width - 12)) + 'px';
  kartya.style.top = Math.max(12, Math.min(y + 18, innerHeight - r.height - 12)) + 'px';
}
function bezar() {
  rogzitettGid = -1;
  uniforms.uSelected.value = -1;
  kartya.hidden = true;
  kartya.classList.remove('rogzitett');
}
function rogzit(gid, x, y) {
  rogzitettGid = gid;
  hoverGid = -1;
  uniforms.uSelected.value = gid;
  kartya.classList.add('rogzitett');
  kartya.innerHTML = kartyaHtml(epuletek[gid], true);
  kartya.hidden = false;
  kartya.querySelector('.kartya-bezar').addEventListener('click', bezar);
  kartyaHelye(x, y);
  wikiBetolt(gid);
  kepBetolt(gid);
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
  const gid = pick(e.clientX, e.clientY);
  if (gid < 0 || !epuletek[gid] || gid === rogzitettGid) { bezar(); return; }
  rogzit(gid, e.clientX, e.clientY);
});
canvas.addEventListener('pointerleave', () => {
  pointer = null;
  if (rogzitettGid < 0) kartya.hidden = true;
  uniforms.uHover.value = -1;
});

// ---------- Bal panel: mód, jelmagyarázat, kiemelés ----------
const maskTarget = periods.map(() => 1);
function renderLegend() {
  document.getElementById('legend').innerHTML = periods.map((p, i) =>
    `<label><input type="checkbox" data-i="${i}" ${maskTarget[i] ? 'checked' : ''}><i style="background:${p.color}"></i>${esc(korNev(i))}</label>`).join('');
  document.querySelectorAll('#legend input').forEach(c => c.addEventListener('change', () => {
    maskTarget[+c.dataset.i] = c.checked ? 1 : 0;
    uniforms.uMask.value = maskTarget;
    drawHist();
  }));
}
function setMode(m) {
  uniforms.uMode.value = m;
  document.querySelectorAll('.modes button').forEach(b => b.setAttribute('aria-pressed', String(+b.dataset.mod === m)));
  document.getElementById('legend').hidden = m !== MODE.period;
  document.getElementById('szintlegend').hidden = m !== MODE.floors;
}
document.querySelectorAll('.modes button').forEach(b => b.addEventListener('click', () => setMode(+b.dataset.mod)));

function frissitKiemelest() {
  const v = document.getElementById('vedett').checked, w = document.getElementById('wikipedia').checked, l = document.getElementById('lechner').checked;
  pickData.fill(0);
  epuletek.forEach((p, gid) => {
    const be = (v && (p.vedettseg || p.vedettseg_helyi)) || (w && p.wikipedia) || (l && p.lechner_nev);
    if (be) pickData[gid * 4] = 255;
  });
  pickTex.needsUpdate = true;
  uniforms.uPickOn.value = (v || w || l) ? 1 : 0;
}
['vedett', 'wikipedia', 'lechner'].forEach(id => document.getElementById(id).addEventListener('change', frissitKiemelest));

function alkalmazSzoveg() {
  document.documentElement.lang = NYELV;
  document.querySelectorAll('[data-t]').forEach(el => { el.textContent = t(el.dataset.t); });
  document.querySelectorAll('#nyelv button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.nyelv === NYELV)));
  document.title = t('cim') + ' (3D)';
  renderLegend();
  drawHist();
  if (rogzitettGid >= 0) {
    kartya.innerHTML = kartyaHtml(epuletek[rogzitettGid], true);
    kartya.querySelector('.kartya-bezar').addEventListener('click', bezar);
    wikiBetolt(rogzitettGid);
    kepBetolt(rogzitettGid);
  }
}
document.querySelectorAll('#nyelv button').forEach(b => b.addEventListener('click', () => {
  NYELV = b.dataset.nyelv === 'en' ? 'en' : 'hu';
  try { localStorage.setItem('nyelv', NYELV); } catch (e) { /* nincs tárhely */ }
  alkalmazSzoveg();
}));

// ---------- Időcsúszka (hisztogram) ----------
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
  hctx.font = '500 11px "Helvetica Neue", Arial, sans-serif';
  const step = w < 500 ? 100 : 50;
  for (let y = Math.ceil(T0 / step) * step; y <= T1; y += step) hctx.fillText(y, Math.min(w - 28, Math.max(0, xOf(y) - 13)), h - 4);
  hctx.fillStyle = '#000';
  hctx.fillRect(xOf(Y) - 1, 0, 2, plotH);
  if (Yf >= T0) { hctx.fillStyle = '#5d6266'; hctx.fillRect(xOf(Yf) - 0.5, 0, 1, plotH); }
  document.getElementById('year').textContent = Y >= config.yearMax ? t('ma') : Math.round(Y);
  document.getElementById('count').textContent = fmt(visibleCount());
}

let handle = null;
hist.addEventListener('pointerdown', e => {
  hist.setPointerCapture(e.pointerId);
  const x = e.offsetX;
  handle = Math.abs(x - xOf(uniforms.uYearFrom.value)) < Math.abs(x - xOf(uniforms.uYear.value)) ? 'uYearFrom' : 'uYear';
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

// Lejátszás: a ritka századokon gyorsan, a sűrűn beépülteken lassan.
let playing = false, playT0 = 0, playStart = 0;
const playBtn = document.getElementById('play');
const playIcon = document.getElementById('play-icon');
const DURATION = (+new URLSearchParams(location.search).get('film') || 30) * 1000;   // ?film=6: rövid film
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

// ---------- Ciklus ----------
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

let frame = 0;
renderer.setAnimationLoop(now => {
  frame++;
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
  if (pointer && !dragging && frame % 3 === 0) {
    const gid = pick(pointer[0], pointer[1]);
    uniforms.uHover.value = gid;
    mutat(gid, pointer[0], pointer[1]);
  }
  renderer.render(scene, camera);
});

window.__dbg = { uniforms, camera, controls, pick, rogzit, bezar, epuletek, config };
