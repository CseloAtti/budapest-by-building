-- One-time migration of an existing database: the architecture office fields.
-- Run it BEFORE deploying the new Worker:  npx wrangler d1 execute budapest-suggestions --remote --file=cloudflare/migration_office.sql
ALTER TABLE javaslatok ADD COLUMN iroda TEXT;
ALTER TABLE javaslatok ADD COLUMN iroda_oldal INTEGER NOT NULL DEFAULT 0;
