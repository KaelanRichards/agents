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
- `gitleaks detect --source . --no-git --redact --verbose`
