# Recommend-Only Agent Fleet: Definitive Improvement Plan

**Author:** Lead engineer (synthesis of 6 research areas + adversarial verifications)
**Date:** 2026-05-30 · **Operated by:** 1 person (Kaelan) · **Fleet:** `vizcom-sre`, `kaelan-pa`, `vizcom-pm`, `vizcom-review` (read-only sensors over disjoint domains)
**Framing:** SOTA single-incident agent resolve rates are low — ITBench **13.8% SRE / 25.2% CISO / 0% FinOps** (independent, arXiv 2502.05352); SREGym frontier E2E varies widely (independent, arXiv 2605.07161). This plan **raises a reliability floor and tightens the human loop**. It does **not** pursue autonomy. The recommend-only framing is correct and stays.

**Observed failures this plan targets** (the load-bearing reference set):
| # | Failure | One-line |
|---|---|---|
| 1 | Silent degradation | 44 dead ticks; Slack send-path silently expired, loop "ran" but delivered nothing |
| 2 | Clock drift | "now" reconstructed from brain → 4-day-stale belief |
| 3 | Fabrication | brain wrote `pushed`/headers with no tool artifact |
| 4 | Over/under-alerting | 14 DMs on one non-incident, then "no clean pages all week" |
| 5 | Human bottleneck | 17-tick approval stall; 38+ unpushed ticks (disk-loss risk) |
| 6 | Dead feedback loop | reaction-reader broken → no online precision signal |
| 7 | No eval | no scored gate on prompt/policy changes for most agents |

---

## 1. Executive summary — top improvements ranked by impact/effort

Ranked high→low leverage. "Vendor" vs "independent" marked where a number anchors a decision.

| # | Improvement | Fixes | Effort | Impact | Evidence grade |
|---|---|---|---|---|---|
| 1 | **External black-box send-path synthetic + per-agent dead-man's-switch** — an out-of-process probe round-trips a real Slack message and confirms delivery; absence-of-heartbeat pages the human | 1, 4, 6 | S | Highest | Independent (Google SRE Ch.10, *not* Ch.6 — corrected) |
| 2 | **Generalize the anti-fabrication hook into a post-condition contract** — any brain write claiming an action must cite a tool-result artifact present in *this tick's* transcript, else hard-deny | 3 | S | Highest | Independent (OWASP LLM01 defense-in-depth; *not* "most reliable layer" — corrected) |
| 3 | **External clock + freshness TTLs** — `CURRENT_UTC` anchored to the external collector, not the agent; every brain fact carries `observed_utc`; retrieval filters stale | 2 | S | High | Independent (verification: anchor clock externally or a degraded brain satisfies its own pin) |
| 4 | **MWMBR burn-rate + dedup in the page pre-gate** — require long+short burn-rate breach on golden-signal SLOs; collapse repeats by fingerprint; **absolute-count guard for low-QPS** | 4 | M | High | Independent (Google SRE Workbook Table 5-8, verified exact) |
| 5 | **MCC + expected-silence FP gate in `score.py`** — F1 misleads at ~0 incidents/week; MCC uses all 4 cells; weight FPs as a first-class gate | 7, 4 | S | High | Independent (standard ML result, verified) |
| 6 | **Fix reaction-reader → online precision loop with small-N statistics** — emoji = label; report Wilson interval + minimum-N gate before any CI trip | 6, 7 | M | High | Independent (small-N omission flagged by verification) |
| 7 | **5th read-only supervisor/digest agent** — reads 4 ledgers → one briefing with liveness + alert-quality + eval rollups; strictly non-authoritative; **has its own watchdog** | 1, 4, 5, 7 | M | High | Vendor-directional (Anthropic orchestrator-worker; "90.2%" is a private eval — do not over-weight; ~80% of lift = tokens) |
| 8 | **Tiered autonomy + batched/TTL approval queue** — reversibility × blast-radius × confidence; one queue per pass replaces 17 stacked gates; T3 stays hard-gated | 5 | M | High | Independent (Parasuraman/Sheridan/Wickens 2000; Horvitz 1999) |
| 9 | **Write-time `adjudicate` hook + brain front-matter** — deny brain write that conflicts with an active fact unless `supersedes` set; provenance/TTL/status tags | 2, 3 | M | Med-High | Independent guardrail compensating for measured model weakness (STALE 55%, MemoryAgentBench CR-MH ≤6%) |
| 10 | **Value-free-tick detector + unpushed-brain alarm** — flag ticks with no artifact/DM/brain-delta; alarm when brain unpushed > K ticks | 1, 5 | S | Med | Independent pattern (deadmancheck is illustrative, not a dependency) |

