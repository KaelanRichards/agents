# Task: refresh the "Engineering Scorecard (CTO)" Notion page

You are a headless weekly job. Re-pull the LIVE metrics below and update the existing Notion
page **in place** (Notion page id `37a496f3-8e96-8136-802b-cbc14cc4ec89`, title "Engineering
Scorecard (CTO)"). Do NOT create a new page. Do NOT touch cells/sections marked MANUAL,
Finance, or HR. Be efficient; this is unattended.

**Scope: the `vizcomtech/vizcom` monorepo only.** Do not pull or add other repos
(smart-image-standalone, omni-analytics, etc.).

## 1. GitHub delivery signals (`vizcomtech/vizcom` monorepo) — use `gh api`
Window = last 30 days (set `D30=$(date -u -v-30d +%Y-%m-%d)`).
- deploy frequency: `gh api "repos/vizcomtech/vizcom/actions/workflows/deploy_apps-prod.yml/runs?created=>=$D30&per_page=100"` → total + success count → deploys/day.
- PR throughput: `gh api "search/issues?q=repo:vizcomtech/vizcom+is:pr+is:merged+merged:>=$D30&per_page=1"` → `.total_count`; per-week = /4.3.
- lead time: sample ~50 recent merged PRs (`pulls/{n}` created_at→merged_at), report median hours.
- change-failure proxy: `gh api "repos/vizcomtech/vizcom/commits?since=${D30}T00:00:00Z"` revert commits, or `search/commits?q=repo:vizcomtech/vizcom+committer-date:>=$D30+revert`; CFR = failed deploys / total deploys.
- NOTE (zsh): this shell does NOT word-split `for n in $x`; use `while read -r`. Org search API is 30 req/min — prefer the core API per-PR.

## 2. Datadog (US5, `env:apps-prod`) — via Datadog MCP (do skill discovery first)
- api error rate: `aggregate_spans` query `env:apps-prod service:api type:web`, COUNT(*) group_by status, 30d and 7d → error/(ok+error).
- api latency: `get_datadog_metric` scalar, 30d: `p50/p95/p99:vizcom.api.request_duration{env:apps-prod}` (values are nanoseconds → ms).
- general-worker job success: `get_datadog_metric` scalar 30d: `sum:worker.job.completed_count{env:apps-prod}.as_count()` vs `sum:worker.job.failed_count{env:apps-prod}.as_count()` → success %.
- firing monitors: `search_datadog_monitors` sort `status,desc`; list any in Alert state (these go in the top alert callout).

## 3. Sentry (org `vizcom`, regionUrl `https://us.sentry.io`) — via Sentry MCP
The `node` (backend) and `javascript-react` (frontend) projects are the monorepo's deploy targets.
- error counts 30d: `search_events` projectSlug `node` and `javascript-react`, dataset `errors`, fields `count()`.
- top user-impacting: `search_issues` query `is:unresolved` sort `user` limit 5, each project.
- bad release: `search_events` projectSlug `javascript-react`, dataset `errors`, fields `release,count(),count_unique(user)`, sort `-count()`, 7d — flag any release with a big affected-user spike.

## 4. Bus-factor (180d) — `gh api`, monorepo areas only
`SINCE=$(date -u -v-180d +%Y-%m-%dT00:00:00Z)`. For each path P in `apps/api`, `apps/api/src/inference`, `apps/api/src/agent`, `apps/modal`: `repos/vizcomtech/vizcom/commits?path=<P>&since=$SINCE`. Tally authors → top author %share and bus-factor (min authors for ≥50%). Flag any area with bus-factor=1 or a single author >50%.

## 5. Update the Notion page — STRICT IN-PLACE RULES

First `mcp__notion__notion-fetch` the page to get its current Notion-flavored-markdown content.
Then update with `mcp__notion__notion-update-page` `update_content`, using a SEPARATE small
`content_updates` entry for EACH individual value you change (narrow old_str → new_str).

**Hard preservation rules — violating any of these is a failed run:**
- **NEVER delete, merge, re-order, or ADD a table row or column.** Every existing row and column
  must still be present after your update, and you must not introduce new repos/rows. The bus-factor
  table has exactly 4 monorepo rows (`apps/api`, `apps/api/src/inference`, `apps/api/src/agent`,
  `apps/modal`); keep all 4 and add none.
- **NEVER replace a whole table or whole section.** Only swap individual numbers/phrases inside
  existing cells via targeted old_str/new_str. If you cannot construct a safe narrow match for a
  value, LEAVE THAT VALUE UNCHANGED rather than rewriting the surrounding block.
- **Preserve all prose, callouts, the 🟢/🟡/GAP legend, every MANUAL/Finance/HR cell, and every
  risk flag/emoji.** Do not paraphrase headings or explanations.
- If a data source errors or returns nothing, keep the prior value and append "(refresh failed
  <date>)" to that section's header — never blank or drop it.

**What you MAY change (values only, in place):**
- The top alert callout: the list of currently-firing Datadog monitors.
- Delivery Health table: the live numbers (deploy freq, lead time, CFR, throughput) for `vizcom`.
- Reliability/SLI table: api error rate, latency, worker success, Sentry counts/top issue, bad release.
- Bus-factor table: each area's top-author %share and bus-factor (keep all 4 rows).
- The "**As of <date>**" line → today's date.

Before calling update, sanity-check: your edit must not change the page's row/column/callout count.
Finish by printing a one-line summary of exactly which values changed.
