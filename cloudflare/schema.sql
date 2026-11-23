-- D1 table of the "I know more" suggestions (anonymous: no IP address, no e-mail).
-- Created once:  npx wrangler d1 execute budapest-suggestions --remote --file=cloudflare/schema.sql
CREATE TABLE IF NOT EXISTS javaslatok (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  ido       TEXT NOT NULL DEFAULT (datetime('now')),   -- UTC
  osm_tipus TEXT NOT NULL,                              -- way / relation
  osm_id    TEXT NOT NULL,
  lat       REAL,
  lon       REAL,
  cim       TEXT,                                       -- the building's address on the card (context for the review)
  nev       TEXT,
  ev        TEXT,
  tervezo   TEXT,
  iroda     TEXT,                                       -- architecture office
  leiras    TEXT,
  link      TEXT,
  iroda_oldal INTEGER NOT NULL DEFAULT 0,              -- 1 = the link is the office's own page about the building (it goes to "Learn more")
  nyelv     TEXT,                                       -- hu / en (the language of the interface)
  allapot   TEXT NOT NULL DEFAULT 'uj'                  -- uj (new) / exportalt (exported) / elutasitott (rejected)
);
CREATE INDEX IF NOT EXISTS idx_javaslatok_osm ON javaslatok (osm_tipus, osm_id);
CREATE INDEX IF NOT EXISTS idx_javaslatok_ido ON javaslatok (ido);
