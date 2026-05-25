# Spec: Shared Personal Actions MCP

## Outcome
Claude Code, Codex CLI, and Hermes all see the same narrow personal-assistant write surface from one canonical local MCP server:

- `personal_slack_send_message`
- `personal_gmail_create_draft`
- `personal_gmail_send_email`
- `personal_calendar_create_event`
- `personal_calendar_update_event`

The server is registered once in `~/.config/agents/mcp.json`, propagated to Claude/Codex by `mcp-sync`, and loaded by Hermes through `hermes-sync`. The exposed tools remain stable even if the backend changes from Pipedream to Composio, Zapier, official Slack MCP, or Google Workspace CLI later.

## Scope
- **In:** A local stdio MCP facade named `personal-actions` with five allowlisted tools, policy checks, dry-run support, append-only audit logs, and provider adapters behind environment-configured endpoints or local CLIs.
- **In:** Config sync changes so the same server is available to Claude Code, Codex CLI, and Hermes without separately installing Claude connectors or Codex plugins.
- **In:** Documentation for setup, env vars, auth/provider choices, and the first live test sequence.
- **In:** Tests that exercise request validation, dry-run behavior, provider dispatch stubs, audit log redaction, and config sync parity.
- **Out:** Building a public remote MCP server, running a cloud OAuth app, storing OAuth refresh tokens ourselves, exposing broad Gmail/Slack/Calendar APIs, deletes, Drive access, Slack channel management, or autonomous send without explicit tool-call arguments.
- **Out:** Installing OpenClaw as a runtime. OpenClaw is a reference pattern only.

## Constraints
- Keep the facade local and stdio by default to avoid exposing a new HTTP attack surface.
- Do not commit secrets. Configuration may commit env var names, provider names, and safe defaults only.
- Stable public tool names must be provider-neutral and prefixed with `personal_`.
- Every mutating tool must validate required fields before provider dispatch and write an audit record after every attempted call.
- Tool descriptions must be short and explicit about side effects.
- Implement with the repo's existing FastMCP/Python pattern unless there is a concrete blocker.
- Prefer provider backends that already handle OAuth/token custody. The local facade should not own Google or Slack OAuth refresh tokens in first pass.
- Support a `PERSONAL_ACTIONS_DRY_RUN=1` mode that never performs outbound writes.
- Support a `PERSONAL_ACTIONS_PROVIDER` selector. Initial planned values:
  - `webhook`: POST normalized JSON to an HTTPS endpoint such as Pipedream, Composio, Zapier, or a private gateway.
  - `google_workspace_cli`: optional direct local fallback for Gmail/Calendar only, after Hermes Google Workspace auth is configured.
- Keep Slack/Gmail/Calendar write permissions narrow:
  - Slack: send one message to a channel/user identifier.
  - Gmail: create draft or send a specific message.
  - Calendar: create or update a specific event.
- Audit logs live under `assistant/logs/personal-actions/YYYY-MM-DD.jsonl` and must redact obvious secrets/tokens.

## Prior decisions / context
- `mcp-sync` already generates Claude Code `~/.claude.json` and Codex `~/.codex/config.toml` from `~/.config/agents/mcp.json`.
- `hermes-sync` currently generates Hermes config separately and has a disabled `personal_actions` placeholder.
- Hermes supports MCP tool filtering, HTTP OAuth for remote MCP, and Codex runtime migration, but a local facade gives all three clients the same tool names and policy.
- Codex curated plugins for Gmail, Google Calendar, Slack, and Google Drive exist locally but are not installed, and they do not sync to Claude.
- Claude connectors do not sync to Codex.
- OpenClaw's useful pattern here is not its full gateway, but its separation of channel/runtime/tool layers and explicit Codex runtime routing.
- May 2026 MCP security guidance argues for least-privilege tools, explicit consent, avoiding broad token passthrough, avoiding unnecessary local executable surfaces, and auditing calls.

## Tasks
- [x] T1 — MCP server implementation — files: `mcp-servers/personal-actions/server.py`, `bin/personal-actions-mcp`
  - Define five FastMCP tools.
  - Validate inputs with conservative Python checks.
  - Route through provider adapters.
  - Implement dry-run and JSONL audit logging.
- [x] T2 — Provider adapters — files: `mcp-servers/personal-actions/server.py`
  - Implement `webhook` provider using `PERSONAL_ACTIONS_WEBHOOK_URL` and optional `PERSONAL_ACTIONS_WEBHOOK_TOKEN`.
  - Implement `google_workspace_cli` provider for Gmail/Calendar where practical, using Hermes' bundled Google Workspace script and only after auth is present.
  - Return actionable errors for unconfigured provider/auth.
- [x] T3 — Shared config sync — files: `mcp.json`, `bin/hermes-sync`, `README.md`, `AGENTS.md`, `assistant/hermes/README.md`
  - Add `personal-actions` stdio MCP server to canonical `mcp.json`.
  - Update `hermes-sync` to include the same stdio server instead of the placeholder remote-only URL, while preserving optional remote URL support if useful.
  - Document that `mcp-sync && hermes-sync` is the sync path for all three clients.
- [x] T4 — Tests and local verification — files: `tests/personal_actions_smoke.py`, `justfile`
  - Add a smoke test that invokes server functions or runs the MCP server in dry-run mode.
  - Verify audit output is produced and redacted.
  - Include in `just test` if fast and deterministic.
- [x] T5 — Setup docs and first-run checklist — files: `README.md`, `assistant/hermes/README.md`
  - Document provider choices: webhook-first, optional Google Workspace local fallback.
  - Document env vars.
  - Document first live tests: Gmail draft to self, calendar test event, Slack test message.

## Verification
- `mcp-sync`
- `hermes-sync`
- `agents-doctor`
- `just ci-local`
- `hermes mcp list` shows `personal_actions` or `personal-actions` enabled with the five selected tools.
- `PERSONAL_ACTIONS_DRY_RUN=1 hermes -z "List personal action tools; do not take action."` completes without writes.
- Dry-run tool calls create audit JSONL entries and never call the configured provider.
- Claude and Codex configs contain the same canonical `personal-actions` MCP server after `mcp-sync`.
- `gitleaks detect --source . --no-git --redact --verbose` passes.
