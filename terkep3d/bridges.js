// Schematic 3D model of the Danube bridges (based on hidak.json written by build_bridges.py).
// One bridge = one Mesh (decks, piers, pylons with per-vertex colour) + one LineSegments (cables, arch, hangers, truss).
// The Mesh gets two materials: a drawing one and a picking one (a GPU identifier image, as for the buildings), so the bridge can be selected together with the buildings, by depth,
// and gets the same card.

export const SZINEK = { ut: [0.55, 0.55, 0.53], sin: [0.43, 0.41, 0.39], gy: [0.72, 0.70, 0.65], szerkezet: [0.80, 0.77, 0.70], kabel: 0x4a4744 };

// ---------- pure geometry (arrays; testable without THREE) ----------
export function szalag(pontok, szel, vastag, szin) {
  const n = pontok.length, pos = [], col = [], idx = [];
  for (let i = 0; i < n; i++) {
    const a = pontok[Math.max(i - 1, 0)], b = pontok[Math.min(i + 1, n - 1)];
    let tx = b[0] - a[0], tz = b[2] - a[2];
    const l = Math.hypot(tx, tz) || 1;
    tx /= l; tz /= l;
    const nx = -tz, nz = tx, h = szel / 2, p = pontok[i];
    // TL, TR, BL, BR
    pos.push(p[0] + nx * h, p[1], p[2] + nz * h,  p[0] - nx * h, p[1], p[2] - nz * h,
             p[0] + nx * h, p[1] - vastag, p[2] + nz * h,  p[0] - nx * h, p[1] - vastag, p[2] - nz * h);
    for (let k = 0; k < 4; k++) col.push(szin[0], szin[1], szin[2]);
  }
  for (let i = 0; i < n - 1; i++) {
    const a = i * 4, b = a + 4;
    idx.push(a, a + 1, b + 1,  a, b + 1, b,            // top
             a + 2, b + 3, a + 3,  a + 2, b + 2, b + 3, // alul
             a, b, b + 2,  a, b + 2, a + 2,            // bal oldal
             a + 1, b + 3, b + 1,  a + 1, a + 3, b + 3); // jobb oldal
  }
  return { pos, col, idx };
}

// Rotated box: centre (x, z), rotation r (the bridge's direction), length d along the direction, width w sideways, y0..y1, sideways offset o.
export function doboz(x, z, r, d, w, y0, y1, o, szin) {
  const c = Math.cos(r), s = Math.sin(r), pos = [], col = [], idx = [];
  for (const dy of [y0, y1]) for (const [u, v] of [[-d / 2, -w / 2], [d / 2, -w / 2], [d / 2, w / 2], [-d / 2, w / 2]]) {
    const vv = v + o;
    pos.push(x + u * c - vv * s, dy, z + u * s + vv * c);
    col.push(szin[0], szin[1], szin[2]);
  }
  idx.push(0, 1, 2, 0, 2, 3,  4, 6, 5, 4, 7, 6,  0, 4, 5, 0, 5, 1,  1, 5, 6, 1, 6, 2,  2, 6, 7, 2, 7, 3,  3, 7, 4, 3, 4, 0);
  return { pos, col, idx };
}

export function egyesit(reszek) {
  const pos = [], col = [], idx = [];
  for (const r of reszek) {
    const base = pos.length / 3;
    for (const v of r.pos) pos.push(v);
    for (const v of r.col) col.push(v);
    for (const i of r.idx) idx.push(base + i);
  }
  return { pos, col, idx };
}

// The solid parts of the bridge: decks, piers, pylons.
export function hidTest(h, szin) {
  const reszek = [];
  for (const v of h.vonalak) if (v.p.length >= 2) reszek.push(szalag(v.p, v.sz, 2.4, szin));
  for (const p of h.piler) reszek.push(doboz(p.x, p.z, p.r, p.d, p.w, p.y0, p.y1, 0, szin));
  for (const t of (felsoNelkul(h) ? [] : h.tornyok)) {
    for (const o of [-t.hsz, t.hsz]) reszek.push(doboz(t.x, t.z, t.r, 3.2, 3.2, t.y0, t.y1, o, szin));
    reszek.push(doboz(t.x, t.z, t.r, 2.4, 2 * t.hsz + 3.2, t.y1 - 3.0, t.y1, 0, szin));
    reszek.push(doboz(t.x, t.z, t.r, 2.0, 2 * t.hsz + 3.2, t.yd + 12.0, t.yd + 13.5, 0, szin));
  }
  return egyesit(reszek);
}

// For these bridges we do not draw the elements above the roadway (pylons, towers, cables, truss) (at the user's request); only the deck and the piers are visible.
// The list contains the bridge's OSM identifiers, so it stays valid after build_bridges.py is rerun.
const FELSO_ELREJT = new Set([954850609, 59718711, 106787454, 40726035, 737289237]);
function felsoNelkul(h) { return (h.osm || []).some(o => FELSO_ELREJT.has(o && o.id)); }

