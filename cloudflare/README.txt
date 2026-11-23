"I know more" suggestions (anonymous form on the building card)

How it works
  card button -> form (app.js) -> POST /api/javaslat -> Cloudflare Worker (api.js) -> D1 database table "javaslatok"
  Only /api/* reaches the Worker; every other request is a plain static file from the release/ folder.
  Nothing personal is stored: no IP address, no e-mail, no cookie. Spam protection: Cloudflare Turnstile (CAPTCHA),
  a hidden honeypot field, field length checks, and daily limits (300 in total, 8 per building).
  The suggestions are published as CC0 (the form says so).

One-time setup (in the project folder)
  1. npx wrangler login
  2. npx wrangler d1 create budapest-suggestions
       -> copy the "database_id" it prints into wrangler.jsonc (replace REPLACE_WITH_DATABASE_ID)
  3. npx wrangler d1 execute budapest-suggestions --remote --file=cloudflare/schema.sql
  4. Cloudflare dashboard -> Turnstile -> Add widget (domain: budapestbuildings.com, mode: Managed)
       -> put the SITE KEY into app.js (const TURNSTILE_KULCS = '...')
       -> npx wrangler secret put TURNSTILE_SECRET   (and paste the SECRET KEY)
  5. release_deploy.bat

Adding the architecture-office fields to an EXISTING database (once; new databases get them from schema.sql)
  1. npx wrangler d1 execute budapest-suggestions --remote --file=cloudflare/migration_office.sql
  2. only then deploy the new Worker (release_deploy.bat); the old table has no iroda columns, so the new Worker could not save without step 1

Reviewing the suggestions
  py suggestions_export.py          new suggestions -> suggestions/javaslatok_<date>.csv  (open in Excel)
  py suggestions_export.py --mark   the same, and the exported rows get the status "exportalt"
  Merge the accepted ones by OSM id (osm_tipus + osm_id) into the data tables.

Local test of the Worker: tests/test_suggestions.py (fake database and fake CAPTCHA, needs node).