**Hype to avoid:** A2A protocol (no cross-vendor need); multi-agent chat between the 4 sensors (Cognition coherence risk for zero benefit); treating MemGPT as "infinite memory"; the fabricated **"~80% false-alarm reduction"** stat (not in the cited source — *delete it*); AIOpsLab "69–88% mitigation" and SREGym "40%" as targets (unverified exact figures — use as direction only); κ≥0.6 / Spearman 0.51 as hard thresholds (vendor-blog rules of thumb).

---

## 2. Reliability & self-monitoring — build this first

The single highest-value control is an **external observer the failing agent cannot fake**. Everything in §1 rows 1-3 is here.

### Build order
1. **External black-box send-path synthetic (P0).** A separate process (the collector / VM cron, not the agent) round-trips a canary Slack DM and confirms out-of-band delivery. White-box "send-path verified" is self-report from the same process that died silently in failure 1 — structurally untrustworthy. This is the one check that cannot be faked by a degraded agent.
2. **Per-agent dead-man's-switch (P0).** Each tick emits a heartbeat to the external collector; N missed (≈2× the 25-30 min cadence) → the *human* gets paged. Absence-of-data is the signal (Google SRE Ch.10/Borgmon — note the research mis-cited Ch.6; Ch.6 is golden-signals only).
3. **Split liveness vs readiness, per-tick JSONL (P0).** Liveness = "loop ran." Readiness = `{mcps_loaded, tool_error_rate, token_expiry_s, degraded_capabilities[], clock_pin_ok}`. **Degraded-but-running is the most dangerous state** → demote agent to "announce degradation, do not act."
4. **External clock anchor (P0).** `CURRENT_UTC` and heartbeat originate from the collector, not the agent — a degraded brain must not be able to satisfy its own freshness pin (verification correction). Readiness fails if clock absent or drifts from wall clock.
5. **Action post-condition contract (P0).** Generalize the existing PreToolUse anti-fabrication hook (currently message-id scoped) to: any brain write asserting `pushed`/`sent`/`read`/`created` must cite an artifact (commit SHA, draft id, API 200) present in this tick's transcript → no artifact = hard-deny. Deterministic enforcement; Reflexion-style self-critique stays **advisory only** (Shinn 2023, correctly demoted).
6. **Rate-limit / dedup + value-free-tick detector (P1).** Max DMs per incident-key per window (14-DM storm structurally impossible). Flag ticks producing no artifact/DM/brain-delta. **Caveat (verification):** do *not* add a naive "zero clean pages = suspicious" meta-alarm — it manufactures low-value pages, the exact anti-pattern. Liveness is covered by the heartbeat; reserve any silence alarm for an explicit page-budget/actionability SLO.
7. **Token-runway readiness + unpushed-brain alarm (P1).** Check refresh-token *expiry runway*, not just presence (silent Slack expiry caused failures 1 and 6). Alarm when brain unpushed > K ticks (disk-loss, failure 5).

**Files:** `hooks/` (extend the PreToolUse contract), per-agent profile readiness in `profiles/*.json`, new external collector job (VM `systemd/` + `state/`), `vizcom-sre` `tests/eval-pregate.sh` neighbor for rate-limit.

---

## 3. Evaluation & feedback

Extend the existing deterministic gate (`~/code/vizcom-sre/evals/score.py` — confirmed: applies `baselines/monitors.classification.json` to frozen scenarios, P/R/F1, exit-nonzero on mismatch) into a fleet-wide scored gate.

### Concrete changes
| Change | Where | Why |
|---|---|---|
| **Add MCC** alongside P/R/F1 | `score.py` (`main()` after line 91) | F1 ignores TN; at ~0 incidents/week the class imbalance is extreme; MCC uses all 4 cells (independent, verified) |
| **Expected-silence FP gate** weighted heavily; fail CI if a sub-baseline monitor would page | `score.py` + new scenarios | Directly encodes the 14-DM failure; formalize existing `iops-noise-canonical`, `contentpolicy-edit-noise` as "expected silence" |
| **Every ❌ reaction → frozen scenario** | reaction-ingest job → `evals/scenarios/` | Closes online↔offline loop; regression-locks each correction |
| **CI-gate prompt/policy/classification changes** | `templates/eval.yml` wired to `vizcom-sre` + `agents/evals/tasks/` | Editing `monitors.classification.json`, `policy.md`, `CLAUDE.md` re-runs the gate |
| **Replay transcripts, not just classification**, for pa/pm/review (no monitor gate) | new `evals/tasks/` per agent | Half the fleet has no symptom pre-gate |
| **κ-calibrated cross-family judge** for triage prose | new `evals/judge/` | Grade "what I couldn't see," RCA plausibility — gated *only after* κ-calibration vs human labels; report κ in digest |