// The thin lines (cables, arch, hangers, truss) as segment pairs.
export function hidVonalak(h) {
  const pos = [];
  if (!felsoNelkul(h)) for (const k of h.kabelek) for (let i = 0; i < k.length - 1; i++) pos.push(...k[i], ...k[i + 1]);
  return pos;
}

// ---------- materials and the scene ----------
const VERT = /* glsl */`
  in vec3 color;
  out vec3 vColor;
  out vec3 vWorld;
  void main() {
    vColor = color;
    vec4 w = modelMatrix * vec4(position, 1.0);
    vWorld = w.xyz;
    gl_Position = projectionMatrix * viewMatrix * w;
  }
`;
const FRAG = /* glsl */`
  precision highp float;
  uniform vec3 uFogColor;
  uniform vec2 uFog;
  uniform vec3 uId;
  uniform vec3 uMaq;
  uniform float uGrey;
  in vec3 vColor;
  in vec3 vWorld;
  out vec4 outColor;
  void main() {
    #ifdef PICK
      outColor = vec4(uId, 1.0);
    #else
      vec3 n = normalize(cross(dFdx(vWorld), dFdy(vWorld)));
      float sun = max(dot(n, normalize(vec3(-0.55, 0.55, 0.62))), 0.0);
      float light = n.y > 0.9 ? 1.04 : 0.66 + 0.34 * sun;
      vec3 c = uGrey > 1.5 ? vec3(1.0) : mix(vColor * light, uMaq, 0.78 * uGrey);   // kiemelés-szűrő: ami nem esik bele, szürke
      float d = length(vWorld - cameraPosition);
      c = mix(c, uFogColor, smoothstep(uFog.x, uFog.y, d));
      outColor = vec4(c, 1.0);
    #endif
  }
`;

// THREE: the three.js namespace; fogUniforms (ködUniformok): { uFogColor, uFog } from app.js; elsoGid: the first picking identifier assigned to the bridges.
export function hidakEpit(THREE, adat, koduniformok, elsoGid, szinFn) {
  const csoport = new THREE.Group();
  const meshek = [];
  const vonalak = [];
  adat.hidak.forEach((h, i) => {
    const gid = elsoGid + i, id = gid + 1;
    const szin = szinFn ? szinFn(h) : SZINEK.szerkezet;   // the colour of the era of construction: the whole bridge is one block, one colour
    const test = hidTest(h, szin);
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(test.pos), 3));
    g.setAttribute('color', new THREE.BufferAttribute(new Float32Array(test.col), 3));
    g.setIndex(new THREE.BufferAttribute(new Uint32Array(test.idx), 1));
    const anyag = pick => new THREE.ShaderMaterial({
      glslVersion: THREE.GLSL3, vertexShader: VERT_ANIM, fragmentShader: FRAG, side: THREE.DoubleSide,
      defines: pick ? { PICK: 1 } : {},
      uniforms: { uFogColor: koduniformok.uFogColor, uFog: koduniformok.uFog, uMaq: koduniformok.uMaquette || { value: new THREE.Color(0.8, 0.8, 0.8) }, uGrey: { value: 0 },
                  // the same entry animation as for the buildings: it rises in the year of construction on playback, drops in on load
                  uYear: koduniformok.uYear, uNow: koduniformok.uNow, uPlaying: koduniformok.uPlaying, uRise: koduniformok.uRise,
                  uBorn: koduniformok.uBorn, uEv: { value: h.ev || 0 }, uSeedGid: { value: gid },
                  uId: { value: new THREE.Vector3((id % 256) / 255, (Math.floor(id / 256) % 256) / 255, Math.floor(id / 65536) / 255) } },
    });
    const mesh = new THREE.Mesh(g, anyag(false));
    mesh.userData = { draw: mesh.material, pick: anyag(true), gid, hid: i };
    mesh.frustumCulled = false;
    csoport.add(mesh);
    meshek.push(mesh);
    const lp = hidVonalak(h);
    if (lp.length) {
      const lg = new THREE.BufferGeometry();
      lg.setAttribute('position', new THREE.BufferAttribute(new Float32Array(lp), 3));
      const l = new THREE.LineSegments(lg, new THREE.LineBasicMaterial({ color: new THREE.Color(szin[0], szin[1], szin[2]) }));
      l.frustumCulled = false;
      l.userData = { hid: i };
      csoport.add(l);
      vonalak.push(l);
    }
  });
  return { csoport, meshek, vonalak };
}

// A "building-like" data-sheet record from the bridges, for the existing card.
export function hidRekord(h, korszakIndex) {
  const r = {
    hid: true, nev: h.nev, tipus: 'híd' + (h.szerkezet ? ` (${{ fuggo: 'függőhíd', kabeles: 'kábeles híd', iv: 'ívhíd', racsos: 'rácsos tartós híd', gerenda: 'gerendahíd' }[h.szerkezet] || h.szerkezet})` : ''),
    ev: h.ev || undefined, ev_forras: h.ev ? (h.ev_forras || 'hid_adat') : undefined, kor: korszakIndex(h.ev),
    tervezo: h.tervezo || undefined, wikipedia: h.wikipedia || undefined, wikidata_id: h.wikidata || undefined,
    lat: h.lat, lon: h.lon, osm_tipus: h.osm && h.osm[0] ? h.osm[0].t : 'way', id: h.osm && h.osm[0] ? h.osm[0].id : '',
    hid_hossz: h.hossz_m, hid_viz: h.viz_m, hid_ujjaepitve: h.ujjaepitve || undefined, hid_megj: h.megjegyzes || undefined, kep_fajl: h.kep || undefined, kep_keres: h.keresesek || [h.nev],
  };
  return r;
}


