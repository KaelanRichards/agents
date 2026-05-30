# Spec: Agent Control Plane

## Outcome
The shared agent environment becomes a local, auditable control plane for multiple coding and personal-assistant agents:

- canonical permission profiles compile into tool-specific artifacts;
- agent runs are recorded in an append-only ledger;
- background tasks can be queued into isolated jj workspaces;
- risky actions can be staged in an approval inbox;
- small eval tasks compare agent/profile behavior;
- a local broker MCP exposes profile-aware policy checks;
- skills carry trust metadata and executable-surface audits;
- prompt-injection fixtures verify untrusted tool/content boundaries.

## Scope
- **In:** Local CLI tools under `bin/`, stdlib Python helpers under `scripts/`, profile JSON under `profiles/`, generated output under gitignored `generated/`, runtime state under gitignored `state/`, a broker MCP server, smoke tests, and docs/status wiring.
- **In:** Conservative MVP behavior that composes with existing `mcp-sync`, `agents-sync`, `swarm`, `dash`, `dashweb`, jj, tmux, and personal-action policy.
- **Out:** Replacing Claude/Codex/Hermes, adopting a full external orchestrator, exposing a public HTTP service, broadening personal-action/provider privileges, or auto-approving production mutations.

## Constraints
- Canonical sources remain in `~/.config/agents`.
- Runtime state must not be committed.
- Generated profile artifacts must be reproducible and disposable.
- Queue workers must run in per-task jj workspaces.
- The broker is policy/audit first; it must not silently widen MCP tool access.
- Tests must run without real agent credentials or network access.
- Existing dirty user memory changes must be preserved.

## Prior decisions / context
- `mcp-sync` owns canonical MCP propagation.
- `agents-sync` owns skills, subagents, hooks, and memory-index propagation.
- Existing `swarm` proves jj workspace fan-out and can remain the ad hoc fast path.
- Current personal actions already use least-privilege tools, dry-run/live mode, audit logs, and confirmation policy.
- Public agent systems in 2026 converge on AGENTS.md, MCP, Skills, profiles/modes, background isolated runs, evals, and explicit approvals.

## Tasks
- [x] T1 — Permission profiles — files: `profiles/*.json`, `bin/agent-profile`, `scripts/agent_control.py`, `bin/agents-sync`
- [x] T2 — Run ledger — files: `bin/agent-ledger`, `scripts/agent_control.py`, `mcp-servers/agents/server.py`
- [x] T3 — Background queue — files: `bin/agentq`, `scripts/agent_control.py`
- [x] T4 — Eval harness — files: `bin/agent-eval`, `evals/tasks/*.json`, `scripts/agent_control.py`
- [x] T5 — Approval inbox — files: `bin/agent-approve`, `scripts/agent_control.py`, `web/dashboard.py`
- [x] T6 — Agent profile compiler — files: `scripts/agent_control.py`, `bin/agents-sync`
- [x] T7 — MCP broker — files: `mcp-servers/agent-broker/server.py`, `bin/agent-broker-mcp`, `mcp.json`
- [x] T8 — Skill trust metadata audit — files: `bin/skills-audit`
- [x] T9 — Prompt-injection fixtures/tests — files: `tests/prompt_injection_policy.py`, `tests/fixtures/prompt-injection/*`
- [x] T10 — Status/docs/tests — files: `bin/agents-status`, `web/dashboard.py`, `README.md`, `tests/agent_system_contract.py`

## Verification
- `agent-profile validate`
- `agent-profile compile`
- `agent-ledger record --kind smoke --status ok --prompt "smoke"`
- `agent-approve request --kind smoke --summary "smoke"`
- `agentq add --repo ~/.config/agents --profile plan-readonly --agent noop --task "smoke"`
- `agent-eval run smoke-noop --agent noop`
- `uv run --script tests/agent_system_contract.py`
- `uv run --script tests/prompt_injection_policy.py`
- `just test`

## Iteration 2 — from advisory to enforced (2026-05-30)

The first iteration described profiles but left enforcement to each tool's own settings; the
broker was advisory and policy guessed mutation from tool-name substrings. This iteration closes
that gap, guided by the 2025/2026 literature (CaMeL / capability + information-flow control;
"tool eligibility" / prompts-are-not-access-control; tamper-evident audit; AgentDojo-style evals).

- **Profile enforcement (`agentp`)** — `agent-profile compile` now also emits, per profile,
  `generated/profiles/claude/<name>.mcp.json` (the granted MCP subset) and
  `<name>.settings.json` (deny/ask rules for filesystem/shell mode and disallowed/confirm tools).
  `bin/agentp <profile>` launches Claude with `--strict-mcp-config` + `--settings`, so the profile
  *removes* servers and tools rather than advising. Claude is the load-bearing target.
- **Authoritative effect registry (fail closed)** — `classify_effect()` replaces substring
  guessing with a per-tool read/write/destructive registry; unknown tools on write-capable
  servers are treated as mutations, so synonym evasion (`personalize_email`) cannot slip through.
- **Provenance rule** — `broker_authorize(..., context_tainted=True)` forces confirmation on any
  mutation drawn from untrusted content and refuses it on high/critical profiles. The
  `personal-actions` facade emits `kind: "taint"` ledger markers when it reads external content.
- **Tamper-evident ledger** — ledger entries form a SHA-256 hash chain (`prev`/`hash`);
  `agent-ledger verify` validates it; `agents-doctor` checks it.
- **Approval TTLs** — requests carry `expires_at` and auto-expire (`agent-approve expire`); the
  personal-actions live-write approval gate now fails closed by default.
- **Behavioral evals** — `tests/behavioral_policy.py` + the `policy-enforcement` eval assert the
  above boundaries in CI so a profile/registry/broker change that weakens them fails the build.
- **Verification:** `uv run --script tests/behavioral_policy.py`; `agent-ledger verify`;
  `agentp list`; `obs status`.

Deferred: A2A / task-DAG planning (no current workload needs cross-agent negotiation; `swarm`
fan-out remains the parallelism path). Gemini/Qwen/OpenCode profile artifacts stay compiled for
reference only.
- `gitleaks detect --source . --no-git --redact --verbose`