### Realistic expectations (independent benchmarks)
- ITBench: **13.8% SRE, 25.2% CISO, 0% FinOps** (0% FinOps is *stronger* support for recommend-only than the research's softened "0–26%").
- SREGym scores **diagnosis, mitigation, E2E separately** — adopt this split in `score.py` (separate diagnosis from action scoring). Adopt AIOpsLab vocabulary: **TTD, TTM, localization accuracy, step-efficiency**.
- **Cite arXiv papers, not vendor co-branded blogs** (e.g. ITBench-AA HuggingFace post is vendor-adjacent — use 2502.05352).

### Gaps the research missed (must close before this loop is trustworthy)
- **Small-N statistics (critical).** At ~0 incidents/week, weekly precision has tiny denominators; week-over-week "regressions" are mostly noise. Add **Wilson/Jeffreys intervals + a minimum-N gate** before any metric trips CI, or the loop generates false regressions and erodes trust.
- **No tool-use benchmark for non-SRE agents.** pa/pm/review need **τ-bench / τ²-bench**-style multi-turn reliability with **pass^k consistency**, not just P/R.
- **Judge nondeterminism/cost.** Temperature>0 judges flip verdicts run-to-run; budget judge cost/latency and fix seeds where possible.

### Judge bias hardening (phenomena independent; thresholds vendor-sourced)
Position/verbosity/self-preference/authority bias are real (arXiv 2406.07791, "Justice or Prejudice"). Mitigations: rubric + CoT (G-Eval), **cross-family judge** (don't let Claude grade Claude), randomize order, score absolute rubric not pairwise, re-sample ~50 fresh examples monthly to catch judge drift. Treat κ≥0.6 as a goal, not a hard gate.

---

## 4. Memory — provenance, validity, consolidation

Keep markdown canonical and git-versioned; add structure *inside* it. Each brain splits `core/` (tiny, always-loaded: `policy.md`, `frontier.md`, current beliefs — line-budget capped) vs `archive/` (paged in on demand) — the MemGPT tiered pattern (**corrected cite: arXiv 2310.08560**, not 08322; the "verified anchor citations" claim was false for this one).

### Fact schema (front-matter / inline block)
```yaml
- fact: "alb-prod p99 baseline ~180ms"
  observed_utc: 2026-05-30T14:02Z   # from external clock, NOT brain-derived
  source: dd:metric:trace.http.p99@<query>   # must resolve in this tick's transcript
  ttl: 14d
  status: active|stale|retracted
  supersedes: <fact-id>
```

### Process
1. **Grounding hook (P0):** every fact's `source` token must resolve to something in this tick's transcript (MCP call id, Datadog query, Slack ts) → makes invented headers/push-narration (failure 3) impossible by construction. Same hook as §2.5.
2. **Write-time `adjudicate` hook (P1):** if a new fact's key matches an existing `active` fact, you MUST set `supersedes` and flip old → `retracted`, or the write is denied. Retrieval filters `status==active AND observed_utc+ttl > CURRENT_UTC`; stale-but-relevant returns with a **STALE banner, never silently**. This is what catches clock drift: telemetry freshness is a TTL check against the *external* clock.
   - **Frame honestly (verification):** this deterministic deny-unless-supersedes hook is a **guardrail compensating for a measured model weakness**, not borrowed confidence from A-MEM. A-MEM (2502.12110) does write-time *linking/evolution of tags*, **not** truth-value supersession — do not cite it as evidence adjudication works. The empirical reality: STALE shows best frontier model only **55.2%** at acting on outdated memory; MemoryAgentBench multi-hop conflict resolution **≤6%**. **Wire LoCoMo's `knowledge_update`/`contradiction_resolution` task (arXiv 2402.17753) as the regression gate** — ship the mechanism *with* its eval, not without.
3. **Nightly `consolidate` tick (P1):** separate from the 25-min loop. Roll JSONL ledger → archive markdown, reflect ("what changed in baselines/incidents?"), retire stale facts, rewrite `core`/`frontier`. Append-only ledger stays the rebuildable source of truth (Generative Agents reflection, 2304.03442, verified; Letta sleep-time is real prior art but vendor — don't import the "~5x" figure).
4. **Retrieval at scale (later):** grep/full-scan until it stops fitting the prompt budget, then **FTS5** (already used for Hermes), embeddings only if semantic recall matters. The index is a **rebuildable derivative** (`reindex` target), never a second source of truth.

**Files:** `templates/brain-skeleton/` (add `core/` + front-matter convention to the existing `baselines/ runbooks/ incidents/ dry-runs/`), `hooks/` (grounding + adjudicate), `assistant/memory/*.md` (apply schema), new nightly job in `systemd/`.

---

## 5. Autonomy & the human bottleneck

Current state: **maxed on sensing/analysis, pinned at the lowest action level** (Parasuraman/Sheridan/Wickens 2000 — independent, correctly applied: automation level is per-stage). The fix is **fewer, higher-value approvals**, not more autonomy. The 17-tick stall is textbook out-of-the-loop disengagement (Endsley & Kiris 1995; Bainbridge 1983).

### Tiering scheme (reversibility × blast-radius × confidence)
| Tier | Reversibility | Blast radius | Confidence | Mode | Examples |
|---|---|---|---|---|---|
| **T0 auto** | trivially undoable (`jj undo`) | self/brain only | any | act, log only | push own brain, label own audit |
| **T1 auto+notify** | undo ≤1 step | scoped, internal | high (≥ measured threshold) | act, post to digest | apply Gmail label, Linear *read*-derived note, dry-run cleanup |
| **T2 batch-approve** | undoable w/ effort | internal, multi-object | medium | queue → 1-pass review | bulk relabel, cleanup commit, PR draft |
| **T3 hard gate** | irreversible / outward / self-mod | external humans or prod | any | blocking, per-item | Slack send, Gmail send/trash, prod change, edits to `policy.md`/`LOOP.md`/hooks/`mcp.json` |

Rule: `tier = max(reversibility_floor, blast_floor); if confidence < threshold → bump up one tier`.

### Approval UX (Horvitz mixed-initiative, 1999)
- **Recommend-as-a-diff/PR:** each T2 item is a reviewable diff/draft approved/edited/rejected in-place. (Verification: drop the "Flightcrew pattern" label — no such pattern of record; it's just GitHub PR-review UX + Horvitz.)
- **Batched digest = actionable queue:** checkbox-approve a batch; **TTL-expire** low-risk items (silence = proceed for T1, silence = drop for T2). Collapses the 17-tick pileup.
- **Exception-based escalation:** only sub-threshold-confidence or T3 items DM synchronously.
- **Reactions as a real channel:** emoji = approve/reject, feeds eval precision (§3, §6).

### Earned/trust-calibrated autonomy — with honest caveats
Use the golden-scenario harness as a **promotion gate** (Lee & See 2004): an action class promotes T2→T1→T0 only after N ticks above threshold with zero overrides; **auto-demote on any override or eval regression**. Reversibility is the enabler (safe-interruptibility — **corrected cite: Orseau & Armstrong 2016 / Soares et al. 2015**, not Amodei 2016).
**Three prerequisites the verification flagged before building the gate:**
1. **pass^k consistency, not just P/R** — irreversible-adjacent promotion needs reliability under repetition (τ-bench formalizes pass^k); single-shot understates tail risk.
2. **Confidence calibration (ECE/reliability diagrams)** — the tier-bump-on-low-confidence rule assumes calibrated confidence; an overconfident agent silently auto-acts at the wrong tier. Measure calibration first.
3. **Auto-demote ↔ deskilling tension** — demoting-to-human reintroduces out-of-the-loop decay when the human is out of practice. Mitigate with periodic shadow review / rehearsal.

### Stays human-gated forever (regardless of eval score)
T3: Gmail send/trash, Slack send, prod mutations, and edits to `policy.md`/`LOOP.md`/hooks/`mcp.json`/`profiles/`. Autonomy is bounded delegation, not independence (Bradshaw 2013).

**Files:** `profiles/*.json` (tier metadata), `hooks/profile-broker.sh` + `guard-bash.sh` (T3 enforcement, already present), digest agent (§7), `recommendations.md` → queue format.

---

## 6. AIOps alert-quality next steps

Built on the shipped pre-gate (`monitors.classification.json` + `score.py` + quarantine). The 14-DM episode was alert-on-cause amplified by per-tick re-firing + no dedup.

| Priority | Adopt | Detail | Evidence |
|---|---|---|---|
| **P0 (co-equal with heartbeat)** | **MWMBR burn-rate in pre-gate** | Require long+short window breach on golden-signal SLOs. 99.9% table: 1h/5m@14.4×, 6h/30m@6× (page); 3d/6h@1× (ticket); short=1/12 long. Short window confirms still-burning → resets in ~5 min | Independent, **verified exact** (SRE Workbook Table 5-8) |
| **P0** | **Low-QPS absolute-count guard** | Burn-rate math is unstable on thin traffic; add absolute-count floor | Independent (Google flags volume dependence; verification add) |
| **P0** | **Per-tick dedup + temporal correlation** | Collapse repeats by fingerprint (resource+type+condition) before any DM | Independent pattern |
| **P1** | **Seasonality-band quarantine** | Flag any monitor whose threshold sits inside the learned seasonal band. **Delete the "~80% false-alarm reduction" stat — fabricated, not in source** | Direction sound; number stripped |
| **P1** | **Sift-style scope guard** | Abort reasoning if matched-series count > threshold (it's a cardinality guard, not an LLM breadth judge) | Vendor feature, verified mechanism |
| **P1** | **Confidence-gated, evidence-cited DMs** | Every DM cites telemetry IDs (reuse grounding hook); below threshold → digest, not page | Pattern (HolmesGPT/Watchdog/Cleric = vendor marketing; design sound, accuracy claims unproven) |
| **P1** | **Precision/recall feedback** | Persist page outcomes; weekly digest trend (with small-N intervals, §3) | Independent |

**Philosophy (durable):** page on symptoms/golden signals, not internal monitors (Google SRE). Adopt a named external RCA/agentic-SRE benchmark (ITBench) so you measure *good*, not just *drift*.

---

## 7. Multi-agent / control-plane

**The 4 sensors are already on the winning side of the fan-out-vs-coherence debate** (independent of vendor framing): independent + read-only over disjoint domains = the case multi-agent provably helps (Anthropic). Cognition's incoherence failure (subagents co-authoring one artifact) **does not apply** — they never merge outputs.

### Do
1. **Keep the 4 independent and read-only. Never let them chat or co-author.** A2A messaging would import coherence risk for zero benefit on a single trust plane. **MCP yes, A2A no.**
2. **Shared read-only facts layer (blackboard):** `infra.md`, `people.md`, `orgs.md` + external `CURRENT_UTC`. Each agent reads facts instead of rediscovering → kills clock drift (2), starves fabrication (3). The substrate is `~/.config/agents` + `assistant/memory/`.
3. **5th read-only supervisor/digest agent:** reads the 4 JSONL ledgers → one briefing with (a) liveness (catches the 44 dead ticks), (b) alert-quality rollup, (c) eval rollup. Reads ledgers/artifacts; agents never narrate to it (avoid game-of-telephone).
4. **Compact the brains** (current-truth `frontier.md`, just-in-time fact loading) to stop context rot re-seeding drift (Anthropic context engineering).

### Critical guards the research underplayed (verification corrections)
- **Shared facts = single point of silent corruption.** One bad write now propagates to all 4 agents (correlated failure replacing isolated drift). **Mandatory:** per-fact provenance + `last_verified` + cheap expiry pass (the §4 schema *is* this — apply it to the shared layer too).
- **The 5th agent is a new SPOF + the largest context surface** (most exposed to context rot). **Mandatory:** its own liveness watchdog ("who watches the watcher") + compaction discipline from day one. If it dies silently you lose *all* visibility — worse than one dead sensor.
- **Keep the digest strictly non-authoritative** — it summarizes, never decides/pages on behalf of agents (Cognition would caution against a supervisor that *acts* on synthesized state).
- **Capture a pre-change eval baseline** (current P/R for all 4) *before* building, or you can't prove the blackboard+digest reduced failures vs merely moved them.
- **Vendor framing:** Anthropic's "90.2%" is a private, unreproducible eval at 15× tokens; ~80% of the lift is explained by token spend alone. Use orchestrator-worker as a *pattern*, not a promise. Drop arXiv 2510.01285 as load-bearing support (data-lake domain mismatch) — cite classical blackboard lit (Hearsay-II) instead.

### When NOT to go multi-agent
When agents would make interdependent decisions on shared mutable state, or co-author one artifact. Never add a 6th agent without an eval showing it reduces a named failure. Cost is unquantified — a 5th always-on agent + per-tick facts reads across 4 agents compounds; estimate token/run delta before shipping.

---

## 8. Safety

Existing controls to **keep**: ops-guard (read-only on Vizcom), PreToolUse anti-fabrication hook, DM-pinned-to-Kaelan, dry-run mode, `.claude/settings.json` deny allowlist, mcp-sync allowlist, guard-bash destructive-op blocker.

| Control | Action | Evidence |
|---|---|---|
| **Self-modification guard** | Immutable invariant: an agent may **not** edit `mcp.json`, `profiles/`, `policy.md`, `LOOP.md`, or its own hooks → hard-deny + page. Widening own authority = highest-severity event. **Keep and extend.** | Independent (OWASP least-privilege + HITL) |
| **Injection hardening** | Tool *output* is untrusted data (Datadog/Sentry/Gmail/Slack content). Wrap fetched content in explicit data delimiters; forbid acting on embedded instructions. Already in `vizcom-sre` policy rule 3 — make it a fleet-wide hook/test (`prompt-injection-policy.json` exists). | Independent (OWASP cheat sheet; LLMs can't reliably separate instruction from data) |
| **Least privilege** | Don't widen FS/MCP scope; T3 stays human-gated; mutating `agents` MCP tools stay behind `AGENTS_MCP_ALLOW_MUTATION=1`. | Independent |
| **Anti-loop** | Circuit breakers on repeated-identical recommendations, error-rate spikes, token/$ ceilings → open circuit, stop acting, escalate. | Independent |
| **OWASP framing** | Defense-in-depth with deterministic post-conditions as enforcement, LLM critique advisory. **Do not claim deterministic = "most reliable layer"** — OWASP says no foolproof layer exists (verification correction). | Independent (OWASP LLM01) |

---

## 9. Prioritized roadmap

Sequenced. **HUMAN-ONLY** = Kaelan runs/approves (sudo, secrets, T3, MDM-adjacent). **Builds on this session** = extends shipped pre-gate/grounding-hook/clock-pin/eval-harness.

| # | Item | Files touched | Effort | Builds on session | Notes |
|---|---|---|---|---|---|
| **Phase A — fail loud (do first)** |
| A1 | External black-box Slack synthetic | new `systemd/` job, `state/` | S | — | The one un-fakeable check; HUMAN-ONLY for token setup |
| A2 | Per-agent dead-man's-switch + external clock anchor | `systemd/`, collector, `profiles/*.json` | M | clock-pin | Heartbeat + `CURRENT_UTC` from collector, not agent |
| A3 | Liveness/readiness JSONL + degraded→announce-only | `profiles/*.json`, `hooks/` | M | preflight gates | Degraded-but-running is the danger state |
| A4 | Action post-condition contract (generalize anti-fab hook) | `hooks/` (PreToolUse) | S | anti-fab hook | Artifact-or-deny for `pushed`/`sent`/`read`/`created` |
| A5 | Rate-limit/dedup DMs + value-free-tick detector + unpushed-brain alarm | `vizcom-sre` pre-gate, `hooks/` | S | pre-gate | NO "silence is suspicious" meta-alarm |
| **Phase B — measure honestly** |
| B1 | MCC + expected-silence FP gate; separate diagnosis/action scoring | `evals/score.py` (line 91+), `evals/scenarios/` | S | score.py | F1 misleads at ~0 incidents/wk |
| B2 | Fix reaction-reader → online precision w/ Wilson interval + min-N gate | reaction-ingest job, digest | M | dead loop | Prevents false weekly regressions |
| B3 | Fleet-wide CI gate on prompt/policy/classification changes | `templates/eval.yml`, `agents/evals/tasks/` | S | eval harness | Editing `policy.md`/classification re-runs gate |
| B4 | Transcript replay + τ-bench-style pass^k for pa/pm/review | new `evals/tasks/*` | M | eval harness | Half the fleet has no gate |
| B5 | κ-calibrated cross-family judge for triage prose | new `evals/judge/` | M | — | Gate only after κ-calibration; report κ in digest |
| **Phase C — memory & control-plane** |
| C1 | Fact front-matter (source/observed_utc/ttl/status) + grounding hook | `templates/brain-skeleton/`, `hooks/`, `assistant/memory/*` | M | grounding hook | Provenance + freshness = checkable observations |
| C2 | Write-time `adjudicate` hook + LoCoMo regression gate | `hooks/`, `evals/` | M | — | Ship mechanism *with* its eval |
| C3 | Nightly `consolidate` tick | `systemd/` | M | — | Ledger append-only stays source of truth |
| C4 | Shared read-only facts layer (`infra/people/orgs` + clock) | `assistant/memory/`, `~/.config/agents` | M | — | Apply C1 schema; provenance prevents correlated corruption |
| C5 | 5th supervisor/digest agent + its own watchdog | new `agents/`, `profiles/`, `systemd/` | M | — | Strictly read-only/non-authoritative; SPOF guard mandatory; capture pre-change baseline first |
| **Phase D — alert quality & autonomy** |
| D1 | MWMBR burn-rate + low-QPS absolute-count guard + dedup | `vizcom-sre` pre-gate, `monitors.classification.json` | M | pre-gate | Verified exact table; delete fabricated 80% stat |
| D2 | Seasonality-band + Sift-style scope guard + evidence-cited DMs | `vizcom-sre` runbooks, pre-gate | M | quarantine | Vendor patterns, design only |
| D3 | Tiered autonomy + batched/TTL/diff approval queue | `profiles/*.json`, `recommendations.md`, digest | M | guards | T3 stays human-gated |
| D4 | Earned-autonomy promotion gate (after calibration + pass^k) | `profiles/*.json`, `evals/` | L | promotion needs B4 | HUMAN-ONLY to enable any promotion; confidence calibration prerequisite |
| **Phase E — safety hardening (ongoing)** |
| E1 | Fleet-wide injection-delimiter hook/test | `hooks/`, `agents/evals/tasks/prompt-injection-policy.json` | S | existing test | Tool output = untrusted data |
| E2 | Self-mod guard extended to all 4 agents + circuit breakers | `hooks/guard-bash.sh`, `profiles/*` | S | guard hook | KEEP; widening authority = page |

### Honest risk statement
SOTA agent single-incident resolve rates are **~10-15%** (ITBench, independent). This roadmap deliberately **raises a floor (fail-loud, grounded, measured) and tightens the human loop (one queue, earned autonomy, T3 gated)** — it is *not* a path to autonomous remediation. The recommend-only framing is the correct ceiling for current capability; the wins here are reliability and human-leverage, not independence.

---

**Key file anchors (all absolute):**
- Eval harness: `/Users/kaelan/code/vizcom-sre/evals/score.py` (add MCC at line 91+), `/Users/kaelan/code/vizcom-sre/evals/scenarios/` (9 scenarios incl. `iops-noise-canonical.json`, `contentpolicy-edit-noise.json`)
- Pre-gate: `/Users/kaelan/code/vizcom-sre/baselines/monitors.classification.json`, `/Users/kaelan/code/vizcom-sre/tests/eval-pregate.sh`
- Policy: `/Users/kaelan/code/vizcom-sre/CLAUDE.md`
- Hooks: `/Users/kaelan/.config/agents/hooks/{guard-bash.sh,profile-broker.sh}`
- Profiles (7): `/Users/kaelan/.config/agents/profiles/*.json`
- Fleet eval tasks (8): `/Users/kaelan/.config/agents/evals/tasks/*.json` (incl. `prompt-injection-policy.json`)
- Brain template: `/Users/kaelan/.config/agents/templates/brain-skeleton/` (+ `eval.yml`, `scheduled-maintenance.yml`)
- Memory: `/Users/kaelan/.config/agents/assistant/memory/{decisions,people,preferences,projects}.md`
- Scheduling: `/Users/kaelan/.config/agents/systemd/`, `state/`

**Corrected citations to propagate:** MemGPT = arXiv **2310.08560** (not 08322); dead-man's-switch = Google SRE **Ch.10** (not Ch.6); safe-interruptibility = **Orseau & Armstrong 2016 / Soares 2015** (not Amodei 2016). **Delete:** the "~80% false-alarm reduction" stat. **Treat as direction-only (unverified exact):** AIOpsLab 69-88% mitigation, SREGym 40% E2E. **Mark vendor/private:** Anthropic 90.2%; HolmesGPT/Watchdog/Cleric capability claims; κ≥0.6 thresholds.