// The vertex shader of the disc: the same look/entry animation as for the buildings of the tiles (rising by year, dropping in on load); the sizes are in metres.
const VERT_ANIM = /* glsl */`
  in vec3 color;
  out vec3 vColor;
  out vec3 vWorld;
  uniform float uYear, uNow, uBorn, uPlaying, uRise, uEv, uSeedGid;
  void main() {
    vColor = color;
    float g = clamp((uYear - uEv + 1.0) / uRise, 0.0, 1.0);
    g = g * g * (3.0 - 2.0 * g);
    if (g <= 0.003) { gl_Position = vec4(2.0, 2.0, 2.0, 1.0); vWorld = vec3(0.0); return; }
    float seed = fract(sin(uSeedGid * 12.9898) * 43758.5453);
    float arrive = clamp((uNow - uBorn) / 0.9 - seed * 0.35, 0.0, 1.0);
    float fly = 1.0 - arrive;
    if (uPlaying > 0.5) fly = max(fly, 1.0 - g);
    vec3 p = position;
    if (fly > 0.0) {
      float e = fly * fly * fly;
      float ang = seed * 6.2831853;
      p += vec3(cos(ang), 0.0, sin(ang)) * (180.0 + 160.0 * fract(seed * 7.13)) * e;
      p.y += (260.0 + 240.0 * fract(seed * 3.71)) * e;
    }
    vec4 w = modelMatrix * vec4(p, 1.0);
    vWorld = w.xyz;
    gl_Position = projectionMatrix * viewMatrix * w;
  }
`;
// A thin, vertical disc (e.g. the Ferris wheel): centre (x, z), the horizontal direction of the disc's plane (ix, iz unit vector), radius R, centre height cy, thickness T.
// It gets the same two materials as the bridges (drawing + picking), the picking identifier is the given gid.
export function korlapEpit(THREE, koduniformok, gid, szin, x, z, ix, iz, R, cy, T, ev, born) {
  const N = 72, nx = -iz, nz = ix, pos = [], col = [], idx = [];
  const pont = (a, o) => [x + Math.cos(a) * R * ix + o * nx, cy + Math.sin(a) * R, z + Math.cos(a) * R * iz + o * nz];
  // 0: front centre, 1: rear centre, then the two rings
  pos.push(...[x + (T / 2) * nx, cy, z + (T / 2) * nz], ...[x - (T / 2) * nx, cy, z - (T / 2) * nz]);
  for (let i = 0; i < N; i++) { const a = (i / N) * Math.PI * 2; pos.push(...pont(a, T / 2)); }
  for (let i = 0; i < N; i++) { const a = (i / N) * Math.PI * 2; pos.push(...pont(a, -T / 2)); }
  for (let i = 0; i < pos.length / 3; i++) col.push(szin[0], szin[1], szin[2]);
  for (let i = 0; i < N; i++) {
    const j = (i + 1) % N, f0 = 2 + i, f1 = 2 + j, b0 = 2 + N + i, b1 = 2 + N + j;
    idx.push(0, f0, f1,  1, b1, b0,  f0, b0, b1,  f0, b1, f1);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(pos), 3));
  g.setAttribute('color', new THREE.BufferAttribute(new Float32Array(col), 3));
  g.setIndex(new THREE.BufferAttribute(new Uint32Array(idx), 1));
  const id = gid + 1;
  const anyag = pick => new THREE.ShaderMaterial({
    glslVersion: THREE.GLSL3, vertexShader: VERT_ANIM, fragmentShader: FRAG, side: THREE.DoubleSide,
    defines: pick ? { PICK: 1 } : {},
    uniforms: { uFogColor: koduniformok.uFogColor, uFog: koduniformok.uFog, uMaq: koduniformok.uMaquette || { value: new THREE.Color(0.8, 0.8, 0.8) }, uGrey: { value: 0 },
                uYear: koduniformok.uYear, uNow: koduniformok.uNow, uPlaying: koduniformok.uPlaying, uRise: koduniformok.uRise,
                uBorn: born, uEv: { value: ev || 0 }, uSeedGid: { value: gid },
                uId: { value: new THREE.Vector3((id % 256) / 255, (Math.floor(id / 256) % 256) / 255, Math.floor(id / 65536) / 255) } },
  });
  const mesh = new THREE.Mesh(g, anyag(false));
  mesh.userData = { draw: mesh.material, pick: anyag(true), gid, rek: gid };
  mesh.frustumCulled = false;
  return mesh;
}
