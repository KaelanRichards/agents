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

## Vizcom — agentic SRE (`~/code/vizcom-sre`, GitHub `KaelanRichards/vizcom-sre` private)

> Read-only, recommend-only SRE agent for Vizcom prod; brain is a git repo; runs as a ~7-min loop on VM `agents`.

**Current truth.** Recommend-only SRE agent whose "brain" is the `vizcom-sre` git repo
(`infra/ code/ baselines/ runbooks/ incidents/` + `LOOP.md`/`policy.md`). Each tick: read brain →
check Datadog/Sentry → **triage** a firing alert (DM Kaelan `U04E9M9235G`, never acts) or
**explore** one area + record a baseline → commit. Runs on always-on VM **`agents`** (`ssh agents`,
Ubuntu 24.04) via `systemd --user` timer `vizcom-sre.{service,timer}` (~7 min). Read-only on Vizcom
(ops-guard + `.claude/settings.json` deny); Linear read-only; DM-only. As-built runbook:
`deploy/README.md`.

**Details.**
- Senses on VM via `deploy/mcp.vm.json` + `--strict-mcp-config`: **datadog + github + slack-dm only**
  (the full `mcp-sync` set hangs `claude -p` headless → first tick timed out; minimal set is the fix).
- Auth (`~/.config/vizcom-sre/runner.env`, chmod 600): Claude **subscription** via `claude setup-token`
  → `CLAUDE_CODE_OAUTH_TOKEN`; GitHub via `gh` device-flow + **SSO for vizcomtech**, runner sets
  `GITHUB_PAT=$(gh auth token)`; Slack bot token (`chat:write`/`im:write`/`im:history`); Datadog
  **header auth** (`DD_API_KEY`+`DD_APPLICATION_KEY`, scoped read-only).
- Vizcom prod facts: `vizcomtech/vizcom` (AWS 502554252943, us-east-2, EKS via Pulumi, **no HPA**);
  api 8 pods + general-worker; Datadog **US5** `apps-prod`; Sentry org `vizcom`. Findings: several
  always-firing monitors are chronic/undertuned (Fal-422 "Deploy Guard" 19161854; job-durations
  16122024 = render queue); plaintext CI secrets in `deploy_apps-prod.yml` (rotate Sentry token).
- Phase-1 dev ran on the Mac via `/loop`. Reuses the `personal-actions` pattern (narrow tools,
  JSONL audit, human-in-the-loop).
- VM codebase cross-checks: `agents` has a read-only local mirror at `~/code/vizcom`
  (`vizcomtech/vizcom`, refreshed by `~/vizcom-sre/deploy/run-tick.sh` before each tick);
  the diagnostician should prefer `rg`/file reads there and fall back to GitHub MCP/`gh`.

**Open questions.**
- Sentry + Linear senses deferred (OAuth-only remotes; Sentry needs node + stdio user-token).
- Confirm first clean VM tick, then `systemctl --user enable --now vizcom-sre.timer`.
- Does the `gh` `gho_` token work with the github *Copilot* MCP endpoint? (fallback: `gh` CLI via Bash).
- Surface the chronic-monitor + CI-secrets findings to the Vizcom team (recommend-only so far).

**Timeline.**
- 2026-05-26 — Built brain + 2 triages (Phase-1 Mac); promoted to VM `agents` (systemd loop).
  Hit+fixed: facade-live canary mishap, headless-OAuth (→token auth), full-MCP tick timeout
  (→`--strict-mcp-config`). Docs: `deploy/README.md`.
- 2026-05-26 — Added VM-local `~/code/vizcom` mirror + `ripgrep` so agentic SRE can
  cross-check alerts against the Vizcom codebase before forming hypotheses.
