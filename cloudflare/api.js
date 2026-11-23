// Cloudflare Worker: receives the "I know more" suggestions about buildings and stores them in the D1 database.
// Only /api/* reaches this code (see run_worker_first in wrangler.jsonc); every other request is served as a plain static file.
// Anonymous by design: no IP address, no e-mail, no cookie is stored. Spam protection: Cloudflare Turnstile + daily limits.

const MAX = { nev: 150, ev: 40, tervezo: 150, iroda: 150, leiras: 500, link: 300, cim: 200 };
const NAPI_KORLAT = 300;          // at most this many suggestions per day in total
const EPULET_NAPI_KORLAT = 8;     // ... and per building

const json = (obj, status = 200) => new Response(JSON.stringify(obj), {
  status, headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' },
});

// removes control characters (a new line is kept only where allowed) and trims the ends
function tisztit(v, ujsor) {
  let s = String(v ?? '');
  s = ujsor ? s.replace(/[\u0000-\u0009\u000b-\u001f\u007f]/g, ' ') : s.replace(/[\u0000-\u001f\u007f]/g, ' ');
  return s.trim();
}

export async function feldolgoz(request, env) {
  if (request.method !== 'POST') return json({ ok: false, hiba: 'method' }, 405);
  // only from our own pages
  const origin = request.headers.get('Origin');
  if (origin && origin !== new URL(request.url).origin) return json({ ok: false, hiba: 'origin' }, 403);
  const raw = await request.text();
  if (raw.length > 8000) return json({ ok: false, hiba: 'too_big' }, 413);
  let b;
  try { b = JSON.parse(raw); } catch (e) { return json({ ok: false, hiba: 'json' }, 400); }
  if (!b || typeof b !== 'object') return json({ ok: false, hiba: 'json' }, 400);

  if (b.web) return json({ ok: true });      // honeypot: only bots fill it; they get a fake success

  const osmTipus = String(b.osm_tipus || '');
  const osmId = String(b.osm_id || '');
  if (!['way', 'relation'].includes(osmTipus) || !/^\d{1,12}$/.test(osmId)) return json({ ok: false, hiba: 'building' }, 400);
  const nev = tisztit(b.nev), ev = tisztit(b.ev), tervezo = tisztit(b.tervezo), iroda = tisztit(b.iroda), leiras = tisztit(b.leiras, true);
  const link = tisztit(b.link), cim = tisztit(b.cim);
  if (nev.length > MAX.nev || ev.length > MAX.ev || tervezo.length > MAX.tervezo || iroda.length > MAX.iroda || leiras.length > MAX.leiras
      || link.length > MAX.link || cim.length > MAX.cim) return json({ ok: false, hiba: 'too_long' }, 400);
  if (!nev && !ev && !tervezo && !iroda && !leiras && !link) return json({ ok: false, hiba: 'empty' }, 400);
  if (link && !/^https?:\/\/[^\s"'<>]{3,}$/i.test(link)) return json({ ok: false, hiba: 'link' }, 400);
  const nyelv = b.nyelv === 'en' ? 'en' : 'hu';
  const irodaOldal = link && b.iroda_oldal === true ? 1 : 0;      // the link is the office's own page about the building
  const szam = (v, a, z) => { const n = Number(v); return Number.isFinite(n) && n >= a && n <= z ? n : null; };
  const lat = szam(b.lat, 46.5, 48.5), lon = szam(b.lon, 17.5, 20.5);

  // Cloudflare Turnstile (the secret key is a Worker secret: wrangler secret put TURNSTILE_SECRET)
  if (!env.TURNSTILE_SECRET) return json({ ok: false, hiba: 'not_configured' }, 503);
  const token = String(b.token || '');
  if (!token || token.length > 4096) return json({ ok: false, hiba: 'captcha' }, 400);
  let ellenorzes;
  try {
    const r = await fetch('https://challenges.cloudflare.com/turnstile/v0/siteverify', {
      method: 'POST',
      body: new URLSearchParams({ secret: env.TURNSTILE_SECRET, response: token }),
    });
    ellenorzes = await r.json();
  } catch (e) { return json({ ok: false, hiba: 'captcha_service' }, 502); }
  if (!ellenorzes || !ellenorzes.success) return json({ ok: false, hiba: 'captcha' }, 400);

  // limits (no IP address is stored, so the limits are global and per building)
  const osszes = await env.DB.prepare("SELECT COUNT(*) AS n FROM javaslatok WHERE ido > datetime('now', '-1 day')").first();
  if (osszes && osszes.n >= NAPI_KORLAT) return json({ ok: false, hiba: 'limit' }, 429);
  const epulet = await env.DB.prepare("SELECT COUNT(*) AS n FROM javaslatok WHERE osm_tipus = ?1 AND osm_id = ?2 AND ido > datetime('now', '-1 day')")
    .bind(osmTipus, osmId).first();
  if (epulet && epulet.n >= EPULET_NAPI_KORLAT) return json({ ok: false, hiba: 'limit' }, 429);

  await env.DB.prepare('INSERT INTO javaslatok (osm_tipus, osm_id, lat, lon, cim, nev, ev, tervezo, iroda, leiras, link, iroda_oldal, nyelv) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13)')
    .bind(osmTipus, osmId, lat, lon, cim || null, nev || null, ev || null, tervezo || null, iroda || null, leiras || null, link || null, irodaOldal, nyelv).run();
  return json({ ok: true });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === '/api/javaslat') {
      try { return await feldolgoz(request, env); }
      catch (e) { return json({ ok: false, hiba: 'server' }, 500); }
    }
    if (url.pathname.startsWith('/api/')) return json({ ok: false, hiba: 'not_found' }, 404);
    return env.ASSETS.fetch(request);
  },
};
