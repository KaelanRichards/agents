# Projects

> Active projects, repos, channels, and operating notes.

Each entry: **Current truth** (what's true now) · **Details** · **Open questions** · **Timeline**
(dated changes — append, don't overwrite, so staleness stays visible).

## Vizcom — local dev (`~/code/vizcom`, jj colocated)

**Current truth.** Full-stack monorepo, run locally on this Mac: PostGraphile API on `:3333`,
Vite/React web on `:4200` (proxies `/api/v1/*` → API, stripping `/api/v1`), Modal GPU workers.
Login `admin@test.com` / `test`.

**Details.** Run order: OrbStack up (`orb start`) → `docker compose up -d postgres redis` → mise
`node@24.13.1` + `pnpm@9.0.4` (matches `.nvmrc` / `packageManager`) → `pnpm install` →
`pnpm api:migrate-db` → `pnpm api:seed` → `pnpm serve`.
Gotcha (~20 min to find): several `apps/api/src/inference/**` modules do
`if (!process.env.FAL_API_KEY) throw` at *import time*; `main.ts` loads `startApiMode` via a dynamic
`import()`, so a missing `FAL_API_KEY` rejects that import and silently skips
`postgraphileMiddleware` + all `/auth/*` routes — `/healthcheck` 200 but `/graphql` and `/auth/*`
404. Fix: set `FAL_API_KEY` to any non-empty placeholder in a gitignored `~/code/vizcom/.env.local`
(`.env` has `FAKE_INFERENCE=true`, so inference is mocked; a real key is only needed to hit FAL).

**Open questions.** Propose the `.env.local` / `FAL_API_KEY` note for the repo README setup section.

**Timeline.**
- 2026-05-24 — Recorded local run steps + the FAL_API_KEY import-time gotcha.

## Vizcom — SRE recruiting

**Current truth.** Kaelan sources engineering candidates for a Vizcom SRE / infra hire via Juicebox
(app.juicebox.ai), Juicebox project label "SRE". Outreach from `kaelan@vizcom.com`; candidates book
intro calls via a Google appointment-scheduling link (Zoom).

**Details.** Heath Chiavettone — Staff SWE @ Freenome (Oakland, CA), Northeastern BS CS,
`vballdemigod@gmail.com`.

**Open questions.** Who else is in the pipeline? (none recorded.)

**Timeline.**
- 2026-05-25 — Heath Chiavettone exploratory intro call; outcome: passed / not moving forward.
