# Spec: hosted OAuth MCP bridge

## Outcome
Notion, Granola, Linear, and Sentry are available to every base agent through one canonical stdio bridge config. Auth is optimized for convenience: run one `mcp-auth login <server>` per host, then Claude, Codex, OpenCode, and other stdio-compatible clients reuse the same `mcp-remote` OAuth cache on that host.

## Scope
- **In:**
  - Convert canonical Notion/Granola/Linear/Sentry MCP entries from native HTTP remotes to `npx -y mcp-remote@latest ...` stdio entries.
  - Track the operational auth model in `mcp.auth.json`.
  - Extend `mcp-auth` with contract validation, local login, VM login, status, and clear setup plans.
  - Update docs, manifest, doctor, and contract checks.
- **Out:**
  - Copying OAuth tokens between hosts.
  - Building custom hosted-service facades before the official hosted MCPs prove insufficient.
  - Making unattended headless agents depend on interactive OAuth.

## Constraints
- `mcp.json` remains the source of truth and must be synced via `mcp-sync`.
- Secrets and OAuth token contents are never printed or committed.
- VM auth must work from a local browser via SSH port forwarding.
- `agents-doctor`, contract checks, `mcp-auth check`, and `gitleaks` must pass.

## Tasks
- [x] T1 — replace selected hosted OAuth direct HTTP MCP entries with `mcp-remote` stdio bridge entries.
- [x] T2 — update `mcp.auth.json` to describe the shared per-host `~/.mcp-auth` model.
- [x] T3 — extend `mcp-auth` for login/status/VM-login.
- [x] T4 — update docs and validation checks.
- [x] T5 — vendor reviewed official Notion workflow skills without installing the full plugin or duplicating MCP definitions.

## Verification
- `mcp-sync`
- `bin/mcp-auth check`
- `python3 tests/agent_system_contract.py`
- `agents-doctor`
- `gitleaks detect --no-banner --no-git --redact`
