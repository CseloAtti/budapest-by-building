# Budapest épületei / Budapest by building

Live site: https://budapestbuildings.com (repo: CseloAtti/budapest-by-building).
Project folder on the owner's computer: `C:\Users\User\Documents\budapest-by-building` (Windows).

## About the owner and how to work with them
- Reply in **Hungarian**. The owner is not a programmer: give simple, numbered, step-by-step instructions, and say exactly what to type and where.
- **Never run `git commit` or `git push` unless explicitly asked.** Never deploy (`wrangler deploy`, `release_deploy.bat`) unless asked.
- Ask before anything hard to undo (deleting files, remote DB changes, deploys).

## Language policy in the code
- English: comments, docstrings, Python identifiers, file names.
- Hungarian (keep as is): data field names (`iroda`, `iroda_link`, `iroda_oldal`, `tervezo`, ...), JS identifiers in `terkep3d/app.js`, UI strings, and test messages.

## File conventions
- Files on Windows use **CRLF** line endings (`terkep3d/index.html` is LF). Preserve each file's existing line endings when editing.
- `terkep3d/app.js`: the tests scan its text, and there is a rule about its last line. Do not append anything after the final line without checking `tests/`.
- Tests: `py tests\run_all.py`. Run them after changes. A skipped test must never be silent (a missing file inside the project is an error).

## Data flow
`assemble.py` -> `year_estimate` -> `assemble` -> `build_tiles` (all run by `zones_refresh.bat`).
Deploy: `release_deploy.bat` (= `build_release.py` + `npx wrangler deploy`).
`release/_headers` caches `/data_varos/*` for 24 h, js/css/json for 1 h, so after a data change the owner may see old data in a normal browser window; check in an incognito window.

## Architecture fields
- `iroda` = architecture office, `iroda_link` = the office's own page (shown under "Tudj meg többet" with `rel="nofollow noopener noreferrer"`), `iroda_oldal` = flag in the suggestion form. Office list: `forras/epitesz_irodak.csv`.
- Manual data corrections live in `forras/kezi_javitasok.csv`.

## User suggestions workflow (Cloudflare Worker + D1 `javaslatok`)
1. `py suggestions_export.py --mark` -> review the CSV together with the owner.
2. `py suggestions_import.py <csv> --dry-run` -- **always the dry run first**. Import skips duplicates; use `--skip ids` for rejected rows.
3. Real import, then `zones_refresh.bat`, then `release_deploy.bat`, then (owner) git add/commit/push.
- Privacy: do not record the names of residents of private houses. Other data may be entered.
- Two named architects are `tervezo`, not an office.

## Cloudflare deploy order
If the D1 schema changes, run the migration **before** deploying the new Worker, e.g.
`npx wrangler d1 execute budapest-suggestions --remote --file=cloudflare/migration_office.sql`
Then deploy. The old `cloudflare/migracio_iroda.sql` is obsolete and should be deleted (the owner does it).

## three.js map notes (`terkep3d/app.js`)
- MapControls; 2D mode = `enableRotate=false`, camera polar 0.001 rad, azimuth 0 (north = -z). Camera flights are tokenised by `repulAz`.
- Navigation block: `nezetFordit`, `mod2dBeallit`, `navSzoveg`, `iranytuFrissit`, `let mod2d`.

## Git
- Large files must not be committed (a 114 MB video once blocked a push; `video/` and `*.mp4` are in `.gitignore`).
